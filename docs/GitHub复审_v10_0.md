# GitHub 复审 · V10.0

> 从开源协作、仓库结构、CI 友好度、跨平台发布包角度评估 V10.0。

## 1. 仓库结构（提交友好度：A-）

- 新增 `core/platforms.py`、`core/cli.py`、`starry_cli.py`：集中在 `core/` 与根目录，符合既有分层。
- 打包配置：`starry_cli.spec` 与 `starrystar.spec` 并列，命名清晰区分 GUI/CLI。
- 脚本：`scripts/` 下新增 `build_*_cli.*` 与 `build_uos.sh`、`build_android.sh`，与既有
  `build_linux.sh` / `build_windows.ps1` / `build_macos.sh` 风格统一。

## 2. 跨端发布包（亮点）

- 每个平台独立版本后缀文件夹（`星语Starry-v10.0-windows-cli` / `linux-cli` / `uos` / `android`），
  均含**完整工程**（源码 + 全部 `docs/*.md` + 主文件 + README/CHANGELOG），自包含、可独立构建。
- 这种「一处仓库、多端清晰分发」的结构对 Fork/PR 友好：贡献者 clone 任一文件夹即可构建对应平台。

## 3. CI 适配性

- 命令行版零 Qt 依赖，可在无桌面 runner（如 GitHub Actions `ubuntu-latest`）中跑 `selftest` 全量，
  也可单独验证 `starry_cli.py --version` / `--platform`。
- `starry_cli.spec` 的 `excludes` 显式剔除 PyQt5，构建更稳、产物更小。

## 4. 文档与 LICENSE

- 八份 V10.0 评审/API/平台文档齐备；`SECURITY.md` / `CONTRIBUTING.md` / `CODE_OF_CONDUCT.md` 沿用。
- `LICENSE`（商业 EULA）与 `SECURITY.md` 已涵盖 API Key 处理说明，CLI 端复用同一套合规约束。

## 5. 建议

1. 建议在 `.github/workflows` 增加「CLI 构建 + selftest」矩阵（windows/ubuntu），自动产出四端产物。
2. 发布说明（Release notes）按 `windows-cli / linux-cli / uos / android / gui` 分栏，呼应版本后缀。

## 6. 评分：**B+**（结构清晰、发布包友好；CI 矩阵待补）
