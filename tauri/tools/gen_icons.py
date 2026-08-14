# -*- coding: utf-8 -*-
"""用 Qt 渲染精灵球 SVG 生成 Tauri 图标(透明背景, 与 WebView 渲染一致)。

用法: python3 tauri/tools/gen_icons.py
"""
import sys
from pathlib import Path

from PySide6.QtCore import QRectF
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtSvg import QSvgRenderer

ICONS = Path(__file__).resolve().parent.parent / "src-tauri" / "icons"
SKINS = Path(__file__).resolve().parent.parent / "src" / "skins"
SKIN_NAMES = ["pokeball", "master", "great", "ultra"]


def render(size: int, path: Path, svg: Path):
    renderer = QSvgRenderer(str(svg))
    img = QImage(size, size, QImage.Format.Format_ARGB32)
    img.fill(QColor(0, 0, 0, 0))
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    renderer.render(p, QRectF(0, 0, size, size))
    p.end()
    assert img.save(str(path), "PNG"), f"保存失败: {path}"
    print(f"{path.name}: {size}x{size}")


def main():
    ICONS.mkdir(parents=True, exist_ok=True)
    render(32, ICONS / "32x32.png", SKINS / "ball_pokeball.svg")
    render(128, ICONS / "128x128.png", SKINS / "ball_pokeball.svg")
    render(256, ICONS / "128x128@2x.png", SKINS / "ball_pokeball.svg")
    # 托盘皮肤图标(皮肤联动用)
    tray_dir = ICONS / "skins"
    tray_dir.mkdir(exist_ok=True)
    for skin in SKIN_NAMES:
        render(32, tray_dir / (skin + ".png"), SKINS / ("ball_" + skin + ".svg"))
    # ico: 用 Qt 生成多尺寸 ICO 需要 QtGui 的 QImageWriter ICO 支持, 直接写 PNG 由
    # tauri 打包时生成 ico; 这里保留 ImageMagick 生成的多尺寸 ico
    import subprocess
    subprocess.run(
        ["magick", str(ICONS / "128x128.png"),
         "-define", "icon:auto-resize=256,128,64,48,32,16",
         str(ICONS / "icon.ico")],
        check=True,
    )
    print("icon.ico 已生成(多尺寸)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
