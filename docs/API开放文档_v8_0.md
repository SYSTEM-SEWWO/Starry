# API 开放文档（v8.0）

> 对外接口契约：在 v7.6 六类接口（MCP 接入 / `register_tool` / 自动化 / 网关 / 配置 / 构建）基础上，新增 **长期记忆** 与 **深度思考（推理）** 两类对外能力。
> ⚠️ 文档示例中的 API Key 仅以 `sk-...` 占位；**切勿提交真实密钥**，`config.json` / `memory.json` 已被 `.gitignore` 忽略。

---

## 1. 长期记忆系统（`core/memory.py`）

### 1.1 存储与权限

```python
from core.memory import MemoryStore, is_safe_entry

store = MemoryStore()                       # 默认路径 <config_dir>/memory.json（0o600）
store = MemoryStore(path="/custom/mem.json")  # 也可指定路径（测试用）

store.add("我是一名后端工程师", "profile")   # 返回 id 或 None（被护栏拒）
store.add("我常用 Python", "preference")
store.forget("m1")                          # 按 id 或文本删除
store.clear()                               # 清空全部
store.set_enabled(False)                    # 关闭记忆（保留数据）
```

### 1.2 写入护栏（S6 安全）

`is_safe_entry(text)` 在写入前校验：**非空 / ≤240 字符 / 无 `<>&` / 无指令诱导**（如 `ignore previous instructions`、`忽略之前的指令`）。被拒条目 `add()` 返回 `None`。

### 1.3 检索与注入

```python
store.relevant("我的职业是什么")            # 按词重叠召回相关记忆（top_k=5）
store.build_memory_block()                  # 拼装可注入系统提示的纯文本块
# 输出示例：
# 【长期记忆】
# 用户画像：我是一名后端工程师
# 偏好：我常用 Python
# 项目背景：项目用 FastAPI
```

### 1.4 启发式学习

```python
n = store.learn_from_conversation("我是设计师。我们团队用 React。我喜欢深色主题。")
# 从白名单句式抽取：n>=2（profile / project / preference 各一）
# 注：只学用户侧；assistant_text 仅签名兼容，不参与学习
```

### 1.5 系统提示接入点

`app/assistant.py::_rebuild_system_prompt`（第 921 行）在基础人设 + 技能提示之后追加 `build_memory_block()`；对话结束（`_on_finished`）自动 `learn_from_conversation` 并即时刷新，下一轮生效。

## 2. 深度思考（推理）引擎（`core/reasoning.py`）

### 2.1 一次性解析

```python
from core.reasoning import split_think_content, ReasoningTrace, StreamingThinkSplitter

think, answer = split_think_content("<think>让我想想</think>最终答案")
# -> think="让我想想", answer="最终答案"
```

### 2.2 流式分片（推荐）

```python
sp = StreamingThinkSplitter()
for chunk in stream:
    think_delta, answer_delta = sp.feed(chunk)
    # think_delta → 思考块；answer_delta → 正文
think_tail, answer_tail = sp.flush()       # 流结束收尾
```

### 2.3 思考轨迹

```python
tr = ReasoningTrace()
tr.append("A").append("B")
tr.full            # "AB"
tr.summarize(20)   # 超长截断 + 省略号（折叠标题用）
```

### 2.4 接入点

`app/assistant.py::_on_content`（第 756 行起）对每片正文调用 `self._think_splitter.feed`，把思考增量转交 `_on_reasoning` → 气泡思考块；`_on_finished` 末尾 `flush()` 收尾。`StreamingThinkSplitter` 不丢字符、不执行内容，仅做状态分离。

## 3. 既有接口（v7.6 已定义，v8.0 继承）

| 类 | 入口 | 说明 |
| --- | --- | --- |
| MCP 接入 | `core/mcp.py::McpClient` / `McpManager` | stdio JSON-RPC，工具进 `mcp_*` 工具箱 |
| 工具扩展 | `register_tool(name, fn, schema)` | 内置 11 工具 + MCP 工具统一注册 |
| 自动化 | `core/automation.py::AutomationManager` | 定时 / 间隔执行提示词 |
| 网关 | `core/gateway.py::GatewayStats` / `KeyPool` | 多 Key 轮询 / 预算告警 / 健康检查 |
| 配置 | `core/config.py::AppConfig` | 0o600 落盘，含记忆 `memory.json` 同级保护 |
| 构建 | `starrystar.spec` + `scripts/build_*.{ps1,sh}` | 三平台打包（新增 `core.memory`/`core.reasoning`/`ui.memory_dialog` 隐藏导入） |

## 4. 调用约定与边界

- 记忆 / 推理模块**纯标准库**，无网络、无新依赖，可离线集成到任意 Python 宿主。
- 记忆内容仅作**纯文本**注入，绝不被执行；思考文本经 `markdown_to_qt_html` 安全清洗后渲染。
- 第三方集成请复用既有 `McpManager` 与 `register_tool`，不要在记忆/推理层直接耦合业务逻辑。
