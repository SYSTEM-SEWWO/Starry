# GitHub 复审 · V11.0

> 从仓库结构、Release 形态、CI、协作友好度评估 V11.0——重点看「是否像 GitHub 提交项目与 Releases 一样好用」。

## 1. 仓库结构（提交友好度：A）

- `android/` 自成 BeeWare 工程（`pyproject.toml` + `starryandroid/` + `core/` 副本），
  与桌面/CLI 并列，Fork 任一端即可独立构建。
- 既有 `scripts/`、`docs/`、`ui/`、`core/`、`app/` 分层清晰，新贡献者五分钟可读懂入口。

## 2. Release / Releases 形态（本次重点补齐）

- 新增 `.github/workflows/build-android.yml`：推送 `v*` tag 即在 GitHub 运行器上
  **真实编译 python-for-android → 签名 APK → 自动发布到 Releases**，完全对标官方开源项目发版体验。
- 版本后缀文件夹（`星语Starry-v11.0-*`）命名与 tag 对齐，本地分发与 Releases 资产一一对应。

## 3. CI 矩阵（建议落地）

| 平台 | 触发 | 产物 |
|------|------|------|
| Android APK | tag `v*` | `*.apk`（Releases 资产） |
| CLI + selftest | push/PR | 全量自测（无桌面也可跑） |

- 命令行版零 Qt 依赖，可在 `ubuntu-latest` 跑 `selftest.py` 全量，作为合并门禁。

## 4. 文档与合规

- V11.0 八份评审/API/平台文档齐备；`SECURITY.md` / `CONTRIBUTING.md` / `CODE_OF_CONDUCT.md` 沿用。
- `使用指南_Android_APK.md` 单独成篇，降低移动端用户的上手门槛。

## 5. 建议

1. 建议增加「CLI 构建 + selftest」与「UOS deb 构建」两条 CI，形成四端自动发版矩阵。
2. Release notes 按 `gui / windows-cli / linux-cli / uos / android` 分栏，呼应版本后缀。

## 6. 评分：**A**（Releases 自动发版落地，达到「像 GitHub Releases 一样好用」目标）
