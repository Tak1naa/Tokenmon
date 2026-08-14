# -*- coding: utf-8 -*-
"""精灵球 SVG 参数调整脚本。

- 按钮半径: 10.5 -> 20(直径比 32%, 接近真实精灵球)
- viewBox: 0 0 256 256 -> 64 64 128 128(裁剪到球体区域, 显示尺寸翻倍)

用法: python3 tauri/tools/gen_half.py
"""
import re
import sys
from pathlib import Path

SKINS_DIR = Path(__file__).resolve().parent.parent / "src" / "skins"
SKINS = ["pokeball", "master", "great", "ultra"]
BUTTON_R = "20"  # 原 10.5 -> 15 -> 20
VIEWBOX = "64 64 128 128"  # 球体区域(原 0 0 256 256, 球只占一半)


def main():
    for skin in SKINS:
        src_path = SKINS_DIR / f"ball_{skin}.svg"
        src = src_path.read_text(encoding="utf-8")
        # 球心按钮放大(圆环描边同源, 仅 r 变化)
        src = src.replace('r="10.5"', f'r="{BUTTON_R}"')
        # 固有尺寸与 viewBox 一致(90.3111mm ≈ 341px 会导致 WebKit 缩放异常)
        src = src.replace('width="90.3111mm" height="90.3111mm"', 'width="256" height="256"')
        # viewBox 裁剪到球体区域, 球占满窗口(显示尺寸翻倍)
        src = src.replace('viewBox="0 0 256 256"', 'viewBox="' + VIEWBOX + '"')
        src_path.write_text(src, encoding="utf-8")
        src_path.write_text(src, encoding="utf-8")
        print(f"{skin}: 按钮 r={BUTTON_R}")
    print("完成: 球心按钮已放大(半片由前端 overflow 容器裁剪, 无需独立文件)")


if __name__ == "__main__":
    sys.exit(main())
