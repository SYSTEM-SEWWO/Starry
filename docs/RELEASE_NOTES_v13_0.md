# 发布说明 · 星语 Starry v13.0.0

**发布日期**：2026-11-07　**上一版本**：v12.0.0　**版本主题**：整体项目 → 多线并行 → 自动更新 · Windows EXE / Linux deb 电脑端大版本

---

## 一、为什么有这个大版本

v12.0 把「安卓闪退根因修复、三端同源、完整 Releases 交付体系」做实了。本轮指令把重心明确移到**电脑端**：

> 「接下来重点放到 exe，也就是 Windows 电脑版上，还有 Linux 电脑版上，做功能更多的更新，复刻 workbuddy，然后做 github, action……接下来多线并行前面加一个整体项目，不断优化，增加更新功能……还需要在电脑端增加更多新功能。大版本更新。」

于是 v13.0 回答三个问题：

1. **「多线并行前面加一个整体项目」** —— 并行只是调度方式，用户真正面对的应该是「一个项目跑完了没有」。新增 `core/project.py` 持有目标、任务、依赖、状态与产物，可序列化为 `.starryproj`。
2. **「复刻 workbuddy」** —— 新增 WorkBuddy 式桌面工作台 `ui/workbench_dialog.py`：目标输入 → 任务树 → 分波并行 → 进度条 → 报告/存档/更新，一处闭环；CLI 侧用 `--workbench` 给出等价的文本工作台。
3. **「增加更新功能」** —— 新增 `core/updatecheck.py` 把「有没有新版本 / 该下哪个资产 / 资产是否完整」做成可离线单测的纯逻辑；`scripts/gen_update_manifest.py` 从**真实字节**生成 `update.json`；`.github/workflows/update-manifest.yml` 在 Release 发布后自动回传权威清单。

**关键取舍**：三层核心全部零 GUI、零网络、零第三方依赖，默认 worker 是本地确定性执行器。因此 Windows EXE 与 Linux deb **不需要 API Key、不需要联网**，打开即可跑通「整体项目 → 分波并行 → 100% 完成」的完整流程。网络和模型只在显式 `--execute` / `--update-url` 时才触碰，且失败一律优雅降级。

## 二、新增能力矩阵

| 层 | 模块 / 文件 | 关键能力 |
| --- | --- | --- |
| 整体项目 | `core/project.py` | 任务状态机（pending→running→done/failed/skipped）、依赖分波、`ready_tasks()`、进度统计、`.starryproj` 存档（SHA-256 完整性校验）、Markdown 报告 |
| 多线并行 | `core/parallel.py` | `ThreadPoolExecutor` 分波执行、结果按输入顺序回填、单线异常隔离、整体超时、失败重试、循环依赖防御、`local_worker` 离线确定性执行 |
| 自动更新 | `core/updatecheck.py` | SemVer 比较、平台归一化、`update.json` 结构与 digest 校验、平台资产选择、分块 SHA-256 校验、离线判定 |
| 桌面工作台 | `ui/workbench_dialog.py` | 任务树 + 进度条 + 报告区；规划 / 并行执行 / 保存 / 载入 / 导出 / 检查更新；双击任务看结果明细 |
| 更新清单生成 | `scripts/gen_update_manifest.py` | 只从真实二进制计算哈希；拒绝空清单；本地离线与 GitHub 正式两种模式 |
| CI 编排 | `.github/workflows/update-manifest.yml` | Release published 后下载全部资产 → 生成权威 `update.json` → `--clobber` 回传，可重跑补齐 APK |

### 2.1 整体项目的默认模板

`plan_from_goal(goal)` 生成一个最小可运行的 WorkBuddy 式项目：**三条互不依赖的线并行 + 一条汇总线依赖前三条**，天然形成两波：

```
第一波（并行）   t1 资料盘点[check]   t2 要点提炼[text]   t3 方案草拟[report]
第二波（汇总）   t4 结果复核与汇总[report]  depends=[t1,t2,t3]
```

`run_project()` 按 `ready_tasks()` 逐波调度；依赖失败的下游标 `skipped`，循环依赖不会死循环（防御上限 100 波 + 剩余 pending 收敛）。

### 2.2 CLI 新增参数（12 个）

| 参数 | 作用 |
| --- | --- |
| `--project GOAL` | 把目标拆成整体项目并打印报告（不执行） |
| `--project-load PATH` | 从 `.starryproj` 载入；magic / 版本 / checksum 任一不符即拒绝 |
| `--project-save PATH` | 把项目（含并行执行结果）另存为 `.starryproj` |
| `--parallel` | 分波并行执行 |
| `--workers N` | 并行度（默认 4） |
| `--timeout SEC` | 每波整体超时 |
| `--retries N` | 单线失败重试次数 |
| `--execute` | `chat` 类任务改用真实模型（需 API Key），默认离线 |
| `--update-check` | 检查更新（本地清单 / 环境变量 / 显式 URL / 未配置离线） |
| `--update-manifest PATH` | 本地 `update.json`，完全离线 |
| `--update-url URL` | 远程清单只读抓取（标准库 urllib，6s 超时降级） |
| `--workbench` | 工作台总览：环境 + 整体项目 + 多线并行 + 更新 + 命令速查 |

### 2.3 桌面命令面板新增 6 条

打开工作台、从当前对话规划项目、规划并多线并行执行、保存整体项目、载入整体项目、检查版本更新。命令面板是工作台的快捷入口，业务逻辑不重复实现。

## 三、构建产物（本机真实产出）

| 产物 | 路径 | 大小 / 结构 | 验证 |
| --- | --- | --- | --- |
| Windows CLI EXE | `releases/assets/v13.0.0/windows/星语Starry-CLI-v13.0.0.exe` | 15,928,759 B | PyInstaller 6.22.3 单文件；10 项子进程冒烟 RC=0，`--version` 输出 13.0.0，`--workbench` 实跑 100% |
| Linux / UOS deb | `releases/assets/v13.0.0/linux/星语Starry-CLI-v13.0.0.deb` | 195,294 B / 59 data 文件 / 3 ar 成员 | 独立解析校验：`Version: 13.0.0`、`/usr/bin/starry`、含新增 3 个 core 模块 |
| 离线更新清单 | `releases/assets/v13.0.0/update.json` | 2 个真实资产（windows / linux） | 哈希与资产字节一致；`validate_manifest` 通过 |
| Android APK | `releases/assets/v13.0.0/apk/` | **不含 APK 二进制**，仅 README | 本机缺 JDK 17 / Android SDK / NDK / Gradle / apksigner，不伪造；由 CI 产出，详见该目录 README |

## 四、验证结果（全部可复跑）

```
selftest.py（offscreen 桌面全量）        779 通过 / 0 失败
tests/test_v12_features.py              63 / 63
tests/test_android_v12.py               37 / 37
android/test_app_logic.py               16 / 16
tests/test_v13_features.py             172 / 172   ← 本版新增
合计                                    1067 项通过，0 失败
```

其它门禁：

- `scripts/sync_core.py` → `core/` 与 `android/core/` **44 个文件字节一致**，桌面专属 4 个按白名单排除。
- `scripts/check_core_parity.py --expect-version 13.0.0` → 版本声明 3 处一致 + 全量 Python AST 通过。
- 5 个 GitHub Actions workflow YAML 全部解析通过；`ci.yml` 新增 v12/v13 单测与 Linux deb 构建验证 job。
- 真实 PyQt5 offscreen 工作台冒烟：规划 4 任务 / 树 4 节点 → 并行 2 波 / 进度 100% / 报告含汇总 / 双击看明细。
- 资产与 `dist/` 字节一致；`update.json` 的 sha256/size 与资产文件实测一致。

## 五、本轮反复优化中修掉的真实缺陷

1. **更新生成器把说明文档当资产**：初版按目录名推断平台，导致 `apk/README.md` 被当成 android 资产写进 `update.json`——这属于伪造资产。改为**只按二进制扩展名**判定，并新增 10 条单测锁死该行为（含「空目录拒绝生成」「哈希来自真实字节」）。
2. **测试与发版号耦合**：版本升到 13.0.0 后，v13 单测里以 13.0.0 作为「远端新版本」的用例全部失效。改为 `REMOTE_VERSION = "99.0.0"`，并把 v12 测试中的硬编码版本断言改为动态读取单一真源，避免每次升级都改测试。
3. **损坏项目载入重复报错**：`--project-load` 校验失败时打印两行提示。改为失败即返回、原因只打印一次。
4. **GUI 工作台线程安全**：并行执行默认走本地确定性 worker（毫秒级），用同步执行 + `processEvents()` 刷新，避免引入 QThread 生命周期问题；同时保留「单线异常隔离」在 core 层的兜底。

## 六、已知限制（不夸大）

1. **本机仍无 v13.0 签名 APK**。三端同源代码已就绪并通过门禁，但签名包必须由带 Android 工具链的 CI 在 `v13.0.0` tag 时真实产出；真机 / 模拟器未跑，不能声称实测不闪退。
2. **`update.json` 的 digest 与 `asset.sha256` 是完整性校验，不是签名认证**。清单来源必须可信（HTTPS / GitHub Releases）；生产环境若需防投毒，应再加一层签名验证。
3. 本地离线清单的下载 URL 是按项目既有占位仓库 `yourname/ai-assistant` 拼出的**预期地址**，notes 中已显式标注；fork 后请以 `update-manifest.yml` 生成的正式清单为准。
4. `--execute`（真实模型）只覆盖 `chat` 类任务；默认模板的三条并行线是本地确定性执行，用于保证离线开箱可用。
5. 当前目录不是 git 仓库：workflow 已备好，但需使用者 `git init` + 首次提交 + 关联 remote + 打 tag 才会触发。
6. 历史 `releases/星语Starry-v11.5.0/` 内含 `starry-release.keystore`，公开分发前必须轮换；v12/v13 快照已由 `assert_no_secrets()` 门禁排除敏感文件。

## 七、升级与回滚

- 从 v12 升级：`.starry` 存档格式未变，直接覆盖 EXE / deb 即可；配置与会话目录不变。
- 新增的 `.starryproj` 与 `.starry` 相互独立，互不影响。
- 回滚：旧版 EXE / deb 完整保留在 `releases/星语Starry-v12.0.0/`，历史版本只追加不覆盖。
