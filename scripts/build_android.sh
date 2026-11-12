#!/usr/bin/env bash
# 一键打包 · Android 版（两种形态）
#
# 形态一（推荐，零编译）：Termux 直接运行
#   在 Android 上安装 Termux，执行以下命令即可把星语 Starry 跑起来：
#     pkg update && pkg install python clang libjpeg-turbo
#     pip install -r requirements.txt
#     git clone <本仓库> && cd ai-assistant
#     python3 starry_cli.py "你好"
#   说明：Termux 提供完整 Linux 用户态，命令行版无需图形界面即可工作。
#
# 形态二（可选，产出 APK）：python-for-android 封装
#   需要主机具备 Android SDK/NDK（约 1GB+），本脚本记录标准流程，
#   因沙箱无法内置 SDK，故 APK 在用户本地主机执行下列命令产出。
#
# 用法：
#     bash scripts/build_android.sh termux      # 仅打印 Termux 安装指引
#     bash scripts/build_android.sh apk         # 打印 p4a 构建命令（需本地 SDK/NDK）
set -euo pipefail

MODE="${1:-termux}"

if [ "$MODE" = "termux" ]; then
  echo "==== Android（Termux）运行指引 ===="
  cat <<'EOF'
1) 在 Android 上安装 Termux（F-Droid 版，非 Play 版，以获得完整包）。
2) 打开 Termux，依次执行：
     pkg update
     pkg install python clang libjpeg-turbo libxml2 libxslt
     pip install --upgrade pip
     pip install -r requirements.txt
     git clone https://github.com/<你的>/ai-assistant.git
     cd ai-assistant
     python3 starry_cli.py --platform
     python3 starry_cli.py "用一句话解释什么是量子纠缠"
3) 如需长期记忆 / 智能体工具，同样开箱即用（配置写在 Termux 的 ~/.config）。
说明：命令行版完全不依赖图形界面，因此无需 Qt 安卓插件即可在 Termux 中运行。
EOF
  exit 0
fi

if [ "$MODE" = "apk" ]; then
  echo "==== Android APK 构建命令（需本地 Android SDK/NDK） ===="
  cat <<'EOF'
# 以下在 Linux/macOS 主机执行，需预先：
#   export ANDROIDSDK=/path/to/android-sdk
#   export ANDROIDNDK=/path/to/android-ndk
#   pip install python-for-android

# 1) 生成启动脚本（p4k 入口）
cat > starry_launcher.py <<'PY'
import sys
from starry_cli import run_cli
sys.exit(run_cli())
PY

# 2) 构建 APK（仅含命令行所需的纯 Python 依赖，排除 PyQt/playwright 等）
p4a apk --private . \
  --package=com.starry.cli \
  --name "星语Starry-CLI" \
  --version 10.0.0 \
  --bootstrap=sdl2 \
  --requirements=python3,requests \
  --android-api=33 \
  --permission=INTERNET \
  --entrypoint=starry_launcher.py

# 构建完成后在 dist/ 得到 星语Starry-CLI-10.0.0-debug.apk
# 通过 adb install 安装到手机；在终端模拟器/Tasker 中调用启动脚本。
EOF
  exit 0
fi

echo "用法：bash scripts/build_android.sh [termux|apk]" >&2
exit 1
