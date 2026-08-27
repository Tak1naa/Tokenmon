@echo off
rem TokenMon Pet Windows 开发启动器(免控制台窗口)
rem 先执行 packaging\build_win.bat，或从 GitHub Release 安装 NSIS 包。
set "EXE=%~dp0tauri\src-tauri\target\release\tokenmon.exe"
if exist "%EXE%" (
  start "" /b "%EXE%" %*
  exit /b 0
)
echo 未找到 Tauri 宠物版: %EXE%
echo 请先运行 packaging\build_win.bat。
exit /b 1
