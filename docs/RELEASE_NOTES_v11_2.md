# 星语 Starry · v11.2.0 发布说明（GitHub Releases 风格）

> 在 v11.1「跨会话检索 + 多格式导出」基础上，**持续优化、增加更新功能**。本版本聚焦**会话组织、消息可控性与离线归档**，核心逻辑对桌面与安卓统一生效。

## 版本资产（Assets）

| 资产 | 形态 | 说明 |
|------|------|------|
| `星语Starry-v11.2-android` | 安卓 APK | BeeWare / Toga 原生安卓应用，已签名、侧载安装即用；含本次 `core/` 标签/编辑/删除/PDF 增强（包名 `com.starry.starryandroid`，版本 11.2.0） |
| `星语Starry-v11.2-uos` | UOS / Debian `.deb` | 命令行版 `.deb`，`dpkg -i` 安装 |
| `星语Starry-v11.2-linux-cli` | Linux 命令行 | `dist/星语Starry-CLI`（PyInstaller 单文件），开箱运行 |
| `星语Starry-v11.2-windows-cli` | Windows 命令行 | 源码 + `scripts/build_windows_cli.ps1`，于 Windows 跑脚本产出 `.exe` |
| `星语Starry-v11.2` | 桌面 GUI（全量源码） | PyQt5 桌面端完整工程 |

> 历史大版本 `星语Starry-v7.6` / `v8.0` / `v9.0` / `v10.0` / `v11.0` / `v11.1` 全部保留。

## 本次更新（v11.2.0）

- 🏷 **会话标签（Tags）**：给会话打标签（如「工作 / 学习 / 灵感」），会话管理框新增**标签筛选下拉**与每行 **🏷 编辑按钮**；`list_tags()` 聚合全部标签及计数。桌面与安卓共用 `core/`，每条会话摘要与检索结果均携带 `tags`
- ✏ **消息编辑 / 删除**：`edit_message(sid, idx, content)` 改某条消息（系统提示受保护、越界安全返回 False）；`delete_message(sid, idx)` 删某条；桌面新增「🗑 删除最后一条消息」（命令面板 + 托盘菜单），撤回刚发出/收到的内容并同步会话存储
- 📄 **PDF 导出**：对话可导出为 **PDF**（在 Markdown / JSON / TXT / HTML 基础上新增），由 WeasyPrint 复用 HTML 版式渲染；环境未装 weasyprint 时导出对话框**自动隐藏 PDF 选项**（避免安卓端误暴露）
- 🧪 **测试加固**：新增 `test_v11_2.py`（21/21 通过）；安卓逻辑回归 `test_app_logic.py` 14/14 全绿
- ♻ **架构零破坏**：新增逻辑均为纯 Python、无 Qt 依赖，桌面与安卓共用 `core/`；UI 仅消费结果，旧 `list/search` 返回结构向后兼容（`tags` 为新增可选字段）
- 🔢 版本号四处一致 **11.2.0**

## 闪退修复（继承自 v11.0/v11.1，本版复用验证）

v11.0 已修复安卓 APK 启动闪退，本版在安卓工程沿用同一修复并复跑 `test_app_logic.py`，核心功能可用、测试完成。详见 `android/README.md` 真机自测清单。

## 安装 / 使用

- 安卓：下载 `星语Starry-v11.2-android/android/dist/星语 Starry-11.2.0.apk`，允许「未知来源」后侧载安装
- UOS/Debian：`sudo dpkg -i 星语Starry-CLI-UOS.deb`
- 桌面 GUI：见 `README.md`（`starrystar.spec` 产出单文件）
- 命令行：`星语Starry-CLI --version` 应打印 `11.2.0`
