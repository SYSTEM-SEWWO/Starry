# -*- coding: utf-8 -*-
"""v5 创新功能端到端验证（无头环境）"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PyQt5.QtWidgets import QApplication

app = QApplication(sys.argv)

from app.assistant import AssistantApp
from ui.command_palette import CommandPalette
from core.tts import Speaker, strip_markdown
from core.context import trim_to_context

results = []


def check(name, cond, extra=""):
    results.append((name, bool(cond), extra))
    print("%s %s %s" % ("[PASS]" if cond else "[FAIL]", name, extra))


a = AssistantApp()
a.window.show()
# 验证状态机：屏蔽真实 worker 启动（避免无网络环境下后台请求干扰断言）
a._start_worker = lambda: None

# ---------- 1. 重新生成 → 对话分支（模拟真实时序） ----------
a.history = [
    {"role": "system", "content": "sys"},
    {"role": "user", "content": "你好"},
    {"role": "assistant", "content": "第一版回答"},
]
# 第一步：点击重新生成 → 旧回答暂存为变体，history 回到 user 结尾
a.on_regenerate()
check("分支：regenerate 后 history 尾部为 user",
      a.history[-1].get("role") == "user",
      a.history[-1].get("role"))
check("分支：旧回答暂存为待并入变体",
      a._pending_variants == ["第一版回答"], str(a._pending_variants))
# 第二步：worker 完成 → 新旧回答合并为变体组
a._regenerating = True
a._assistant_text = "第二版回答"
a._current_bubble = None
a._on_finished()
last = a.history[-1]
check("分支：history 追加 assistant", last.get("role") == "assistant")
check("分支：variants 含两版", last.get("variants") == ["第一版回答", "第二版回答"],
      str(last.get("variants")))
check("分支：active 指向新版", last.get("active") == 1)
check("分支：会话存储同步",
      a.sessions.messages()[-1].get("variants") == ["第一版回答", "第二版回答"])

# 切换变体 → history / 存储同步
a._on_variant_selected(0)
check("分支：切换后 active=0", a.history[-1].get("active") == 0)
check("分支：切换后 content=旧版", a.history[-1].get("content") == "第一版回答")

# 再次重新生成：已有变体组的旧回答应整体并入
a.on_regenerate()
check("分支：再次 regenerate 可进入（旧变体组整体并入）",
      a._pending_variants == ["第一版回答", "第二版回答"],
      str(a._pending_variants))
check("分支：再次 regenerate 后 history 尾部为 user",
      a.history[-1].get("role") == "user")

# ---------- 2. 渲染历史变体（先补一次“worker 完成”得到 3 变体） ----------
a._regenerating = True
a._assistant_text = "第三版回答"
a._current_bubble = None
a._on_finished()
a._render_history()
bubbles = [a.window.msg_layout.itemAt(i).widget()
           for i in range(a.window.msg_layout.count())]
from ui.widgets import AssistantBubble
abubs = [b for b in bubbles if isinstance(b, AssistantBubble)]
check("历史渲染：分支气泡显示切换器",
      len(abubs) == 1 and not abubs[0].variant_box.isHidden()
      and len(abubs[0]._variant_btns) == 3,
      "bubbles=%d" % len(abubs))
check("历史渲染：激活第 3 个变体",
      len(abubs) == 1 and abubs[0].active_variant_index() == 2)

# ---------- 3. 命令面板 ----------
cmds = a._palette_commands()
check("命令面板：命令数量 >= 15", len(cmds) >= 15, str(len(cmds)))
pal = CommandPalette(cmds, a.window)
check("命令面板：默认渲染全部", pal.list.count() == len(cmds))
pal._reload("主题")
check("命令面板：搜索过滤", pal.list.count() == 1)
pal._reload("")
# 触发一个安全命令（切换主题）
before = a.cfg.appearance.get("theme")
a._on_palette_command("theme")
after = a.cfg.appearance.get("theme")
check("命令面板：切换主题命令生效", before != after,
      "%s -> %s" % (before, after))
pal.close()

# 切换模型命令（空列表时给提示，不崩溃）
a._cycle_model()
check("命令面板：空模型列表不崩溃", True)

# ---------- 4. TTS 优雅降级 ----------
sp = Speaker()
check("TTS：strip_markdown 去记号",
      strip_markdown("**加粗** `代码` [链接](http://x)") == "加粗 代码 链接",
      repr(strip_markdown("**加粗** `代码` [链接](http://x)")))
if not sp.available():
    check("TTS：未安装 pyttsx3 时优雅降级", sp.speak("测试") is False)
    a.on_speak("测试内容")
    check("TTS：on_speak 降级不崩溃", True)
else:
    check("TTS：pyttsx3 可用", True)

# ---------- 5. 资料库角标 ----------
b = a.window.add_user_message("带角标的问题")
a.window.set_last_user_badge("📚 已引用资料库片段作为回答依据")
check("角标：set_last_user_badge 点亮", not b.badge.isHidden())
a.window.set_last_user_badge("")
check("角标：空文本隐藏", b.badge.isHidden())

# ---------- 6. 上下文裁剪联动 ----------
msgs = [{"role": "system", "content": "系统"}] + \
       [{"role": "user", "content": "问题" * 500} for _ in range(20)]
out, used, dropped = trim_to_context(msgs, 2000)
check("上下文：裁剪丢弃旧消息", dropped > 0, "dropped=%d" % dropped)
check("上下文：保留系统消息", out[0].get("role") == "system")

print()
fails = [r for r in results if not r[1]]
print("=" * 40)
print("v5 创新功能验证：%d 通过，%d 失败" % (len(results) - len(fails), len(fails)))
sys.exit(1 if fails else 0)
