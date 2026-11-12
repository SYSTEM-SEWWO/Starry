# 星语 Starry · v11.3.0 发布说明（GitHub Releases 风格）

> 主题：**安卓闪退彻底根治 + 电脑端新增功能**
> 包名 `com.starry.starryandroid` ｜ 版本 **11.3.0** ｜ 桌面/安卓/CLI 版本号一致

## 一句话摘要
安卓端此前仍闪退，本次**彻底定位并根治根因**（构建链路复用了陈旧缓存 wheel，分发的是未修复 APK），并修掉一个真实存在的发送失败路径 `NameError`；同时让初始化失败「显示错误而非静默杀进程」。电脑端新增**消息收藏 / AI 会话总结 / 批量导出全部会话**。

## 安卓闪退根治（本次重点）
| 项 | 说明 |
| --- | --- |
| 根因 | 上一版 APK 的 `starryandroid-*.dist-info` 中 `Version` 残留 `11.0.0`，证明构建复用了**陈旧缓存 wheel**——用户装到的其实是未修复的旧构建 |
| 修复① | **干净重建**：清空 `build/`、`dist/` 与 venv 内陈旧 app wheel，改用系统 JDK17（`/usr/lib/jvm/java-17-openjdk-amd64`，Briefcase 0.4.7 硬性要求），重新 `briefcase create/build` + `gradle assembleRelease` |
| 修复② | 真 bug：`_do_turn` 异常处理器 `lambda: ... % e` 引用 `except` 变量，延迟执行触发 `NameError`、崩坏「发送失败」错误显示 → 改为固化 `err` 再传入 |
| 修复③ | 流程优化：`startup()` 初始化失败不再 `re-raise` 杀进程，改为弹出最小**错误窗口 + logcat**；构造期与 `main_loop()` 加崩溃兜底 |
| 验证 | 新 APK 经 `apksigner` **v2+v3 校验通过**；解包核验 `pyc` 无 `from toga.style import Column/Row`、用 `direction="column"` 字符串、`_show_fatal_error` 存在、`Version: 11.3.0` |

## 安装方式
- 安卓：下载 `星语Starry-v11.3-android/android/dist/星语 Starry-11.3.0.apk`，允许「未知来源」后侧载安装；首次启动若异常会在屏上显示原因并写入 `adb logcat | grep StarryApp`
- 桌面：下载 `星语Starry-v11.3` 全量包，`python3 main.py`（开发态）或用对应平台 CLI 包
- 命令行：`星语Starry-CLI --version` 应打印 `11.3.0`
- UOS/Debian：下载 `星语Starry-v11.3-uos` 的 `.deb` 包 `dpkg -i` 安装
- Windows：下载 `星语Starry-v11.3-windows-cli`，含 `build_windows_cli.ps1` 一键打包脚本（沙箱无 Wine，未产出 exe 二进制，脚本随包提供）

## 电脑端新增功能（V11.3）
- ⭐ **消息收藏（Star）**：命令面板「收藏最后回复」一键收藏当前会话最后一条 AI 回复；「收藏夹」对话框列出全部收藏、双击跳转到所在会话
- 📋 **AI 会话总结**：命令面板「AI 总结当前会话」，后台线程流式生成中文要点，缓存到会话元数据
- 📦 **批量导出全部会话**：命令面板「批量导出全部会话」，合并导出 Markdown/JSON/文本/HTML，或 ZIP（每会话独立 `.md` + `index.md`）

## 测试
- 新增 `test_v11_3_pc.py`（4/4 通过）：收藏切换/列表、摘要缓存、`build_summary_prompt`、批量导出五种格式
- 安卓无头 GTK 启动回归：单窗口、设置页切换、发送路径（含错误兜底）全绿
- 版本号四处一致 **11.3.0**（`APP_VERSION` / `CLIENT_INFO.version` / `pyproject.toml` / selftest 断言）

## 文件清单（每个带后缀版本文件夹均含完整工程 + 全部 docs + 主文件 + README/CHANGELOG）
- `星语Starry-v11.3`（桌面 GUI 全量）
- `星语Starry-v11.3-android`（含签名 APK，单独拎出）
- `星语Starry-v11.3-linux-cli` / `星语Starry-v11.3-windows-cli` / `星语Starry-v11.3-uos`（.deb）
