# -*- coding: utf-8 -*-
"""V13.6.3 回归：SSE 流式响应不带 charset 时，中文不再乱码（ä½ å¥½…）。

复现条件：OpenAI 兼容流式接口（LM Studio / Ollama / 云端）常在 text/event-stream
里不带 charset，requests 会把 resp.encoding 默认成 ISO-8859-1(latin-1)，
iter_lines(decode_unicode=True) 据此解码 UTF-8 字节 → 中文变成 ä½ å¥½ 这类乱码。
修复：chat_stream / chat_agent_stream 在读取前强制 resp.encoding = "utf-8"。
"""
import os
import sys
import json

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from unittest import mock

import core.api as api_mod


def make_sse(content):
    """构造一段 UTF-8 的 SSE 字节流（无 charset，正是触发乱码的条件）。"""
    obj = {"choices": [{"delta": {"content": content}}]}
    return ("data: " + json.dumps(obj, ensure_ascii=False) + "\n\n"
            "data: [DONE]\n\n").encode("utf-8")


class FakeResp:
    """模拟 requests.Response：encoding 默认 latin-1（复现无 charset 场景），
    iter_lines(decode_unicode=True) 按 self.encoding 解码原始 UTF-8 字节。"""
    def __init__(self, raw_bytes, encoding="iso-8859-1"):
        self.status_code = 200
        self.encoding = encoding          # requests 在无 charset 时的默认行为
        self._lines = raw_bytes.split(b"\n")
        self._text = ""

    def iter_lines(self, decode_unicode=False):
        for lb in self._lines:
            if decode_unicode:
                yield lb.decode(self.encoding)
            else:
                yield lb

    @property
    def text(self):
        return self._text


def run():
    results = []
    def check(name, cond, extra=""):
        results.append((name, bool(cond)))
        print(("PASS " if cond else "FAIL ") + name + (("  -> " + extra) if extra else ""))

    # 用真实的中文字符串，正是用户报错的「你好！有什么我可以帮你的吗？」
    chinese = "你好！有什么我可以帮你的吗？"
    raw = make_sse(chinese)

    client = api_mod.ChatClient(base_url="http://localhost:1234/v1",
                                api_key="", model="minicpm5-1b")

    # ---- 普通流式 chat_stream ----
    with mock.patch.object(api_mod.requests, "post",
                           return_value=FakeResp(raw, encoding="iso-8859-1")):
        out = "".join(t for kind, t in client.chat_stream([{"role": "user", "content": "hi"}])
                      if kind == "content")
    check("chat_stream 正确解码中文（无乱码）", out == chinese, repr(out))
    check("chat_stream 未出现 latin-1 乱码", "ä½" not in out and "å¥½" not in out, repr(out))

    # ---- 带工具的流式 chat_agent_stream ----
    with mock.patch.object(api_mod.requests, "post",
                           return_value=FakeResp(raw, encoding="iso-8859-1")):
        out2 = "".join(t for kind, t in
                       client.chat_agent_stream([{"role": "user", "content": "hi"}], [])
                       if kind == "content")
    check("chat_agent_stream 正确解码中文（无乱码）", out2 == chinese, repr(out2))
    check("chat_agent_stream 未出现 latin-1 乱码", "ä½" not in out2 and "å¥½" not in out2, repr(out2))

    # ---- 回归：即使服务端真的发了 charset=utf-8（正常情况）也应正确 ----
    with mock.patch.object(api_mod.requests, "post",
                           return_value=FakeResp(raw, encoding="utf-8")):
        out3 = "".join(t for kind, t in client.chat_stream([{"role": "user", "content": "hi"}])
                       if kind == "content")
    check("显式 utf-8 头也正确", out3 == chinese, repr(out3))

    passed = sum(1 for _, ok in results if ok)
    print("\n=== 结果：%d/%d 通过 ===" % (passed, len(results)))
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(run())
