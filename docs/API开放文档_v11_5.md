# 星语 Starry · API 开放文档（V11.5.0）

> 适用版本：**11.5.0**（2026-11-07）。本版新增两层对外能力：
> **`core/insights.py` 对话洞察纯函数层**（分支对比 / 会话合并 / 统计）与
> **Windows EXE 交付链路**。所有纯逻辑零 GUI 框架依赖，桌面与安卓 `core/`
> 字节一致；外部可直接 import 使用，无需启动 Qt 或 Toga。

## 1. `core.insights` —— 对话洞察纯函数层（新建）

导入：`from core import insights` 或 `from core.insights import diff_sessions, ...`

设计约定：**绝不修改入参**（返回新对象），不 import `core.sessions`（避免与
`SessionStore.merge_into` 循环依赖），消息文本提取自带多模态兼容实现。

### 1.1 基础工具

| 接口 | 签名 | 返回 | 说明 |
|---|---|---|---|
| `message_content` | `(message) → str` | 纯文本 | 兼容 `str` / `dict.content` 为 `str` / 多模态 `list[dict]`（取 `text`/`content`）/ `None` |
| `estimate_tokens` | `(text) → int` | 估算 token | CJK 每字约 1 token，其余约 4 字符 ≈ 1 token；**离线相对量级参考，非计费值** |
| `common_prefix_len` | `(a_messages, b_messages) → int` | 最长共同前缀长度 | 按 `(role, 规范化文本)` 指纹判定 |

### 1.2 分支对比

```python
diff_sessions(session_a, session_b, max_chars=140) -> dict
```

返回字段：

| 字段 | 类型 | 说明 |
|---|---|---|
| `a_id` / `b_id` / `a_title` / `b_title` | str | 会话标识与标题 |
| `a_count` / `b_count` | int | 消息总数 |
| `common_prefix` | int | 最长共同前缀长度（V11.4 分支的天然锚点） |
| `modified` | list[dict] | 前缀之后**同位置**内容不同的项：`{index, a_role, a_text, b_role, b_text}` |
| `a_only` / `b_only` | list[dict] | 各自多出的尾部：`{index, role, text}` |
| `identical` | bool | 两序列是否完全一致 |
| `similarity` | float | `2*common/(a_count+b_count)`，0~1 |

> 算法刻意选择「最长共同前缀 + 同位置对齐」而非通用 LCS：对「从某点分叉后
> 各自续写」的真实分支场景结果更稳定、可读。`max_chars` 控制差异文本截断。

```python
from core.insights import diff_sessions, format_diff_markdown
d = diff_sessions(store.get(sid_a), store.get(sid_b))
print("共同前缀", d["common_prefix"], "相似度", d["similarity"])
print(format_diff_markdown(d))          # 可直接展示 / 另存的 Markdown
```

### 1.3 会话合并

```python
merge_messages(a_messages, b_messages, dedup=True, common_prefix=None)
    -> (merged: list[dict], report: dict)
```

| 参数 | 说明 |
|---|---|
| `dedup` | `True` 时跳过指纹已在结果序列中出现过的 B 条目 |
| `common_prefix` | `None` → 自动求最长共同前缀并**跳过 B 的前 N 条**（分支合并不会重复追加前缀）；显式传入可覆盖 |

`report` 字段：

| 字段 | 说明 |
|---|---|
| `added` / `skipped` / `total` | 实际追加数 / 跳过数 / 合并后总数 |
| `common_prefix` | 本次采用的前缀长度 |
| `mapping` | `{B 原下标: 合并后新下标}`，**供收藏下标重映射** |

### 1.4 `SessionStore.merge_into`（`core/sessions.py` 新增方法）

```python
merge_into(target_id, source_id, dedup=True) -> (ok: bool, report: dict)
```

- 复用 `merge_messages`，自动识别共同前缀；
- `source.starred` 按 `report["mapping"]` **重映射**后并入 target（去重排序），收藏不因下标变化错位；
- `tags` 合并去重；**source 会话不删除**（保留可回溯）；
- target 置为 `current` 并落库；会话不存在 / 自合并返回 `(False, {})`；
- `report` 额外带 `tags_merged`、`starred_total`。

```python
ok, report = store.merge_into(current_id, branch_id)
# report: {"added": 2, "skipped": 0, "total": 6, "common_prefix": 3,
#          "mapping": {...}, "tags_merged": 2, "starred_total": 2}
```

### 1.5 统计

```python
session_stats(session)      -> dict      # 单会话
overview_stats(sessions)    -> dict      # 全局聚合
```

`session_stats` 字段：`id / title / messages / roles / user / assistant /
system / other / chars / tokens / avg_chars / starred / has_summary / tags /
is_branch / branched_from / pinned / created / updated`。

`overview_stats` 字段：`sessions / messages / user / assistant / system /
other / chars / tokens / starred / with_summary / branches / tagged /
unique_tags / pinned / avg_messages / busiest`（`busiest` 为 `{id,title,messages}` 或 `None`）。

```python
format_stats_markdown(stats, overview=None) -> str   # 渲染为 Markdown 表格
```

## 2. Windows EXE 交付链路（新增 / 加固）

| 位置 | 变更 | 对外意义 |
|---|---|---|
| `starry_cli.py` | 入口对 `sys.stdout/stderr` 执行 `reconfigure(errors="replace")` | 英文代码页下打印中文不再崩溃 |
| `core.cli._emit(out, text)` | 捕获 `UnicodeEncodeError` → 按目标流编码 `replace` 重写 → 最后退 ASCII | 打印层绝不因编码而退出，三端同源 |
| `scripts/build_windows_cli.ps1` | 幂等 venv + 读 `APP_VERSION` + `--version`/`--platform` 自检 + 校验退出码 | 本地一键产出并自证可用 |
| `.github/workflows/build-windows.yml` | 推 `v*` tag → `windows-latest` 打包 → 自检 → Artifact → 追加 Release 资产 | 一个 tag 同时拿到 APK + EXE |
| `docs/Windows_EXE_构建指南.md` | 三种构建方式 / Wine 踩坑 / 验证清单 / FAQ | 完整使用指南 |

> `softprops/action-gh-release` 使用 `append_body: true` 且不设 `name`，
> 因此与 `build-android.yml` 并行触发时**只追加资产、不覆盖** Release 标题与说明。

## 3. 桌面命令面板（`Ctrl+K`）新增命令

| 命令 id | 图标 | 标题 | 行为 |
|---|---|---|---|
| `insight` | 📊 | 对话统计洞察 | 当前会话 + 全局统计，弹 `InsightDialog` |
| `diff` | 🔀 | 分支对比 | 选另一会话 → `diff_sessions` → 展示差异 |
| `merge` | 🧬 | 会话合并 | 选来源会话 → 确认 → `merge_into` → 重载渲染 |

`ui/insight_dialog.py`：

```python
InsightDialog(markdown, title="📊 对话洞察", parent=None)
```

只读 Markdown 面板，支持「复制内容」「另存为 .md」；`setMarkdown` 不可用时
自动退化 `setPlainText`（不会被老版本 PyQt5 拖崩）。

## 4. 边界与向后兼容

| 场景 | 行为 |
|---|---|
| 会话为空 / 消息为空 | `diff_sessions({}, {})` 返回 `identical=True`；`overview_stats([])` 返回全 0、`busiest=None` |
| 越界 / 不存在的会话 | `merge_into` 返回 `(False, {})`，不抛异常 |
| 自合并 | 显式拒绝 |
| 多模态消息 | 取其中文本参与指纹与统计，图片等非文本部分忽略 |
| 旧 `sessions.json` | 无 `branched_from` / `starred` / `summary` 字段时按空值处理，无需迁移 |
| 纯逻辑层依赖 | `core/insights.py` 仅用标准库；AST 校验无 GUI 框架 import |

## 5. 最小完整示例

```python
from core.sessions import SessionStore
from core.insights import (diff_sessions, format_diff_markdown,
                           session_stats, overview_stats,
                           format_stats_markdown)

store = SessionStore()
sid = store.current_id()
branch = store.branch_from(sid, 2, title="分支")   # V11.4 能力
store.append({"role": "user", "content": "换个角度"}, branch["id"])

print(format_diff_markdown(diff_sessions(store.get(sid), store.get(branch["id"]))))
print(format_stats_markdown(session_stats(store.get(sid)),
                            overview_stats(store.data["sessions"])))
ok, report = store.merge_into(sid, branch["id"])
print("merged:", ok, report["added"], "messages")
```
