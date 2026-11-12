# API 开放文档 · V11.0

> 星语 Starry 的「开放接口」分三层：① 命令行 JSON 接口；② Python 核心函数接口；
> ③ OpenAI 兼容的远端模型接口（由配置决定）。本版新增安卓端，但**全部复用同一核心 API**。

## 0. 版本与入口

| 端 | 入口 | 版本令牌 |
|----|------|---------|
| 桌面 GUI | `main.py` / `starrystar.spec` | `APP_VERSION=11.0.0` |
| 命令行 | `starry_cli.py` / `core/cli.py` | `CLIENT_INFO.version=11.0.0` |
| 安卓 | `android/starryandroid/app.py` | 同核心 |

## 1. 命令行 JSON 接口

```bash
# 普通对话（JSON 输出）
python3 starry_cli.py "你好" --json
# 智能体（含工具调用）
python3 starry_cli.py --agent "列出当前目录文件" --json
# 仅查看平台
python3 starry_cli.py --platform
```

### 响应 Schema（`--json`）

普通对话：
```json
{
  "platform": "Linux",
  "reasoning": "（模型推理过程，可能为空）",
  "answer": "（最终回答）"
}
```
智能体：
```json
{
  "platform": "Android",
  "reasoning": "…",
  "answer": "…",
  "tools": [
    {"name": "run_command", "args": {"cmd": "ls"}, "result": "…"}
  ]
}
```

### 参数表（`build_arg_parser`）

| 参数 | 说明 |
|------|------|
| `-p/--prompt` | 提问文本 |
| `-f/--file` | 从文件读取提问 |
| `-a/--agent` | 启用智能体（工具调用） |
| `--tools` | 限定工具名（逗号分隔） |
| `--provider/--model/--base-url/--api-key` | 覆盖配置 |
| `--max-iterations` | 智能体最大轮数（默认 6） |
| `--no-reasoning` | 不打印思考 |
| `--json` | JSON 输出 |
| `--platform` | 打印平台与版本后缀 |
| `--no-memory` | 不注入长期记忆 |
| `--add-rea` | 并入 REA 逆向工程 MCP 预设 |
| `-V/--version` | 版本号 |

## 2. Python 核心函数接口（`core/cli.py`）

```python
from core.cli import build_client, collect_chat, collect_agent, run_cli

client = build_client(cfg, overrides={...})          # 与桌面同构的流式客户端
reasoning, answer = collect_chat(client, messages)   # -> (思考, 回答)
reasoning, answer, tools = collect_agent(client, messages, enabled_tools=None)
rc = run_cli(argv, out=sys.stdout)                   # 命令行主入口，返回退出码
```

- `messages`：OpenAI 兼容的 `[{role, content}]` 列表。
- `client.chat_stream(messages)`：逐块 yield `("reasoning"|"content", 文本)`。
- `client.chat_agent_stream(messages, specs)`：带工具调用的流式生成器。

## 3. 配置接口（`config.json` 关键字段）

```json
{
  "provider": "zhipu",
  "api_keys": {"zhipu": "你的KEY"},
  "models": {"zhipu": "glm-4-flash"},
  "reasoning_effort": "medium",
  "deep_thinking": false,
  "memory": true
}
```
- 配置文件权限 `0o600`；路径见 `core.config.get_config_dir()`。
- 内置 20+ OpenAI 兼容服务商（见 `core.config.PROVIDERS`），含免费额度与本地模型（Ollama/LM Studio）。

## 4. 远端模型接口

星语 Starry 本身**不提供**自有模型 API，而是接入第三方 OpenAI 兼容 `/chat/completions`；
因此「开放」体现在**可插拔的远端端点**与**统一的核心函数接口**上，便于二次开发与集成。

## 5. 安卓端集成说明

- 安卓 `app.py` 直接 `import` 上述 `core.cli` 函数，UI 层不重写对话逻辑。
- 网络在后台线程执行，经事件循环线程安全回写，符合安卓主线程联网限制。
- 网页接入型服务商（DeepSeek/智谱/豆包网页版）在手机端不适用，已在 UI 过滤。

## 6. 评分：**A**（接口稳定、三端统一、JSON 便于自动化与二次开发）
