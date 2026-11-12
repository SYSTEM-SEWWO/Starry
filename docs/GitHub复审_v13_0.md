# GitHub 复审 · v13.0.0

**视角**：Actions 编排、Release 资产时序、触发与权限、可复现性　**结论：通过（附 3 条建议）**

---

## 1. Workflow 矩阵（实测 YAML 全部解析通过）

| 文件 | 触发 | jobs | 本版变化 |
| --- | --- | --- | --- |
| `ci.yml` | push/PR to main | `test`, `build-deb`, `browser-e2e`, `build-windows` | **新增** v12/v13 单测、三端同源门禁、`build-deb` 结构验证 job |
| `release.yml` | tag `v*.*.*` / dispatch | `verify`, `snapshot`, `publish` | **新增** v13 单测与更新清单生成器自测；summary 改 v13 口径 |
| `build-windows.yml` | tag `v*.*.*` / dispatch | `build-cli-exe`, `release` | 版本示例更新到 13.0.0 |
| `build-android.yml` | tag `v*.*.*` / dispatch | `build-apk` | 保持；`verify_apk.py --strict` 门禁保留 |
| `update-manifest.yml` | **release published** / dispatch | `manifest` | **本版新增** |

`concurrency: release-${{ github.ref }}` 在 release / build-windows / build-android 间串行化，
避免并发写 Release 覆盖正文；`update-manifest` 用独立 group，不阻塞主线。

## 2. 核心设计：为什么更新清单要独立成 workflow

Release 资产由三个流程**异步追加**：`release.yml` 先创建 Release 与源码 zip，
`build-windows.yml` 追加 EXE，`build-android.yml` 追加 APK。
在任何一个流程内部生成 `update.json`，都无法保证看到全部资产——
尤其 APK 通常最后到，清单会缺 android 条目。

`update-manifest.yml` 的解法：

```
on: release published（或手动 dispatch 指定 tag）
   ↓ gh release download --dir release-assets --clobber   ← 拿到当时全部真实资产
   ↓ gen_update_manifest.py --online --repo <github.repository>
   ↓ core.updatecheck.validate_manifest 自复核            ← 客户端视角再验一次
   ↓ gh release upload update.json --clobber              ← 幂等覆盖
```

**幂等**：APK 晚到时重跑一次即可补齐；`--clobber` 保证不产生重复资产。
**诚实**：`--min-assets 1` + 空目录直接报错，绝不上传空清单。
**真实**：哈希来自下载后的真实字节，`--repo` 传入真实 `github.repository`，
正式模式拒绝使用项目占位仓库 `yourname/ai-assistant`。

## 3. 门禁增强

| 门禁 | 位置 | 内容 |
| --- | --- | --- |
| 版本单一真源 | `ci.yml` / `release.yml` | `check_core_parity.py --expect-version <tag>` |
| 三端同源 | 同上 | core/ 与 android/core/ 44 文件字节一致 |
| 全量 AST | 同上 | 全量 Python 源码语法 |
| 桌面全量自测 | 同上 | `QT_QPA_PLATFORM=offscreen python selftest.py` |
| v12 / v13 单测 | 同上 | 63 + 172 项 |
| deb 结构 | `ci.yml::build-deb` | 重新解析 ar / control / data，断言启动器与 3 个新 core 模块 |
| 清单生成器自测 | `release.yml::verify` | 造一个临时 exe → 生成清单 → `validate_manifest` + `check_update` 双断言 |

`build-deb` 的自检刻意从 `core.config.APP_VERSION` 动态读版本，
不硬编码 `13.0.0`——避免下次升版时 CI 因字符串失配而误报。

## 4. 权限与触发

- `release.yml` / `update-manifest.yml`：`permissions: contents: write`，仅用于 Release 读写。
- `GH_TOKEN: ${{ github.token }}`，不引入额外 PAT / secret。
- tag 统一 `v*.*.*`；`workflow_dispatch` 支持手动指定版本或 tag，便于重跑。
- `release.yml` 的 `publish` 有 `if: startsWith(github.ref, 'refs/tags/')`，
  手动 dispatch 只生成快照不误发 Release。

## 5. 建议（不阻塞本版）

| # | 建议 | 优先级 |
| --- | --- | --- |
| 1 | `publish` 之后加一步 `gh release view <tag> --json assets` 校验资产数量与名称，把「上传成功」与「资产齐全」区分开 | 中 |
| 2 | 让 GUI 版 `星语Starry.exe` 也随 tag 进 Release；当前 Release 只有 CLI EXE / deb / zip | 中 |
| 3 | `release.yml` 回写索引用 `git push origin HEAD:main`，在 detached HEAD 的 tag 构建里可能失败（当前用 `|| echo 跳过` 兜底）。建议改为 `git fetch origin main` 后显式 checkout 再提交 | 低 |

## 6. 本地复现

```bash
python scripts/check_core_parity.py --expect-version 13.0.0
python scripts/build_deb.py
python scripts/gen_update_manifest.py --version 13.0.0 --online --repo owner/starry
python -m yaml safe_load 五个 workflow   # 已实测 5/5 解析通过
```

## 7. 结论

**通过**。新增 workflow 解决了「异步资产导致更新清单不全」的真实问题，
门禁覆盖版本、同源、测试、产物结构与清单自校验；3 条建议登记为后续优化。
