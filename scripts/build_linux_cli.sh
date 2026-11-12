#!/usr/bin/env bash
# 一键打包 · Linux 命令行版
# 产物：dist/星语Starry-CLI/星语Starry-CLI（控制台程序，无 GUI 依赖）
# 用法（在项目根目录执行）：  bash scripts/build_linux_cli.sh
set -euo pipefail

echo "==> 1/4 创建虚拟环境 .venv-cli"
python3 -m venv .venv-cli
# shellcheck disable=SC1091
source .venv-cli/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
pip install pyinstaller

echo "==> 2/4 PyInstaller 打包（控制台模式，不收集 GUI 模块）"
python3 -m PyInstaller starry_cli.spec --noconfirm --clean

echo "==> 3/4 整理产物（PyInstaller 已产出 dist/星语Starry-CLI 可执行文件）"
PKG_DIR="dist/星语Starry-CLI-pkg"
rm -rf "$PKG_DIR"
mkdir -p "$PKG_DIR"
mv dist/星语Starry-CLI "$PKG_DIR/星语Starry-CLI"
cp README.md "$PKG_DIR/"
cp 命令行使用指南.md "$PKG_DIR/" 2>/dev/null || true
chmod +x "$PKG_DIR/星语Starry-CLI"

echo "==> 4/4 完成：dist/星语Starry-CLI-pkg/星语Starry-CLI"
echo "    直接运行：./星语Starry-CLI-pkg/星语Starry-CLI --platform"
