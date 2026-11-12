#!/usr/bin/env bash
# 一键打包 · macOS
# 用法：在项目根目录执行  bash scripts/build_macos.sh
set -euo pipefail

echo "==> 1/5 创建虚拟环境 .venv-build"
python3 -m venv .venv-build
source .venv-build/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
pip install -r requirements-optional.txt
pip install pyinstaller pillow

echo "==> 2/5 生成应用图标"
python3 scripts/make_icon.py

echo "==> 3/5 转换 icns（iconutil）"
ICONSET="assets/icon.iconset"
rm -rf "$ICONSET"; mkdir -p "$ICONSET"
for s in 16 32 64 128 256 512 1024; do
  sips -z $s $s assets/icon_1024.png --out "$ICONSET/icon_${s}x${s}.png" >/dev/null
done
# retina 变体
cp "$ICONSET/icon_32x32.png"    "$ICONSET/icon_16x16@2x.png"
cp "$ICONSET/icon_64x64.png"    "$ICONSET/icon_32x32@2x.png"
cp "$ICONSET/icon_256x256.png"  "$ICONSET/icon_128x128@2x.png"
cp "$ICONSET/icon_512x512.png"  "$ICONSET/icon_256x256@2x.png"
cp "assets/icon_1024.png"       "$ICONSET/icon_512x512@2x.png"
iconutil -c icns "$ICONSET" -o assets/icon.icns || echo "（iconutil 不可用，跳过 icns）"

echo "==> 4/5 PyInstaller 打包（windowed .app）"
# 追加 BUNDLE 生成 .app：onefile spec + --windowed 会同时产出 Unix 可执行与 .app
python3 - <<'PY'
import re
src = open("starrystar.spec", encoding="utf-8").read()
if "BUNDLE(" not in src:
    src += '''

app = BUNDLE(
    exe,
    name="星语Starry.app",
    icon="assets/icon.icns" if os.path.exists("assets/icon.icns") else None,
    bundle_identifier="cn.starry.assistant",
    info_plist={
        "CFBundleName": "星语Starry",
        "CFBundleDisplayName": "星语 Starry",
        "NSHighResolutionCapable": True,
    },
)
'''
    open("starrystar.spec", "w", encoding="utf-8").write(src)
print("spec 已包含 BUNDLE")
PY
python3 -m PyInstaller starrystar.spec --noconfirm --clean --windowed

echo "==> 5/5 整理产物"
mkdir -p "dist/星语Starry-macOS"
cp -R dist/星语Starry.app "dist/星语Starry-macOS/" 2>/dev/null || true
[ -f dist/星语Starry ] && cp dist/星语Starry "dist/星语Starry-macOS/"
cp README.md requirements-optional.txt "dist/星语Starry-macOS/"

echo "完成：dist/星语Starry-macOS/星语Starry.app"
echo "首次运行如提示「无法验证开发者」：系统设置 → 隐私与安全性 → 仍要打开"
