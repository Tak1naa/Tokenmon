@echo off
rem TokenMon Windows 一键构建(生成 dist\tokenmon\tokenmon.exe)
rem 要求: 已安装 Python 3.11+;其余依赖本脚本自动装
cd /d "%~dp0\.."

echo ==&gt; [1/3] 创建虚拟环境 .venv-win
python -m venv .venv-win || goto :err

echo ==&gt; [2/3] 安装依赖 (PySide6 + PyInstaller)
".venv-win\Scripts\python" -m pip install --upgrade pip
".venv-win\Scripts\python" -m pip install pyside6 pyinstaller || goto :err

echo ==&gt; [3/3] 构建单文件 exe
".venv-win\Scripts\python" -m PyInstaller --noconfirm --distpath dist --workpath build packaging\tokenmon_pyinstaller.spec || goto :err

echo.
echo ==&gt; 构建完成: dist\tokenmon\tokenmon.exe
echo     运行:    dist\tokenmon\tokenmon.exe
echo     打包zip: 直接压缩 dist\tokenmon 目录分发
pause
exit /b 0

:err
echo.
echo [错误] 构建失败,请检查上方输出。
pause
exit /b 1
