# 星语 Starry · v11.1.0 发布说明（GitHub Releases 风格）

> 在 v11.0「移动端 + 信创端开箱即用」基础上，**持续迭代、增加功能**。本版本聚焦**会话检索与导出体验**，核心逻辑对桌面与安卓统一生效。

## 版本资产（Assets）

| 资产 | 形态 | 说明 |
|------|------|------|
| `星语Starry-v11.1-android` | 安卓 APK | BeeWare / Toga 原生安卓应用，已签名、侧载安装即用；含本次 `core/` 检索/导出增强（包名 `com.starry.starryandroid`，版本 11.1.0） |
| `星语Starry-v11.1-uos` | UOS / Debian `.deb` | 命令行版 `.deb`，`dpkg -i` 安装 |
| `星语Starry-v11.1-linux-cli` | Linux 命令行 | `dist/星语Starry-CLI`（PyInstaller 单文件），开箱运行 |
| `星语Starry-v11.1-windows-cli` | Windows 命令行 | 源码 + `scripts/build_windows_cli.ps1`，于 Windows 跑脚本产出 `.exe` |
| `星语Starry-v11.1` | 桌面 GUI（全量源码） | PyQt5 桌面端完整工程 |

> 历史大版本 `星语Starry-v7.6` / `v8.0` / `v9.0` / `v10.0` / `v11.0` 全部保留。

## 本次更新（v11.1.0）

- 🔍 **跨会话相关性检索**：`SessionStore.search_ranked()` 中英文混合分词 + 词频/标题加权排序，返回带高亮摘要的结果；桌面会话框直接看到命中片段，更相关的会话排在前
- 📤 **多格式导出**：对话可导出为 **Markdown / JSON / TXT / HTML** 四种格式（原仅 Markdown），导出对话框四选一、自动补扩展名；HTML 已做转义，可直接浏览器打开分享
- 🧪 **测试加固**：新增 `test_search_export.py`（5/5 通过）；安卓逻辑回归 `test_app_logic.py` 14/14 全绿
- ♻ **架构零破坏**：新增逻辑均为纯 Python、无 Qt 依赖，桌面与安卓共用 `core/`；UI 仅消费结果，旧 `search()` 返回结构向后兼容
- 🔢 版本号四处一致 **11.1.0**

## 闪退修复（继承自 v11.0，本版复用验证）

v11.0 已修复安卓 APK 启动闪退（`toga.Box(visibility="hidden")` + 回调/发送同步化），本版在安卓工程沿用同一修复并复跑 `test_app_logic.py`，核心功能可用、测试完成。详见 `android/README.md` 真机自测清单。

## 安装 / 使用

- 安卓：下载 `星语Starry-v11.1-android/android/dist/星语 Starry-11.1.0.apk`，允许「未知来源」后侧载安装
- UOS/Debian：`sudo dpkg -i 星语Starry-CLI-UOS.deb`
- 桌面 GUI：见 `README.md`（`starrystar.spec` 产出单文件）
- 命令行：`星语Starry-CLI --version` 应打印 `11.1.0`
