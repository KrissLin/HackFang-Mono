# HackFang Mono

将 [Hack Nerd Font](https://github.com/ryanoasis/nerd-fonts) 与 macOS 默认中文 fallback（**苹方 PingFang SC**）合成为等宽字体，**中文全角宽度 = 西文半角 × 2**。

## 原理

| 来源 | 用途 | 字宽 |
|------|------|------|
| Hack Nerd Font | ASCII、拉丁字母、Nerd 图标 | 半角（自动检测，约 1233/2048 em） |
| 苹方 SC | CJK 汉字、全角标点等 | 全角 = 半角 × 2 |

## 快速开始

```bash
# 安装依赖
pip install -r requirements.txt

# 构建全部字重（Regular / Bold / Italic / BoldItalic）
python build.py

# 或仅构建 Regular
python scripts/merge_cjk.py --download --variant HackFangMono-Regular.ttf
```

输出在 `output/` 目录。

### 安装字体

```bash
cp output/*.ttf ~/Library/Fonts/
```

然后在终端 / IDE 中选择 **HackFang Mono**。

## 配置

编辑 `config.yaml`：

- `cjk.scale`：中文字形视觉缩放（默认 `0.8`，保持 2:1 字宽不变）
- `cjk.ttc_path`：苹方 TTC 路径（macOS 默认已填好）
- `width.half_width`：手动指定半角宽度；留空则自动从 Hack NF 检测
- `variants`：要生成的字重列表

### 非 macOS 系统

系统没有苹方时，将任意中文字体（如思源黑体）放到：

```
fonts/cjk/fallback.ttf
```

## 项目结构

```
├── build.py              # 一键构建入口
├── config.yaml           # 配置
├── scripts/merge_cjk.py  # 核心合成逻辑
├── fonts/
│   ├── hack-nf/          # Hack Nerd Font（自动下载）
│   └── cjk/              # 中文 fallback 缓存
└── output/               # 生成的字体
```

## 许可

- Hack / Hack Nerd Font：见 [Nerd Fonts](https://github.com/ryanoasis/nerd-fonts) 许可
- 苹方为 Apple 系统字体，仅限个人本机使用；分发合成字体请注意版权
