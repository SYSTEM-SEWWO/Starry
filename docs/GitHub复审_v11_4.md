# GitHub 复审 · v11.4.0

> 视角：仓库工程规范 / 提交结构 / CI / Releases / 分发一致性。

## 1. 版本号同步（防漂移）
- 11.3.0 → **11.4.0** 在六处同步：桌面 `core/config.py`、`core/mcp.py`；安卓 `android/core/config.py`、`android/core/mcp.py`；`android/pyproject.toml`（`[project]` 与 `[tool.briefcase]` 共 2 处）；`selftest.py`（4 处断言）。
- `android/README.md` 的 APK 文件名 / 签名命令 / `git tag` 示例同步到 11.4.0；`CLI --version` 实跑打印 `星语 Starry 11.4.0`。
- 杜绝「界面写新、配置写旧」漂移；`core/sessions.py` 与安卓副本字节一致。

## 2. 提交结构
- 新增：`ui/message_picker_dialog.py`、`test_v11_4_pc.py`、`docs/*_v11_4.md`（9 份）。
- 变更：`core/sessions.py`（+ 安卓副本）、`app/assistant.py`、`core/config.py` / `mcp.py`（+ 安卓）、`android/pyproject.toml`、`selftest.py`、`README.md`、`CHANGELOG.md`、`android/README.md`。
- `.gitignore` 沿用既有规则：APK（`android/dist/`）、CLI 虚拟环境（`.venv-cli/`）不入提交，CI 负责构建产物，仓库保持源码/文档/脚本洁净。

## 3. CI / Releases
- `.github/workflows/build-android.yml` 沿用：推送 `v11.4.0` tag 即在 GitHub 运行器**真实编译并签名 APK、自动发布 Releases**。
- 本地沿用 v11.3 已验证的**干净重建**链路：`rm -rf build` → 系统 JDK17（避免联网下载超时）→ gradle **wrapper 9.5.0**（AGP 要求，非系统 9.3.0）→ `assembleRelease` → `zipalign -p 4` → `apksigner sign`（别名 `starry`）→ v2/v3 校验。
- 构建期注意：不设 `_JAVA_OPTIONS`（否则 `javac -version` 多输出一行污染 Briefcase 的 JDK 探测），堆内存参数仅给后续 gradle 步骤单独设置。

## 4. 分发物一致性
- 5 个带后缀版本文件夹 + zip：`星语Starry-v11.4` / `-android`（含单独拎出的签名 APK）/ `-linux-cli`（含 CLI 二进制）/ `-windows-cli`（含 `build_windows_cli.ps1`，无 Wine 环境未出 exe，与历史一致）/ `-uos`（含 `.deb`）。
- 每个文件夹均为**完整工程副本**（源码 + 全部 `docs/*.md` + 主文件 + README/CHANGELOG），自包含可独立构建。
- 历史大版本 **v7.6 / v8.0 / v9.0 / v10.0 / v11.0 / v11.1 / v11.2 / v11.3** 文件夹与 zip 全部保留，未覆盖。

## 5. 提交与标签
- `git commit`（源码/文档/脚本，41+ 文件规模）+ `tag v11.4.0`，干净可推送状态，符合「像 GitHub 提交项目 / Releases 一样好用」。

**结论**：v11.4.0 版本同步完整、提交结构清晰、CI 与 Releases 链路稳定、多端分发一致，工程规范通过。
