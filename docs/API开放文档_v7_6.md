# 星语 Starry · API 开放文档（v7.6）

> 面向**第三方开发者**与**后续维护者**的集成 / 扩展接口说明。
> 星语 Starry 不提供云端 REST API（本地优先、数据不出机）；它的「开放接口」由三层组成：
> **① 外部 MCP 服务器接入**（把你的工具喂给星语）、**② 内部扩展点**（给你的代码加能力）、**③ 构建 / 合规 API**（把星语打包 / 接入你的流程）。
> 所有接口均为 Python 公共符号，可直接 `import` 使用，并有 `selftest.py` 覆盖。

---

## 0. 读者对象与前提

- 已读完 [`CONTRIBUTING.md`](../CONTRIBUTING.md) 与 [`docs/项目结构与提交指南_v7_6.md`](项目结构与提交指南_v7_6.md)
- 环境：Python 3.9+，`pip install -r requirements.txt`
- 入口模块：`main.py`（含 EULA 首启门）

---

## 1. 外部接入 API —— MCP 工具生态

星语通过 **MCP（Model Context Protocol）** 接入任意第三方工具服务器，零新依赖（纯标准库实现 stdio JSON-RPC）。源码见 [`core/mcp.py`](../core/mcp.py)。

### 1.1 协议（stdio JSON-RPC）

服务器以**子进程**方式启动（`python your_server.py`），通过 stdin/stdout 收发换行分隔的 JSON：

| 方法 | 方向 | 说明 |
| --- | --- | --- |
| `initialize` | 客户端→服务器 | 握手，携带 `clientInfo`（名称/版本）、`protocolVersion` |
| `tools/list` | 客户端→服务器 | 列出可用工具（`name` / `description` / `inputSchema`） |
| `tools/call` | 客户端→服务器 | 调用某工具，参数在 `arguments` |
| `notifications/initialized` | 客户端→服务器 | 握手完成通知 |

> 传输仅 **stdio**，且客户端以**列表式 `subprocess.Popen([cmd, *args])`（非 shell）** 启动服务器 → **无命令注入面**。

### 1.2 最小 MCP 服务器（Python）

```python
#!/usr/bin/env python3
# my_mcp_server.py —— 一个能跑起来的 MCP 服务器
import sys, json

def send(obj):
    sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
    sys.stdout.flush()

def read():
    line = sys.stdin.readline()
    return json.loads(line) if line.strip() else None

TOOLS = [{
    "name": "add",
    "description": "两个整数相加",
    "inputSchema": {"type": "object",
                    "properties": {"a": {"type": "integer"},
                                   "b": {"type": "integer"}},
                    "required": ["a", "b"]},
}]

while True:
    msg = read()
    if not msg:
        break
    m, iid = msg.get("method"), msg.get("id")
    if m == "initialize":
        send({"jsonrpc": "2.0", "id": iid, "result": {
            "protocolVersion": "2024-11-05",
            "capabilities": {}, "serverInfo": {"name": "my", "version": "1.0"}}})
    elif m == "notifications/initialized":
        continue
    elif m == "tools/list":
        send({"jsonrpc": "2.0", "id": iid, "result": {"tools": TOOLS}})
    elif m == "tools/call":
        n = msg["params"]["name"]; a = msg["params"].get("arguments", {})
        if n == "add":
            r = a["a"] + a["b"]
            send({"jsonrpc": "2.0", "id": iid, "result": {
                "content": [{"type": "text", "text": str(r)}]}})
        else:
            send({"jsonrpc": "2.0", "id": iid,
                  "result": {"content": [{"type": "text", "text": "unknown"}],
                             "isError": True}})
```

### 1.3 客户端公共 API

```python
from core.mcp import (McpClient, McpManager, tool_id,
                       classify_destructive, MOCK_SERVER_SOURCE)

# 纯函数
tool_id("我的服务器", "add")                 # -> "mcp_我的服务器__add"
classify_destructive("rm_file", "删除文件")  # -> True（写/执行类被识别）

# 单服务器客户端
cli = McpClient("我的服务器", sys.executable, ["my_mcp_server.py"], timeout=8)
ok, msg = cli.start()          # 启动子进程 + initialize 握手
tools = cli.list_tools()       # tools/list
res = cli.call_tool("add", {"a": 3, "b": 4})   # tools/call -> 文本结果
cli.stop()

# 多服务器管理 + 注册进智能体工具箱
mgr = McpManager([{"name": "我的服务器", "command": sys.executable,
                   "args": ["my_mcp_server.py"], "enabled": True,
                   "trusted": False}])
mgr.connect_all()
mgr.register_tools()            # 工具以 mcp_* 前缀进入 core.agent.tools.TOOLS
mgr.status()                    # 连接状态
mgr.stop_all()
```

| 符号 | 作用 |
| --- | --- |
| `McpClient(name, command, args, timeout=8, env=None)` | 单服务器 stdio 客户端；`start()/list_tools()/call_tool()/stop()` |
| `McpManager(entries, confirm_cb=None)` | 多服务器管理；`connect_all()/register_tools()/stop_all()/status()` |
| `tool_id(server, tool)` | 生成工具箱唯一 id（`mcp_<server>__<tool>`，下划线折叠） |
| `classify_destructive(name, desc="")` | 词元级识别写文件 / 执行命令类工具 |
| `MOCK_SERVER_SOURCE` | 一个可运行的示例服务器源码（自测用） |

### 1.4 安全护栏（动作权限）

- 来自**未勾选「信任此服务器」**的 MCP 服务器的**危险工具**（写文件 / 执行命令）默认**拒绝执行**；
- `McpManager(confirm_cb=...)` 可注入放行判定（如会话内已批准则放行）；
- 设置 → **MCP 工具**页可增删改服务器、启用开关、勾选「信任」。

---

## 2. 内部扩展 API —— 智能体工具

源码见 [`core/agent/tools.py`](../core/agent/tools.py)。所有工具统一进入全局注册表 `TOOLS`，自动成为对话可调用工具与命令面板候选。

### 2.1 注册一个工具

```python
from core.agent.tools import tool, register_tool, get_tool_specs, execute_tool

@tool("weather_now", "查询城市当前天气", {
    "type": "object",
    "properties": {"city": {"type": "string", "description": "城市名"}},
    "required": ["city"]})
def weather_now(city: str) -> str:
    return f"{city}：晴 26℃"

# 等价（函数式）：
register_tool("weather_now", "查询城市当前天气", {"type": "object",
             "properties": {"city": {"type": "string"}}}, weather_now)
```

| 符号 | 作用 |
| --- | --- |
| `@tool(name, description, parameters=None)` | 装饰器注册 |
| `register_tool(name, description, parameters, func)` | 函数式注册 |
| `register_dynamic(name, description, parameters, func, plugin_id="")` | 插件市场安装的工具（可整体卸载） |
| `unregister_tool(name)` / `unregister_plugin_tools(plugin_id)` | 注销 |
| `get_tool_specs(enabled=None)` | 生成 **OpenAI `tools` 兼容数组**（`ToolSpec.to_openai()`） |
| `execute_tool(name, arguments)` | 在调用方线程执行；任何异常转可读字符串 |

> 工具的 `parameters` 直接是 **JSON Schema**，与 OpenAI / 兼容网关的工具调用协议一致（`get_tool_specs()` 即 `tools` 数组），便于接入任意大模型后端。

---

## 3. 自动化 API

源码见 [`core/automation.py`](../core/automation.py)。任务以纯数据结构存储于 `automation.json`，触发计算为**纯函数**便于单测。

```python
task = {
    "id": "t1", "name": "晨报", "prompt": "总结今日待办",
    "mode": "daily",          # "daily"=每天定时(HH:MM) | "interval"=每N分钟
    "time": "08:30",          # mode=daily 时生效
    "every": 60,              # mode=interval 时生效（分钟，5~10080）
    "skill": "", "enabled": True, "last_run": 0, "created": 0,
}
from core.automation import AutomationManager, next_run, due
mgr = AutomationManager()
mgr.add_task(task)
next_run(task)               # -> 下次触发 Unix 时间戳（纯函数）
due(task, now)               # -> bool，是否到点
```

| 常量 / 函数 | 说明 |
| --- | --- |
| `MODE_DAILY` / `MODE_INTERVAL` | 触发模式 |
| `DEFAULT_EVERY=60` / `MIN_EVERY=5` / `MAX_EVERY=10080` | 间隔约束（分钟） |
| `AutomationManager` | `add_task / update / remove / list / run_due` |
| `next_run(task, now=None)` / `due(task, now=None)` | 纯函数，触发计算 |

---

## 4. 网关与多站点网页接入 API

源码见 [`core/gateway.py`](../core/gateway.py)、[`core/web_sites.py`](../core/web_sites.py)。

```python
from core.gateway import KeyPool, check_providers_parallel, route_pick, budget_status
kp = KeyPool()
kp.add_key("deepseek", "sk-...")          # 密钥入池（本地存储，0o600）
kp.list_keys("deepseek")
from core.web_sites import site_keys, get_site, is_web_site, site_models
print(site_keys())                        # 已注册网页站点列表
```

| 符号 | 作用 |
| --- | --- |
| `KeyPool.add_key(provider, key)` / `list_keys(provider)` | 多密钥池（含轮询 / 预算） |
| `check_providers_parallel(providers, timeout, max_workers)` | 并行健康检查 |
| `route_pick(policy, summary, manual_provider, current)` | 多供应商路由 |
| `budget_status(summary, budgets)` | 预算三档（告警 / 限速 / 熔断） |
| `web_sites.site_keys() / get_site(k) / is_web_site(k) / site_models(k)` | 多站点注册表（工厂 + 选择器） |

---

## 5. 配置与合规 API

源码见 [`core/config.py`](../core/config.py)。

```python
from core.config import APP_VERSION, AppConfig, validate_license_key, generate_license_key
print(APP_VERSION)                        # "7.6.0"
cfg = AppConfig.load()
cfg.data["accepted_eula"]                 # 是否同意 EULA
cfg.data["license_key"]                   # 商业许可密钥
validate_license_key("XXXX-XXXX-XXXX-XXXX")   # 离线确定性校验（含校验位）
generate_license_key()                    # 生成合法密钥（签发用）
```

| 符号 | 作用 |
| --- | --- |
| `APP_VERSION` | 当前版本字符串（与 README/CHANGELOG/自测断言一致） |
| `AppConfig.load()/.save()` | 配置读写（落盘 `chmod 0o600`，保护密钥） |
| `validate_license_key(key)` / `generate_license_key()` | 许可离线校验 / 签发 |
| EULA 防篡改令牌 | `sha256(EULA 正文 + 版本)`，绕过即拒绝启动（见 [`代码安全性评估_v7_5.md`](代码安全性评估_v7_5.md)） |

---

## 6. 构建 / 打包 API

- 打包配置：[`starrystar.spec`](../starrystar.spec)（`Analysis(["main.py"], hiddenimports=_HIDDEN, excludes=重量级Qt模块) → EXE(console=False, icon=assets/icon.ico)`）
- 三平台脚本：[`scripts/build_windows.ps1`](../scripts/build_windows.ps1)（→ `星语Starry.exe`）、[`scripts/build_linux.sh`](../scripts/build_linux.sh)、[`scripts/build_macos.sh`](../scripts/build_macos.sh)
- `hiddenimports` 已显式声明全部懒加载模块（`ui.frost`、`ui.eula_dialog`、`core.mcp`、`core.screen` 等）
- 验证记录：Linux 下 `pyinstaller starrystar.spec` 成功产出 134MB 单文件可执行（见 [`项目结构与提交指南_v7_6.md`](项目结构与提交指南_v7_6.md) §4）

---

## 7. 安全与鉴权约定

1. **首启 EULA 门**：`main.py` 在装配前强制检查 EULA 同意（含防篡改令牌），拒绝即 `sys.exit(0)`。
2. **商业许可**：二进制 / 商用须密钥（`validate_license_key`），源码 MIT 自由使用。
3. **密钥存储**：`config.json`（含 API Key）以 `0o600` 落盘，且被 `.gitignore` 忽略——**切勿提交真实密钥**。
4. **MCP 护栏**：危险工具来自未信任服务器默认拒绝执行（§1.4）。
5. **漏洞上报**：走 `.github/SECURITY.md` 私有渠道，勿公开 Issue。

---

## 8. 版本与兼容性

- 语义化版本 `主.次.修`；破坏性变更在 `CHANGELOG.md` 标注。
- 扩展接口稳定性优先级：`core.mcp` / `core.agent.tools` / `core.automation` 的公共函数为**稳定接口**，新增参数向后兼容；内部私有符号（`_` 前缀）不保证稳定。
- 新增扩展点须同步补 `selftest.py` 自测，并保持 `pyflakes` 无新增告警。

---

## 9. 30 秒上手

```bash
# 1) 写一个 MCP 服务器（见 §1.2）
# 2) 设置 → MCP 工具 → 名称=我的服务器 / 命令=python / 参数=my_mcp_server.py
# 3) 保存后后台自动握手，工具即以 mcp_我的服务器__add 进入对话
# 4) 对话里直接说「帮我算 3+4」
```

需要更细的接入示例或想贡献新扩展点，请按 `CONTRIBUTING.md` 提 Issue / PR。
