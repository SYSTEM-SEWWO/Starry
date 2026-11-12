# GitHub 复审 · 星语 Starry V9.0

> 视角：开源友好度、仓库结构、LICENSE、.gitignore、提交结构、可复现构建。

## 1. 仓库与提交结构（延续 V8.0 约定）

- 每个版本独立文件夹：`星语Starry-v8.0/`（基线）、`星语Starry-v9.0/`（本次），每个均含**完整源码 + 全部 `docs/*.md` + 主文件 `main.py` + README/CHANGELOG**，自包含、可独立构建/打包（用户明确要求）。
- 单一 `ai-assistant/` 主线仓库，版本号四处一致：`core/config.py` `APP_VERSION`、 `core/mcp.py` `CLIENT_INFO`、 `selftest.py` 断言、README/CHANGELOG 均为 **9.0.0**。
- `git` 提交信息含范围与自测变化（`727 → 751`）。

## 2. 开源合规

- 根目录 `LICENSE`（商业 EULA）+ `SECURITY.md` + `CONTRIBUTING.md` + `CODE_OF_CONDUCT.md` 齐备。
- 本轮新增外部学习明确**仅借鉴产品设计、未复制源码**，并标注 REA(MIT) / Cherry Studio(AGPL-3.0) / LobeChat(LobeHub CL) 等协议，知识产权边界清晰。
- `.gitignore` 持续硬化：`config.json` / `memory.json` / `*.key` / `*.pem` / `secrets.json` / `.codebuddy` 均忽略，敏感运行数据不入库。

## 3. 可复现构建

- `starrystar.spec` 隐藏导入已含 `core.rea`（`starrystar.spec` v9.0 段）；同一 spec 在 Windows 即产出 `星语Starry.exe`，在 Linux 经 PyInstaller 真实构建验证通过（140MB+ 单文件，入口/隐藏导入/PyQt5 收集全正确）。
- `selftest.py` 支持 `QT_QPA_PLATFORM=offscreen` 无头运行，**751 项全绿**，CI 友好。

## 4. 评分

**A-（GitHub / 开源）**：结构清晰、合规完备、构建可复现、文档同格式版本化。
建议（非阻断）：在仓库 `README` 顶部增加一张「V7.x→V9.0 能力演进」表格，降低外部贡献者理解成本。
