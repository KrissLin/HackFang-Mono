#!/usr/bin/env python3
"""将 Hack NF 与中文 fallback 合成为 2:1 等宽字体。"""

from __future__ import annotations

import argparse
import copy
import sys
from collections import Counter
from pathlib import Path

import yaml
from fontTools.misc.transform import Transform
from fontTools.pens.boundsPen import BoundsPen
from fontTools.pens.transformPen import TransformPen
from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.ttLib import TTFont, newTable
from fontTools.ttLib.ttCollection import TTCollection

# 从 fallback 引入的字形 Unicode 范围（西文、Nerd 图标等保留 Hack NF）
FALLBACK_RANGES: list[tuple[int, int]] = [
    (0x3000, 0x303F),  # CJK 符号和标点
    (0x3100, 0x312F),  # 注音
    (0x31A0, 0x31BF),  # 注音扩展
    (0x3200, 0x32FF),  # 带圈 CJK
    (0x3400, 0x4DBF),  # 扩展 A
    (0x4E00, 0x9FFF),  # 统一汉字
    (0xF900, 0xFAFF),  # 兼容汉字
    (0xFE10, 0xFE1F),  # 竖排形式
    (0xFE30, 0xFE4F),  # 兼容形式
    (0xFF00, 0xFFEF),  # 全角字符
]

# Hack NF 优先保留的范围（不覆盖）
BASE_PRIORITY_RANGES: list[tuple[int, int]] = [
    (0x0000, 0x024F),  # 基本拉丁 + 扩展拉丁
    (0xE000, 0xF8FF),  # 私有区（Nerd Font 图标）
]


def in_ranges(codepoint: int, ranges: list[tuple[int, int]]) -> bool:
    return any(start <= codepoint <= end for start, end in ranges)


def should_use_fallback(codepoint: int) -> bool:
    if in_ranges(codepoint, BASE_PRIORITY_RANGES):
        return False
    return in_ranges(codepoint, FALLBACK_RANGES)


def most_common_half_width(font: TTFont) -> int:
    gs = font.getGlyphSet()
    cmap = font.getBestCmap()
    widths: Counter[int] = Counter()
    for _cp, gname in cmap.items():
        if gname in gs:
            w = gs[gname].width
            if w > 0:
                widths[w] += 1
    if not widths:
        raise ValueError("无法从西文字体检测半角宽度")
    return widths.most_common(1)[0][0]


def load_cjk_font(ttc_path: Path, index: int, cache_dir: Path) -> TTFont:
    cache_dir.mkdir(parents=True, exist_ok=True)
    cached = cache_dir / f"pingfang-sc-{index}.ttf"
    if not cached.exists():
        if not ttc_path.exists():
            raise FileNotFoundError(
                f"找不到中文 fallback: {ttc_path}\n"
                "请将任意中文字体放到 fonts/cjk/fallback.ttf"
            )
        collection = TTCollection(ttc_path)
        if index >= len(collection.fonts):
            raise IndexError(f"TTC 索引 {index} 超出范围（共 {len(collection.fonts)} 个字体）")
        collection.fonts[index].save(cached)
    return TTFont(cached)


def load_cjk_font_fallback(cache_dir: Path, fallback_path: Path) -> TTFont:
    if not fallback_path.exists():
        raise FileNotFoundError(
            f"找不到备用中文字体: {fallback_path}\n"
            "macOS 上应能自动使用系统苹方；其他系统请下载思源黑体等到该路径。"
        )
    cache_dir.mkdir(parents=True, exist_ok=True)
    cached = cache_dir / "fallback-extracted.ttf"
    if fallback_path.suffix.lower() == ".ttc":
        if not cached.exists():
            TTCollection(fallback_path).fonts[0].save(cached)
        return TTFont(cached)
    return TTFont(fallback_path)


def glyph_bounds(font: TTFont, glyph_name: str) -> tuple[float, float, float, float]:
    glyph_set = font.getGlyphSet()
    if glyph_name not in glyph_set:
        return (0.0, 0.0, 0.0, 0.0)
    pen = BoundsPen(glyph_set)
    glyph_set[glyph_name].draw(pen)
    if pen.bounds is None:
        return (0.0, 0.0, 0.0, 0.0)
    return tuple(float(v) for v in pen.bounds)


def build_cjk_transform(
    src_font: TTFont,
    glyph_name: str,
    *,
    src_upm: int,
    dst_upm: int,
    full_width: int,
    ascender: int,
    descender: int,
    cjk_scale: float = 1.0,
) -> Transform:
    """按 em 方块等比缩放，而非按 bbox 撑满。

    标点符号在源字体里通常只占 em 的一小部分；若按 bbox 适配，
    会被放大到接近汉字高度。固定 em→全角格的映射可保持标点原始比例。
    """
    x_min, y_min, x_max, y_max = glyph_bounds(src_font, glyph_name)
    src_w = max(x_max - x_min, 1.0)
    src_h = max(y_max - y_min, 1.0)

    # 源字体 1em → 目标全角宽度，再乘以 cjk_scale 调节视觉大小
    scale = (full_width / src_upm) * cjk_scale

    target_h = ascender - descender
    # 防止极少数超高字形溢出
    if src_h * scale > target_h:
        scale = target_h / src_h

    tx = (full_width - src_w * scale) / 2.0 - x_min * scale
    ty = (ascender + descender) / 2.0 - (y_min + y_max) / 2.0 * scale
    return Transform(scale, 0, 0, scale, tx, ty)


def draw_transformed_glyph(
    src_font: TTFont,
    dst_font: TTFont,
    src_name: str,
    dst_name: str,
    transform: Transform,
    full_width: int,
) -> None:
    src_set = src_font.getGlyphSet()
    if src_name not in src_set:
        return

    pen = TTGlyphPen(None)
    tpen = TransformPen(pen, transform)
    src_set[src_name].draw(tpen)
    dst_font["glyf"][dst_name] = pen.glyph()

    lsb = round(transform.transformPoint((glyph_bounds(src_font, src_name)[0], 0))[0])
    lsb = max(0, min(lsb, full_width))
    dst_font["hmtx"][dst_name] = (full_width, lsb)


def ensure_glyph_slot(font: TTFont, glyph_name: str) -> None:
    order = font.getGlyphOrder()
    if glyph_name not in order:
        font.setGlyphOrder(order + [glyph_name])
    if glyph_name not in font["hmtx"].metrics:
        font["hmtx"][glyph_name] = (0, 0)


def rebuild_cmap(font: TTFont) -> None:
    """用 format 12 重建 cmap，避免字形过多时 format 4 溢出。"""
    from fontTools.ttLib.tables._c_m_a_p import cmap_format_12

    best = font.getBestCmap()
    if not best:
        return
    table = cmap_format_12()
    table.cmap = dict(best)
    table.platformID = 3
    table.platEncID = 10
    table.language = 0
    cmap = newTable("cmap")
    cmap.tableVersion = 0
    cmap.tables = [table]
    font["cmap"] = cmap


def update_cmap(font: TTFont, codepoint: int, glyph_name: str) -> None:
    cmap = font.get("cmap")
    if cmap is None:
        return
    for table in cmap.tables:
        if hasattr(table, "cmap"):
            table.cmap[codepoint] = glyph_name


def set_font_names(font: TTFont, family: str, style: str, version: str) -> None:
    full_name = f"{family} {style}".strip()
    ps_name = f"{family}-{style.replace(' ', '')}"
    name_table = font["name"]
    strings = {
        1: family,
        2: style,
        3: f"{version}; {full_name}",
        4: full_name,
        6: ps_name,
        16: family,
        17: style,
    }
    for name_id, value in strings.items():
        name_table.setName(value, name_id, 3, 1, 0x409)
        name_table.setName(value, name_id, 1, 0, 0)


def mark_monospace(font: TTFont, half_width: int, full_width: int) -> None:
    post = font.get("post")
    if post is not None:
        post.isFixedPitch = 1

    os2 = font.get("OS/2")
    if os2 is not None:
        os2.panose.bProportion = 9  # monospace
        os2.xAvgCharWidth = round((half_width + full_width) / 2)

    hhea = font.get("hhea")
    if hhea is not None:
        hhea.advanceWidthMax = max(hhea.advanceWidthMax, full_width)


def merge_fonts(
    base_font: TTFont,
    cjk_font: TTFont,
    *,
    half_width: int,
    family: str,
    style: str,
    version: str,
    cjk_scale: float = 1.0,
) -> TTFont:
    full_width = half_width * 2
    dst = copy.deepcopy(base_font)
    dst_upm = dst["head"].unitsPerEm
    src_upm = cjk_font["head"].unitsPerEm
    ascender = dst["hhea"].ascent
    descender = dst["hhea"].descent

    base_cmap = dst.getBestCmap()
    cjk_cmap = cjk_font.getBestCmap()
    cjk_gs = cjk_font.getGlyphSet()

    added = 0
    for codepoint, src_glyph_name in sorted(cjk_cmap.items()):
        if not should_use_fallback(codepoint):
            continue
        if codepoint in base_cmap and not in_ranges(codepoint, FALLBACK_RANGES):
            continue
        if src_glyph_name not in cjk_gs:
            continue

        dst_glyph_name = f"uni{codepoint:04X}"
        ensure_glyph_slot(dst, dst_glyph_name)

        transform = build_cjk_transform(
            cjk_font,
            src_glyph_name,
            src_upm=src_upm,
            dst_upm=dst_upm,
            full_width=full_width,
            ascender=ascender,
            descender=descender,
            cjk_scale=cjk_scale,
        )
        draw_transformed_glyph(
            cjk_font, dst, src_glyph_name, dst_glyph_name, transform, full_width
        )
        update_cmap(dst, codepoint, dst_glyph_name)
        added += 1

    set_font_names(dst, family, style, version)
    mark_monospace(dst, half_width, full_width)
    rebuild_cmap(dst)

    # 清理合并后可能残留的 lookup 表，避免终端渲染异常
    for tag in ("GSUB", "GPOS", "BASE", "JSTF"):
        if tag in dst:
            del dst[tag]

    print(f"  已合并 {added} 个中文字形（半角={half_width}, 全角={full_width}, scale={cjk_scale}）")
    return dst


def load_config(path: Path) -> dict:
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f)


def resolve_cjk_font(config: dict, index_key: str, project_root: Path) -> TTFont:
    cache_dir = project_root / "fonts" / "cjk" / ".cache"
    ttc_path = Path(config["cjk"]["ttc_path"])
    index = config["cjk"]["sc_indices"][index_key]
    fallback = project_root / "fonts" / "cjk" / "fallback.ttf"

    try:
        return load_cjk_font(ttc_path, index, cache_dir)
    except (FileNotFoundError, IndexError, OSError) as exc:
        print(f"  警告: 无法加载系统苹方 ({exc})，尝试 fallback.ttf")
        return load_cjk_font_fallback(cache_dir, fallback)


def build_variant(
    config: dict,
    variant: dict,
    project_root: Path,
    *,
    half_width_override: int | None,
) -> Path:
    base_dir = project_root / config["base_dir"]
    output_dir = project_root / config["output_dir"]
    output_dir.mkdir(parents=True, exist_ok=True)

    base_path = base_dir / variant["base"]
    if not base_path.exists():
        raise FileNotFoundError(f"缺少基础字体: {base_path}")

    print(f"\n构建 {variant['output']} …")
    base_font = TTFont(base_path)
    half_width = half_width_override or config["width"].get("half_width") or most_common_half_width(base_font)
    cjk_font = resolve_cjk_font(config, variant["cjk_index_key"], project_root)

    cjk_scale = float(config.get("cjk", {}).get("scale", 1.0))

    merged = merge_fonts(
        base_font,
        cjk_font,
        half_width=half_width,
        family=config["font"]["family"],
        style=variant["style"],
        version=config["font"]["version"],
        cjk_scale=cjk_scale,
    )

    out_path = output_dir / variant["output"]
    merged.save(out_path)
    print(f"  → {out_path}")
    return out_path


def download_hack_nf(project_root: Path) -> None:
    import urllib.request
    import zipfile

    dest = project_root / "fonts" / "hack-nf"
    if (dest / "HackNerdFont-Regular.ttf").exists():
        return

    url = "https://github.com/ryanoasis/nerd-fonts/releases/download/v3.3.0/Hack.zip"
    print(f"下载 Hack Nerd Font …")
    dest.mkdir(parents=True, exist_ok=True)
    zip_path = dest / "_Hack.zip"
    urllib.request.urlretrieve(url, zip_path)
    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(dest)
    zip_path.unlink()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="合成 Hack NF + 中文 2:1 等宽字体")
    parser.add_argument(
        "-c", "--config",
        type=Path,
        default=Path(__file__).resolve().parent.parent / "config.yaml",
    )
    parser.add_argument("--half-width", type=int, default=None, help="手动指定半角宽度")
    parser.add_argument("--variant", type=str, default=None, help="仅构建指定输出文件名")
    parser.add_argument("--download", action="store_true", help="自动下载 Hack NF")
    args = parser.parse_args(argv)

    project_root = args.config.resolve().parent
    if args.download:
        download_hack_nf(project_root)

    config = load_config(args.config)
    variants = config["variants"]
    if args.variant:
        variants = [v for v in variants if v["output"] == args.variant]
        if not variants:
            print(f"未找到 variant: {args.variant}", file=sys.stderr)
            return 1

    built: list[Path] = []
    for variant in variants:
        built.append(
            build_variant(
                config,
                variant,
                project_root,
                half_width_override=args.half_width,
            )
        )

    print(f"\n完成，共生成 {len(built)} 个字体文件。")
    print("安装: cp output/*.ttf ~/Library/Fonts/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
