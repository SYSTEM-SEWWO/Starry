# GitHub 复审 · v12.0.0

**视角**：以开源项目维护者身份核对 CI / Releases / 提交结构 / 版本一致性 / 分发体验。

---

## 1. 上轮建议的落地情况（先算旧账）

`GitHub复审_v11_5.md` 第 5 节提了三条建议，本轮逐条核对：

| v11.5 建议 | v12.0 状态 | 说明 |
| --- | --- | --- |
| 增加 `concurrency` 组避免同 tag 重复构建 | ✅ 已落地 | 三个 workflow 统一 `group: release-${{ github.ref }}`、`cancel-in-progress: false` |
| GUI exe 也随 tag 进 Release | ❌ 仍未落地 | `ci.yml` 仍只在 main/PR 产出 GUI exe Artifact；Release 里是 CLI exe |
| `gh release view` 发布后校验（可选 job） | ❌ 仍未落地 | 目前靠 `upload-artifact` 与 `action-gh-release` 成功推断 |

**不粉饰**：两条未落地项继续登记在建议表，不因为本版做了很多就抹掉。

---

## 2. 新增 `release.yml`：三段式发版编排

```
push tag vX.Y.Z（或 workflow_dispatch 指定版本）
        │
        ├─ verify    ubuntu-latest：解析 tag + SemVer 正则校验
        │            → 装钉版本依赖 + playwright install chromium
        │            → check_core_parity.py --expect-version
        │            → selftest.py（offscreen）
        │            → tests/test_android_v12.py
        │            → android/test_app_logic.py
        │            → tests/test_v12_features.py
        │
        ├─ snapshot  needs: verify
        │            → make_release.py --version <解析出的版本>
        │            → 校验主文件 + 全部 md + core/ui/android/docs/.github 目录齐备
        │            → upload-artifact（zip / SHA256SUMS / RELEASE_NOTES / RELEASES.md，90 天）
        │
        └─ publish   needs: [verify, snapshot]，if: tag
                     → softprops/action-gh-release@v2
                       body_path: RELEASE_NOTES.md，append_body: true
                     → 回写 RELEASES.md 索引到 main
```

| 审查项 | 评价 |
| --- | --- |
| tag 规则 | 三个 workflow 由 `v*` 收紧为 `v*.*.*`，`verify` 里再用 `^[0-9]+\.[0-9]+\.[0-9]+$` 校验，杜绝 `v12` / `vbeta` 误触发 ✅ |
| 版本单一真源 | tag 解析出的版本传给 `--expect-version`，与源码 3 处声明比对，不一致直接红 ✅ |
| 并发 | 三 workflow 共享 `concurrency` 组串行；`cancel-in-progress: false` 保证正在发布的 Release 不被后来者取消 ✅ |
| Release 冲突 | 全部 `append_body: true` 且 Windows / Android 侧不设 `name`，只追加资产，不覆盖标题与正文 ✅ |
| 权限 | `contents: write` 最小集，仅用 `GITHUB_TOKEN` ✅ |
| 门禁强度 | `selftest.py` + 3 套 v12 测试 + 同源/版本/AST 门禁，**比 v11.5 只做 exe 自检严格得多** ✅ |
| 快照校验 | 显式列举 `main.py / starry_cli.py / README.md / CHANGELOG.md / RELEASE_NOTES.md / MANIFEST.md / checksums.txt / selftest.py` 与 5 个目录，缺一即失败 ✅ |
| 失败定位 | 门禁、快照、发布拆成三个 job，红了能一眼看出卡在哪段 ✅ |

---

## 3. Android / Windows 工作流的改造

| 文件 | v12.0 变更 | 审查 |
| --- | --- | --- |
| `build-android.yml` | tag 收紧 `v*.*.*`；加 `concurrency`；`append_body: true`；**新增签名后 `verify_apk.py --apk ... --expect-version ... --strict` 门禁** | 把「静态鉴定」变成发布阻断条件，是本轮最实在的一处加固 ✅ |
| `build-windows.yml` | tag 收紧；加 `concurrency`；`pip install "pyinstaller==6.22.3"` 钉版本；保留 `append_body: true` | 构建工具钉版本，避免 PyInstaller 漂移导致产物不可复现 ✅ |

`verify_apk.py --strict` 会拒绝：签名块头尾长度不自洽、`build.json` 中
`app.imy` SHA1 不符、`.pyc` magic 非 3.11、toga 元包与 `toga-core` 主版本混装、
应用版本与 tag 不符、缺 INTERNET 权限。**v11.5 实测唯一 FAIL 的
`toga 0.2.15 / 0.5.7` 混装，今后会被 CI 自动拦下。**

---

## 4. 提交结构

| 项 | 状态 |
| --- | --- |
| 新增文件落位 | `core/`、`tests/`、`scripts/`、`docs/`、`.github/workflows/`、`releases/`，无散落在根目录的临时文件 ✅ |
| 版本文件夹 | `releases/星语Starry-v11.5.0/` 完整保留（331 个文件 / 106MB），`releases/星语Starry-v12.0.0/` 由 `make_release.py` 生成，**只追加、不覆盖历史** ✅ |
| 资产分目录 | `assets/{apk,windows,linux}/`，APK 单独拎出，便于分发与成本核算 ✅ |
| 二进制入库 | `*.exe` / `*.deb` / `*.apk` / `*.zip` 按白名单排除出源码快照，走 Release 资产分发；`.gitignore` 既有规则一致 ✅ |
| 敏感文件 | 本轮安全复审修复：通配排除任意 `*.keystore / *.jks / *.p12 / *.pfx / *.pem / *.key`，并在发布前 `assert_no_secrets` 扫描 ✅ |
| 版本一致性 | `APP_VERSION` / `CLIENT_INFO.version` / `pyproject.toml` 三处 = `12.0.0`，`--expect-version 12.0.0` 实测通过 ✅ |

### 需要使用者注意的两点（如实记录）

1. **当前工作目录不是 git 仓库**：本机 `git status` 返回
   `fatal: not a git repository`。所有 workflow 文件与 `releases/` 结构已备好，
   但要真正「像 GitHub 项目一样好用」，还需执行一次 `git init` + 首次提交 +
   关联 remote + `git tag v12.0.0 && git push --tags`。步骤已写进
   `docs/项目结构与提交指南_v12_0.md`。
2. `release.yml` 的 publish job 用 `git push origin HEAD:main` 回写索引；
   tag 触发时 checkout 处于 detached HEAD，该推送可能失败。
   命令带 `|| echo "索引回写跳过…"` 兜底，**不阻断发布**，但索引可能只留在
   artifact 里。建议改用 `git checkout main` 后再提交，或直接用
   `gh api` 更新文件。

---

## 5. Releases 体验核对

一个 `git tag v12.0.0 && git push --tags` 之后，用户应能拿到：

| 资产 | 产出方 |
| --- | --- |
| `星语Starry-v12.0.0.zip`（完整自包含项目：全部源码 + 主文件 + 全部 md + .github + 构建脚本） | `release.yml / snapshot` |
| `SHA256SUMS-v12.0.0.txt` | `release.yml / snapshot` |
| Release 正文 = `RELEASE_NOTES.md` | `release.yml / publish` |
| `星语Starry-Android-v12.0.0.apk`（签名，`verify_apk --strict` 通过后） | `build-android.yml` |
| `星语Starry-CLI.exe`（`--version` / `--platform` 自检通过） | `build-windows.yml` |

本地另有 `releases/星语Starry-v12.0.0/` 文件夹版快照（含
`MANIFEST.md` 逐文件 SHA-256、`checksums.txt`、`RELEASE_NOTES.md`），
以及 `releases/RELEASES.md` 倒序索引（新版本标 `latest`，旧版本自动改 `superseded`）。

---

## 6. 建议（不阻塞发布）

| 建议 | 优先级 |
| --- | --- |
| 初始化 git 仓库并完成首次提交 / 打 tag（否则所有 workflow 无法触发） | 高（用户侧动作） |
| 发布后加 `gh release view vX.Y.Z --json assets` 校验 job | 中 |
| 修 `HEAD:main` 回写在 detached HEAD 下的失败 | 中 |
| `ci.yml` 的 GUI exe 也随 tag 进 Release | 低 |
| 给 `releases/星语Starry-v11.5.0/` 加公开分发前的密钥轮换确认 | 中（安全） |

---

## 结论

**通过**。v11.5 的 `concurrency` 建议已落地，tag 规则收紧、三 workflow 串行化、
`append_body` 统一、Release 正文与完整源码快照自动产出，Android 侧新增
`verify_apk.py --strict` 把静态鉴定变成发布门禁——**发版链路从「能出资产」
升级为「出得对才让出」**。剩余两条 v11.5 未落地建议与 git 初始化事项
已如实登记，不阻塞 v12.0.0 的代码与产物交付。
