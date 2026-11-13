# -*- coding: utf-8 -*-
"""V11.5 单测：分支对比 / 会话合并 / 对话统计 / SessionStore.merge_into。

全部针对 core.insights 纯函数与 core.sessions 的薄层状态方法，
零 Qt、零网络，可离线运行。
"""
from core import insights as I
from core.sessions import SessionStore


def _msg(role, content):
    return {"role": role, "content": content}


def _session(sid, title, messages, **extra):
    d = {"id": sid, "title": title, "messages": messages,
         "created": 1000, "updated": 2000}
    d.update(extra)
    return d


def _fork_pair():
    """A 与其分支 B：前 3 条相同，之后各自续写。"""
    head = [_msg("system", "你是助手"),
            _msg("user", "讲讲量子计算"),
            _msg("assistant", "量子计算利用叠加态与纠缠")]
    a = _session("A", "原会话", head + [_msg("user", "再举个例子")])
    b = _session("B", "分支 · 原会话", head + [
        _msg("user", "换个角度"),
        _msg("assistant", "从密码学看 Shor 算法"),
    ], branched_from={"session_id": "A", "index": 2},
        tags=["物理", "量子"], starred=[2], summary="量子计算入门")
    return a, b


def _store(tmp_path):
    return SessionStore(path=str(tmp_path / "sessions.json"))


def _fill(store, sid):
    for m in [_msg("system", "你是助手"),
              _msg("user", "讲讲量子计算"),
              _msg("assistant", "利用叠加态与纠缠"),
              _msg("user", "再举个例子")]:
        store.append(m, sid)
    return sid


# ---------------------------------------------------------------------------
# diff_sessions
# ---------------------------------------------------------------------------
def test_diff_common_prefix_and_alignment():
    a, b = _fork_pair()
    d = I.diff_sessions(a, b)
    assert d["common_prefix"] == 3
    assert d["a_count"] == 4 and d["b_count"] == 5
    assert not d["identical"]
    assert 0.6 < d["similarity"] < 0.8
    # 第 4 条同位置不同 → modified；B 多出 1 条 → b_only
    assert len(d["modified"]) == 1
    assert d["modified"][0]["index"] == 3
    assert len(d["b_only"]) == 1 and len(d["a_only"]) == 0


def test_diff_identical():
    a, _ = _fork_pair()
    d = I.diff_sessions(a, dict(a))
    assert d["identical"] is True
    assert d["similarity"] == 1.0
    assert d["common_prefix"] == 4
    assert not d["modified"] and not d["a_only"] and not d["b_only"]


def test_diff_unrelated_sessions():
    a = _session("A", "甲", [_msg("user", "你好")])
    b = _session("B", "乙", [_msg("assistant", "世界")])
    d = I.diff_sessions(a, b)
    assert d["common_prefix"] == 0
    assert len(d["modified"]) == 1
    assert d["similarity"] == 0.0


def test_diff_empty_and_no_mutation():
    assert I.diff_sessions({}, {})["identical"] is True
    a, b = _fork_pair()
    a_before = [dict(m) for m in a["messages"]]
    I.diff_sessions(a, b)
    assert a["messages"] == a_before       # 纯函数不修改入参


def test_diff_multimodal_content():
    a = _session("A", "甲", [_msg("user", [{"type": "text", "text": "你好"}])])
    b = _session("B", "乙", [_msg("user", "你好")])
    assert I.message_content(a["messages"][0]) == "你好"
    assert I.diff_sessions(a, b)["common_prefix"] == 1


def test_diff_max_chars_truncates():
    a = _session("A", "甲", [_msg("user", "短")])
    b = _session("B", "乙", [_msg("user", "很长" * 200)])
    d = I.diff_sessions(a, b, max_chars=20)
    assert len(d["modified"][0]["b_text"]) <= 21


# ---------------------------------------------------------------------------
# merge_messages
# ---------------------------------------------------------------------------
def test_merge_branch_skips_duplicate_prefix():
    a, b = _fork_pair()
    merged, report = I.merge_messages(a["messages"], b["messages"])
    assert report["common_prefix"] == 3
    assert report["added"] == 2 and report["skipped"] == 0
    assert len(merged) == 6
    assert report["mapping"] == {0: 0, 1: 1, 2: 2, 3: 4, 4: 5}
    assert merged[4]["content"] == "换个角度"


def test_merge_unrelated_full_append():
    a = _session("A", "甲", [_msg("user", "你好")])
    b = _session("B", "乙", [_msg("assistant", "世界"), _msg("user", "继续")])
    merged, report = I.merge_messages(a["messages"], b["messages"])
    assert report["common_prefix"] == 0
    assert report["added"] == 2 and len(merged) == 3


def test_merge_explicit_common_prefix():
    a, b = _fork_pair()
    merged, report = I.merge_messages(
        a["messages"], b["messages"], dedup=False, common_prefix=2)
    assert report["common_prefix"] == 2
    assert report["added"] == 3        # B 的第 3/4/5 条都会追加
    assert len(merged) == 7


def test_merge_dedup_false_keeps_duplicates():
    a = _session("A", "甲", [_msg("user", "你好")])
    b = _session("B", "乙", [_msg("assistant", "世界"),
                             _msg("user", "你好")])
    _m, r = I.merge_messages(a["messages"], b["messages"], dedup=True)
    assert r["skipped"] == 1
    merged2, r2 = I.merge_messages(a["messages"], b["messages"], dedup=False)
    assert r2["skipped"] == 0 and len(merged2) == 3


def test_merge_no_mutation():
    a, b = _fork_pair()
    a_copy = [dict(m) for m in a["messages"]]
    b_copy = [dict(m) for m in b["messages"]]
    I.merge_messages(a["messages"], b["messages"])
    assert a["messages"] == a_copy and b["messages"] == b_copy


# ---------------------------------------------------------------------------
# stats
# ---------------------------------------------------------------------------
def test_session_stats_basic():
    a, b = _fork_pair()
    s = I.session_stats(b)
    assert s["messages"] == 5 and s["user"] == 2 and s["assistant"] == 2
    assert s["system"] == 1
    assert s["chars"] > 0 and s["tokens"] > 0
    assert s["starred"] == 1 and s["has_summary"] is True
    assert s["is_branch"] is True
    assert s["tags"] == ["物理", "量子"]
    assert s["branched_from"]["session_id"] == "A"


def test_session_stats_empty():
    s = I.session_stats(_session("X", "空", []))
    assert s["messages"] == 0 and s["avg_chars"] == 0.0
    assert s["tokens"] == 0 and s["is_branch"] is False


def test_overview_stats():
    a, b = _fork_pair()
    o = I.overview_stats([a, b])
    assert o["sessions"] == 2
    assert o["messages"] == 9
    assert o["user"] == 4 and o["assistant"] == 3
    assert o["branches"] == 1 and o["with_summary"] == 1
    assert o["unique_tags"] == 2
    assert o["avg_messages"] == 4.5
    assert o["busiest"]["id"] == "B"


def test_overview_stats_empty():
    o = I.overview_stats([])
    assert o["sessions"] == 0 and o["avg_messages"] == 0.0
    assert o["busiest"] is None


def test_estimate_tokens():
    assert I.estimate_tokens("量子计算") == 4       # CJK 每字 1 token
    assert I.estimate_tokens("hello world") >= 2     # 11 字符 ≈ 3 token
    assert I.estimate_tokens("") == 0
    assert I.estimate_tokens("中a") == 2             # 1 CJK + 1 其他


def test_stats_multimodal_and_other_role():
    s = I.session_stats(_session(
        "X", "多模态",
        [_msg("user", [{"type": "text", "text": "看图"}]),
         _msg("tool", "工具输出")]))
    assert s["chars"] == 6
    assert s["other"] == 1 and s["user"] == 1


def test_format_markdown():
    a, b = _fork_pair()
    d = I.diff_sessions(a, b)
    md = I.format_diff_markdown(d)
    assert "会话对比" in md and "共同前缀" in md and "相似度" in md
    st = I.format_stats_markdown(I.session_stats(b), I.overview_stats([a, b]))
    assert "对话统计" in st and "全局概览" in st and "估算 tokens" in st


# ---------------------------------------------------------------------------
# SessionStore.merge_into
# ---------------------------------------------------------------------------
def test_merge_into_branch_starred_remap(tmp_path):
    store = _store(tmp_path)
    sid = _fill(store, store.current_id())
    store.toggle_star(sid, 2)                     # 源会话收藏 #2
    branch = store.branch_from(sid, 2, title="分支")   # 继承 starred [2]
    bid = branch["id"]
    store.append(_msg("user", "换个角度"), bid)
    store.append(_msg("assistant", "从密码学看"), bid)
    store.toggle_star(bid, 3)                     # 分支再收藏 #3

    ok, report = store.merge_into(sid, bid)
    assert ok is True
    assert report["common_prefix"] == 3 and report["added"] == 2
    assert len(store.messages(sid)) == 6
    # 收藏下标重映射：源的 #2 保持，分支的 #3 → 合并后 #4
    starred = store.get(sid)["starred"]
    assert 2 in starred and 4 in starred and 3 not in starred
    assert store.current_id() == sid
    assert store.get(bid) is not None              # source 保留可回溯


def test_merge_into_tags_and_invalid(tmp_path):
    store = _store(tmp_path)
    sid = _fill(store, store.current_id())
    store.set_tags(sid, ["物理"])
    branch = store.branch_from(sid, 2, title="分支")
    bid = branch["id"]
    store.set_tags(bid, ["物理", "量子"])
    ok, report = store.merge_into(sid, bid)
    assert ok and report["tags_merged"] == 2
    assert set(store.get(sid)["tags"]) == {"物理", "量子"}
    # 非法：不存在 / 自合并
    assert store.merge_into(sid, "not-exist")[0] is False
    assert store.merge_into(sid, sid)[0] is False


def test_merge_into_persisted(tmp_path):
    path = str(tmp_path / "sessions.json")
    store = SessionStore(path=path)
    sid = _fill(store, store.current_id())
    branch = store.branch_from(sid, 2, title="分支")
    bid = branch["id"]
    store.append(_msg("user", "新方向"), bid)
    assert store.merge_into(sid, bid)[0] is True
    # 重新从磁盘加载
    again = SessionStore(path=path)
    assert len(again.messages(sid)) == 5
    assert again.current_id() == sid


def test_insights_has_no_qt_dependency():
    """纯逻辑层不得 import 任何 GUI/安卓框架（AST 校验真实依赖）。"""
    import ast
    import inspect
    tree = ast.parse(inspect.getsource(I))
    roots = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            roots.add(node.module.split(".")[0])
    assert "PyQt5" not in roots and "toga" not in roots
    assert I.__name__ == "core.insights"
