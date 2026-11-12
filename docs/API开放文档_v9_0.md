# API 开放文档 · 星语 Starry V9.0

> 对外可调用 / 可扩展接口总览。V8.0 既有 MCP 接入、`register_tool`、自动化、网关、配置、打包六类接口继续有效，V9.0 新增 **REA 逆向工程接入** 与 **产物预览 / 思考字幕** 接口。

## 1. REA 逆向工程接入（V9.0 新增）

模块：`core/rea.py`

| 符号 | 说明 |
|---|---|
| `REA_MCP_PRESET` | REA 的 MCP 服务器预设字典（`name/command/args/enabled/trusted`），可直接并入 `config.mcp_servers` |
| `REA_ANALYSIS_TARGETS` | 支持的分析目标清单（原生二进制 / Electron / APK / .NET / 网站 / 固件…） |
| `rea_capabilities()` | 返回 REA 能力声明（license / kind / principle / targets / workflow） |
| `build_rea_prompt(target_path, goal)` | 构造「证据驱动」的逆向分析提示（与 REA 工作流同构） |
| `ensure_rea_preset(servers)` | 按 name 去重并入 REA 预设，返回 `(新列表, 是否已存在)` |

**一键接入**：设置页 MCP 区「🔍 添加 REA 预设」（→ `ui/settings_dialog.py:_on_mcp_add_rea`）；或命令面板 `rea`（→ `app/assistant.py:open_rea`）。
**前置**：本地需 Node.js（运行 `npx -y rea-agents@latest`）+ 按需安装 Ghidra/IDA 等引擎（与 REA 官方一致）。

## 2. 产物预览 Artifacts（V9.0 新增）

| 符号 | 说明 |
|---|---|
| `app.assistant.extract_html_artifact(content)` | 纯函数：从文本提取最后一个 ```html 块，无则 `None` |
| `app.assistant.open_artifacts()` | 扫描最近 assistant 回复的 ```html 块 → 落地临时文件 → 浏览器打开预览 |
| `ui.chat_window.artifacts_requested` (signal) | 标题栏 🧪 按钮触发的信号 |
| 命令面板 `artifacts` | 同上入口 |

## 3. 深度思考可视化（V9.0 增强）

| 符号 | 说明 |
|---|---|
| `ui.floating_ball.FloatingBall.show_thinking_text(text)` | 把流式思考推到悬浮球上方「液态玻璃 + 微光」字幕卡 |
| `ui.floating_ball.ThinkingCaption` | 实时思考字幕控件（自绘液态玻璃 + 微光扫掠） |
| `ui.floating_ball.FloatingBall._paint_glass_overlay` | THINKING 态液态玻璃折射 + 微光覆盖层 |

**接线**：`app/assistant._on_reasoning(text)` 同时写聊天窗思考块与 `ball.show_thinking_text(text)`。

## 4. 既有对外接口（V8.0 及更早，继续有效）

- **MCP 接入**：`core.mcp.McpManager` / `McpClient`，工具注册进 `core.agent.tools.register_tool`（见 V8.0 API 文档）。
- **`register_tool` 扩展**：插件市场 / 技能可向 Agent 工具箱注册能力。
- **自动化**：`core.automation.AutomationManager`（定时 / 间隔执行提示词）。
- **网关**：`core.gateway.GatewayStats` / `KeyPool` / `route_pick`（密钥轮询、失败退避）。
- **配置**：`core.config.AppConfig`（服务商 / 参数 / 外观 / MCP / 记忆）。
- **打包**：`starrystar.spec`（PyInstaller 单文件；隐藏导入含 `core.rea`）。

## 5. 调用示例（REA）

```python
from core.rea import ensure_rea_preset, build_rea_prompt
servers, existed = ensure_rea_preset(cfg.data.get("mcp_servers") or [])
cfg.data["mcp_servers"] = servers
prompt = build_rea_prompt("/path/app", "理解它的登录实现原理")
# 连接 REA 后，把 prompt 交给 Agent，由 REA 的 MCP 工具完成证据驱动分析
```
