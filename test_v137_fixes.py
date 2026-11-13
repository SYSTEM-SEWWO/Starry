# -*- coding: utf-8 -*-
"""V13.7 回归：清空 / 勾选删除 / 背景配置 / 存储隔离。零 Qt 依赖部分。"""
import os
import sys
import shutil
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from core.sessions import SessionStore          # noqa: E402
from core.config import DEFAULT_CONFIG          # noqa: E402


def check(results, name, cond, extra=""):
    results.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name + ((" -> " + extra) if extra else ""))


def test_storage(results):
    d = tempfile.mkdtemp(prefix="starry_v137_")
    try:
        path = os.path.join(d, "sessions.json")
        st = SessionStore(path)
        sid1 = st.current_id()
        for i in range(4):
            st.append({"role": "user" if i % 2 == 0 else "assistant",
                       "content": "A%d" % i}, session_id=sid1)
        st.create("其它对话")
        sid2 = st.current_id()
        for i in range(3):
            st.append({"role": "user", "content": "B%d" % i}, session_id=sid2)

        # 1) 清空只作用于目标会话
        st.data["current"] = sid1
        ok, removed = st.clear_messages(sid1, keep_system=True)
        s1 = [m["content"] for m in st.get(sid1)["messages"]]
        s2 = [m["content"] for m in st.get(sid2)["messages"]]
        check(results, "清空返回成功且报告移除数", ok and removed == 4,
              "removed=%s" % removed)
        check(results, "目标对话记录被清空", s1 == [], str(s1))
        check(results, "其它对话完全不受影响", s2 == ["B0", "B1", "B2"], str(s2))
        check(results, "会话列表数量不变", len(st.list()) == 2, str(len(st.list())))
        reload_st = SessionStore(path)
        check(results, "重新加载后目标对话仍为空",
              reload_st.get(sid1)["messages"] == [], "持久化生效")
        check(results, "重新加载后其它对话仍在",
              [m["content"] for m in reload_st.get(sid2)["messages"]]
              == ["B0", "B1", "B2"])

        # 2) 勾选删除：只删所选，保留未选，会话/列表不变
        st2 = SessionStore(path)
        st2.data["current"] = sid2
        before = [m["content"] for m in st2.get(sid2)["messages"]]
        ok2, n = st2.delete_messages(sid2, [1])      # 删中间那条
        after = [m["content"] for m in st2.get(sid2)["messages"]]
        check(results, "批量删除返回删除数", ok2 and n == 1, "n=%s" % n)
        check(results, "仅删除所选消息", after == ["B0", "B2"], str(after))
        check(results, "未选中消息顺序保留", before[0] == after[0] and before[2] == after[1])
        check(results, "会话 ID 不变", st2.current_id() == sid2)
        check(results, "会话列表仍为 2 个", len(st2.list()) == 2)
        check(results, "另一会话未被删除选中影响",
              st2.get(sid1)["messages"] == [])

        # 3) 越界 / 空索引安全
        ok3, n3 = st2.delete_messages(sid2, [99, -1, 0])
        check(results, "越界索引被忽略不误删", ok3 and n3 == 1,
              "n=%s" % n3)
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_config(results):
    ap = DEFAULT_CONFIG["appearance"]
    for key, val in (("background_mode", "theme"), ("background_color", ""),
                     ("background_image", ""), ("background_opacity", 35)):
        check(results, "默认背景配置 %s 存在" % key, key in ap and ap[key] == val,
              "%s=%r" % (key, ap.get(key)))


def test_sources(results):
    import io as _io
    def read(p):
        return _io.open(p, encoding="utf-8").read()
    cw = read("ui/chat_window.py")
    cd = read("ui/cache_dialog.py")
    ap = read("app/assistant.py")
    check(results, "缓存扫描在 QThread 后台执行",
          "class _CacheWorker(QThread)" in cd and "cc.scan(" in cd)
    check(results, "缓存按钮全程不禁用", "b.setEnabled(True)" in cd)
    check(results, "缓存失败也恢复交互", "_finish_busy" in cd and
          "_on_worker_failed" in cd)
    check(results, "子窗口统一非模态", "setWindowModality(Qt.NonModal)" in ap
          and "def _show_child" in ap)
    check(results, "关闭子窗口刷新主窗口", "def _on_child_closed" in ap)
    check(results, "拖拽覆盖窗口子树", "installEventFilter(self)" in cw
          and "def _drag_allowed" in cw)
    check(results, "交互控件在拖拽中放行", "_INTERACTIVE" in cw)
    check(results, "背景立即应用接口", "def apply_background" in cw
          and "set_custom_background" in read("ui/frost.py"))


def main():
    results = []
    test_storage(results)
    test_config(results)
    test_sources(results)
    passed = sum(1 for _, ok in results if ok)
    print("\n=== 结果：%d/%d 通过 ===" % (passed, len(results)))
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
