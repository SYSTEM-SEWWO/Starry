# 星语 Starry · API 开放文档（v11.3.0）

> 本文档描述 v11.3 **新增的可复用纯逻辑接口**，供开发者在自有项目中调用或二次集成。
> 所有接口位于 `core/`，**零 Qt / 零安卓依赖**，桌面端与安卓端同源共用。
> - 会话标签 / 消息编辑删除 / PDF 导出见 `API开放文档_v11_2.md`
> - 相关性检索 / 多格式导出见 `API开放文档_v11_1.md`
> 下表为 v11.3 增量。

## 1. 消息收藏（Star）

模块：`core/sessions.py`　类：`SessionStore`

收藏以「消息在会话中的下标 `index`」为准（与 `edit_message` / `delete_message` 一致：删除或编辑前序消息会改变后续下标）。

```python
from core.sessions import SessionStore

store = SessionStore()
sid = store.current_id()
n = len(store.messages(sid))

# 收藏 / 取消收藏第 idx 条消息；返回切换后的状态(bool)
starred_now = store.toggle_star(sid, n - 1)   # 最后一条 -> True；再调一次 -> False
# 仅查询（不写入）：未收藏或会话不存在 -> False
print(store.is_starred(sid, n - 1))

# 跨全部会话聚合收藏列表，按会话更新时间倒序
for item in store.list_starred():
    print(item["session_id"], item["title"], item["index"],
          item["role"], item["content"][:40], item["snippet"])
```

### 接口一览

| 方法 | 签名 | 说明 |
|------|------|------|
| `toggle_star` | `toggle_star(sid, index) -> bool \| None` | 切换收藏；返回新状态；会话不存在或越界返回 `None` |
| `is_starred` | `is_starred(sid, index) -> bool` | 是否已收藏；会话不存在返回 `False` |
| `list_starred` | `list_starred() -> List[dict]` | 跨会话收藏聚合，按 `updated` 倒序；每项含 `session_id / title / index / role / content / snippet / updated` |

> 存储：每个会话新增 `"starred": []` 整型下标数组，随 `sessions.json` 落盘；不影响既有 `messages` 结构，对老会话向后兼容。

## 2. AI 摘要缓存

模块：`core/sessions.py`（实例方法）+ 模块级纯函数 `build_summary_prompt`

```python
from core.sessions import SessionStore, build_summary_prompt

store = SessionStore()
sid = store.current_id()
history = store.messages(sid)          # 与 UI 的 history 一致（含系统提示）

# 纯函数：根据历史构造「总结」提示词，自动过滤 system 与空内容
system_prompt, user_prompt = build_summary_prompt(history)
# system_prompt -> "你是摘要助手，请用中文提炼本对话的 3-5 条要点与关键结论……"
# user_prompt   -> "用户：…\n助手：…\n…"（空对话返回兜底文案）

# 把模型返回的摘要缓存进会话（空字符串表示清除）；上限 8000 字
store.set_summary(sid, "1. 讨论了… 2. 结论是…")
print(store.get_summary(sid))          # -> 缓存的摘要文本
```

### 接口一览

| 方法 / 函数 | 签名 | 说明 |
|------|------|------|
| `set_summary` | `set_summary(sid, text) -> bool` | 缓存摘要（截断 8000 字）；会话不存在返回 `False` |
| `get_summary` | `get_summary(sid) -> str` | 读取摘要；缺省返回 `""` |
| `build_summary_prompt` | `build_summary_prompt(messages) -> Tuple[str, str]` | **模块级纯函数**；返回 `(system, user)`；过滤 `role=system` 与空内容；空对话返回兜底 |

> 设计与测试性：`build_summary_prompt` 刻意做成无副作用的纯函数，便于单测与在桌面 / 安卓两端复用同一套提示词。

## 3. 批量导出全部会话

模块：`core/exporter.py`

```python
from core.exporter import export_all_sessions, session_block_markdown, SessionStore

store = SessionStore()

# 合并导出：markdown / json / text / html -> (字符串, 扩展名)
content, ext = export_all_sessions(store, fmt="markdown")   # -> (str, ".md")
content, ext = export_all_sessions(store, fmt="json")       # -> (str, ".json")
content, ext = export_all_sessions(store, fmt="text")       # -> (str, ".txt")
content, ext = export_all_sessions(store, fmt="html")       # -> (str, ".html")

# zip：每会话一个独立 .md + index.md，返回 (bytes, ".zip")
blob, ext = export_all_sessions(store, fmt="zip")           # -> (bytes, ".zip")
with open("星语全部会话.zip", "wb") as f:
    f.write(blob)

# 单会话渲染为 Markdown 章节（标题+元信息+正文，含摘要/标签）
md = session_block_markdown(store.get(sid))
```

### 接口一览

| 方法 | 签名 | 说明 |
|------|------|------|
| `export_all_sessions` | `export_all_sessions(store, fmt="markdown", title="星语 Starry · 全部会话") -> Tuple[str\|bytes, str]` | 合并导出全部会话；`fmt∈{markdown,json,text,html}` 返回 `(字符串, 扩展名)`；`fmt=="zip"` 返回 `(bytes, ".zip")` |
| `session_block_markdown` | `session_block_markdown(session) -> str` | 单会话渲染为 Markdown 章节（含 `> 摘要` / `> 标签` 元信息） |

> 兼容性：`store` 只需提供 `_sessions()` 或 `data["sessions"]` 之一；`title` 自定义导出大标题。`zip` 模式内部调用 `_export_all_zip`，每会话独立文件便于归档检索。

## 4. 桌面端命令面板入口（Ctrl+K）

v11.3 在桌面端命令面板新增 4 条一键命令，均基于上述 `core` 接口：

| 命令 id | 图标 | 标题 | 行为 |
|---------|------|------|------|
| `star_last` | ⭐ | 收藏最后回复 | `toggle_star(sid, len-1)` |
| `starred` | 📌 | 收藏夹 | 打开跨会话收藏列表，双击跳转 |
| `summary` | 📋 | AI 总结当前会话 | `build_summary_prompt` → 流式生成 → `set_summary` |
| `export_all` | 📦 | 批量导出全部会话 | `export_all_sessions` → 保存文件 |

> 安卓端（BeeWare/Toga）同样调用同一份 `core`，上述 `core` 接口在安卓构建中已一并打包。

## 5. 端到端自测

```bash
python test_v11_3_pc.py            # 4/4 通过：star / summary / build_summary_prompt / export_all(zip 字节流)
python android/test_app_logic.py   # 安卓逻辑无回归
```

> 版本约束：v11.3.0 起 `APP_VERSION="11.3.0"`（桌面 `core/config.py` 与安卓 `android/core/config.py` 同步）。调用 `export_all_sessions(fmt="zip")` 需标准库 `zipfile`（内置，无额外依赖）。
