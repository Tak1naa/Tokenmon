@echo off
rem TokenMon Pet Windows 一键构建(Tauri + 系统 WebView2，不打包浏览器运行时)
rem 要求: Rust stable/cargo；Windows 10/11 通常自带 WebView2
cd /d "%~dp0\..\tauri"

where cargo >nul 2>nul || (
  echo [错误] 未找到 Rust/Cargo，请先安装 https://rustup.rs/
  pause
  exit /b 1
)

echo ==^> [1/2] 确认 Tauri CLI
cargo tauri --version >nul 2>nul || cargo install tauri-cli --version "^2" --locked || goto :err

echo ==^> [2/2] 构建 Windows NSIS 安装包
cargo tauri build || goto :err

echo.
echo ==^> 构建完成: src-tauri\target\release\bundle\nsis\
echo     运行开发二进制: src-tauri\target\release\tokenmon.exe
pause
exit /b 0

:err
echo.
echo [错误] 构建失败，请检查上方输出。
pause
exit /b 1
