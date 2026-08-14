#!/usr/bin/env python3
"""一次性生成 TokenMon Lite 的球体图片资产(开发机需 PySide6;运行时不需要)。

产物(写入仓库根目录 assets/):
  ball_<skin>.png   透明底球(Windows 键色透明模式)
  card_<skin>.png   深色底卡片球(Linux 无逐像素透明)
  ball_<skin>.svg   矢量源图(由 Qt 绘制代码导出,便于未来缩放/换引擎)

用法:  python3 packaging/generate_assets.py
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.argv = ["tokenmon"]
import tokenmon as tm
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QPixmap, QPainter, QColor
from PySide6.QtCore import QRectF, Qt

app = QApplication([])
S = 256          # 渲染尺寸(运行时缩到 64)
BALL_SIZE = 128  # 球体在画布中的尺寸
out = Path(__file__).resolve().parent.parent / "assets"
out.mkdir(exist_ok=True)
DARK = "#16181d"


def render_ball(skin, bg):
    pm = QPixmap(S, S)
    pm.fill(bg)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    off = (S - BALL_SIZE) // 2
    tm.draw_pokeball(p, QRectF(off, off, BALL_SIZE, BALL_SIZE), None, skin=skin)
    p.end()
    return pm


for name, skin in tm.SKINS.items():
    render_ball(skin, Qt.GlobalColor.transparent).save(str(out / f"ball_{name}.png"), "PNG")
    render_ball(skin, QColor(DARK)).save(str(out / f"card_{name}.png"), "PNG")
    try:
        from PySide6.QtSvg import QSvgGenerator
        gen = QSvgGenerator()
        gen.setFileName(str(out / f"ball_{name}.svg"))
        gen.setSize(__import__("PySide6.QtCore", fromlist=["QSize"]).QSize(S, S))
        gen.setViewBox(QRectF(0, 0, S, S))
        p = QPainter(gen)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        off = (S - BALL_SIZE) // 2
        tm.draw_pokeball(p, QRectF(off, off, BALL_SIZE, BALL_SIZE), None, skin=skin)
        p.end()
    except Exception as exc:
        print(f"SVG 生成跳过({name}): {exc}")
print("生成完成:", sorted(f.name for f in out.iterdir()))
