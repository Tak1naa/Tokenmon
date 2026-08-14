Name:           tokenmon
Version:        2.0.0
Release:        1%{?dist}
Summary:        Pokeball-style floating widget to monitor LLM gateway token usage

License:        MIT
Source0:        tokenmon.py
Source1:        tokenmon.desktop
Source2:        tokenmon.service

# 直装即自动带上运行依赖 + 顶栏图标所需扩展
Requires:       python3-pyside6
Requires:       gnome-shell-extension-appindicator

%description
TokenMon is a small always-on-top floating widget that polls an LLM API
gateway (LiteLLM / OpenRouter / any custom HTTP endpoint) for token usage
and displays it in real time as a Pokeball-style ball: prompt/completion/
reasoning tokens, cache hit/miss, session totals and cost.

It also shows the most recent conversations (prompt + total tokens) from
the gateway's log endpoint (LiteLLM /spend/logs or a custom logs_url),
and provides a system tray icon (Windows native; GNOME needs the
AppIndicator extension, otherwise it degrades gracefully).

%install
mkdir -p %{buildroot}%{_datadir}/tokenmon
install -m 0644 %{SOURCE0} %{buildroot}%{_datadir}/tokenmon/tokenmon.py

mkdir -p %{buildroot}%{_bindir}
cat > %{buildroot}%{_bindir}/tokenmon <<'WRAPPER'
#!/bin/sh
exec /usr/bin/python3 %{_datadir}/tokenmon/tokenmon.py "$@"
WRAPPER
chmod 0755 %{buildroot}%{_bindir}/tokenmon

mkdir -p %{buildroot}%{_datadir}/applications
install -m 0644 %{SOURCE1} %{buildroot}%{_datadir}/applications/tokenmon.desktop

mkdir -p %{buildroot}%{_libdir}/systemd/user
install -m 0644 %{SOURCE2} %{buildroot}%{_libdir}/systemd/user/tokenmon.service

%files
%{_bindir}/tokenmon
%{_datadir}/tokenmon/tokenmon.py
%{_datadir}/applications/tokenmon.desktop
%{_libdir}/systemd/user/tokenmon.service

%changelog
* Wed Aug 13 2026 TokenMon - 2.0.0-1
- Rewrite in PySide6 (Windows/Linux), pokeball-style ball, recent conversations panel
