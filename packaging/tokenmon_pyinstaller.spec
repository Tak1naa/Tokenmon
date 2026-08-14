# -*- mode: python ; coding: utf-8 -*-
# PyInstaller 打包配置(tokenmon 单文件可执行程序)
#
# Windows 一键构建:  packaging\build_win.bat
# Linux 手动构建:    pyinstaller --noconfirm packaging/tokenmon_pyinstaller.spec
#
# 产物: dist/tokenmon(.exe) —— 目录模式(onedir),含 _internal 运行库
# 注意: PyInstaller 不支持交叉编译,Windows exe 必须在 Windows 上构建(CI 已配置)。

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
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="tokenmon",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,          # 无控制台窗口(Windows pythonw 风格)
    disable_windowed_traceback=False,
    icon=["icons/tokenmon.ico"],  # Windows exe 图标; Linux 构建时忽略
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="tokenmon",
)
