# 星语 Starry · v11.0.0 发布说明（GitHub Releases 风格）

> 一处代码，多端分发。本版本重点补齐**移动端与信创端开箱即用**，并让发版形态对齐 GitHub Releases。

## 版本资产（Assets）

| 资产 | 形态 | 说明 |
|------|------|------|
| `星语Starry-v11.0-android` | 安卓 APK | **BeeWare / Toga 原生安卓应用**，已用 v2/v3 签名、侧载安装即用；文件夹内 `android/dist/星语 Starry-11.0.0.apk`（约 52MB，包名 `com.starry.starryandroid`） |
| `星语Starry-v11.0-uos` | UOS / Debian `.deb` | `dist/星语Starry-CLI-UOS.deb`（命令行版，32MB），`dpkg -i` 安装 |
| `星语Starry-v11.0-linux-cli` | Linux 命令行 | `dist/星语Starry-CLI`（PyInstaller 单文件，32MB），开箱运行 |
| `星语Starry-v11.0-windows-cli` | Windows 命令行 | 源码 + `scripts/build_windows_cli.ps1`，于 Windows 跑脚本产出 `星语Starry-CLI.exe` |
| `星语Starry-v11.0` | 桌面 GUI（全量源码） | PyQt5 桌面端完整工程；Windows/macOS 用 `starrystar.spec` 产出 GUI 单文件 |

## 本次更新（v11.0.0）

- 📱 **安卓 APK 开箱即用**：基于 `briefcase → Gradle → Chaquopy`，**移植全部核心代码**（聊天 / 深度思考流 /
  长期记忆 / 智能体工具 / 平台检测复用桌面版纯 Python `core/`），思考卡片还原「液态玻璃悬浮球」
- 🐧 **UOS / Debian `.deb` 完整打包并验证**（`dpkg-deb -I` 校验通过）
- 🚀 **GitHub Releases 式发版**：推送 `v*` tag 即在 GitHub Actions 真实编译并签名 APK、自动发布到 Releases
- 🔒 八份评审/API 文档（安全 / HR / 美术 / 资深 / GitHub / 创造力 / API / 提交指南）+《使用指南_Android_APK.md》
- 🐞 **安卓闪退已修复并验证**：首版 APK 启动即崩，根因为 `toga.Box(visibility=False)` 触发
  `validated_property` 抛 `ValueError`（Toga 0.5.7 仅接受 `"visible"`/`"hidden"`）；
  另修 `Switch`/`Selection` 回调（`on_change` 而非 `on_toggle`/`on_select`）、发送按钮同步化。
  含 `test_app_logic.py` 端到端逻辑测试（14/14 通过），真机自测清单见《android/README.md》。
- ♻ V8.0 / V9.0 / V10.0 能力完整保留；版本号四处一致 **11.0.0**

## 安装速览

- **安卓**：下载 `*.apk` → 允许「未知来源」→ 安装 → 设置里填 API Key。
- **UOS / Linux**：`sudo dpkg -i 星语Starry-CLI-UOS.deb`，或 `./星语Starry-CLI --platform` 直接跑命令行版。
- **Windows 命令行**：在 Windows 上 `powershell -File scripts/build_windows_cli.ps1` 产出 `星语Starry-CLI.exe`。
- **桌面 GUI**：`pip install -r requirements.txt && pyinstaller starrystar.spec`（Windows/macOS/Linux）。

## 校验

- 命令行版：`星语Starry-CLI --version` 应打印 `11.0.0`；`--platform` 打印平台与版本后缀。
- 自测：`python3 selftest.py`（全量用例，桌面/CLI 共用）。
