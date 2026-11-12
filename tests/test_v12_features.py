# -*- coding: utf-8 -*-
"""星语 Starry v12.0 · 新功能纯逻辑单测（跨三端同源模块 core.stardust）。

运行：python tests/test_v12_features.py    （退出码 0 = 全绿）
覆盖：星尘卡确定性 / 上下文预算三种策略 / .starry 存档完整性与防篡改 /
      CLI 新增子命令 / 版本单一真源 / 桌面命令面板入口存在性。
"""
import ast
import io
import json
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core import stardust                                 # noqa: E402
from core import config as cfg_mod                         # noqa: E402
from core import cli as cli_mod                            # noqa: E402

RESULTS = []


def check(name, cond, extra=""):
    RESULTS.append((name, bool(cond), extra))
    print(("PASS" if cond else "FAIL"), "-", name, extra)


# ---------------------------------------------------------------------------
# 1) token 估算
# ---------------------------------------------------------------------------
check("estimate_tokens 空串为 0", stardust.estimate_tokens("") == 0)
check("estimate_tokens None 为 0", stardust.estimate_tokens(None) == 0)
check("estimate_tokens 中文按字数",
      stardust.estimate_tokens("你好世界") == 4)
check("estimate_tokens 英文按 4 字符 1 token",
      stardust.estimate_tokens("abcdefgh") == 2)

# ---------------------------------------------------------------------------
# 2) 星尘卡
# ---------------------------------------------------------------------------
kw = dict(title="T", reasoning="第一句分析。\n第二句推导。\n第三句结论。",
          answer="这是最终回答内容。", prompt="请分析这个问题？",
          branched_from="sess-1", ts="2026-11-07 12:00")
card = stardust.build_echo_card(**kw)
check("星尘卡确定性（同输入同输出）", card == stardust.build_echo_card(**kw))
check("星尘卡含标题", "**T**" in card)
check("星尘卡含提问首句", "请分析这个问题？" in card)
check("星尘卡含思考起点与落点", "第一句分析" in card and "第三句结论" in card)
check("星尘卡含回答", "这是最终回答内容。" in card)
check("星尘卡含分支锚点", "sess-1" in card)
check("星尘卡含 token 量级", "tokens" in card)
check("星尘卡分片数正确", "思考分片 3" in card)
check("星尘卡时间戳可省略",
      "2026-11-07" not in stardust.build_echo_card(answer="x"))
check("星尘卡空输入不崩",
      "（无正文）" in stardust.build_echo_card())
check("星尘卡超长回答被截断",
      len(stardust.build_echo_card(answer="啊" * 2000)) < 700)
check("星尘卡不修改入参", kw["answer"] == "这是最终回答内容。")

# ---------------------------------------------------------------------------
# 3) 上下文预算裁剪
# ---------------------------------------------------------------------------
msgs = [{"role": "system", "content": "你是助手"}] + [
    {"role": "user" if i % 2 else "assistant", "content": "第%d条消息内容" % i}
    for i in range(1, 13)]
snapshot = json.dumps(msgs, ensure_ascii=False)
for policy in ("keep_recent", "keep_first", "keep_ends"):
    plan = stardust.plan_trim(msgs, 60, policy=policy)
    check("plan_trim %s 返回完整字段" % policy,
          set(plan) >= {"keep_indices", "drop_indices", "kept_tokens",
                        "total_tokens", "trimmed", "policy", "max_tokens"})
    check("plan_trim %s 保留系统消息" % policy, 0 in plan["keep_indices"])
    check("plan_trim %s 不超预算" % policy,
          plan["kept_tokens"] <= 60 or plan["kept_tokens"] == plan["total_tokens"])
check("plan_trim 不修改入参", json.dumps(msgs, ensure_ascii=False) == snapshot)
check("plan_trim 下标无重复且互补",
      (lambda p: sorted(p["keep_indices"] + p["drop_indices"]) == list(range(len(msgs))))(
          stardust.plan_trim(msgs, 60)))
check("plan_trim 大预算不裁剪",
      stardust.plan_trim(msgs, 100000)["trimmed"] is False)
check("plan_trim 空消息安全", stardust.plan_trim([], 100)["keep_indices"] == [])
check("plan_trim keep_recent 保住最后一条",
      len(msgs) - 1 in stardust.plan_trim(msgs, 30)["keep_indices"])
check("plan_trim keep_first 保住最早一条",
      1 in stardust.plan_trim(msgs, 30, policy="keep_first")["keep_indices"])

# ---------------------------------------------------------------------------
# 4) .starry 存档
# ---------------------------------------------------------------------------
src_sessions = {"current": "a", "sessions": [{"id": "a", "messages": [
    {"role": "user", "content": "你好"}]}]}
src_memory = {"enabled": True, "seq": 2, "entries": [{"text": "喜欢简洁"}]}
arch = stardust.pack_archive(sessions=src_sessions, memory=src_memory,
                             meta={"v": "12.0.0"})
back = stardust.unpack_archive(arch)
check("存档 round-trip 会话", back["sessions"] == src_sessions)
check("存档 round-trip 记忆", back["memory"] == src_memory)
check("存档 round-trip 元信息", back["meta"] == {"v": "12.0.0"})
check("存档版本号", back["version"] == stardust.ARCHIVE_VERSION)
check("存档不修改入参", src_sessions["current"] == "a"
      and src_memory["seq"] == 2)
check("存档返回独立副本",
      (back["sessions"]["sessions"][0]["messages"].append({"x": 1}) is None
       and len(src_sessions["sessions"][0]["messages"]) == 1))


def reject(mutate, label):
    env = json.loads(arch)
    mutate(env)
    try:
        stardust.unpack_archive(json.dumps(env, ensure_ascii=False))
        check(label, False)
    except ValueError:
        check(label, True)


reject(lambda e: e["payload"].update(memory={"x": 1}), "篡改 payload 被拒绝")
reject(lambda e: e.update(magic="OTHER"), "错误 magic 被拒绝")
reject(lambda e: e.update(version=999), "未来版本被拒绝")
reject(lambda e: e.update(version=0), "非法版本被拒绝")
reject(lambda e: e.update(checksum="00" * 32), "校验和错误被拒绝")
reject(lambda e: e["payload"].pop("meta"), "缺字段被拒绝")
try:
    stardust.unpack_archive("not-json")
    check("非法 JSON 被拒绝", False)
except ValueError:
    check("非法 JSON 被拒绝", True)

# ---------------------------------------------------------------------------
# 5) CLI 新增子命令（离线，不发网络请求）
# ---------------------------------------------------------------------------
_TMP = tempfile.mkdtemp(prefix="starry-v12-cli-")
_orig_dir = cfg_mod.get_config_dir
cfg_mod.get_config_dir = lambda: _TMP
try:
    buf = io.StringIO()
    check("--doctor 退出码 0", cli_mod.run_cli(["--doctor"], out=buf) == 0)
    check("--doctor 含版本号", cfg_mod.APP_VERSION in buf.getvalue())

    buf = io.StringIO()
    check("--version 退出码 0", cli_mod.run_cli(["--version"], out=buf) == 0)

    ap = os.path.join(_TMP, "t.starry")
    buf = io.StringIO()
    check("--archive 退出码 0", cli_mod.run_cli(["--archive", ap], out=buf) == 0)
    check("--archive 产出文件", os.path.isfile(ap))
    if os.path.isfile(ap):
        check("--archive 产物可被验签解析",
              stardust.unpack_archive(open(ap, encoding="utf-8").read())["version"]
              == stardust.ARCHIVE_VERSION)

    buf = io.StringIO()
    check("--restore 合法存档退出码 0",
          cli_mod.run_cli(["--restore", ap], out=buf) == 0)
    bad = ap + ".bad"
    open(bad, "w", encoding="utf-8").write("{broken")
    buf = io.StringIO()
    check("--restore 损坏存档被拒绝",
          cli_mod.run_cli(["--restore", bad], out=buf) == 2)

    buf = io.StringIO()
    check("--budget 退出码 0", cli_mod.run_cli(["--budget", "800"], out=buf) == 0)
    check("--budget 输出裁剪计划", "裁剪计划" in buf.getvalue())

    # --echo：用离线 client，验证 JSON 模式也带 echo_card
    class _C:
        def chat_stream(self, messages, should_stop=None):
            yield ("reasoning", "推演")
            yield ("content", "离线回答")
    buf = io.StringIO()
    cli_mod.run_chat(_C(), "测试", cfg=None, as_json=True, out=buf, echo=True)
    payload = json.loads(buf.getvalue())
    check("--echo JSON 模式带 echo_card", "✦ 星尘卡" in payload.get("echo_card", ""))
finally:
    cfg_mod.get_config_dir = _orig_dir

# ---------------------------------------------------------------------------
# 6) 版本单一真源 + 桌面命令面板入口（AST 静态检查，不需 Qt）
# ---------------------------------------------------------------------------
check("APP_VERSION 非空", bool(cfg_mod.APP_VERSION))
mcp = open(os.path.join(ROOT, "core", "mcp.py"), encoding="utf-8").read()
check("MCP CLIENT_INFO 版本同步",
      '"version": "%s"' % cfg_mod.APP_VERSION in mcp)
pyproject = open(os.path.join(ROOT, "android", "pyproject.toml"),
                 encoding="utf-8").read()
check("Android 工程版本同步",
      'version = "%s"' % cfg_mod.APP_VERSION in pyproject)

tree = ast.parse(open(os.path.join(ROOT, "app", "assistant.py"),
                      encoding="utf-8").read())
ids = set()
for node in ast.walk(tree):
    if isinstance(node, ast.Tuple) and node.elts and isinstance(node.elts[0], ast.Constant):
        if isinstance(node.elts[0].value, str):
            ids.add(node.elts[0].value)
for cid in ("echo_card", "budget_plan", "archive_export", "archive_import", "doctor"):
    check("命令面板含新命令 %s" % cid, cid in ids)

total = len(RESULTS)
passed = sum(1 for _, ok, _ in RESULTS if ok)
print("\n==== v12.0 新功能单测：%d/%d 通过 ====" % (passed, total))
for name, ok, extra in RESULTS:
    if not ok:
        print("  ✗", name, extra)
sys.exit(0 if passed == total else 1)
