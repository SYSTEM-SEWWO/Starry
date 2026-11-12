# -*- coding: utf-8 -*-
"""深度思考（推理）引擎（V8.0）：把模型的「思考过程」与「正式回答」清晰分离。

背景：
- 部分推理模型以独立字段 `reasoning_content` 流式返回思考（见 core/api.py）。
- 部分模型把思考包进 `<think>...</think>` 再随正文 `content` 返回。
- 本模块统一解析：业务侧只拿到干净正文，UI 只负责渲染思考块，
  让「深度思考多一点」在每个环节都可控、可测、可折叠。

全部为纯函数 / 无状态类，离线可单测（selftest.py::test_v80_memory_reasoning）。
"""

import re

_THINK_OPEN = re.compile(r"<think\s*>", re.I)
_THINK_CLOSE = re.compile(r"</think\s*>", re.I)


class ReasoningTrace:
    """累积一段思考过程（支持流式分片到达）。"""

    def __init__(self):
        self._parts = []

    def append(self, text):
        if text:
            self._parts.append(text)
        return self

    @property
    def full(self):
        return "".join(self._parts)

    @property
    def segments(self):
        return list(self._parts)

    def is_empty(self):
        return not self._parts

    def summarize(self, max_chars=200):
        """压缩摘要：过长思考截断并加省略号（UI 折叠标题用）。"""
        t = self.full.strip()
        if len(t) <= max_chars:
            return t
        return t[:max_chars].rstrip() + "…"


def split_think_content(text):
    """把可能含 `<think>...</think>` 的文本拆成 `(thinking, answer)`。

    适用于一次性完整文本；流式分片请用 StreamingThinkSplitter。
    无标签时返回 `("", text)`。
    """
    if not text:
        return "", ""
    out_think, out_ans = [], []
    pos = 0
    in_think = False
    for m in re.finditer(r"</?think\s*>", text, re.I):
        seg = text[pos:m.start()]
        (out_think if in_think else out_ans).append(seg)
        # 开标签 → 进入思考态；闭标签 → 退出思考态
        in_think = not m.group(0).lower().startswith("</")
        pos = m.end()
    tail = text[pos:]
    (out_think if in_think else out_ans).append(tail)
    return "".join(out_think).strip(), "".join(out_ans).strip()


class StreamingThinkSplitter:
    """增量解析器：逐片喂入 content，按状态分离思考 / 正文增量。

    用法：
        s = StreamingThinkSplitter()
        for chunk in stream:
            think_delta, ans_delta = s.feed(chunk)
            # 分别投递到思考块 / 正文
        think_tail, ans_tail = s.flush()   # 流结束收尾

    设计：不在标签边界的字符会被「即时」发出；处于可能形成
    开/闭标签前缀的尾部字符会被短暂扣留，待下一片确认后发出，
    **绝不丢失内容**（最终由 flush 兜底）。
    """

    def __init__(self):
        self.in_think = False
        self._buf = ""

    def feed(self, chunk):
        """返回 `(thinking_delta, answer_delta)`，可能为空串。"""
        self._buf += (chunk or "")
        thinking_delta, answer_delta = "", ""
        while True:
            if not self.in_think:
                m = _THINK_OPEN.search(self._buf)
                if not m:
                    cut = self._safe_cut(self._buf, "<think")
                    if cut > 0:
                        answer_delta += self._buf[:cut]
                        self._buf = self._buf[cut:]
                    break
                pre = self._buf[:m.start()]
                if pre:
                    answer_delta += pre
                self._buf = self._buf[m.end():]
                self.in_think = True
            else:
                m = _THINK_CLOSE.search(self._buf)
                if not m:
                    cut = self._safe_cut(self._buf, "</think")
                    if cut > 0:
                        thinking_delta += self._buf[:cut]
                        self._buf = self._buf[cut:]
                    break
                mid = self._buf[:m.start()]
                if mid:
                    thinking_delta += mid
                self._buf = self._buf[m.end():]
                self.in_think = False
        return thinking_delta, answer_delta

    @staticmethod
    def _safe_cut(buf, prefix):
        """扣留可能成为标签前缀的尾部字符，返回可安全发出的长度。"""
        for i in range(len(prefix), 0, -1):
            if buf.endswith(prefix[:i]):
                return len(buf) - i
        return len(buf)

    def flush(self):
        """流结束：把剩余缓冲按当前状态全部发出。返回 `(think, ans)`。"""
        if not self._buf:
            return "", ""
        delta = ("", self._buf) if self.in_think else (self._buf, "")
        self._buf = ""
        return delta
