# 星语 Starry · API 开放文档（v11.1.0）

> 本文档描述 v11.1 新增的**可复用纯逻辑接口**，供开发者在自有项目中调用或二次集成。
> 所有接口位于 `core/`，**零 Qt / 零安卓依赖**，桌面端与安卓端同源共用。

## 1. 跨会话相关性检索

模块：`core/sessions.py`

```python
from core.sessions import SessionStore

store = SessionStore()                       # 默认读写配置目录 sessions.json
results = store.search_ranked("Python", top_k=20)
for r in results:
    print(r["title"], r["score"], r["snippet"])
```

### `SessionStore.search_ranked(query, top_k=20)`
- **入参**
  - `query: str` — 检索词（中英文混合）；空串返回 `list()`（全部会话摘要）
  - `top_k: int` — 返回上限，默认 20
- **返回**：列表，每项含字段

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | str | 会话 ID |
| `title` | str | 会话标题 |
| `updated` / `created` | int | 时间戳（秒） |
| `count` | int | 用户/助手消息数 |
| `pinned` | bool | 是否置顶 |
| `score` | int | 相关性得分（标题命中加权更高） |
| `snippet` | str | 命中摘要片段，`⚡` 标记命中词 |

- **分词策略**：英文/数字按词；中文按单字 + 相邻二元组（兼顾子串/短语召回）。
- **排序**：`-score → 未置顶在前 → -updated`。

> 旧接口 `search(query)` 现已委托本方法，返回结构向后兼容（仅多 `score`/`snippet`）。

## 2. 对话多格式导出

模块：`core/exporter.py`

```python
from core.exporter import (conversation_to_markdown, conversation_to_json,
                           conversation_to_text, conversation_to_html,
                           export_conversation, EXPORT_FORMATS)

md  = conversation_to_markdown(history, title="对话", model="gpt", provider_name="OpenAI")
js  = conversation_to_json(history, title="对话")
txt = conversation_to_text(history, title="对话")
html= conversation_to_html(history, title="对话")
```

### 函数签名（四个格式一致）
```python
conversation_to_<fmt>(history, title="AI 对话记录", model="", provider_name="") -> str
```
- `history`：`[{"role": "system"|"user"|"assistant", "content": str | 多模态 list}, ...]`
- `model` / `provider_name`：仅写入导出头信息，不参与渲染

### 统一入口
```python
export_conversation(history, fmt="markdown", **kwargs) -> str
```
- `fmt ∈ {"markdown", "json", "text", "html"}`（未知值回退 `markdown`）
- `EXPORT_FORMATS`：格式注册表 `{key: (显示名, 扩展名, 函数)}`，UI 下拉可直接消费

### 安全说明
`conversation_to_html` 对全部文本经 `_esc()` 转义 `& < > "`，导出自带 HTML/外链的消息不会注入脚本，**可直接浏览器打开分享**。

## 3. 端到端自测
```bash
python test_search_export.py     # 5/5 通过：检索排序 / 中文命中 / 四格式导出 / HTML 转义 / 多模态
python android/test_app_logic.py # 14/14 通过（安卓逻辑无回归）
```
