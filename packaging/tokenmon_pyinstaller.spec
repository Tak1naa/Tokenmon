# -*- mode: python ; coding: utf-8 -*-
# PyInstaller 打包配置(tokenmon 单文件可执行程序)
#
# Windows 一键构建:  packaging\build_win.bat
# Linux 手动构建:    pyinstaller --noconfirm packaging/tokenmon_pyinstaller.spec
#
# 产物: dist/tokenmon(.exe) —— 目录模式(onedir),含 _internal 运行库
# 注意: PyInstaller 不支持交叉编译,Windows exe 必须在 Windows 上构建(CI 已配置)。

import os

datas, binaries, hiddenimports = [], [], []

# 只用 QtCore/QtGui/QtWidgets: 排除未用的大模块(QtWebEngine/Qt3D/多媒体等),
# 否则默认 hook 会随 PySide6 包带入数百 MB 的无关库
excludes = [
    "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtWebEngineQuick",
    "PySide6.Qt3DCore", "PySide6.Qt3DRender", "PySide6.Qt3DInput", "PySide6.Qt3DAnimation",
    "PySide6.Qt3DExtras", "PySide6.Qt3DLogic", "PySide6.Qt3DQuick",
    "PySide6.QtCharts", "PySide6.QtDataVisualization", "PySide6.QtGraphs",
    "PySide6.QtPdf", "PySide6.QtPdfWidgets", "PySide6.QtMultimedia",
    "PySide6.QtMultimediaWidgets", "PySide6.QtQuick3D", "PySide6.QtQuick3DAssetsImport",
    "PySide6.QtQuick3DHelpers", "PySide6.QtQuick3DParticleEffects",
    "PySide6.QtSensors", "PySide6.QtSerialPort", "PySide6.QtSerialBus",
    "PySide6.QtSql", "PySide6.QtTest", "PySide6.QtBluetooth", "PySide6.QtNfc",
    "PySide6.QtPositioning", "PySide6.QtRemoteObjects", "PySide6.QtScxml",
    "PySide6.QtStateMachine", "PySide6.QtTextToSpeech", "PySide6.QtWebChannel",
    "PySide6.QtWebSockets", "PySide6.QtDesigner", "PySide6.QtHelp",
    "PySide6.QtNetworkAuth", "PySide6.QtOpcUa", "PySide6.QtQml",
    "PySide6.QtQuick", "PySide6.QtQuickControls2", "PySide6.QtQuickTemplates2",
    "PySide6.QtQuickWidgets", "PySide6.QtOpenGLWidgets", "PySide6.QtShaderTools",
    "PySide6.QtSpatialAudio", "PySide6.QtHttpServer", "PySide6.QtLabsQmlModels",
    "PySide6.QtLabsSettings", "PySide6.QtLabsSharedImage", "PySide6.QtLabsWaveFrontMesh",
    "PySide6.QtQuickLayouts", "PySide6.QtQuickParticles", "PySide6.QtQuickShapes",
    "PySide6.QtQuickTest", "PySide6.QtQuickTimeline", "PySide6.QtQuickToolUtils",
    "tkinter", "unittest", "pydoc",
]


def _drop_dep(entry):
    """按文件名裁剪不需要的 Qt 依赖。

    TokenMon 的球体/图标/托盘图标全部由 QPainter 自绘,不加载任何外部图片:
    - 图像格式插件(imageformats)整体不需要 → 连带砍掉 AV1/JPEG-XL/HEIF/EXR/
      RAW/TIFF 等编解码库与 libQt6Pdf(24MB)
    - libQt6Network / libQt6Svg 无使用者(网络用标准库 urllib)
    - 保留: libssl/libcrypto(Python ssl,https 抓取)、libdbus(托盘)、
      xcb/wayland 平台插件
    """
    n = os.path.basename(entry[0]).lower()
    if "imageformats" in entry[0]:
        return True
    if n.startswith(("libqt6pdf", "libqt6network", "libqt6svg",
                     "libqopensslbackend")):
        return True
    if n.startswith(("libaom", "libavif", "libdav1d", "libjxl", "libheif",
                     "libopenexr", "libraw", "libsvtav1", "librav1e", "libvmaf",
                     "libglycin", "libopenh264", "libyuv", "libde265",
                     "libiex", "libilmthread", "libimath", "libopenjph",
                     "libopenjp2", "libjasper", "libmng", "libduktape",
                     "libkf6archive", "libtinysparql", "libssh")):
        return True
    return False


a = Analysis(
    ["../tokenmon.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
)
a.binaries = [b for b in a.binaries if not _drop_dep(b)]
a.datas = [d for d in a.datas if not _drop_dep(d)]

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="tokenmon",
    debug=False,
    bootloader_ignore_signals=False,
    strip=True,
    upx=True,
    console=False,          # 无控制台窗口(Windows pythonw 风格)
    disable_windowed_traceback=False,
    icon=["icons/tokenmon.ico"],  # Windows exe 图标; Linux 构建时忽略
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=True,
    upx=True,
    upx_exclude=[],
    name="tokenmon",
)
