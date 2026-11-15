# -*- coding: utf-8 -*-
"""V13.8 回归：删除即时生效 / 勾选覆盖全部气泡 / 拖拽 / 毛玻璃 / 新功能。

零 Qt 依赖部分可直接运行；Qt 部分单独在 ASCII 路径下跑 UI 集成。
"""
import io
import json
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from core import messagetools as mt                 # noqa: E402
from core.sessions import SessionStore, message_text  # noqa: E402
from core.config import DEFAULT_CONFIG             # noqa: E402

R = []
def check(name, cond, extra=""):
    R.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name + ((" -> " + extra) if extra else ""))


def test_store_revision():
    d = tempfile.mkdtemp(prefix="v138_rev_")
    try:
        st = SessionStore(os.path.join(d, "sessions.json"))
        seen = []
        st.add_listener(lambda rev: seen.append(rev))
        sid = st.current_id()
        st.append({"role": "user", "content": "A"}, session_id=sid)
        st.append({"role": "assistant", "content": "B"}, session_id=sid)
        check("写盘递增版本并通知订阅者", st.revision >= 2 and len(seen) >= 2,
              "rev=%s seen=%s" % (st.revision, seen))
        st.clear_messages(sid)
        check("清空后目标会话为空", st.get(sid)["messages"] == [])
        # 重新加载不复活
        st2 = SessionStore(st.path)
        check("重载后仍为空（不复活）", st2.get(sid)["messages"] == [])
        # 删除整个当前会话后 current 自动切换且不残留
        st2.append({"role": "user", "content": "C"}, session_id=sid)
        st2.delete(sid)
        check("删除当前会话后 current 切换", st2.current_id() != sid)
        check("删除后新 current 无旧消息",
              st2.current() is None or
              "C" not in json.dumps(st2.current().get("messages") or [], ensure_ascii=False))
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_messagetools():
    h = [{"role": "system", "content": "sys"},
         {"role": "user", "content": "你好 世界"},
         {"role": "assistant", "content": "你好！有什么可以帮你"},
         {"role": "user", "content": "Hello"}]
    check("气泡序号映射含全部可见消息", mt.rendered_indices(h) == [1, 2, 3])
    check("映射单个序号", mt.map_ordinals(h, [1]) == [2])
    check("映射多个序号降序", mt.map_ordinals(h, [0, 2]) == [3, 1])
    check("越界序号被忽略", mt.map_ordinals(h, [99, 0]) == [1])
    hits = mt.search_messages(h, "你好")
    check("会话内查找命中 2 条", len(hits) == 2, str([x["ordinal"] for x in hits]))
    st = mt.message_stats(h)
    check("统计条数正确", st["visible"] == 3 and st["roles"]["user"] == 2)
    e = mt.edit_message_text(h[1], "改过")
    check("编辑消息不改变原对象", h[1]["content"] == "你好 世界" and e["content"] == "改过")
    check("导出所选为 Markdown", "# 对话" in mt.export_messages(h, [0]))
    check("斜杠命令解析", mt.parse_slash_command("/clear") == ("/clear", ""))
    check("普通文本不是命令", mt.parse_slash_command("你好")[0] is None)
    check("斜杠帮助含全部命令", all(c in mt.format_slash_help()
                                   for c, _d in mt.SLASH_COMMANDS))


def test_backup():
    d = tempfile.mkdtemp(prefix="v138_bak_")
    try:
        p = os.path.join(d, "sessions.json")
        with open(p, "w", encoding="utf-8") as f:
            json.dump({"current": "x", "sessions": [{"id": "x", "messages": []}]}, f)
        b = mt.backup_sessions(p)
        check("备份文件生成", bool(b) and os.path.isfile(b), str(b))
        with open(p, "w", encoding="utf-8") as f:
            json.dump({"current": "y", "sessions": []}, f)
        n = mt.restore_sessions(p, b)
        check("恢复会话数量", n == 1)
        with open(p, encoding="utf-8") as f:
            check("恢复内容正确", json.load(f)["current"] == "x")
        check("备份列表非空", len(mt.list_backups(p)) >= 1)
        try:
            mt.restore_sessions(p, os.path.join(d, "nope.json"))
            check("无效备份被拒绝", False)
        except ValueError:
            check("无效备份被拒绝", True)
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_sources():
    def rd(p):
        return io.open(p, encoding="utf-8").read()
    cw = rd("ui/chat_window.py")
    ast_ = rd("app/assistant.py")
    gl = rd("ui/glass_dialog.py")
    mn = rd("main.py")
    check("拖拽按下锁定、移动不重判",
          "self._drag_active = True" in cw and
          "if self._drag_active and self._drag_pos is not None:" in cw)
    check("所有气泡统一挂复选框", "_ensure_checks" in cw and "_bubble_ordinals" in cw)
    check("可见选择按钮", "self.select_msg_btn" in cw)
    check("消息右键菜单", "_bubble_context_menu" in cw)
    check("会话变更自动同步", "add_listener(self._on_store_changed)" in ast_
          and "def _sync_from_store" in ast_)
    check("删除后强制同步（不等重启）", "_sync_from_store(force=True)" in ast_)
    check("单一真源落盘", "m.get(\"role\") != \"system\"" in ast_)
    check("全局二级窗口玻璃钩子", "install_glass_hook" in gl and
          "install_glass_hook(qt" in mn)
    check("玻璃装饰器三态跳过", "_SKIP_TYPES" in gl and "findChild(FrostGlass)" in gl)
    check("新功能入口齐全", all(k in ast_ for k in
          ("delete_one_message", "edit_one_message", "copy_one_message",
           "star_one_message", "open_find_in_chat", "show_message_stats",
           "backup_sessions_now", "restore_sessions_now",
           "export_selected_messages", "_run_slash_command")))


def main():
    test_store_revision()
    test_messagetools()
    test_backup()
    test_sources()
    ok = sum(1 for _n, c in R if c)
    print("\n=== 结果：%d/%d 通过 ===" % (ok, len(R)))
    return 0 if ok == len(R) else 1


if __name__ == "__main__":
    sys.exit(main())
