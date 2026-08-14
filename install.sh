#!/usr/bin/env bash
# TokenMon 一键安装(装到用户目录,免 sudo;系统依赖仍需 dnf 装一次,脚本会提示)
# 用法: ./install.sh
set -euo pipefail
cd "$(dirname "$0")"

BIN_DIR="$HOME/.local/bin"
APP_DIR="$HOME/.local/share/applications"
SYS_DIR="$HOME/.config/systemd/user"
DEST="$BIN_DIR/tokenmon"

echo "==> 安装 TokenMon 到 $BIN_DIR"
mkdir -p "$BIN_DIR" "$APP_DIR" "$SYS_DIR"
install -m 0755 tokenmon.py "$DEST"

cat > "$APP_DIR/tokenmon.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=TokenMon
GenericName=LLM token usage monitor
Comment=Real-time LLM gateway token usage pokeball widget (Windows/Linux)
Exec=$DEST
Icon=utilities-system-monitor-symbolic
Terminal=false
Categories=Utility;System;
StartupNotify=false
EOF

# 服务文件以仓库根目录 tokenmon.service 为唯一模板,只替换 ExecStart 为实际安装路径
sed -e "s|^ExecStart=.*|ExecStart=$DEST|" tokenmon.service > "$SYS_DIR/tokenmon.service"

echo "==> 检查系统依赖"
missing=""
if ! rpm -q python3-pyside6 >/dev/null 2>&1; then
    missing=" python3-pyside6"
fi
[ -n "$missing" ] && echo "    请安装: sudo dnf install$missing"
echo "    (备选: /usr/bin/python3 -m pip install --user PySide6)"

if ! rpm -q gnome-shell-extension-appindicator >/dev/null 2>&1; then
    echo "    托盘图标需要: sudo dnf install gnome-shell-extension-appindicator(装完注销重登)"
    echo "    不装也能用: 精灵球照常工作,托盘图标不可用"
fi

echo
echo "==> 安装完成。"
echo "    启动:     $DEST"
echo "    开机自启: systemctl --user daemon-reload && systemctl --user enable --now tokenmon.service"
echo "    首次运行生成配置 ~/.config/tokenmon/config.toml,填好 base_url 后重启生效"
echo "    调试抓取: $DEST --once"
echo "    Windows:  复制 tokenmon.py + tokenmon.bat,pip install pyside6 后双击 bat"
