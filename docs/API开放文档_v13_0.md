# API 开放文档 · 星语 Starry v13.0.0

> 面向二次开发者。v13 新增的三个 `core` 模块均为**纯标准库、零 GUI、零网络、零第三方依赖**，
> 可直接 `from core import project, parallel, updatecheck` 使用，也可从 `core.__getattr__` 懒加载。
> 本文档只描述 v13 新增接口；v12 及更早接口见 `docs/API开放文档_v12_0.md`。

---

## 0. 通用约定

| 约定 | 说明 |
| --- | --- |
| 纯函数 | `core.project` 的所有变更函数**不修改入参**，返回新的 project 字典（内部用 JSON 深拷贝） |
| 零 I/O | 除 `updatecheck.load_manifest(path)` / `verify_asset_sha256(path, ...)` 与 `parallel.local_worker` 的 `os.path.exists` 外，三层不读写文件 |
| 时间戳 | 由调用方传入，模块内不取当前时间（保证确定性、可单测） |
| 异常策略 | 解析/校验失败抛 `ValueError`；执行失败**不抛**，转成报告里的 `{ok:False, error}` |
| 序列化 | 所有结构均为 JSON 可序列化对象 |
| 三端同源 | 三个模块同时存在于 `core/` 与 `android/core/`，由 `scripts/check_core_parity.py` 强制字节一致 |

```python
from core import project, parallel, updatecheck
# 或
import core
core.project          # PEP 562 懒加载
```

---

## 1. `core.project` · 整体项目

### 常量

```python
PROJECT_MAGIC   = "STARRY-PROJECT"
PROJECT_VERSION = 1
TASK_STATES     = ("pending", "running", "done", "failed", "skipped")
VALID_KINDS     = ("text", "check", "report", "chat")
```

`kind` 语义：`text` 本地文本统计 / `check` 本地校验 / `report` 生成报告片段 /
`chat` 需调用模型（默认明确报错，只有 `--execute` 才启用）。

### 构造函数

```python
new_task(title, kind="text", payload=None, depends=None, task_id=None) -> dict
```
- `payload` 为 dict 时原样深拷贝；非 dict 且非空时包装为 `{"text": str(payload)}`；空则 `{}`。
- 非法 `kind` 自动回退 `text`；`depends` 统一转成 `str` 列表；`task_id` 缺省用标题 slug。
- 返回字段：`id / title / kind / status / depends / payload / result / error / ts`。

```python
create_project(title, goal="", tasks=None, meta=None) -> dict
```
- `tasks` 元素可为 `str` 或 `dict`（dict 可带 `id/title/kind/payload/depends/status/result/error/ts`）。
- 重复 `id` 自动追加 `-2`、`-3`…。
- 返回：`{"title", "goal", "created", "meta", "tasks"}`。

### 变更与查询（均返回新对象）

```python
add_task(project, title, kind="text", payload=None, depends=None, task_id=None) -> dict
update_task(project, task_id, *, status=None, result=None, error=None, ts=None) -> dict
find_task(project, task_id) -> dict | None
ready_tasks(project) -> list[dict]
project_progress(project) -> dict
```

- `update_task` 找不到任务时**返回新拷贝，不抛异常**；非法 status 回退为 `failed`。
- `ready_tasks` 返回「自身 pending 且 `depends` 全部 `done`」的任务，天然形成分波并行。
- `project_progress` 返回：
  `total / done / failed / running / pending / skipped / finished / percent / complete`；
  空项目返回全 0 且 `percent=0`，不抛异常。

### 规划模板

```python
plan_from_goal(goal, steps=None, title=None) -> dict
```
默认生成 4 个任务（`t1`~`t4`）：前三条 `check/text/report` 互不依赖，
` t4 结果复核与汇总` 依赖 `t1,t2,t3`。`steps` 可传 `list[str]` 或
`list[(name, kind, payload)]`；无论传入几步，最后都会追加一条汇总任务。
`meta` 记录 `planner="local-template"` 与并行线数。

> 这是**确定性模板，不是智能规划**：离线、可测、可复现，但不会根据目标动态判断拆几条线。

### `.starryproj` 存档

```python
project_digest(project) -> str          # 规范化 JSON 的 SHA-256 hex
pack_project(project) -> str            # UTF-8 JSON 文本
unpack_project(text) -> dict            # 失败抛 ValueError
```

信封结构（与 v12 `.starry` 同款语义）：

```json
{
  "magic": "STARRY-PROJECT",
  "version": 1,
  "payload": { "...项目字典..." },
  "checksum": "<sha256 of payload>"
}
```

`unpack_project` 会拒绝：非法 JSON、非对象根节点、magic 不符、
version 非正整数或大于 `PROJECT_VERSION`、缺 `tasks` 列表、checksum 不匹配。
**checksum 是完整性校验，不是签名认证。**

### 渲染

```python
render_project_markdown(project, report=None) -> str
```
生成标题、目标、进度、任务表格；`report` 非空时附「多线并行执行」段落。

---

## 2. `core.parallel` · 多线并行

```python
DEFAULT_WORKERS = 4
```

```python
split_work(items, lanes) -> list[list]
```
轮转分配；`lanes<=0` 回退 1；空输入返回 `lanes` 个空列表。

```python
local_worker(job) -> dict
```
默认离线确定性 worker，零联网、零模型调用：

| kind | 返回 |
| --- | --- |
| `text` | `{"type":"text","chars","lines","words","keywords"}` |
| `check` | `{"type":"check","passed","checks"}`；`payload.path` 存在时附路径存在性 |
| `report` | `{"type":"report","markdown"}` |
| `chat` | **抛 `RuntimeError`**（需模型与 API Key） |

> 注意：`check` 的 `passed=False` 表示「校验结论为不通过」，worker 本身**没有失败**，
> 因此 `run_parallel` 记 `ok=True`。需要判断结论请读 `value["passed"]`。

```python
run_parallel(jobs, worker=None, max_workers=4, timeout=None, retries=0) -> dict
```
- `jobs`: `list[dict]`，建议含 `id / title`，可含 `kind / payload`。
- `worker`: `callable(job) -> JSON 可序列化值`；默认 `local_worker`。
- `timeout`: 每波整体超时秒数，`None` 不限。超时用
  `shutdown(wait=False, cancel_futures=True)`，不等待残留线程。
- `retries`: 每条线失败后的**额外**重试次数。
- 返回：
  ```python
  {
    "results": [{"id","title","ok","value","error"}, ...],  # 按输入顺序
    "ok": int, "failed": int, "total": int,
    "workers": int, "elapsed_ms": int,
    "timed_out": bool, "order": [id, ...]
  }
  ```
- **不抛异常**：worker 异常被收敛为 `ok=False` + `"RuntimeError: ..."`。

```python
run_project(project, worker=None, max_workers=4, timeout=None, retries=0)
    -> (new_project, list[report])
```
按 `ready_tasks()` **分波并行**；每波先把任务置 `running`，执行后按 `ok` 置
`done` / `failed` 并回填 `result` / `error`；剩余 pending 统一标 `skipped`
（原因「依赖未完成或存在循环依赖」）。防御上限 100 波，杜绝死循环。
不修改传入的 project。

```python
merge_results(report, title="多线并行汇总") -> str
```
生成 Markdown 表格（序号 / 线 / 状态 / 结果或错误），错误与换行做表格安全转义。

---

## 3. `core.updatecheck` · 自动更新

### 常量

```python
UPDATE_MAGIC     = "STARRY-UPDATE"
MANIFEST_VERSION = 1
PLATFORMS        = ("windows", "linux", "android", "macos")
```

### 版本与平台

```python
normalize_platform(platform) -> str   # win32/exe→windows, uos/deb→linux, apk→android, darwin→macos
parse_version(text) -> tuple[int,...] # "v13.2.1-beta" → (13,2,1)
compare_versions(a, b) -> int         # a>b → 1, == → 0, < → -1（自动补零）
is_newer(remote, current) -> bool
```

### 清单

```python
manifest_digest(manifest) -> str       # 对不含 digest 字段的规范化 JSON 算 SHA-256
build_manifest(app_version, assets=None, notes="", released_at=None, repo_url="") -> dict
validate_manifest(obj) -> (ok: bool, reason: str)
select_asset(manifest, platform) -> dict | None
verify_asset_sha256(path, expected) -> bool
check_update(current, manifest, platform="windows") -> dict
configured_manifest_url() -> str
load_manifest(path) -> dict            # 失败抛 ValueError
```

`assets` 契约为 **`list[dict]`**，每项必须含：

| 字段 | 要求 |
| --- | --- |
| `platform` | 可归一化为 `PLATFORMS` 之一 |
| `name` | 非空字符串 |
| `url` | 以 `http://` 或 `https://` 开头 |
| `sha256` | 64 位十六进制 |
| `size` | 非负整数 |

`check_update` 返回：

```python
{
  "current": str, "latest": str, "manifest_valid": bool,
  "update_available": bool, "asset": dict | None,
  "reason": str, "platform": str
}
```
任何异常都收敛为「不可判定」（`manifest_valid=False`），**不抛**。

`update.json` 完整格式：

```json
{
  "magic": "STARRY-UPDATE", "schema": 1,
  "app_version": "13.0.0",
  "assets": [{"platform":"windows","name":"...exe",
              "url":"https://...","sha256":"<64 hex>","size":123}],
  "notes": "...", "released_at": "2026-11-07",
  "repo_url": "https://github.com/owner/repo",
  "digest": "<sha256 of the object above without digest>"
}
```

> **安全边界**：`digest` 与 `asset.sha256` 都是完整性校验，不是签名认证。
> 清单来源必须可信（HTTPS / GitHub Releases）；生产环境建议再加签名验证。
> 本模块**不会**下载或替换任何程序。

### 环境变量

| 变量 | 作用 | 默认 |
| --- | --- | --- |
| `STARRY_UPDATE_URL` | 远程更新清单 URL；为空即离线模式，不发起任何网络请求 | 空 |
| `GITHUB_REPOSITORY` | `gen_update_manifest.py` 拼下载 URL 时使用 | 见脚本 |
| `STARRY_DATA_DIR` | v12 契约，仅影响 gateway 统计/预算数据落盘 | `~/.starry` |
| `PLAYWRIGHT_BROWSERS_PATH` | v12 契约，Chromium 内核探测 | 平台默认 |

---

## 4. CLI 契约（`core.cli` / `starry_cli.py` / EXE / deb 的 `starry`）

### v13 参数

| 参数 | 类型 | 说明 |
| --- | --- | --- |
| `--project GOAL` | str | 生成整体项目并打印报告，不执行 |
| `--project-load PATH` | path | 载入 `.starryproj`；校验失败 `rc=2` |
| `--project-save PATH` | path | 保存项目（可保存执行结果） |
| `--parallel` | flag | 分波并行执行 |
| `--workers N` | int | 并行度，默认 4 |
| `--timeout SEC` | float | 每波整体超时 |
| `--retries N` | int | 单线失败重试 |
| `--execute` | flag | `chat` 任务走真实模型（需 API Key） |
| `--update-check` | flag | 检查更新 |
| `--update-manifest PATH` | path | 本地清单，完全离线 |
| `--update-url URL` | str | 远程清单只读 GET（6s 超时，1 MiB 上限） |
| `--workbench` | flag | 工作台总览（五段 Markdown） |

### 退出码

| rc | 含义 |
| --- | --- |
| 0 | 成功（包括「没有新版本」「未配置更新源」等确定性结论） |
| 2 | 项目载入/保存失败、清单读取失败、配置错误 |
| 其它 | argparse 参数错误 |

### 组合示例

```bash
starry --project "调研并撰写发版方案"                      # 只规划
starry --project "..." --parallel --workers 4 --retries 1  # 分波并行
starry --project "..." --parallel --project-save p.starryproj
starry --project-load p.starryproj --parallel             # 只跑剩余 pending
starry --update-check --update-manifest update.json        # 离线判定
starry --update-check --update-url https://.../update.json
starry --workbench                                        # 一站式总览
```

> 载入已执行完的项目再 `--parallel` 不会重复执行：`ready_tasks()` 为空，波次为 0。

---

## 5. 桌面工作台接口

```python
from ui.workbench_dialog import WorkbenchDialog
dlg = WorkbenchDialog(parent=None, initial_goal="目标文本")
```

| 成员 | 说明 |
| --- | --- |
| `dlg.project` | 当前项目字典或 `None` |
| `dlg.waves` | 每波并行报告列表 |
| `dlg.report` | 合并后的总报告 |
| `dlg._on_plan()` / `_on_run()` | 规划 / 分波并行执行（同步，本地 worker 毫秒级） |
| `dlg._on_save()` / `_on_load()` / `_on_export()` / `_on_update_check()` | 文件对话框动作 |

命令面板 ID：`workbench` / `project_plan` / `project_run` /
`project_save` / `project_load` / `update_check`（`app/assistant.py::_palette_commands`）。

---

## 6. 更新清单生成器

```bash
python scripts/gen_update_manifest.py --version 13.0.0 \
    [--assets-dir DIR] [--out PATH] [--repo owner/name] \
    [--notes TEXT] [--min-assets N] [--online]
```

| 参数 | 默认 | 说明 |
| --- | --- | --- |
| `--version` | 必需 | 不带 v 前缀 |
| `--assets-dir` | `releases/assets/v<version>` | 递归扫描 |
| `--out` | `<assets-dir>/update.json` | 输出路径 |
| `--repo` | `GITHUB_REPOSITORY` → `yourname/ai-assistant` | 拼下载 URL |
| `--min-assets` | 1 | 少于该数直接失败，绝不生成空清单 |
| `--online` | 关 | 正式模式；开启时拒绝占位仓库 |

平台判定**只按扩展名**：`.exe→windows`、`.deb/.appimage→linux`、
`.apk→android`、`.dmg/.pkg→macos`。`README.md` / `update.json` / 校验和一律跳过。
同平台多个资产保留体积最大者，行为确定。

---

## 7. 打包接入契约

| 位置 | 内容 |
| --- | --- |
| `core/__init__.py::_LAZY_EXPORTS` | `project` / `parallel` / `updatecheck` 三项懒导出 |
| `starry_cli.spec::_HIDDEN` | `core.project` / `core.parallel` / `core.updatecheck` |
| `scripts/build_deb.py::_collect_sources()` | 自动递归收集 `core/*.py`，3 个新模块随 deb 分发 |
| `scripts/sync_core.py` | 三端同步，桌面专属白名单仍为 4 个模块 |
| `.github/workflows/update-manifest.yml` | Release published 后生成权威清单 |

改动任一模块后必须重跑：

```bash
python scripts/sync_core.py
python scripts/check_core_parity.py --expect-version 13.0.0
python tests/test_v13_features.py
```

---

## 8. 最小可运行示例

```python
from core import project as pj, parallel as pl, updatecheck as uc

# 1) 整体项目 → 分波并行
p = pj.plan_from_goal("调研并撰写 v13 发版方案")
done, waves = pl.run_project(p, worker=pl.local_worker, max_workers=4)
print(pj.project_progress(done)["percent"])        # 100
print(len(waves))                                   # 2 波
open("p.starryproj", "w", encoding="utf-8").write(pj.pack_project(done))

# 2) 更新清单
m = uc.build_manifest("13.0.0", assets=[{
    "platform": "windows", "name": "starry.exe",
    "url": "https://example.com/s.exe", "sha256": "a"*64, "size": 1}])
res = uc.check_update("12.0.0", m, "win32")
print(res["update_available"], res["asset"]["name"])
```
