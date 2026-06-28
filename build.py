#!/usr/bin/env python3
"""一键构建 HackFang Mono 等宽字体。"""

from scripts.merge_cjk import main

if __name__ == "__main__":
    raise SystemExit(main(["--download"]))
