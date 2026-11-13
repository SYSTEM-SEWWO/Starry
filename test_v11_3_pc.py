# -*- coding: utf-8 -*-
"""V11.3 电脑端新功能测试：消息收藏 / AI 摘要 / 批量导出。"""
import os
import sys
import tempfile
import zipfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.sessions import SessionStore, build_summary_prompt
from core import exporter


def _new_store():
    d = tempfile.mkdtemp()
    os.environ["XDG_CONFIG_HOME"] = d
    return SessionStore(path=os.path.join(d, "sess.json"))


def test_star():
    st = _new_store()
    sid = st.current_id()
    st.append({"role": "user", "content": "你好"})
    st.append({"role": "assistant", "content": "你好，我是星语。"})
    st.append({"role": "user", "content": "再问一次"})
    # 收藏第 1 条助手消息（index=1）
    assert st.toggle_star(sid, 1) is True
    assert st.is_starred(sid, 1) is True
    assert st.toggle_star(sid, 1) is False
    assert st.is_starred(sid, 1) is False
    # 收藏两条
    st.toggle_star(sid, 1)
    st.toggle_star(sid, 2)
    starred = st.list_starred()
    assert len(starred) == 2
    assert all(x["session_id"] == sid for x in starred)
    # 越界应返回 None
    assert st.toggle_star(sid, 99) is None
    print("[OK] test_star")


def test_summary():
    st = _new_store()
    sid = st.current_id()
    st.append({"role": "user", "content": "讲讲量子计算"})
    st.append({"role": "assistant", "content": "量子计算利用叠加与纠缠..."})
    assert st.get_summary(sid) == ""
    assert st.set_summary(sid, "量子计算入门要点") is True
    assert st.get_summary(sid) == "量子计算入门要点"
    # 持久化：新建 store 读同一文件
    st2 = SessionStore(path=st.path)
    assert st2.get_summary(sid) == "量子计算入门要点"
    print("[OK] test_summary")


def test_build_summary_prompt():
    msgs = [
        {"role": "system", "content": "你是助手"},
        {"role": "user", "content": "什么是深度学习？"},
        {"role": "assistant", "content": "深度学习是多层的神经网络。"},
    ]
    system, user = build_summary_prompt(msgs)
    assert "深度学习" in user
    assert "系统" not in user  # 系统提示被过滤
    # 空对话
    s2, u2 = build_summary_prompt([])
    assert "空" in u2
    print("[OK] test_build_summary_prompt")


def test_export_all():
    st = _new_store()
    sid = st.current_id()
    st.append({"role": "user", "content": "问题A"})
    st.append({"role": "assistant", "content": "回答A"})
    st.create(title="第二个会话")
    st.append({"role": "user", "content": "问题B"})
    st.append({"role": "assistant", "content": "回答B"})
    st.set_summary(sid, "要点摘要")

    for fmt, expect_ext in [("markdown", ".md"), ("json", ".json"),
                            ("text", ".txt"), ("html", ".html")]:
        content, ext = exporter.export_all_sessions(st, fmt=fmt)
        assert ext == expect_ext
        assert isinstance(content, str) and len(content) > 0
        assert "问题A" in content and "问题B" in content
        assert "要点摘要" in content  # 摘要被带入

    # zip 返回字节流，内含每会话文件 + index.md
    data, ext = exporter.export_all_sessions(st, fmt="zip")
    assert ext == ".zip" and isinstance(data, bytes)
    with zipfile.ZipFile(io_mod().BytesIO(data)) as zf:
        names = zf.namelist()
        assert "index.md" in names
        assert len([n for n in names if n.endswith(".md")]) >= 3
    print("[OK] test_export_all")


def io_mod():
    import io
    return io


if __name__ == "__main__":
    test_star()
    test_summary()
    test_build_summary_prompt()
    test_export_all()
    print("\nALL V11.3 PC TESTS PASSED")
