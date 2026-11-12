# 星语 Starry · API 开放文档（v11.2.0）

> 本文档描述 v11.2 新增的**可复用纯逻辑接口**，供开发者在自有项目中调用或二次集成。
> 所有接口位于 `core/`，**零 Qt / 零安卓依赖**，桌面端与安卓端同源共用。
> （v11.1 的检索/导出接口见 `API开放文档_v11_1.md`，下表为 v11.2 增量。）

## 1. 会话标签（Tags）

模块：`core/sessions.py`

```python
from core.sessions import SessionStore

store = SessionStore()
sid = store.create("工作周报")["id"]

# 设置标签：list / 逗号分隔字符串均可，自动去重、截断
store.set_tags(sid, ["工作", "重要", "重要"])   # -> ["工作", "重要"]
store.set_tags(sid, "学习, 作业")               # -> ["学习", "作业"]

# 聚合全部标签及计数，按次数降序、名称升序
print(store.list_tags())          # [("工作", 1), ("学习", 1), ...]

# 按标签过滤（不区分大小写）
for s in store.list(tag="工作"):
    print(s["title"], s["tags"])

# 检索时一并按标签过滤
for r in store.search_ranked("周报", tag="工作"):
    print(r["title"], r["score"], r["tags"])
```

### 接口一览

| 方法 | 签名 | 说明 |
|------|------|------|
| `set_tags` | `set_tags(session_id, tags) -> bool` | 归一化并写入标签；返回 False 表示会话不存在 |
| `list_tags` | `list_tags() -> List[Tuple[str, int]]` | 全部标签及出现次数，按 `(−count, name)` 排序 |
| `list` | `list(tag=None) -> List[dict]` | 会话摘要；`tag` 非空时按标签过滤；每条含 `tags` 字段 |
| `search_ranked` | `search_ranked(query, top_k=20, tag=None)` | 相关性检索；新增 `tag` 过滤参数；结果含 `tags` 字段 |

> 归一化规则（`_normalize_tags`）：list 或 `,，、;；空格` 分隔字符串 → 去空白 → 去重（保留首序、大小写不敏感）→ 单标签截断 24 字 → 单会话上限 12 个。

## 2. 消息编辑 / 删除

模块：`core/sessions.py`

```python
sid = store.current_id()
msgs = store.messages(sid)        # 与 history 一一对应（含系统提示）

# 修改第 idx 条消息内容（保留 role）；越界 / 系统提示 → 返回 False
store.edit_message(sid, 1, "修改后的提问")
# 删除第 idx 条消息；越界 → 返回 False
store.delete_message(sid, len(msgs) - 1)
```

### 接口一览

| 方法 | 签名 | 说明 |
|------|------|------|
| `edit_message` | `edit_message(sid, index, content) -> list \| False` | 改内容；系统提示（role=system）不可改；越界返回 False |
| `delete_message` | `delete_message(sid, index) -> list \| False` | 删消息；越界返回 False |

> 二者均落在 `sessions.json` 并刷新 `updated`；UI 侧删除「最后一条」需同步 `app.history`（桌面已封装 `AssistantApp.delete_last_message()`）。

## 3. PDF 导出

模块：`core/exporter.py`

```python
from core.exporter import (conversation_to_pdf, available_formats,
                           export_conversation)

# 环境是否提供 PDF（依赖可选包 weasyprint）
if "pdf" in available_formats():
    data: bytes = conversation_to_pdf(history, title="对话",
                                     model="gpt", provider_name="OpenAI")
    with open("对话.pdf", "wb") as f:
        f.write(data)
```

### 接口一览

| 方法 | 签名 | 说明 |
|------|------|------|
| `conversation_to_pdf` | `conversation_to_pdf(history, title, model, provider_name) -> bytes` | 复用 HTML 版式经 WeasyPrint 渲染；缺依赖时抛 `RuntimeError` |
| `available_formats` | `available_formats() -> List[str]` | 当前环境可用格式键（`pdf` 仅当 weasyprint 已装） |
| `export_conversation` | `export_conversation(history, fmt="markdown", **kwargs) -> str \| bytes` | v11.2 起 `fmt` 支持 `"pdf"`（返回字节流，其余返回字符串） |

> 安全：PDF 由已转义的 HTML 生成，内容与导出头不引入外部脚本；weasyprint 仅在函数内 guard 导入，安卓端 import `exporter` 不触发缺失报错。

## 4. 端到端自测

```bash
python test_v11_2.py             # 21/21 通过：标签解析/过滤 / 消息编辑·删除保护 / PDF 字节流
python android/test_app_logic.py # 14/14 通过（安卓逻辑无回归）
```
