# -*- mode: python ; coding: utf-8 -*-
# TokenMon Lite(极简版)PyInstaller 配置 —— 仅 tkinter + 标准库,无 PySide6
# 构建: pyinstaller --noconfirm packaging/tokenmon_lite.spec
# 产物: dist/tokenmon-lite/tokenmon-lite(.exe),约 15-20MB

a = Analysis(
    ["../tokenmon_lite.py"],
    pathex=[],
    binaries=[],
    datas=[("../assets", "assets")],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # 关键: 排除 PySide6 —— tokenmon.py 数据层里的 Qt 导入必须走 HAVE_QT=False 分支
    excludes=["PySide6", "PySide6.QtCore", "PySide6.QtGui", "PySide6.QtWidgets",
              "shiboken6", "tkinter.test", "unittest", "pydoc"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="tokenmon-lite",
    debug=False,
    bootloader_ignore_signals=False,
    strip=True,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    icon=["icons/tokenmon.ico"],
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=True,
    upx=True,
    upx_exclude=[],
    name="tokenmon-lite",
)
