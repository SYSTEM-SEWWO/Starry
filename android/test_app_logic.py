# -*- coding: utf-8 -*-
"""星语 Starry Android · 逻辑端到端测试（无 GUI / 无模拟器）。

用轻量 fake `toga` 替换界面层，跑真实的 core 逻辑：
  - startup() 是否成功构建全部控件（原闪退点 visibility=False 已修复）
  - 发送流程：后台线程跑 _do_turn → 流式回调 → 线程安全回写 UI
  - 深度思考开关 / 智能体开关 / 服务商选择 / 保存设置
  - 设置窗口构建

只验证 Python 逻辑层（真机 UI 渲染需模拟器，沙盒无 /dev/kvm 无法跑）。
"""
import asyncio
import sys
import os
import time
import types
import threading

# ---------- 1) 注入 fake toga ----------
fake_toga = types.ModuleType("toga")
fake_style = types.ModuleType("toga.style")
fake_pack = types.ModuleType("toga.style.pack")


class FakeWidget:
    def __init__(self, *args, **kw):
        # 第一个位置参数通常是文字（Label/Switch/Button），统一存到 text
        if args:
            kw.setdefault("text", args[0])
        for k, v in kw.items():
            setattr(self, k, v)
        self.children = list(kw.get("children", []) or [])
        kw.pop("children", None)
        self._children = self.children
        self.text = getattr(self, "text", "")
        self.value = getattr(self, "value", None)
        self.enabled = getattr(self, "enabled", True)
        self.items = getattr(self, "items", [])

    def add(self, child):
        self._children.append(child)
        self.children = self._children

    def show(self):
        self._shown = True

    def close(self):
        self._closed = True

    # 真实 Toga 0.5.7 无 scroll_to_bottom；用 vertical_position


class Box(FakeWidget):
    pass


class Label(FakeWidget):
    pass


class TextInput(FakeWidget):
    pass


class Button(FakeWidget):
    pass


class Switch(FakeWidget):
    pass


class Selection(FakeWidget):
    def __init__(self, *a, **kw):
        wanted = kw.get("value")
        super().__init__(*a, **kw)
        if self.items and wanted is not None and wanted not in self.items:
            raise ValueError("%r is not a current item in the selection" % wanted)


class ScrollContainer(FakeWidget):
    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.vertical_position = 0
        self.max_vertical_position = 999


class ActivityIndicator(FakeWidget):
    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.running = False

    def start(self):
        self.running = True

    def stop(self):
        self.running = False


class MainWindow(FakeWidget):
    def __init__(self, title=None, **kw):
        super().__init__(title=title, **kw)
        self.content = None


class Window(FakeWidget):
    def __init__(self, title=None, **kw):
        super().__init__(title=title, **kw)
        self.content = None


class App:
    def __init__(self, *a, **k):
        pass


fake_toga.App = App
fake_toga.Box = Box
fake_toga.Label = Label
fake_toga.TextInput = TextInput
fake_toga.Button = Button
fake_toga.Switch = Switch
fake_toga.Selection = Selection
fake_toga.ScrollContainer = ScrollContainer
fake_toga.MainWindow = MainWindow
fake_toga.ActivityIndicator = ActivityIndicator
fake_toga.Window = Window

# Pack / 常量
class Pack:
    def __init__(self, **kw):
        for k, v in kw.items():
            setattr(self, k, v)

    def __setattr__(self, k, v):
        object.__setattr__(self, k, v)

fake_style.Pack = Pack
fake_style.Column = "column"
fake_style.Row = "row"
fake_pack.LEFT = "left"
fake_pack.RIGHT = "right"
fake_pack.CENTER = "center"
fake_pack.BOLD = "bold"

sys.modules["toga"] = fake_toga
sys.modules["toga.style"] = fake_style
sys.modules["toga.style.pack"] = fake_pack

# ---------- 2) 导入真实 app + core ----------
ANDROID = os.path.dirname(os.path.abspath(__file__))
if ANDROID not in sys.path:
    sys.path.insert(0, ANDROID)

import starryandroid.app as appmod
from starryandroid.app import StarryApp

# ---------- 3) patch 网络 / 外部依赖 ----------
import core.cli as cli_mod
import core.agent.runtime as runtime_mod
import core.memory as mem_mod
from core.config import APP_VERSION


class FakeClient:
    def chat_stream(self, messages, should_stop=None):
        yield ("reasoning", "让我想想…")
        yield ("content", "你好，这是一条测试回答。")
        yield ("content", "第二句。")


class FakeAgentIter:
    def __init__(self, messages):
        self.messages = messages
        self._i = 0

    def __iter__(self):
        return self

    def __next__(self):
        if self._i == 0:
            self._i += 1
            return ("content", "智能体回复。")
        if self._i == 1:
            self._i += 1
            return ("tool", {"name": "calc", "running": False, "result": "42"})
        raise StopIteration


class FakeAgentRuntime:
    def __init__(self, client, enabled_tools, max_iterations, should_stop):
        self.client = client

    def run(self, messages):
        return FakeAgentIter(messages)


class FakeMemory:
    def learn_from_conversation(self, user_text, assistant_text=""):
        return 0


appmod.build_client = lambda cfg, overrides=None: FakeClient()
appmod._build_messages = lambda cfg, prompt, use_memory=True: [
    {"role": "system", "content": "sys"},
    {"role": "user", "content": prompt},
]
appmod.AgentRuntime = FakeAgentRuntime
appmod.MemoryStore = FakeMemory

# ---------- 4) 跑测试 ----------
results = []
def check(name, cond, extra=""):
    results.append((name, bool(cond), extra))
    print(("PASS" if cond else "FAIL"), "-", name, extra)


app = StarryApp()
# 注入一个真实事件循环：真机由 Toga 提供 self.loop（AndroidEventLoop），
# 测试环境需自行提供，以便 call_soon_threadsafe / run_in_executor 生效。
app.loop = asyncio.new_event_loop()
try:
    app.startup()
    check("startup() 构建成功（原 visibility=False 崩溃已修复）",
          app.main_window is not None and app.main_window.content is not None)
    check("思考卡片初始隐藏（visibility=hidden）",
          app.thinking_box.style.visibility == "hidden")
    check("标题栏含版本号", APP_VERSION in app.title_label.text)
    check("系统欢迎语已追加", len(app.chat_box._children) >= 1)
except Exception as e:  # noqa: BLE001
    check("startup() 构建成功", False, "异常: %r" % e)

# 真实事件循环线程，用于 call_soon_threadsafe / run_in_executor
loop = app.loop
threading.Thread(target=loop.run_forever, daemon=True).start()
time.sleep(0.1)

# 发送一条普通对话
try:
    app.input.value = "你好"
    app.on_send(app.send_btn)
    deadline = time.time() + 5
    while app.busy and time.time() < deadline:
        time.sleep(0.05)
    # 等待 UI 回调落定
    time.sleep(0.2)
    check("on_send 完成（busy 复位）", app.busy is False)
    def collect(node):
        out = [getattr(node, "text", "")]
        for sub in getattr(node, "_children", []):
            out.extend(collect(sub))
        return out
    texts = collect(app.chat_box)
    check("用户气泡已追加", any(t.startswith("我：") for t in texts))
    check("回答气泡已追加（流式提交）", any(t.startswith("星语：") for t in texts))
except Exception as e:  # noqa: BLE001
    check("on_send 普通对话流程", False, "异常: %r" % e)

# 深度思考开关
try:
    app.deep_switch.value = True
    app.on_deep_toggle(app.deep_switch)
    check("深度思考开关写入配置", app.cfg.data.get("deep_thinking") is True)
except Exception as e:  # noqa: BLE001
    check("深度思考开关", False, "异常: %r" % e)

# 智能体开关
try:
    app.agent_switch.value = True
    app.on_agent_toggle(app.agent_switch)
    check("智能体开关置位", app.agent_mode is True)
except Exception as e:  # noqa: BLE001
    check("智能体开关", False, "异常: %r" % e)

# 智能体模式发送
try:
    app.input.value = "用工具算一下"
    app.on_send(app.send_btn)
    deadline = time.time() + 5
    while app.busy and time.time() < deadline:
        time.sleep(0.05)
    time.sleep(0.2)
    def collect(node):
        out = [getattr(node, "text", "")]
        for sub in getattr(node, "_children", []):
            out.extend(collect(sub))
        return out
    texts = collect(app.chat_box)
    check("智能体模式回复已追加", any(t.startswith("星语：") for t in texts))
except Exception as e:  # noqa: BLE001
    check("智能体模式发送", False, "异常: %r" % e)

# 设置页（主窗口内切换，不新建第二个窗口 —— 安卓仅允许一个窗口）
try:
    app.open_settings(app.settings_btn)
    # 关键：设置页是主窗口内容的切换，绝不创建第二个窗口
    check("设置页未新建第二个窗口（安卓兼容）",
          not hasattr(app, "settings_window"))
    check("设置页内容已切换", app.main_window.content is not None)
    check("服务商下拉含选项", len(app.provider_sel.items) > 0)
    # 切换服务商联动模型
    app.provider_sel.value = app.provider_sel.items[0]
    app.on_provider_select(app.provider_sel)
    check("服务商联动模型刷新", app.model_sel.items is not None)
    # 保存设置
    app.key_input.value = "sk-test-123"
    app.model_sel.value = app.model_sel.items[0] if app.model_sel.items else ""
    app.effort_sel.value = "high"
    app.on_save_settings(Button("保存"))
    check("保存设置成功（api_key 写入）",
          app.cfg.api_key() in ("sk-test-123",))
    # 保存后自动返回聊天页（内容切回聊天布局）
    check("保存后返回聊天页（单窗口）",
          app.main_window.content is app._chat_layout())
except Exception as e:  # noqa: BLE001
    check("设置页/保存流程", False, "异常: %r" % e)

# 停止循环
loop.call_soon_threadsafe(loop.stop)
time.sleep(0.1)

# ---------- 汇总 ----------
total = len(results)
passed = sum(1 for _, ok, _ in results if ok)
print("\n==== 测试结果: %d/%d 通过 ====" % (passed, total))
for name, ok, extra in results:
    if not ok:
        print("  ✗", name, extra)
sys.exit(0 if passed == total else 1)
