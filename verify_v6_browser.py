# -*- coding: utf-8 -*-
"""v6 浏览器 harness 端到端验证：用本地 fixture 页模拟 DeepSeek 网页版 DOM。

验证点：
    1. 未登录态 → 明确中文错误（登录指引）
    2. 登录后 → 发送 → 流式逐字返回 → 完整拼接 == 页面最终回答
    3. should_stop 中断 → 提前返回，不超时
    4. compose_prompt：多轮前情提要 / 截断 / 单轮直发
    5. 选择器覆盖（url_override + selectors 自定义）
    6. 登录态持久化（同一 profile 二次连接仍已登录）
"""
import os
import shutil
import sys
import tempfile
import threading
import time
from http.server import HTTPServer, SimpleHTTPRequestHandler

_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _ROOT)
os.chdir(_ROOT)

FIXTURE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       "fixture_deepseek.html")


def start_server(directory):
    handler = lambda *a, **kw: SimpleHTTPRequestHandler(
        *a, directory=directory, **kw)

    httpd = HTTPServer(("127.0.0.1", 0), handler)
    port = httpd.server_address[1]
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    return httpd, port


def main():
    from core.browser_llm import (BrowserLLMError, BrowserSession,
                                  playwright_available)
    from core.web_deepseek import DeepSeekWebClient

    results = []

    def check(name, cond, detail=""):
        results.append((name, bool(cond), detail))
        print("[%s] %s%s" % ("PASS" if cond else "FAIL", name,
                             (" — " + detail) if detail else ""))

    if not playwright_available():
        print("SKIP: playwright 不可用")
        return 0

    tmp = tempfile.mkdtemp(prefix="starry_v6_")
    profile = os.path.join(tmp, "profile")
    shutil.copy(FIXTURE, os.path.join(tmp, "index.html"))
    httpd, port = start_server(tmp)
    url = "http://127.0.0.1:%d/index.html" % port

    shared_profile = os.path.join(profile, "shared")

    def make_client(**kw):
        kw.setdefault("headless", True)
        kw.setdefault("profile_dir", shared_profile)
        return DeepSeekWebClient(model="deepseek-chat（网页版）",
                                 url_override=url, **kw)

    try:
        # ---------- 1. compose_prompt ----------
        c = make_client()
        p1 = c.compose_prompt([{"role": "user", "content": "你好"}])
        check("compose：单轮直发", p1 == "你好", p1[:30])
        p2 = c.compose_prompt([
            {"role": "system", "content": "系统提示"},
            {"role": "user", "content": "第一个问题"},
            {"role": "assistant", "content": "第一个回答"},
            {"role": "user", "content": "第二个问题"},
        ])
        check("compose：多轮含前情提要",
              "请接着继续" in p2 and "请回答：第二个问题" in p2
              and "第一个问题" in p2 and "第一个回答" in p2)
        p3 = c.compose_prompt(
            [{"role": "user", "content": "x" * 9000},
             {"role": "user", "content": "最后的问题"}])
        check("compose：超长前情截断", len(p3) < 9000 + 500 and "已截断" in p3)

        # ---------- 2. 未登录态 ----------
        c = make_client()
        try:
            list(c.chat_stream([{"role": "user", "content": "hi"}]))
            check("未登录态报错", False, "竟然没有报错")
        except BrowserLLMError as e:
            check("未登录态报错", "登录" in str(e), str(e)[:60])

        # ---------- 3. 登录后全链路 ----------
        # 复用第 2 步遗留的浏览器会话页面完成登录（同一 playwright 实例）
        sess = BrowserSession.instance()
        page = sess.ensure(shared_profile, True)
        page.click("#login-btn")
        page.wait_for_selector(".avatar[style*='inline']", timeout=5000)

        c = make_client()
        chunks = []
        reasoning = []
        t0 = time.time()
        for kind, text in c.chat_stream(
                [{"role": "user", "content": "流式测试问题"}]):
            if kind == "reasoning":
                reasoning.append(text)
            else:
                chunks.append(text)
        full = "".join(chunks)
        dt = time.time() - t0
        check("流式返回完整回答", "END_OF_FIXTURE_ANSWER" in full,
              "耗时 %.1fs，%d 个分片" % (dt, len(chunks)))
        check("流式分片 > 1（增量而非一次性）", len(chunks) > 1,
              "%d 片" % len(chunks))
        check("思考过程被抓取", bool(reasoning),
              reasoning[0][:30] if reasoning else "无")
        check("速度合理（< 60s）", dt < 60, "%.1fs" % dt)

        # ---------- 4. should_stop 中断 ----------
        c2 = make_client()
        got = []
        state = {"n": 0}

        def should_stop():
            state["n"] += 1
            return state["n"] >= 3

        t0 = time.time()
        for kind, text in c2.chat_stream(
                [{"role": "user", "content": "会被中断的长问题" * 30}],
                should_stop):
            if kind == "content":
                got.append(text)
        dt = time.time() - t0
        check("should_stop 提前中断", dt < 20, "耗时 %.1fs" % dt)
        check("中断时已收到部分内容", len(got) >= 1,
              "%d 片" % len(got))

        # ---------- 5. 登录态持久化 ----------
        c3 = make_client()
        ok, detail = c3.login_status()
        check("登录态持久化（同 profile 二次连接）", ok, detail)

        # ---------- 6. 选择器覆盖 ----------
        c4 = DeepSeekWebClient(
            model="x", headless=True,
            profile_dir=shared_profile,
            url_override=url,
            selectors={"input": ["textarea#chat-input"],
                       "send": ["#send"],
                       "answer": [".ds-markdown"],
                       "answer_block": [".ds-message--assistant"],
                       "stop": ["#stop"],
                       "new_chat": ["#newchat"],
                       "logged_in": [".avatar"],
                       "logged_out": ["#login-btn"]})
        got = []
        for kind, text in c4.chat_stream(
                [{"role": "user", "content": "自定义选择器测试"}]):
            if kind == "content":
                got.append(text)
        check("自定义选择器覆盖生效",
              "END_OF_FIXTURE_ANSWER" in "".join(got))

        BrowserSession.instance().stop()
    finally:
        httpd.shutdown()
        shutil.rmtree(tmp, ignore_errors=True)

    failed = [n for n, ok, _ in results if not ok]
    print("=" * 50)
    print("浏览器 harness 验证：%d 通过，%d 失败"
          % (len(results) - len(failed), len(failed)))
    for n in failed:
        print("  FAIL:", n)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
