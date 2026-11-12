#!/usr/bin/env bash
# 一键打包 · 统信 UOS 版（国产操作系统）
#
# UOS 本质为 Debian 系 Linux，因此：先构建「Linux 命令行版」二进制，
# 再封装为 .deb 安装包，符合 UOS 软件商店 / 统信应用商店的分发形态。
#
# 产物：dist/星语Starry-UOS/星语Starry-CLI(.deb)
# 用法（在具备 dpkg 的 Debian/Ubuntu/UOS 主机上执行）：
#     bash scripts/build_uos.sh
set -euo pipefail

APP="星语Starry-CLI"
VERSION="${1:-10.0.0}"
ARCH="$(dpkg --print-architecture 2>/dev/null || echo amd64)"

echo "==> 1/5 构建 Linux 命令行版二进制"
bash scripts/build_linux_cli.sh

echo "==> 2/5 准备 .deb 目录骨架"
WORK="dist/${APP}-UOS"
rm -rf "$WORK"
mkdir -p "$WORK/DEBIAN"
mkdir -p "$WORK/opt/starry/bin"
mkdir -p "$WORK/usr/share/applications"
mkdir -p "$WORK/usr/share/icons/hicolor/128x128/apps"

echo "==> 3/5 复制二进制与说明"
cp dist/星语Starry-CLI-pkg/星语Starry-CLI "$WORK/opt/starry/bin/"
cp README.md "$WORK/opt/starry/" 2>/dev/null || true
cp 命令行使用指南.md "$WORK/opt/starry/" 2>/dev/null || true
chmod +x "$WORK/opt/starry/bin/星语Starry-CLI"

echo "==> 4/5 写入控制文件与桌面入口"
cat > "$WORK/DEBIAN/control" <<EOF
Package: starry-cli
Version: $VERSION
Section: utils
Priority: optional
Architecture: $ARCH
Maintainer: 星语 Starry <starry@example.com>
Description: 星语 Starry 命令行版（AI 助手，跨平台无界面）
 支持 Windows / Linux / 统信 UOS / Android(Termux)，可接多家 OpenAI 兼容
 大模型，支持智能体工具调用与长期记忆。
EOF

cat > "$WORK/usr/share/applications/starry-cli.desktop" <<EOF
[Desktop Entry]
Name=星语 Starry CLI
Comment=AI 助手命令行版
Exec=/opt/starry/bin/星语Starry-CLI --platform
Terminal=true
Type=Application
Categories=Utility;
EOF

echo "==> 5/5 打包 .deb"
dpkg-deb --build --root-owner-group "$WORK" "${WORK}.deb"
echo "完成：dist/${APP}-UOS.deb  （可用 dpkg -i 安装，或在 UOS 应用商店侧载）"
