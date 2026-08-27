#!/usr/bin/env bash
# TokenMon 安装器: 默认安装 Tauri 宠物 GUI；Python 版只保留为调试 CLI。
# 用法: ./install.sh [已构建的 Tauri tokenmon 二进制路径]
set -euo pipefail
cd "$(dirname "$0")"

BIN_DIR="$HOME/.local/bin"
APP_DIR="$HOME/.local/share/applications"
SYS_DIR="$HOME/.config/systemd/user"
GUI_SRC="${1:-tauri/src-tauri/target/release/tokenmon}"
GUI_DEST="$BIN_DIR/tokenmon"
CLI_DEST="$BIN_DIR/tokenmon-cli"

if [[ ! -x "$GUI_SRC" ]]; then
    echo "未找到已构建的 Tauri 程序: $GUI_SRC" >&2
    echo "先构建: cd tauri && cargo tauri build" >&2
    echo "或传入二进制路径: ./install.sh /path/to/tokenmon" >&2
    exit 1
fi

echo "==> 安装 TokenMon 宠物版到 $BIN_DIR"
mkdir -p "$BIN_DIR" "$APP_DIR" "$SYS_DIR"
install -m 0755 "$GUI_SRC" "$GUI_DEST"

# CLI 继续复用 Python 数据层，保留 --once / --logs 给配置与网关排障。
install -m 0755 tokenmon.py "$CLI_DEST"
install -m 0644 tokenmon_core.py "$BIN_DIR/tokenmon_core.py"

cat > "$APP_DIR/tokenmon.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=TokenMon Pet
GenericName=LLM token companion
Comment=Desktop pet that watches LLM gateway token usage
Exec=$GUI_DEST
Icon=utilities-system-monitor-symbolic
Terminal=false
Categories=Utility;System;
StartupNotify=false
EOF

sed -e "s|^ExecStart=.*|ExecStart=$GUI_DEST|" tokenmon.service > "$SYS_DIR/tokenmon.service"

echo "==> 检查系统依赖"
if command -v rpm >/dev/null 2>&1; then
    if ! rpm -q webkit2gtk4.1 >/dev/null 2>&1; then
        echo "    Linux GUI 需要: sudo dnf install webkit2gtk4.1"
    fi
    if ! rpm -q gnome-shell-extension-appindicator >/dev/null 2>&1; then
        echo "    托盘图标建议: sudo dnf install gnome-shell-extension-appindicator(装完注销重登)"
    fi
fi

echo
echo "==> 安装完成。"
echo "    启动宠物 GUI: $GUI_DEST"
echo "    调试抓取:     $CLI_DEST --once --logs"
echo "    开机自启:     systemctl --user daemon-reload && systemctl --user enable --now tokenmon.service"
