#!/usr/bin/env bash
# 一键打包 · 安卓 APK（BeeWare / Briefcase 0.4.7，产出【已签名、可直接侧载】的 APK）
#
# 前置（本脚本会自动补齐）：
#   - Android cmdline-tools + platform-36 + build-tools-36.0.0 + NDK 25.1.8937393
#   - JDK 17（如系统未装，请先 apt install openjdk-17-jdk）
#   - pip install "briefcase==0.4.7"
#
# 产物：android/dist/星语 Starry-<版本>.apk（已用 v2/v3 签名，可安装）
# 用法（在仓库根目录执行）：  bash scripts/build_android_apk.sh
#
# 关键说明：
#   1) Briefcase 0.4.7 的模板要求 compileSdk/build-tools 36，故此处安装 android-36。
#   2) briefcase package android 产出的是【未签名】release APK，无法直接安装；
#      故本脚本显式用 zipalign + apksigner 自签名。
#   3) 请勿在本脚本中设置 _JAVA_OPTIONS，否则 java/javac -version 会多出
#      “Picked up _JAVA_OPTIONS” 行，导致 Briefcase 的 JDK 版本解析误判。
set -euo pipefail

unset _JAVA_OPTIONS
export ANDROID_HOME="${ANDROID_HOME:-/opt/android-sdk}"
export JAVA_HOME="${JAVA_HOME:-/usr/lib/jvm/java-17-openjdk-amd64}"

echo "==> 0/6 准备系统依赖与 Android SDK"
if [ ! -x "$ANDROID_HOME/cmdline-tools/latest/bin/sdkmanager" ]; then
  sudo apt-get update -qq
  sudo apt-get install -y -qq unzip curl openjdk-17-jdk >/dev/null 2>&1 || true
  mkdir -p "$ANDROID_HOME/cmdline-tools"
  curl -fsSL -o /tmp/cmdtools.zip \
    https://dl.google.com/android/repository/commandlinetools-linux-11076708_latest.zip
  unzip -q -o /tmp/cmdtools.zip -d "$ANDROID_HOME/cmdline-tools"
  mv "$ANDROID_HOME/cmdline-tools/cmdline-tools" "$ANDROID_HOME/cmdline-tools/latest" 2>/dev/null || true
fi
export PATH="$JAVA_HOME/bin:$ANDROID_HOME/cmdline-tools/latest/bin:$ANDROID_HOME/platform-tools:$PATH"

yes | sdkmanager --sdk_root="$ANDROID_HOME" --licenses >/dev/null 2>&1 || true
sdkmanager --sdk_root="$ANDROID_HOME" "platform-tools" "platforms;android-36" \
  "build-tools;36.0.0" "ndk;25.1.8937393" >/dev/null 2>&1 || \
  sdkmanager --sdk_root="$ANDROID_HOME" "platform-tools" "platforms;android-36" \
    "build-tools;36.0.0" "ndk;25.1.8937393"

# 避免 Gradle 重复下载 JDK / 加速解析
mkdir -p "$HOME/.gradle"
cat > "$HOME/.gradle/gradle.properties" <<'EOF'
org.gradle.java.installations.auto-download=false
org.gradle.daemon=false
EOF

echo "==> 1/6 安装 Briefcase（固定 0.4.7，模板依赖 compileSdk 36）"
pip install "briefcase==0.4.7" >/dev/null 2>&1 || pip3 install "briefcase==0.4.7"

echo "==> 2/6 生成签名密钥库（侧载演示用；上架 Play 请换自有发布密钥）"
KS="$PWD/android/starry-release.keystore"
if [ ! -f "$KS" ]; then
  keytool -genkey -v -keystore "$KS" \
    -alias starry -keyalg RSA -keysize 2048 -validity 10000 \
    -storepass starry123456 -keypass starry123456 \
    -dname "CN=Starry, OU=Starry, O=Starry, L=CN, S=CN, C=CN"
fi
KS_PASS=starry123456
KEY_PASS=starry123456
KS_ALIAS=starry

echo "==> 3/6 创建安卓工程（下载 BeeWare 模板 + Gradle 包装器）"
cd android
briefcase create android

echo "==> 4/6 构建 APK（Chaquopy 打包 CPython 运行时 + 资源/代码）"
briefcase build android

echo "==> 5/6 打包（未签名 release）+ zipalign + apksigner 签名"
briefcase package android -p apk
UNSIGNED=$(find dist -name "*.apk" | head -n1)
echo "未签名 APK: $UNSIGNED"
BUILD_TOOLS="$ANDROID_HOME/build-tools/36.0.0"
ALIGNED=/tmp/starry-aligned.apk
"$BUILD_TOOLS/zipalign" -p 4 "$UNSIGNED" "$ALIGNED"
"$BUILD_TOOLS/apksigner" sign \
  --ks "$KS" --ks-key-alias "$KS_ALIAS" \
  --ks-pass pass:"$KS_PASS" --key-pass pass:"$KEY_PASS" \
  --out "$UNSIGNED" "$ALIGNED"
"$BUILD_TOOLS/apksigner" verify "$UNSIGNED" && echo "SIGN_VERIFY_OK"

echo "完成（已签名、可侧载安装）："
ls -lh "$UNSIGNED"
