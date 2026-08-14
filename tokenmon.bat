@echo off
rem TokenMon Windows 启动器(免控制台窗口)
rem 依赖: Python 3.11+ 与 PySide6 —— 先运行: pip install pyside6
cd /d "%~dp0"
where pythonw >nul 2>nul
if %errorlevel%==0 (
  start "" /b pythonw "%~dp0tokenmon.py" %*
) else (
  where pyw >nul 2>nul && (pyw -3 "%~dp0tokenmon.py" %*) || (python "%~dp0tokenmon.py" %*)
)
