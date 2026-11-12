# -*- coding: utf-8 -*-
"""智能体运行时：LLM + 工具循环。

流程：
  1. 带 tools 调用模型（流式）
  2. 模型请求工具调用 → 本地执行 → 结果以 role=tool 消息回喂
  3. 继续循环，直到模型给出纯文本答复（或达到最大轮数 / 用户停止）

事件（yield）：
  ("reasoning", 文本)   思考流
  ("content", 文本)     正文流
  ("tool", {"name", "args", "result", "running"})  工具调用生命周期
  ("notice", 文本)      提示信息（降级 / 达到上限等）
  ("error", 文本)       致命错误
"""
import json

from core import api as api_mod
from core.agent.tools import get_tool_specs, execute_tool


class AgentRuntime:
    def __init__(self, client, enabled_tools=None, max_iterations=6,
                 should_stop=None):
        self.client = client
        self.enabled_tools = enabled_tools      # None = 全部启用
        self.max_iterations = max(1, int(max_iterations))
        self.should_stop = should_stop

    def _stopped(self):
        return bool(self.should_stop and self.should_stop())

    def run(self, messages):
        """生成器：驱动一轮完整的多轮工具调用对话"""
        specs = get_tool_specs(self.enabled_tools)
        msgs = list(messages)

        for iteration in range(self.max_iterations):
            pending = []
            try:
                for ev in self.client.chat_agent_stream(msgs, specs):
                    if ev[0] == "tool_calls":
                        pending = ev[1]
                    else:
                        yield ev
            except api_mod.ToolsUnsupportedError as e:
                # 服务商不支持 tools：降级为普通流式对话（仅一次）
                yield ("notice", str(e))
                for ev in self.client.chat_stream(msgs):
                    yield ev
                return
            except api_mod.ChatError as e:
                yield ("error", str(e))
                return

            if not pending:
                return                      # 纯文本答复，结束
            if self._stopped():
                return

            # 记录助手消息（含 tool_calls）
            msgs.append({
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {"id": c["id"], "type": "function",
                     "function": {"name": c["name"],
                                  "arguments": json.dumps(
                                      c["arguments"], ensure_ascii=False)}}
                    for c in pending],
            })

            for call in pending:
                if self._stopped():
                    return
                yield ("tool", {"name": call["name"],
                                "args": call["arguments"],
                                "running": True})
                result = execute_tool(call["name"], call["arguments"])
                yield ("tool", {"name": call["name"],
                                "args": call["arguments"],
                                "result": result, "running": False})
                msgs.append({"role": "tool",
                             "tool_call_id": call["id"],
                             "content": result})

        yield ("notice", "已达到最大工具调用轮数（%d），以上为目前结果。"
                % self.max_iterations)
