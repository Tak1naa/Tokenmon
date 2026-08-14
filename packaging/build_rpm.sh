#!/usr/bin/env bash
# 在 Fedora 上把 tokenmon 打成可直装的 RPM
# 用法: ./build_rpm.sh   (需要 rpm-build: sudo dnf install rpm-build)
# 产物: ./rpmbuild/RPMS/<arch>/tokenmon-*.rpm  →  sudo dnf install ./tokenmon-*.rpm
set -euo pipefail
cd "$(dirname "$0")"

if ! command -v rpmbuild >/dev/null 2>&1; then
    echo "缺少 rpmbuild,请先: sudo dnf install rpm-build" >&2
    exit 1
fi

# 从 spec 里取版本号
VERSION=$(sed -n 's/^Version:[[:space:]]*//p' tokenmon.spec | head -1)
echo "==> 构建 tokenmon-${VERSION} RPM"

rm -rf rpmbuild
mkdir -p rpmbuild/SOURCES rpmbuild/SPECS rpmbuild/RPMS rpmbuild/BUILD rpmbuild/BUILDROOT

# 源文件: 主程序从仓库根目录取,desktop/service 在 packaging/ 下
cp ../tokenmon.py rpmbuild/SOURCES/tokenmon.py
cp tokenmon.desktop rpmbuild/SOURCES/tokenmon.desktop
cp tokenmon.service rpmbuild/SOURCES/tokenmon.service
cp tokenmon.spec rpmbuild/SPECS/tokenmon.spec

rpmbuild --define "_topdir $(pwd)/rpmbuild" --define "_sourcedir $(pwd)/rpmbuild/SOURCES" \
         -bb rpmbuild/SPECS/tokenmon.spec

echo
echo "==> 构建完成,安装:"
find rpmbuild/RPMS -name '*.rpm' -printf '  sudo dnf install %p\n' | head -1
