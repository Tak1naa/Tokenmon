# -*- coding: utf-8 -*-
"""生成半片精灵球 SVG(内部 clipPath, 不依赖 CSS clip-path)。
同时把球心按钮从 r=10.5 放大到 r=15(显示比例更接近真实精灵球)。

用法: python3 tauri/tools/gen_half.py
"""
import re
import sys
from pathlib import Path

SKINS_DIR = Path(__file__).resolve().parent.parent / "src" / "skins"
SKINS = ["pokeball", "master", "great", "ultra"]
BUTTON_R = "15"  # 原 10.5


def main():
    for skin in SKINS:
        src_path = SKINS_DIR / f"ball_{skin}.svg"
        src = src_path.read_text(encoding="utf-8")
        # 球心按钮放大(圆环描边同源, 仅 r 变化)
        src = src.replace('r="10.5"', f'r="{BUTTON_R}"')
        # 固有尺寸与 viewBox 一致(90.3111mm ≈ 341px 会导致 WebKit 缩放异常)
        src = src.replace('width="90.3111mm" height="90.3111mm"', 'width="256" height="256"')
        src_path.write_text(src, encoding="utf-8")
        src_path.write_text(src, encoding="utf-8")
        print(f"{skin}: 按钮 r={BUTTON_R}")
    print("完成: 球心按钮已放大(半片由前端 overflow 容器裁剪, 无需独立文件)")


if __name__ == "__main__":
    sys.exit(main())
