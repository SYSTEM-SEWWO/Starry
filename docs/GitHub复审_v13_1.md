# GitHub 复审 · v13.1.0

> 视角：把整个项目当作一个准备提交到 GitHub、靠 Actions 自动发版的仓库来审。
> 关注 workflow 正确性、Release 资产完整性、清单权威性、以及首次提交的可操作性。

## 1. Workflow 清单与改动

| 文件 | v13.1 改动 | 状态 |
| --- | --- | --- |
| `.github/workflows/ci.yml` | 增加 `python tests/test_v13_1_hub.py`；`build-deb` 结构自检仍动态读 `APP_VERSION` | YAML 解析通过 |
| `.github/workflows/release.yml` | 默认版本 `13.1.0`；增加 Hub 单测；生成器自测版本改由 `steps.ver.outputs.version` 注入；快照校验增加 `skills/` 与 `core/hub.py`、`ui/hub_dialog.py` | YAML 解析通过 |
| `.github/workflows/build-windows.yml` | **新增 `build-gui-exe` job**（`starrystar.spec` + `smoke_gui_exe.py`）；CLI 冒烟加 `--hub`；Release 资产追加 `星语Starry.exe` | YAML 解析通过 |
| `.github/workflows/build-android.yml` | 未改；`verify_apk.py --strict` 门禁保持 | YAML 解析通过 |
| `.github/workflows/update-manifest.yml` | tag 示例改 `v13.1.0`；Release published 后下载**全部**资产生成权威 `update.json` | YAML 解析通过 |

三者仍共用 `concurrency: group: release-${{ github.ref }}`、`cancel-in-progress: false`
串行化，避免并发写 Release 覆盖正文或资产。

## 2. 本轮关闭的 GitHub 复审遗留项

v13.0 复审登记了 3 条建议，本轮状态：

| 建议 | 状态 |
| --- | --- |
| GUI exe 随 tag 进 Release | ✅ 已落地：`build-windows.yml` 新增 GUI job，两份 EXE 一同 `append_body` 追加 |
| `gh release view` 发布后校验 | ⏳ 仍未落地（低优先级，不影响产物正确性） |
| detached HEAD 下 `HEAD:main` 回写修复 | ⏳ 仍未落地（`release.yml` 末尾仍为 `git push origin HEAD:main`，失败时只打印跳过提示） |

## 3. Release 资产矩阵（推 `v13.1.0` tag 后）

| 来源 | 资产 |
| --- | --- |
| `release.yml` snapshot | `星语Starry-v13.1.0.zip`（完整快照）、`SHA256SUMS-v13.1.0.txt` |
| `build-windows.yml` | `星语Starry-CLI.exe`（CLI）、`星语Starry.exe`（GUI） |
| `build-android.yml` | 签名 APK（仅在带 Android 工具链的 CI 上） |
| `update-manifest.yml` | 权威 `update.json`（从上述真实资产计算哈希与大小） |

`releases/assets/v13.1.0/` 本地资产目录保留 `windows/` `linux/` `apk/` 三段结构；
`apk/` 仍只放 README，**不伪造 APK 二进制**。

## 4. GUI EXE 的 CI 门禁为什么这样设计

窗口程序 `console=False`，`sys.stdout` 可能为 `None`，且 Actions 的 Windows 运行器
没有交互桌面。因此：

1. `main.py --selftest --out r.json` 把结果写文件，不依赖 stdout；
2. 环境变量 `QT_QPA_PLATFORM=offscreen` 让 `QApplication` 无显示器也能构造；
3. `scripts/smoke_gui_exe.py` 用 `subprocess.run` 启动 EXE（会等待进程退出），
   读落盘 JSON，逐项断言，超时 180s（onefile 解压较慢）；
4. 自检里包含「随包 `skills/` 已打进产物」，直接防住
   「EXE 能启动但 Skills Hub 是空的」这类假成功。

这是 v13.0 创造力复审里「校验全绿但产物是假的」教训的直接落地。

## 5. 版本与清单一致性

- 单一真源 `13.1.0` 三处（`core/config.py` / `core/mcp.py` / `android/pyproject.toml`），
  由 `release.yml` 的 `check_core_parity.py --expect-version` 门禁强制。
- `workflow_dispatch` 的 version 输入与 tag 解析走同一条 SemVer 正则。
- `release.yml` 生成器自测不再硬编码 `13.0.0`，改为注入 `STARRY_REL_VERSION`。
- `update.json` 由 `update-manifest.yml` 在 Release **发布之后**重算，
  因此本地 `assets/v13.1.0/update.json` 只是离线自检样本，正式以 Release 资产为准。

## 6. 首次提交操作（当前目录仍不是 git 仓库）

```bash
git init
git add .
git commit -m "feat: 星语 Starry v13.1.0 Skills Hub / GUI EXE / 技能更新"
git remote add origin https://github.com/<you>/<repo>.git
git push -u origin main
git tag -a v13.1.0 -m "v13.1.0 Skills Hub / GUI EXE"
git push origin v13.1.0
```

> 未完成 `git init` + 首次提交 + remote + tag 之前，workflow 文件虽齐备但不会被触发。
> 另外 `releases/星语Starry-v11.5.0/` 历史快照含 `starry-release.keystore`，
> **公开推送前务必移除或轮换**，否则等于公开签名私钥。

## 7. 建议（按优先级）

1. P1：公开仓库前处理历史 keystore。
2. P2：发布 job 末尾加 `gh release view vX.Y.Z --json assets` 断言资产齐备。
3. P2：`HEAD:main` 回写改为按 `github.event.repository.default_branch` 动态推送。
4. P3：给 `hub.json` 增加可选签名（Ed25519），把「完整性校验」升级为「来源认证」。
