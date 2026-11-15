# -*- coding: utf-8 -*-
"""MCP（Model Context Protocol）客户端 —— 把外部 MCP 服务器的工具接入智能体。

为什么要有它：2026 年桌面 AI 助手的事实标准（Claude Desktop / OpenClaw /
Continue / Jini 等均已支持），MCP 让「工具」脱离本程序独立演进：任何人写的
MCP 服务器（数据库、Jira、本地文件系统、浏览器自动化……）都能被本智能体
直接调用，而不必等我们内置。参见 docs/GitHub开源调研_v7_3.md。

实现约束（刻意保持轻量）：
- **纯标准库**：subprocess + json + threading，不引入 mcp / anyio 等新依赖，
  避免把打包体积和依赖树再次撑大（延续 v7.2 的瘦身方针）。
- stdio 传输，**newline-delimited JSON** 帧（与官方 spec 一致）：
      initialize → notifications/initialized → tools/list → tools/call
- 所有进程 / IO 异常一律收敛为可读字符串，绝不上抛到模型调用循环。

可被自测直接验证：纯函数（tool_id / extract_text / normalize_schema /
normalize_entry）不依赖任何进程，端到端则由一个内置 mock 服务器脚本走通。
"""
import json
import os
import queue
import re
import shutil
import subprocess
import threading
import time

PROTOCOL_VERSION = "2024-11-05"
CLIENT_INFO = {"name": "星语Starry", "version": "13.9.0"}
DEFAULT_TIMEOUT = 15.0


# ---------------------------------------------------------------------------
# 纯函数（无 IO，可直接单测）
# ---------------------------------------------------------------------------
def tool_id(server_name, tool_name):
    """把「服务器名 + 工具名」压成 OpenAI tools 合法的 function name。

    OpenAI 仅允许 [A-Za-z0-9_-]，且建议不超过 64 字符；中文服务器名会被
    逐字替换为下划线。
    """
    raw = "mcp_%s__%s" % (server_name or "srv", tool_name or "tool")
    safe = re.sub(r"[^A-Za-z0-9_-]+", "_", raw)   # 连续非法字符压成单个下划线
    safe = re.sub(r"_{2,}", "_", safe)            # 再折叠重复下划线，保持可读
    return safe[:64]


def extract_text(result):
    """从 tools/call 的 result 中提取纯文本（content 数组 → 字符串）。"""
    if result is None:
        return ""
    if isinstance(result, str):
        return result
    if not isinstance(result, dict):
        return repr(result)
    content = result.get("content") or []
    parts = []
    for c in content:
        if not isinstance(c, dict):
            continue
        if c.get("type") == "text":
            parts.append(str(c.get("text", "")))
        else:
            parts.append(str(c.get("text") or c.get("data") or c.get("type")))
    body = "\n".join(p for p in parts if p)
    if result.get("isError"):
        return "（MCP 工具返回错误）%s" % (body or "未知错误")
    return body


def normalize_schema(schema):
    """MCP inputSchema → OpenAI parameters（补齐必需字段）"""
    s = dict(schema or {})
    s.setdefault("type", "object")
    if not isinstance(s.get("properties"), dict):
        s["properties"] = {}
    return s


def normalize_entry(entry):
    """配置条目规范化（去空、类型收敛），纯函数"""
    e = dict(entry or {})
    args = e.get("args") or []
    if isinstance(args, str):
        args = args.split()
    env = e.get("env") or {}
    return {
        "name": str(e.get("name") or "").strip(),
        "command": str(e.get("command") or "").strip(),
        "args": [str(a) for a in args],
        "env": {str(k): str(v) for k, v in dict(env).items()},
        "enabled": bool(e.get("enabled", True)),
        "trusted": bool(e.get("trusted", False)),
    }


def is_valid_entry(entry):
    """配置条目是否可用（有名字、有命令）"""
    e = normalize_entry(entry)
    return bool(e["name"]) and bool(e["command"])


# ---------------------------------------------------------------------------
# 危险（写 / 执行）工具识别 —— v7.5 安全护栏
# ---------------------------------------------------------------------------
# 词元级匹配，避免 "nowrite" 之类子串误判；用于决定调用前是否需要用户确认。
DESTRUCTIVE_HINTS = {
    "delete", "remove", "rm", "del", "drop", "truncate", "write", "create",
    "mkdir", "touch", "edit", "update", "patch", "put", "post", "upload",
    "send", "exec", "execute", "run", "shell", "kill", "shutdown", "restart",
    "move", "mv", "rename", "reset", "purge",
}


def classify_destructive(name, desc=""):
    """按工具名 / 描述判断是否为写或执行类（需护栏）工具。"""
    low = ("%s %s" % (name or "", desc or "")).lower()
    tokens = re.split(r"[^a-z0-9]+", low)
    return any(h in tokens for h in DESTRUCTIVE_HINTS)


# ---------------------------------------------------------------------------
# 单个 MCP 服务器
# ---------------------------------------------------------------------------
class McpClient:
    """一个 MCP 服务器（stdio 传输）的客户端。线程安全。"""

    def __init__(self, name, command, args=None, env=None, timeout=DEFAULT_TIMEOUT):
        self.name = name
        self.command = command
        self.args = [str(a) for a in (args or [])]
        self.env = dict(env or {})
        self.timeout = float(timeout or DEFAULT_TIMEOUT)
        self.proc = None
        self._q = queue.Queue()
        self._id = 0
        self._lock = threading.Lock()
        self._reader = None
        self.server_info = {}
        self.tools = []
        self.last_error = ""

    # ---------------- 生命周期 ----------------
    def is_running(self):
        return self.proc is not None and self.proc.poll() is None

    def start(self):
        """启动子进程并完成 initialize 握手。返回 (ok, msg)"""
        if self.is_running():
            return True, "已连接"
        if not (self.command or "").strip():
            self.last_error = "启动命令为空"
            return False, self.last_error
        # v7.5 安全：先校验命令可解析（PATH 查找或文件存在），失败早返回
        # 说明：以列表形式 [command]+args 传给 Popen（绝无 shell=True），
        # 因此不存在 shell 命令注入面；此处仅做「命令不存在」的清晰拦截。
        resolved = shutil.which(self.command) or (
            os.path.isfile(self.command) and os.access(self.command, os.X_OK)
            and self.command)
        if not resolved:
            self.last_error = "启动命令不存在或不可执行：%s" % self.command
            return False, self.last_error
        self.command = resolved
        env = dict(os.environ)
        env.update({str(k): str(v) for k, v in self.env.items()})
        try:
            self.proc = subprocess.Popen(
                [self.command] + self.args,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                env=env, text=True, encoding="utf-8",
                errors="replace", bufsize=1)
        except Exception as e:                          # noqa: BLE001
            self.proc = None
            self.last_error = "启动失败：%s" % e
            return False, self.last_error

        self._reader = threading.Thread(
            target=self._read_loop, args=(self.proc,), daemon=True)
        self._reader.start()

        res = self.request("initialize", {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": CLIENT_INFO,
        })
        if res is None:
            self.stop()
            return False, self.last_error or "握手超时"
        self.server_info = res.get("serverInfo") or {}
        self.notify("notifications/initialized")
        label = self.server_info.get("name") or self.name
        version = self.server_info.get("version") or ""
        return True, "已连接：%s%s" % (label, (" v" + version) if version else "")

    def stop(self):
        """终止子进程（先 terminate，超时再 kill）"""
        proc, self.proc = self.proc, None
        self.tools = []
        if proc is None:
            return
        try:
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=3)
                except Exception:                       # noqa: BLE001
                    try:
                        proc.kill()
                    except Exception:                   # noqa: BLE001
                        pass
        except Exception:                               # noqa: BLE001
            pass
        try:
            if proc.stdin:
                proc.stdin.close()
        except Exception:                               # noqa: BLE001
            pass

    # ---------------- IO ----------------
    def _read_loop(self, proc):
        """后台线程：持续读 stdout，把带 id 的响应投递到队列"""
        try:
            for line in proc.stdout:
                line = (line or "").strip()
                if not line:
                    continue
                try:
                    msg = json.loads(line)
                except Exception:                       # noqa: BLE001
                    continue        # 非 JSON 行（日志/噪声）直接忽略
                if isinstance(msg, dict) and "id" in msg:
                    self._q.put(msg)
        except Exception:                               # noqa: BLE001
            pass

    def request(self, method, params=None, timeout=None):
        """发一条 JSON-RPC 请求并等待同 id 响应；失败返回 None（错误见 last_error）"""
        if not self.is_running():
            self.last_error = "未连接"
            return None
        with self._lock:
            self._id += 1
            mid = self._id
        payload = {"jsonrpc": "2.0", "id": mid, "method": method}
        if params is not None:
            payload["params"] = params
        try:
            self.proc.stdin.write(json.dumps(payload, ensure_ascii=False) + "\n")
            self.proc.stdin.flush()
        except Exception as e:                          # noqa: BLE001
            self.last_error = "发送失败：%s" % e
            return None

        limit = float(timeout) if timeout is not None else self.timeout
        end = time.time() + limit
        while True:
            remaining = end - time.time()
            if remaining <= 0:
                self.last_error = "请求超时：%s" % method
                return None
            try:
                msg = self._q.get(timeout=remaining)
            except queue.Empty:
                self.last_error = "请求超时：%s" % method
                return None
            if msg.get("id") != mid:
                continue                     # 过期/错序响应，继续等
            err = msg.get("error")
            if err:
                self.last_error = "远程错误 %s：%s" % (
                    err.get("code"), err.get("message"))
                return None
            return msg.get("result")

    def notify(self, method, params=None):
        """发通知（无 id，不等待响应）"""
        if not self.is_running():
            return
        payload = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            payload["params"] = params
        try:
            self.proc.stdin.write(json.dumps(payload, ensure_ascii=False) + "\n")
            self.proc.stdin.flush()
        except Exception:                               # noqa: BLE001
            pass

    # ---------------- 工具 ----------------
    def list_tools(self):
        """拉取工具清单；失败返回空列表"""
        res = self.request("tools/list")
        if res is None:
            return []
        self.tools = [t for t in (res.get("tools") or [])
                      if isinstance(t, dict) and t.get("name")]
        return self.tools

    def call_tool(self, name, arguments=None):
        """调用工具，返回文本结果（错误也以文本返回，便于模型自我纠正）"""
        res = self.request("tools/call",
                           {"name": name, "arguments": arguments or {}})
        if res is None:
            return "错误：MCP 工具调用失败（%s）" % (self.last_error or "未知原因")
        return extract_text(res)


# ---------------------------------------------------------------------------
# 多服务器管理 + 注册进智能体工具箱
# ---------------------------------------------------------------------------
class McpManager:
    """管理配置中的多个 MCP 服务器，并把其工具注册进智能体工具箱。

    confirm_cb(tool_id) -> bool：危险（写/执行）工具在被非信任服务器调用前
    会先询问；返回 False 或直接为 None 时**拒绝执行**并返回提示文本（安全默认）。
    信任的服务器（配置 trusted=True）跳过该询问。
    """

    def __init__(self, servers=None, confirm_cb=None):
        self.entries = [normalize_entry(e) for e in (servers or [])
                        if is_valid_entry(e)]
        self.clients = {}            # name -> McpClient
        self._registered = []        # 已注册进 tools 的工具名
        self.confirm_cb = confirm_cb

    def _make_caller(self, client, tool_name, tid, destructive, trusted):
        """工厂：为每个工具生成独立闭包（含危险工具护栏）"""
        def _call(**kwargs):
            if destructive and not trusted:
                # v7.5 安全护栏：非信任服务器的写/执行工具默认拒绝，
                # 仅当用户/会话显式批准（confirm_cb 返回 True）才放行。
                if self.confirm_cb is None or not self.confirm_cb(tid):
                    return ("⚠ 安全护栏：工具 %s 属于写/执行类，来源服务器未标记为"
                            "「信任」。请先在设置 → MCP 工具中将其设为信任，"
                            "或在弹出的确认框中批准后方可执行。本次未执行。" % tid)
            return client.call_tool(tool_name, kwargs)
        _call.__name__ = "mcp_call_%s" % tool_name
        return _call

    # ---------------- 连接 ----------------
    def connect_all(self):
        """连接所有启用的服务器并拉取工具。返回 {name: (ok, msg)}"""
        report = {}
        for entry in self.entries:
            if not entry["enabled"]:
                report[entry["name"]] = (False, "已禁用")
                continue
            cli = McpClient(entry["name"], entry["command"],
                            entry["args"], entry["env"])
            ok, msg = cli.start()
            self.clients[entry["name"]] = cli
            if ok:
                cli.list_tools()
                report[entry["name"]] = (True, "%s（%d 个工具）"
                                         % (msg, len(cli.tools)))
            else:
                report[entry["name"]] = (False, msg)
        return report

    def connect_one(self, name):
        """只连接一个服务器（设置页「测试连接」用）。返回 (ok, msg, tools)"""
        entry = next((e for e in self.entries if e["name"] == name), None)
        if entry is None:
            return False, "未找到服务器配置", []
        cli = McpClient(entry["name"], entry["command"],
                        entry["args"], entry["env"])
        ok, msg = cli.start()
        if not ok:
            return False, msg, []
        tools = cli.list_tools()
        # 测试连接不常驻：拉完清单即关闭
        cli.stop()
        return True, "%s（%d 个工具）" % (msg, len(tools)), tools

    # ---------------- 注册 ----------------
    def register_tools(self):
        """把已连接服务器的工具注册进 core.agent.tools。返回注册数量"""
        from core.agent.tools import register_tool
        count = 0
        for entry in self.entries:
            if not entry["enabled"]:
                continue
            cli = self.clients.get(entry["name"])
            if cli is None or not cli.is_running():
                continue
            for t in cli.tools:
                tname = t.get("name")
                if not tname:
                    continue
                tid = tool_id(entry["name"], tname)
                desc = "[MCP:%s] %s" % (entry["name"],
                                        t.get("description") or tname)
                destructive = classify_destructive(
                    tname, t.get("description") or "")
                caller = self._make_caller(
                    cli, tname, tid, destructive, bool(entry.get("trusted")))
                register_tool(tid, desc[:200],
                              normalize_schema(t.get("inputSchema")),
                              caller)
                if tid not in self._registered:
                    self._registered.append(tid)
                count += 1
        return count

    def unregister_all(self):
        """卸载本管理器注册过的全部工具（重连前清理）"""
        from core.agent.tools import unregister_tool
        for tid in self._registered:
            unregister_tool(tid)
        self._registered = []

    def stop_all(self):
        self.unregister_all()
        for cli in self.clients.values():
            cli.stop()
        self.clients = {}

    # ---------------- 视图 ----------------
    def status(self):
        """给设置页用的状态清单：[{name, enabled, connected, msg, tools}]"""
        rows = []
        for entry in self.entries:
            cli = self.clients.get(entry["name"])
            connected = bool(cli and cli.is_running())
            tools = [t.get("name") for t in (cli.tools if cli else [])]
            rows.append({
                "name": entry["name"],
                "command": entry["command"],
                "enabled": entry["enabled"],
                "connected": connected,
                "msg": (cli.last_error if (cli and not connected
                                           and cli.last_error) else
                        ("已连接" if connected else "未连接")),
                "tools": tools,
            })
        return rows

    def tool_count(self):
        return sum(len(c.tools) for c in self.clients.values() if c.is_running())


# ---------------------------------------------------------------------------
# 内置 mock 服务器源码（自测端到端用，不随包启用）
# ---------------------------------------------------------------------------
MOCK_SERVER_SOURCE = '''
import json, sys
for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    try:
        msg = json.loads(line)
    except Exception:
        continue
    method = msg.get("method")
    mid = msg.get("id")
    if mid is None:
        continue
    if method == "initialize":
        res = {"protocolVersion": "2024-11-05",
               "capabilities": {"tools": {}},
               "serverInfo": {"name": "mock", "version": "1.0.0"}}
    elif method == "tools/list":
        res = {"tools": [
            {"name": "echo", "description": "回显一段文本",
             "inputSchema": {"type": "object",
                             "properties": {"text": {"type": "string"}}}},
            {"name": "add", "description": "两数相加",
             "inputSchema": {"type": "object",
                             "properties": {"a": {"type": "number"},
                                            "b": {"type": "number"}}}}]}
    elif method == "tools/call":
        p = msg.get("params") or {}
        name, args = p.get("name"), (p.get("arguments") or {})
        if name == "echo":
            out = "echo:" + str(args.get("text", ""))
        elif name == "add":
            out = str(float(args.get("a", 0)) + float(args.get("b", 0)))
        else:
            out = {"content": [{"type": "text", "text": "未知工具"}],
                   "isError": True}
            sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": mid,
                                         "result": out}) + "\\n")
            sys.stdout.flush()
            continue
        res = {"content": [{"type": "text", "text": out}]}
    else:
        sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": mid,
                                     "error": {"code": -32601,
                                               "message": "方法不存在"}}) + "\\n")
        sys.stdout.flush()
        continue
    sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": mid,
                                 "result": res}) + "\\n")
    sys.stdout.flush()
'''
