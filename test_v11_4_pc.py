# -*- coding: utf-8 -*-
"""V11.4 电脑端新功能测试：消息引用（Quote）/ 分支对话（Branch）。

全部为纯逻辑测试，零 Qt / 零安卓依赖，桌面与安卓同源共用。
运行：python3.11 -m pytest test_v11_4_pc.py -q
"""
import os
import sys
import json
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.sessions import (SessionStore, format_quote, build_quoted_prompt,
                           QUOTE_MAX_CHARS)


def _new_store():
    d = tempfile.mkdtemp()
    os.environ["XDG_CONFIG_HOME"] = d
    return SessionStore(path=os.path.join(d, "sess.json"))


def _seed(st):
    """建立 5 条消息：system / user / assistant / user / assistant。"""
    sid = st.current_id()
    st.append({"role": "system", "content": "你是助手"})
    st.append({"role": "user", "content": "讲讲量子计算"})
    st.append({"role": "assistant", "content": "量子计算利用叠加态与纠缠。"})
    st.append({"role": "user", "content": "再举个例子"})
    st.append({"role": "assistant", "content": "比如 Shor 算法。"})
    st.toggle_star(sid, 2)
    st.toggle_star(sid, 4)
    st.set_tags(sid, "物理, 计算")
    return sid


# ----------------------------------------------------------------------
# format_quote（模块级纯函数）
# ----------------------------------------------------------------------
def test_format_quote_basic():
    m = {"role": "assistant", "content": "量子计算利用叠加态与纠缠。"}
    q = format_quote(m, index=2)
    assert q.startswith("> 【引用 #2 · 助手】")
    assert "> 量子计算利用叠加态与纠缠。" in q
    print("[OK] test_format_quote_basic")


def test_format_quote_filters():
    # 系统提示 / 空内容 / 非 dict 一律返回空串
    assert format_quote({"role": "system", "content": "隐藏的提示"}) == ""
    assert format_quote({"role": "user", "content": "   "}) == ""
    assert format_quote(None) == ""
    assert format_quote({"role": "user", "content": ""}) == ""
    print("[OK] test_format_quote_filters")


def test_format_quote_multiline_and_truncate():
    # 多行逐行加 > 前缀
    q = format_quote({"role": "user", "content": "第一行\n第二行"}, index=1)
    assert "> 第一行\n> 第二行" in q
    # 超长截断
    long = "量" * (QUOTE_MAX_CHARS + 50)
    q2 = format_quote({"role": "assistant", "content": long})
    assert q2.endswith("…")
    assert len(q2) < len(long)
    # 多模态 content 取文本部分
    mm = {"role": "user", "content": [
        {"type": "text", "text": "这是图片说明"},
        {"type": "image_url", "image_url": {"url": "data:..."}},
    ]}
    assert "这是图片说明" in format_quote(mm)
    print("[OK] test_format_quote_multiline_and_truncate")


# ----------------------------------------------------------------------
# build_quoted_prompt（模块级纯函数）
# ----------------------------------------------------------------------
def test_build_quoted_prompt():
    q = "> 【引用 #2 · 助手】\n> 一段历史"
    # 引用 + 新问题
    out = build_quoted_prompt(q, "那它和经典计算有何区别？")
    assert q in out and "那它和经典计算有何区别？" in out and "---" in out
    # 无引用 → 原样返回用户输入
    assert build_quoted_prompt("", "纯问题") == "纯问题"
    assert build_quoted_prompt(None, "纯问题") == "纯问题"
    # 有引用无新问题 → 续写提示
    only_q = build_quoted_prompt(q, "")
    assert q in only_q and "续写" in only_q
    # 全空
    assert build_quoted_prompt("", "") == ""
    print("[OK] test_build_quoted_prompt")


# ----------------------------------------------------------------------
# Store.quote_block / get_message
# ----------------------------------------------------------------------
def test_quote_block_and_get_message():
    st = _new_store()
    sid = _seed(st)
    assert st.get_message(sid, 2)["role"] == "assistant"
    assert st.get_message(sid, 99) is None
    assert st.get_message("不存在的会话", 0) is None
    assert "【引用 #2 · 助手】" in st.quote_block(sid, 2)
    assert st.quote_block(sid, 99) == ""           # 越界
    assert st.quote_block(sid, 0) == ""           # 系统提示被过滤
    print("[OK] test_quote_block_and_get_message")


# ----------------------------------------------------------------------
# Store.branch_from（核心）
# ----------------------------------------------------------------------
def test_branch_from_copies_prefix():
    st = _new_store()
    sid = _seed(st)
    b = st.branch_from(sid, 2, title="量子新分支")
    assert b is not None
    assert b["title"] == "量子新分支"
    # 复制 messages[:3]（含 system + 前两条对话）
    assert len(b["messages"]) == 3
    assert b["messages"][0]["role"] == "system"
    assert b["messages"][2]["content"] == "量子计算利用叠加态与纠缠。"
    # 溯源
    assert b["branched_from"] == {"session_id": sid, "index": 2}
    # 新会话成为 current
    assert st.current_id() == b["id"]
    # 原会话不变
    assert len(st.messages(sid)) == 5
    print("[OK] test_branch_from_copies_prefix")


def test_branch_from_metadata():
    st = _new_store()
    sid = _seed(st)
    b = st.branch_from(sid, 2)
    # 默认标题
    assert b["title"].startswith("分支 · ")
    # tags 继承
    assert set(b["tags"]) == {"物理", "计算"}
    # starred 仅保留下标 <= 2（原收藏 {2,4} → 仅 {2}）
    assert b["starred"] == [2]
    # summary 全新
    assert b["summary"] == ""
    # 深拷贝：改动分支不污染原会话
    b["messages"][2]["content"] = "已被改动"
    assert st.messages(sid)[2]["content"] == "量子计算利用叠加态与纠缠。"
    print("[OK] test_branch_from_metadata")


def test_branch_from_invalid_and_persist():
    st = _new_store()
    sid = _seed(st)
    assert st.branch_from(sid, 99) is None          # 越界
    assert st.branch_from("不存在的会话", 0) is None
    assert st.branch_from(sid, -1) is None         # 负索引
    b = st.branch_from(sid, 1)
    # 持久化：新建 store 读同一文件，分支与溯源仍在
    st2 = SessionStore(path=st.path)
    got = st2.get(b["id"])
    assert got is not None and got["branched_from"]["index"] == 1
    assert len(got["messages"]) == 2
    print("[OK] test_branch_from_invalid_and_persist")


# ----------------------------------------------------------------------
# Store.list_branches + 向后兼容（旧会话无新字段）
# ----------------------------------------------------------------------
def test_list_branches_and_backward_compat():
    st = _new_store()
    sid = _seed(st)
    assert st.list_branches(sid) == []
    st.branch_from(sid, 1)
    st.branch_from(sid, 3)
    assert len(st.list_branches(sid)) == 2
    assert len(st.list_branches()) == 2           # 全部
    # 模拟旧格式：注入一条无任何 v11.3/v11.4 字段的历史会话
    st.data["sessions"].append({
        "id": "legacy_1", "title": "老会话",
        "created": 1, "updated": 2,
        "messages": [{"role": "user", "content": "旧数据"}],
    })
    st.save()
    st3 = SessionStore(path=st.path)
    legacy = st3.get("legacy_1")
    assert legacy is not None
    assert legacy.get("starred") is None          # 旧数据无字段
    assert legacy.get("branched_from") is None
    assert st3.quote_block("legacy_1", 0).startswith("> 【引用 #0 · 我】")
    assert st3.list_branches(sid)                 # 老会话不干扰分支列表
    print("[OK] test_list_branches_and_backward_compat")


if __name__ == "__main__":
    test_format_quote_basic()
    test_format_quote_filters()
    test_format_quote_multiline_and_truncate()
    test_build_quoted_prompt()
    test_quote_block_and_get_message()
    test_branch_from_copies_prefix()
    test_branch_from_metadata()
    test_branch_from_invalid_and_persist()
    test_list_branches_and_backward_compat()
    print("\nALL V11.4 TESTS PASSED (9/9)")
