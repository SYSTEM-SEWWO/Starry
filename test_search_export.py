# -*- coding: utf-8 -*-
"""V11.1 新功能测试：相关性检索 + 多格式导出（纯逻辑，无 Qt 依赖）。

运行：python test_search_export.py
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core import sessions as S
from core import exporter as E


def _tmp_store():
    fd, path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    os.remove(path)
    store = S.SessionStore(path=path)
    return store, path


def test_empty_query_returns_all():
    store, path = _tmp_store()
    try:
        a = store.create(title="会话A")["id"]
        b = store.create(title="会话B")["id"]
        c = store.create(title="会话C")["id"]
        res = store.search("")
        ids = [r["id"] for r in res]
        # 空查询应包含所有已建会话（构造时会自带 1 个默认空会话）
        for sid in (a, b, c):
            assert sid in ids, "空查询应返回全部会话，缺失 %s" % sid
        # search_ranked 空查询同样返回全部
        assert all(sid in [r["id"] for r in store.search_ranked("")]
                   for sid in (a, b, c))
    finally:
        os.remove(path)
    print("PASS - 空查询返回全部会话")


def test_ranked_search_ordering_and_snippet():
    store, path = _tmp_store()
    try:
        # 会话1：标题命中关键词
        s1 = store.create(title="Python 入门教程")["id"]
        store.set_messages([
            {"role": "user", "content": "怎么学 Python"},
            {"role": "assistant", "content": "建议从基础语法开始。"},
        ], session_id=s1)
        # 会话2：仅正文命中
        s2 = store.create(title="杂谈")["id"]
        store.set_messages([
            {"role": "user", "content": "今天天气不错"},
            {"role": "assistant", "content": "是的，适合出门散步。"},
        ], session_id=s2)
        # 会话3：不相关
        s3 = store.create(title="菜谱")["id"]
        store.set_messages([
            {"role": "user", "content": "红烧肉怎么做"},
        ], session_id=s3)

        res = store.search_ranked("Python")
        assert res, "应检索到结果"
        # 标题命中的会话应排第一
        assert res[0]["id"] == s1, "标题命中应排第一，实际 %s" % res[0]["id"]
        # 不相关会话不应出现（s2/s3 不含 Python，score=0 被过滤）
        ids = [r["id"] for r in res]
        assert s2 not in ids and s3 not in ids, "不相关会话不应出现"
        # 摘要片段应包含高亮标记
        assert "⚡" in res[0]["snippet"], "摘要应包含高亮标记"
        assert "Python" in res[0]["snippet"]
    finally:
        os.remove(path)
    print("PASS - 相关性排序正确且摘要带高亮")


def test_chinese_bigram_match():
    store, path = _tmp_store()
    try:
        s = store.create(title="深度学习笔记")["id"]
        store.set_messages([
            {"role": "user", "content": "卷积神经网络是什么"},
        ], session_id=s)
        # 用二元组子串「深度」检索，应命中标题
        res = store.search_ranked("深度")
        assert any(r["id"] == s for r in res), "中文二元组应命中标题"
    finally:
        os.remove(path)
    print("PASS - 中文二元组检索命中")


def test_export_formats():
    history = [
        {"role": "system", "content": "你是一个助手"},
        {"role": "user", "content": "你好 <b>world</b> & 世界"},
        {"role": "assistant", "content": "你好！很高兴为你服务。"},
    ]
    md = E.conversation_to_markdown(history, title="测试对话")
    assert "# 测试对话" in md
    assert "你好" in md

    js = E.conversation_to_json(history, title="测试对话")
    import json
    obj = json.loads(js)
    assert obj["title"] == "测试对话"
    assert len(obj["messages"]) == 3

    txt = E.conversation_to_text(history, title="测试对话")
    assert "【我】" in txt and "【AI】" in txt

    html = E.conversation_to_html(history, title="测试对话")
    assert html.startswith("<!doctype html>")
    # HTML 转义应生效，原始 <b> 不应原样出现
    assert "&lt;b&gt;" in html, "HTML 特殊字符应被转义"
    assert "<b>world</b>" not in html

    # 统一入口（时间戳会导致字符串不等，改为解析后比较结构）
    re_json = json.loads(E.export_conversation(history, fmt="json", title="测试对话"))
    assert re_json["title"] == obj["title"] and len(re_json["messages"]) == 3
    # 未知格式回退 markdown
    assert E.export_conversation(history, fmt="unknown_fmt",
                                title="测试对话").startswith("# 测试对话")
    print("PASS - JSON/TXT/HTML 导出内容正确且 HTML 已转义")


def test_multimodal_message_text():
    msg = {"role": "user", "content": [
        {"type": "text", "text": "看这张图"},
        {"type": "image_url", "image_url": {"url": "x"}},
    ]}
    assert S.message_text(msg) == "看这张图"
    img_only = {"role": "user", "content": [
        {"type": "image_url", "image_url": {"url": "x"}},
    ]}
    assert S.message_text(img_only) == "（图片消息）"
    print("PASS - 多模态消息文本提取正确")


if __name__ == "__main__":
    test_empty_query_returns_all()
    test_ranked_search_ordering_and_snippet()
    test_chinese_bigram_match()
    test_export_formats()
    test_multimodal_message_text()
    print("\n==== 测试结果: 5/5 通过 ====")
