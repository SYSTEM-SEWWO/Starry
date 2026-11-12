# API 开放文档 · V10.0

> 本文档汇总星语 Starry 对外的可编程接口。V10.0 新增「无界面命令行版」作为最轻量的集成入口。

## 1. 命令行版接口（V10.0 新增，最轻量集成）

入口：`starry_cli.py` / `星语Starry-CLI`（零 PyQt 依赖，跨平台）。

### 1.1 进程调用（stdin/stdout）

```bash
python3 starry_cli.py "问题"            # 文本输出
python3 starry_cli.py --json "问题"      # JSON 输出
echo "问题" | python3 starry_cli.py      # 管道
```

JSON 输出结构：

```json
{
  "platform": "linux",
  "reasoning": "思考过程……",
  "answer": "最终答复……",
  "tools": [{"name": "...", "args": {...}, "result": "..."}]
}
```

### 1.2 关键参数（完整见《命令行使用指南.md》）

| 参数 | 作用 |
| --- | --- |
| `-p/--prompt`, `-f/--file` | 提问来源 |
| `--provider/--model/--base-url/--api-key` | 覆盖配置 |
| `-a/--agent [--tools x,y] [--max-iterations N]` | 智能体工具模式 |
| `--no-reasoning` / `--json` / `--platform` / `-V` | 输出与诊断 |
| `--no-memory` / `--config PATH` / `--add-rea` | 记忆 / 配置 / REA 预设 |

### 1.3 程序内调用

```python
from core.cli import collect_chat, build_client
from core.config import AppConfig
client = build_client(AppConfig.load())
reasoning, answer = collect_chat(client, [{"role": "user", "content": "你好"}])
```

## 2. MCP 工具生态（V7.4+，V9.0 含 REA）

- `core/mcp.py`：纯标准库 JSON-RPC stdio 客户端；`McpManager` 注册工具到智能体工具箱。
- REA 预设：`core/rea.py` 的 `ensure_rea_preset()` 将 REA 逆向工程 MCP 服务器并入配置
  （默认关闭、不信任，需在设置启用）——命令行可用 `starry_cli.py --add-rea` 并入。
- 接入方式：设置页「MCP」添加服务器（name/cmd/args/enabled/trusted），或脚本调用。

## 3. 智能体 / 工具注册（V7.4+）

- `register_tool(name, func, schema)`：把 Python 函数注册为智能体可调用的工具。
- 内置工具位于 `core/agent/builtin/*`（utility/system/web/files/library）。
- `AgentRuntime`（V10.0 复用于 CLI 的 `collect_agent`）驱动「模型 ↔ 工具」多轮循环。

## 4. 自动化 / 网关 / 配置 / 打包（沿用 V7.6+）

- 自动化：`core/automation.py` 定时/触发任务。
- 网关：`core/gateway.py` 本地 HTTP 网关（将助手能力以 API 暴露）。
- 配置：`core/config.py` 的 `AppConfig`（load/save，0o600）。
- 打包：`starrystar.spec`（GUI）、`starry_cli.spec`（CLI console）。

## 5. 版本化分发接口约定

各平台发布包命名：`星语Starry-v10.0-<后缀>`，后缀由 `core/platforms.platform_suffix()`
统一产出（`windows-cli / linux-cli / uos / android`），保证分发命名与代码一致。
