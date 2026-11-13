# -*- coding: utf-8 -*-
"""V11.2 新增功能测试：会话标签 + 消息编辑/删除 + PDF 导出。

纯逻辑、无网络、无 GUI：
  - 标签：set_tags / list_tags / list(tag=) / search_ranked(tag=) 过滤
  - 消息编辑/删除：edit_message / delete_message（含越界与系统提示保护）
  - PDF 导出：weasyprint 可用时验证字节流，否则 skip
直接 `python test_v11_2.py` 运行，全部通过退出码 0。
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.sessions import SessionStore
from core.exporter import (conversation_to_html, conversation_to_pdf,
                           available_formats)


def _new_store():
    fd, path = tempfile.mkstemp(suffix=".json", prefix="starry_v112_")
    os.close(fd)
    os.remove(path)
    return SessionStore(path), path


results = []
def check(name, cond, extra=""):
    results.append((name, bool(cond), extra))
    print(("PASS" if cond else "FAIL"), "-", name, extra)


# ----------------------------------------------------------------------
# 标签
# ----------------------------------------------------------------------
def test_tags():
    store, path = _new_store()
    try:
        s1 = store.create("工作会话")
        s2 = store.create("学习笔记")
        s3 = store.create("灵感收集")
        store.append({"role": "user", "content": "周报怎么写"}, s1["id"])
        store.append({"role": "user", "content": "微积分复习"}, s2["id"])

        # set_tags：list / 字符串 / 去重 / 截断
        ok = store.set_tags(s1["id"], ["工作", "重要", "重要"])
        check("set_tags 返回 True", ok is True)
        check("标签去重", store.get(s1["id"])["tags"] == ["工作", "重要"])
        ok = store.set_tags(s2["id"], "学习, 作业")
        check("字符串标签解析", store.get(s2["id"])["tags"] == ["学习", "作业"])
        store.set_tags(s3["id"], "灵感")

        # list_tags 聚合计数，按次数降序
        tags = store.list_tags()
        tag_map = dict(tags)
        check("list_tags 含工作(1)", tag_map.get("工作") == 1)
        check("list_tags 返回 (tag,count) 列表", all(len(t) == 2 for t in tags))

        # list(tag=) 过滤
        work_only = store.list(tag="工作")
        check("list(tag=工作) 仅命中带该标签会话",
              [s["id"] for s in work_only] == [s1["id"]]
              and all("工作" in s["tags"] for s in work_only))
        check("list 摘要携带 tags 字段", "tags" in store.list()[0])

        # search_ranked(tag=) 过滤 + 标签字段
        res = store.search_ranked("怎么", tag="工作")
        check("search_ranked(tag=) 过滤生效",
              all("工作" in r["tags"] for r in res) and len(res) >= 1)
        res2 = store.search_ranked("怎么")
        check("search_ranked 无 tag 返回全部命中",
              len(res2) >= 1 and any(r["id"] == s1["id"] for r in res2))
        check("无 tag 命中数 >= 有 tag 命中数",
              len(res2) >= len(res))
    finally:
        os.remove(path)


# ----------------------------------------------------------------------
# 消息编辑 / 删除
# ----------------------------------------------------------------------
def test_edit_delete():
    store, path = _new_store()
    try:
        s = store.create("测试会话")
        sid = s["id"]
        # 注入：系统提示 + 用户 + 助手
        store.set_messages([
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "原问题"},
            {"role": "assistant", "content": "原回答"},
        ], sid)
        msgs = store.messages(sid)
        check("初始 3 条消息", len(msgs) == 3)

        # edit_message 正常
        out = store.edit_message(sid, 1, "修改后的问题")
        check("edit_message 返回更新后历史", out is not False and out[1]["content"] == "修改后的问题")
        # 越界
        check("edit_message 越界返回 False", store.edit_message(sid, 99, "x") is False)
        # 系统提示不可改
        check("edit_message 系统提示受保护", store.edit_message(sid, 0, "hack") is False)
        # 内容确实落盘
        check("edit_message 已持久化", store.messages(sid)[1]["content"] == "修改后的问题")

        # delete_message 正常
        out = store.delete_message(sid, 2)
        check("delete_message 删除助手消息", out is not False and len(out) == 2)
        # 越界
        check("delete_message 越界返回 False", store.delete_message(sid, 99) is False)
        # 同步到会话存储
        check("delete_message 已持久化", len(store.messages(sid)) == 2)
    finally:
        os.remove(path)


# ----------------------------------------------------------------------
# PDF 导出
# ----------------------------------------------------------------------
def test_pdf():
    hist = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "你好"},
        {"role": "assistant", "content": "你好，有什么可以帮你？"},
    ]
    if "pdf" not in available_formats():
        check("PDF 依赖未安装 → 跳过 PDF 断言（环境无关）", True,
              "weasyprint 不可用")
        return
    data = conversation_to_pdf(hist, title="测试", model="x", provider_name="y")
    check("conversation_to_pdf 返回 bytes", isinstance(data, (bytes, bytearray)))
    check("PDF 魔数正确", data[:4] == b"%PDF")
    # 与 HTML 导出内容一致
    html = conversation_to_html(hist)
    check("HTML 导出含对话内容", "你好" in html)


if __name__ == "__main__":
    test_tags()
    test_edit_delete()
    test_pdf()
    total = len(results)
    passed = sum(1 for _, ok, _ in results if ok)
    print("\n==== V11.2 测试结果: %d/%d 通过 ====" % (passed, total))
    for name, ok, extra in results:
        if not ok:
            print("  ✗", name, extra)
    sys.exit(0 if passed == total else 1)
