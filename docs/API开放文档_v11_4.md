# 星语 Starry · API 开放文档（v11.4.0）

> 本文档描述 v11.4 **新增的可复用纯逻辑接口**，供开发者在自有项目中调用或二次集成。
> 所有接口位于 `core/`，**零 Qt / 零安卓依赖**，桌面端与安卓端同源共用。
> - 消息收藏 / AI 摘要 / 批量导出见 `API开放文档_v11_3.md`
> - 会话标签 / 消息编辑删除 / PDF 导出见 `API开放文档_v11_2.md`
> - 相关性检索 / 多格式导出见 `API开放文档_v11_1.md`
> 下表为 v11.4 增量：**消息引用（Quote）** 与 **分支对话（Branch）**。

## 1. 消息引用（Quote）

模块：`core/sessions.py`（模块级纯函数 + `SessionStore` 便捷方法）

引用以「消息在会话中的下标 `index`」为准（与 `edit_message` / `delete_message` / `toggle_star` 一致）。
核心是**两个无副作用的纯函数**，便于单测与桌面 / 安卓两端复用。

```python
from core.sessions import (SessionStore, format_quote, build_quoted_prompt,
                           QUOTE_MAX_CHARS)

store = SessionStore()
sid = store.current_id()
history = store.messages(sid)

# 纯函数①：把某条消息格式化成 Markdown 引用块
quote = format_quote(history[2], index=2)
# -> "> 【引用 #2 · 助手】\n> 量子计算利用叠加态与纠缠…"
#    过滤 system / 空内容（返回 ""）；超长按 QUOTE_MAX_CHARS 截断；多行逐行加 "> "

# 纯函数②：把引用块与用户追问拼成一条带上下文的 user 消息 content
content = build_quoted_prompt(quote, "那它和经典计算到底有什么区别？")
# 结果含引用块 + 分隔线 + "请结合引用内容作答" 指令 + 新问题
# 无引用 / 无新问题 / 全空均有安全兜底

# 直接放进 messages 发送给模型：
messages = [{"role": "system", "content": "你是助手"},
            {"role": "user", "content": content}]
```

### 便捷方法（内部委托上面的纯函数）

```python
m = store.get_message(sid, 2)      # 取第 2 条消息 dict；越界/会话不存在 -> None
q = store.quote_block(sid, 2)      # 等价于 format_quote(get_message(sid,2), index=2)
                                   # 非法索引 / 系统提示 / 空内容 -> ""
```

### 接口一览

| 方法 / 函数 | 签名 | 说明 |
|------|------|------|
| `format_quote` | `format_quote(message, index=0, max_chars=QUOTE_MAX_CHARS) -> str` | **模块级纯函数**；生成 Markdown 引用块；过滤 `system` 与空内容；超长截断加 `…`；多行逐行 `>` 前缀；多模态 content 取文本 |
| `build_quoted_prompt` | `build_quoted_prompt(quote_text, user_text) -> str` | **模块级纯函数**；组合引用块与用户新问题；空引用→原样返回输入；无新问题→续写提示；全空→`""` |
| `get_message` | `get_message(sid, index) -> dict \| None` | 取单条消息；越界 / 会话不存在返回 `None` |
| `quote_block` | `quote_block(sid, index, max_chars=QUOTE_MAX_CHARS) -> str` | 生成引用块文本；非法返回 `""` |
| `QUOTE_MAX_CHARS` | 常量 `= 300` | 引用片段最大字符数，防止把整段长回答塞进输入上下文 |

## 2. 分支对话（Branch）

模块：`core/sessions.py`　类：`SessionStore`

从会话的**某条消息（含）处**复制前缀历史，生成一条全新的会话继续对话，原会话保持不变。
典型用途：对某个回答不满意，想从更早的问答点换一个方向追问，又不覆盖原对话。

```python
from core.sessions import SessionStore

store = SessionStore()
sid = store.current_id()
# 假设 messages = [system, user, assistant, user, assistant]（5 条）

# 从第 2 条（含）处分支：新会话 messages = 复制前 3 条
new = store.branch_from(sid, 2, title="量子新分支")
print(new["id"], new["title"])         # 新会话 id / "量子新分支"
print(len(new["messages"]))             # 3（含前置 system）
print(new["branched_from"])             # {'session_id': sid, 'index': 2}
print(store.current_id() == new["id"])  # True —— 新会话已置为 current
print(len(store.messages(sid)))         # 5 —— 原会话未变

# 列出派生分支
for b in store.list_branches(sid):
    print(b["id"], b["title"], b["index"], b["from"])

# 缺省标题自动为 "分支 · <原标题>"；越界 / 负索引 / 会话不存在 -> None
assert store.branch_from(sid, 99) is None
```

### 接口一览

| 方法 | 签名 | 说明 |
|------|------|------|
| `branch_from` | `branch_from(sid, index, title=None) -> dict \| None` | 复制 `messages[:index+1]` 到新会话（逐条浅拷贝）；继承 `tags`；`starred` 仅保留下标 `<= index`；记录 `branched_from={session_id,index}`；新会话自动 `current` 并落库；越界 / 不存在返回 `None` |
| `list_branches` | `list_branches(sid=None) -> List[dict]` | 列出派生分支摘要；`sid` 为空则列出全部；每项含 `id / title / from / index / updated`，按 `updated` 倒序 |

### 会话数据结构增量

分支会话新增字段（旧会话无此字段，全部用 `.get()` 读取，**向后兼容**）：

```json
{
  "id": "s_...",
  "title": "分支 · 量子计算",
  "messages": ["...复制的前缀消息..."],
  "tags": ["物理", "计算"],
  "starred": [2],
  "summary": "",
  "branched_from": {"session_id": "s_...", "index": 2}
}
```

> 设计与隔离性：`branch_from` 对每条消息做**浅拷贝**，改动分支消息不会污染原会话；
> `starred` 按下标过滤避免引用到被截断的消息；`branched_from` 提供溯源，`list_branches` 据此聚合。

## 3. 桌面端命令面板入口（Ctrl+K）

v11.4 在桌面端命令面板新增 4 条一键命令，均基于上述 `core` 接口：

| 命令 id | 图标 | 标题 | 行为 |
|---------|------|------|------|
| `quote_pick` | 💬 | 引用消息追问 | 打开消息选择器选任意一条 + 输入框提问 → `build_quoted_prompt` → 发送 |
| `quote_last` | ↩️ | 引用最后回复 | 快速引用末条 AI 回复并追问 |
| `branch` | 🌿 | 分支对话 | 消息选择器选分支点 → `branch_from` → 重载渲染新会话 |
| `branches` | 🌱 | 分支列表 | `list_branches` → 选择并跳转派生分支 |

配套 UI：`ui/message_picker_dialog.py`（`MessagePickerDialog`，`mode="quote"|"branch"` 两模式共用的消息选择器，`picked(int,str)` 信号，样式与收藏夹一致）。

> 索引一致性：打开选择器前调用 `_save_current_session()`，确保 UI 的 `history` 与 `sessions.messages` 下标一致（启动时可能补 `system` 提示但未写回，会造成偏移）。

> 安卓端（BeeWare/Toga）同样打包同一份 `core/sessions.py`，上述 `core` 接口在安卓构建中已一并可用（安卓当前为单会话流式 UI，未接入多会话引用/分支界面，但逻辑同源）。

## 4. 端到端自测

```bash
python3.11 -m pytest test_v11_4_pc.py -q   # 9/9 通过：引用格式化/过滤/截断/多行/多模态、
                                           # build_quoted_prompt 各分支、quote_block/get_message 越界、
                                           # branch_from 复制前缀/元数据继承/深拷贝隔离/越界/持久化、
                                           # list_branches 与旧数据向后兼容
python3.11 -m pytest test_v11_3_pc.py -q   # V11.3 回归 4/4
python3.11 android/test_app_logic.py        # 安卓逻辑无回归
```

> 版本约束：v11.4.0 起 `APP_VERSION="11.4.0"`（桌面 `core/config.py` 与安卓 `android/core/config.py` 同步）。
> 全部新接口仅依赖标准库（`json` / `os` / `re` / `time`），无额外依赖。
