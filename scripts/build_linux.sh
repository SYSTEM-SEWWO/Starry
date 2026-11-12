#!/usr/bin/env bash
# 一键打包 · Linux
# 用法：在项目根目录执行  bash scripts/build_linux.sh
set -euo pipefail

echo "==> 1/5 系统依赖（Debian/Ubuntu）"
if command -v apt-get >/dev/null 2>&1; then
  echo "    如需语音朗读：sudo apt install espeak espeak-ng"
  echo "    如需托盘图标：sudo apt install libxcb-cursor0"
fi

echo "==> 2/5 创建虚拟环境 .venv-build"
python3 -m venv .venv-build
source .venv-build/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
pip install -r requirements-optional.txt
pip install pyinstaller pillow

echo "==> 3/5 生成应用图标"
python3 scripts/make_icon.py

echo "==> 4/5 PyInstaller 打包（单文件）"
python3 -m PyInstaller starrystar.spec --noconfirm --clean

echo "==> 5/5 整理产物"
mkdir -p dist/星语Starry-Linux
cp dist/星语Starry dist/星语Starry-Linux/
cp README.md requirements-optional.txt dist/星语Starry-Linux/
chmod +x dist/星语Starry-Linux/星语Starry

echo "完成：dist/星语Starry-Linux/星语Starry"
echo "运行：./星语Starry（需图形环境；无托盘环境自动降级）"
