# GitHub 复审 · v11.5.0

**视角**：以 GitHub 开源项目维护者身份核对 CI / Releases / 提交结构 / 分发一致性。

## 1. 本轮最大发现：exe 从未进过 Releases

复核 `.github/workflows/`：

| 工作流 | 触发 | 产物 | 问题 |
|---|---|---|---|
| `build-android.yml` | `push tags: v*` | 签名 APK → **Releases** | 正常 |
| `ci.yml` → `build-windows` | `push main` / PR | GUI exe → Artifact（14 天） | **只在 main/PR 触发、从不进 Releases** |
| `build_windows_cli.ps1` | 本地 | 无（仅脚本） | 无任何 CI 产出 CLI exe |

也就是说「打包成点 exe」在此前版本里只做到了「有脚本 / 有临时 Artifact」，
用户从一个 release tag 上**下载不到 exe**。本轮新增
`.github/workflows/build-windows.yml` 补齐这一环。

## 2. 新工作流审查

| 项 | 评价 |
|---|---|
| 触发 | `push tags: v*` + `workflow_dispatch`，与安卓对齐 ✅ |
| Runner | `windows-latest`（真 Windows，非 Wine 模拟） ✅ |
| 门禁 | 打包后 `--version` / `--platform` 自检并校验 `$LASTEXITCODE`，失败即红 ✅ |
| Artifact | `retention-days: 30`、`if-no-files-found: error` ✅ |
| Release | `append_body: true` 且**不设 `name`** → 只追加资产 ✅ |

### 并发 Release 冲突的规避

两个 workflow 会因同一 `v*` tag 并行触发。若各自都 `createRelease` 并设
`name`/`body`，后执行者会覆盖前者标题与说明。本轮让 Windows 侧：
- 不设 `name`（不覆盖标题）；
- `append_body: true`（追加而非替换说明）；
- `files` 只给 exe。

这样无论谁先创建 Release，最终 APK 与 EXE 都在同一个 Release 下，
标题/正文由安卓侧主说明 + Windows 侧追加段落组成。**判断正确**。

## 3. 提交结构

- `.gitignore` 已含 `.venv-cli/`、`android/dist/`、`*.apk`、`build/`；
  本轮新增的 `dist/星语Starry-CLI.exe` 属构建产物，需确认按既有规则不入库
  ——exe 走 CI 产出 / 版本文件夹分发，不进 git（与 APK 一致）。
- 新增文件均落在既有目录约定：`core/`、`ui/`、`.github/workflows/`、
  `scripts/`、`docs/`、`test_*.py`，无散落文件。
- 版本号四处一致 11.5.0（`APP_VERSION` / `CLIENT_INFO.version` /
  `pyproject.toml` / selftest 断言），`grep` 无 11.4.0 残留。

## 4. Releases 体验核对

一个 `git tag v11.5.0 && git push --tags` 之后，用户应能拿到：

- `星语Starry-Android-v11.5.0.apk`（已签名可侧载）
- `星语Starry-CLI.exe`（Windows 单文件，自检通过）
- Release 正文含 APK 说明 + Windows EXE 追加段

本地另有 5 个带后缀完整项目文件夹 + zip（含 Linux CLI / UOS deb /
Android 独立 APK / Windows 构建包），历史 v7.6–v11.4 版本文件夹全保留。

## 5. 建议（不阻塞发布）

- 让 `ci.yml` 的 GUI exe 也随 tag 进 Release，补齐桌面 GUI 端。
- 增加 `concurrency` 组避免同一 tag 重复触发时产生多次构建。
- 用 `gh release view` 做一次发布后校验（可选 job）。

## 结论

**通过**。发现并补齐了跨多版本遗留的发布缺口，工作流并发语义处理正确，
提交结构与版本一致性符合开源项目惯例。
