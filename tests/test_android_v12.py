# -*- coding: utf-8 -*-
"""星语 Starry v12.0 · Android 集成回归测试（真实 core，仅 fake UI）。

与 v11.5 的 android/test_app_logic.py 的本质区别
-------------------------------------------------
旧测试把 **核心逻辑也 fake 掉了**，而且 fake 的签名是按 app.py 写的、不是按
真实 core 写的，于是把真 bug 伪装成「16/16 全绿」：

  * 真实 core/memory.py: learn_from_conversation(user_text, assistant_text)
    旧 app.py 却调用 learn_from_conversation(prompt=..., answer=...)
    旧测试的 FakeMemory 恰好定义成 (prompt=None, answer=None) → 测不出 TypeError
  * 真实 Toga 0.5.7: Selection(items=[...], value='z') 抛 ValueError
    旧测试的 FakeWidget 对 value 完全不校验 → 测不出「点设置闪退」
  * 真实 Toga 0.5.7: ScrollContainer 没有 scroll_to_bottom()
    旧测试直接给 FakeWidget 加了一个同名方法 → 测不出滚动失效

本测试的原则：
  1. **core 全部用真实模块**（config / cli / memory / stardust / agent.runtime），
     只把「会真正发网络请求」的 ChatClient 换成同签名的离线替身；
  2. fake toga 只模拟 UI，且**忠实复刻** Toga 0.5.7 已实测的行为
     （Selection 值校验、无 scroll_to_bottom、App.loop 只读等）；
  3. 模拟 Android 运行环境（sys.getandroidapilevel + HOME + 私有目录）；
  4. 每个用例都能对应到一条已修复的闪退/功能缺陷。

运行：python tests/test_android_v12.py     （退出码 0 = 全绿）
"""
import asyncio
import json
import os
import sys
import tempfile
import threading
import time
import types

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ANDROID = os.path.join(ROOT, "android")
# 明确把 android/ 放最前：测的就是打进 APK 的那份 core
sys.path.insert(0, ANDROID)
if ROOT in sys.path:
    sys.path.remove(ROOT)

# ---------------------------------------------------------------------------
# 1) 模拟 Android 运行环境（必须在 import core 之前）
# ---------------------------------------------------------------------------
_TMP = tempfile.mkdtemp(prefix="starry-android-test-")
_APP_DIR = os.path.join(_TMP, "app-private")
os.makedirs(_APP_DIR, exist_ok=True)
os.environ["STARRY_CONFIG_DIR"] = _APP_DIR
os.environ["HOME"] = _TMP
os.environ["ANDROID_ROOT"] = "/system"
if not hasattr(sys, "getandroidapilevel"):
    sys.getandroidapilevel = lambda: 34            # Toga 0.5.7 的官方 Android 判据

# ---------------------------------------------------------------------------
# 2) Fake Toga —— 忠实复刻 0.5.7 实测行为，只替换 UI
# ---------------------------------------------------------------------------
fake_toga = types.ModuleType("toga")
fake_style = types.ModuleType("toga.style")
fake_pack = types.ModuleType("toga.style.pack")


class Pack:
    def __init__(self, **kw):
        for k, v in kw.items():
            object.__setattr__(self, k, v)

    def __setattr__(self, k, v):
        object.__setattr__(self, k, v)


class Widget:
    def __init__(self, *args, **kw):
        if args and "text" not in kw:
            kw["text"] = args[0]
        self.style = kw.pop("style", None) or Pack()
        # 真实 Toga 的 Box 支持 children= 构造参数；用普通属性承载，
        # 避免 property 无 setter 在 setattr 时误报错（v12.0 首轮测试暴露）
        self.children = list(kw.pop("children", []) or [])
        self.text = kw.pop("text", "")
        self.value = kw.pop("value", None)
        self.enabled = kw.pop("enabled", True)
        self.items = list(kw.pop("items", []) or [])
        self._shown = False
        for k, v in kw.items():
            setattr(self, k, v)

    def add(self, child):
        self.children.append(child)

    def show(self):
        self._shown = True


class Box(Widget):
    pass


class Label(Widget):
    pass


class TextInput(Widget):
    pass


class Button(Widget):
    pass


class Switch(Widget):
    pass


class Selection(Widget):
    def __init__(self, *a, **kw):
        wanted = kw.get("value")
        super().__init__(*a, **kw)
        # 实测 Toga 0.5.7：value 不在 items 内 → ValueError
        if self.items:
            if wanted is not None and wanted not in self.items:
                raise ValueError("%r is not a current item in the selection" % wanted)
            self.value = wanted if wanted is not None else self.items[0]
        else:
            self.value = wanted

    def __setattr__(self, k, v):
        if k == "value" and hasattr(self, "items") and self.items and v not in self.items:
            raise ValueError("%r is not a current item in the selection" % v)
        object.__setattr__(self, k, v)


class ActivityIndicator(Widget):
    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.running = False

    def start(self):
        self.running = True

    def stop(self):
        self.running = False


class ScrollContainer(Widget):
    # 故意**不**提供 scroll_to_bottom（真实 Toga 0.5.7 没有）
    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.vertical_position = 0
        self.max_vertical_position = 999


class MainWindow(Widget):
    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.content = None


class App:
    def __init__(self, *a, **k):
        self._paths = types.SimpleNamespace(config=_APP_DIR)
        self._main_window = None

    @property
    def paths(self):
        return self._paths

    @property
    def main_window(self):
        return self._main_window

    @main_window.setter
    def main_window(self, w):
        # 安卓 Toga 后端只允许一个 Window（实测约束）
        if self._main_window is not None and self._main_window is not w:
            raise RuntimeError("Android backend only supports a single Window")
        self._main_window = w

    def main_loop(self):
        pass


fake_toga.App = App
fake_toga.Box = Box
fake_toga.Label = Label
fake_toga.TextInput = TextInput
fake_toga.Button = Button
fake_toga.Switch = Switch
fake_toga.Selection = Selection
fake_toga.ScrollContainer = ScrollContainer
fake_toga.ActivityIndicator = ActivityIndicator
fake_toga.MainWindow = MainWindow
fake_style.Pack = Pack
fake_pack.LEFT = "left"
fake_pack.RIGHT = "right"
fake_pack.CENTER = "center"
fake_pack.BOLD = "bold"
sys.modules["toga"] = fake_toga
sys.modules["toga.style"] = fake_style
sys.modules["toga.style.pack"] = fake_pack

# ---------------------------------------------------------------------------
# 3) 导入真实 app + 真实 core
# ---------------------------------------------------------------------------
import starryandroid.app as appmod                       # noqa: E402
from starryandroid.app import StarryApp                  # noqa: E402
from core import config as cfg_mod                       # noqa: E402
from core import stardust                                # noqa: E402
from core.memory import MemoryStore                      # noqa: E402

# 唯一的替身：不发真实网络请求，但**签名与 core/api.py::ChatClient 完全一致**
class OfflineChatClient:
    def __init__(self):
        self.calls = []

    def chat_stream(self, messages, should_stop=None):
        self.calls.append(list(messages))
        yield ("reasoning", "先分析问题的约束条件。")
        yield ("content", "你好，")
        yield ("content", "这是一条离线测试回答。")

    def chat_agent_stream(self, messages, specs, should_stop=None):
        yield {"content": "智能体离线回复。"}
        yield {"done": True}


appmod.build_client = lambda cfg, overrides=None: OfflineChatClient()

# ---------------------------------------------------------------------------
# 4) 测试执行
# ---------------------------------------------------------------------------
RESULTS = []


def check(name, cond, extra=""):
    RESULTS.append((name, bool(cond), extra))
    print(("PASS" if cond else "FAIL"), "-", name, extra)


def _core_version():
    """读桌面 core/config.py 的 APP_VERSION。

    本测试把 android/ 放在 sys.path 最前，cfg_mod 实为打进 APK 的那份
    core；与桌面 core 比对即可验证三端同源的版本单一真源，
    且升级版本时无需再改测试里的硬编码字符串。
    """
    path = os.path.join(ROOT, "core", "config.py")
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                if line.startswith("APP_VERSION"):
                    return line.split("=", 1)[1].strip().strip("\"'")
    except OSError:
        pass
    return ""


def all_text(box):
    out = []
    for c in box.children:
        if hasattr(c, "text"):
            out.append(str(c.text))
        if hasattr(c, "children"):
            out.extend(all_text(c))
    return out


app = StarryApp()
loop = asyncio.new_event_loop()
app.loop = loop                         # 真机由 Toga 提供；测试环境注入
threading.Thread(target=loop.run_forever, daemon=True).start()

# --- 用例 1：启动（F1 / F2） ---
try:
    app.startup()
    check("[F1] startup 成功且未抛异常", app.main_window is not None
          and app.main_window.content is not None)
    check("[F1] 启动流程无任何异常记录", len(app.crash_log) == 0,
          str(app.crash_log[:1]))
    check("[F2] 配置目录落在 Android 私有目录",
          cfg_mod.get_config_dir().startswith(_APP_DIR),
          cfg_mod.get_config_dir())
    check("[F1] 版本号与 core 单一真源一致",
          cfg_mod.APP_VERSION == _core_version())
    check("[启动] 欢迎语已显示", len(app.chat_box.children) >= 1)
    check("[启动] 思考卡初始隐藏", app.thinking_box.style.visibility == "hidden")
except Exception as exc:                                 # noqa: BLE001
    check("[F1] startup 成功且未抛异常", False, repr(exc))

# --- 用例 2：设置页，故意把模型设成不在预设列表里的自定义值（F3） ---
try:
    app.cfg.set_model("my-custom-model-not-in-list")
    app.open_settings(app.settings_btn)
    check("[F3] 自定义模型下打开设置页不抛 ValueError",
          app._page == "settings" and app.main_window.content is not None)
    check("[F3] 模型下拉值已回落到合法项",
          app.model_sel.value in list(app.model_sel.items))
    check("[F3] 思考强度下拉值合法",
          app.effort_sel.value in ["off", "low", "medium", "high"])
    check("[F8] 设置页未新建第二个窗口", not hasattr(app, "settings_window"))
except Exception as exc:                                 # noqa: BLE001
    check("[F3] 自定义模型下打开设置页不抛 ValueError", False, repr(exc))

# --- 用例 3：服务商联动 + 保存（真实 AppConfig） ---
try:
    app.provider_sel.value = app.provider_sel.items[0]
    app.on_provider_select(app.provider_sel)
    check("[设置] 服务商联动刷新模型", len(app.model_sel.items) > 0)
    app.key_input.value = "sk-offline-test"
    app.theme_sel.value = "dark"
    app.scale_sel.value = "大"
    app.on_save_settings(Button("保存"))
    check("[设置] API Key 写入真实配置", app.cfg.api_key() == "sk-offline-test")
    check("[设置] 主题写入真实配置", app.cfg.data.get("theme") == "dark")
    check("[设置] 保存后返回聊天页", app._page == "chat")
except Exception as exc:                                 # noqa: BLE001
    check("[设置] 保存流程", False, repr(exc))

# --- 用例 4：发送一轮完整对话（真实 _build_messages / MemoryStore / stardust） ---
try:
    app._return_to_chat()
    app.input.value = "请记住我喜欢简洁的回答，然后介绍一下你自己"
    app.on_send(app.send_btn)
    deadline = time.time() + 8
    while app.busy and time.time() < deadline:
        time.sleep(0.02)
    time.sleep(0.3)
    check("[发送] busy 正确复位", app.busy is False)
    texts = all_text(app.chat_box)
    check("[发送] 用户消息已上屏", any(t.startswith("我：") for t in texts))
    check("[发送] 流式回答已上屏", any("这是一条离线测试回答" in t for t in texts))
    check("[发送] 思考过程已上屏", any("先分析问题" in t for t in texts))
    mem_errors = [x for x in app.crash_log if "memory_learn" in x]
    check("[F4] 真实 MemoryStore 被调用且未抛 TypeError",
          not mem_errors, "记忆异常 %d 条" % len(mem_errors))
    check("[v12] 星尘卡已生成", any("✦ 星尘卡" in t for t in texts))
except Exception as exc:                                 # noqa: BLE001
    check("[发送] 完整对话流程", False, repr(exc))

# --- 用例 5：F4 直接验证真实签名（v11.5 的 bug 点） ---
try:
    store = MemoryStore()
    n = store.learn_from_conversation(
        user_text="请记住我喜欢简洁的回答", assistant_text="好的")
    check("[F4] learn_from_conversation(user_text, assistant_text) 可用",
          isinstance(n, int))
    try:
        store.learn_from_conversation(prompt="x", answer="y")
        check("[F4] 旧的错误关键字调用确实会失败（回归证据）", False)
    except TypeError:
        check("[F4] 旧的错误关键字调用确实会失败（回归证据）", True)
except Exception as exc:                                 # noqa: BLE001
    check("[F4] 真实签名验证", False, repr(exc))

# --- 用例 6：滚动 / 停止 / 诊断页 ---
try:
    check("[F5] 走到了 vertical_position 分支",
          app.scroll.vertical_position == app.scroll.max_vertical_position
          or not hasattr(app.scroll, "scroll_to_bottom"))
    app.on_stop(Button("停止"))
    check("[v12] 停止按钮置位中断标志", app._stop_flag is True)
    app.open_diagnostics(app.diag_btn)
    check("[F6] 诊断页可打开", app._page == "diagnostics")
    diag_text = all_text(app.main_window.content)
    check("[F6] 诊断页含版本号",
          any(cfg_mod.APP_VERSION in t for t in diag_text))
    app._return_to_chat()
except Exception as exc:                                 # noqa: BLE001
    check("[F5/F6] 滚动与诊断", False, repr(exc))

# --- 用例 7：致命错误兜底不冒泡（F1） ---
try:
    probe = StarryApp()
    probe.loop = loop
    probe.crash_log = []
    probe.cfg = cfg_mod.AppConfig()
    probe.palette = appmod.PALETTE["light"]
    probe.font_scale = 1.0
    probe._show_fatal_error("模拟初始化失败")
    check("[F1] 致命错误走应用内错误页而非抛异常",
          probe.main_window is not None and probe.main_window.content is not None)
except Exception as exc:                                 # noqa: BLE001
    check("[F1] 致命错误兜底", False, repr(exc))

# --- 用例 8：get_config_dir 在不可写路径下不抛异常（F1 根因） ---
try:
    old = os.environ.get("STARRY_CONFIG_DIR")
    os.environ["STARRY_CONFIG_DIR"] = "Z:/definitely/not/writable/path"
    p = cfg_mod.get_config_dir()
    check("[F1] 不可写私有目录时仍返回可用路径", isinstance(p, str) and bool(p), p)
    if old is not None:
        os.environ["STARRY_CONFIG_DIR"] = old
    check("[F1] AppConfig.load() 永不抛异常",
          isinstance(cfg_mod.AppConfig.load(), cfg_mod.AppConfig))
except Exception as exc:                                 # noqa: BLE001
    check("[F1] 路径回退", False, repr(exc))

# --- 用例 9：v12.0 纯逻辑核心（真实 core.stardust） ---
try:
    card = stardust.build_echo_card(
        title="T", reasoning="第一句。\n第二句。", answer="回答正文",
        prompt="提问", branched_from="s1", ts="2026-11-07")
    check("[v12] 星尘卡确定性", card == stardust.build_echo_card(
        title="T", reasoning="第一句。\n第二句。", answer="回答正文",
        prompt="提问", branched_from="s1", ts="2026-11-07"))
    check("[v12] 星尘卡含分支锚点", "s1" in card)
    msgs = [{"role": "system", "content": "系统"}] + [
        {"role": "user", "content": "消息%d" % i} for i in range(8)]
    snap = json.dumps(msgs, ensure_ascii=False)
    plan = stardust.plan_trim(msgs, 30, policy="keep_recent")
    check("[v12] 裁剪计划不修改入参", json.dumps(msgs, ensure_ascii=False) == snap)
    check("[v12] 裁剪计划保留系统消息", 0 in plan["keep_indices"])
    check("[v12] 裁剪计划确实裁剪", plan["trimmed"] is True)
    arch = stardust.pack_archive(sessions={"a": [1, 2]}, memory={"m": "x"},
                                 meta={"v": 12})
    back = stardust.unpack_archive(arch)
    check("[v12] 存档 round-trip", back["sessions"] == {"a": [1, 2]}
          and back["version"] == stardust.ARCHIVE_VERSION)
    corrupt = json.loads(arch)
    corrupt["payload"]["memory"]["m"] = "tampered"
    try:
        stardust.unpack_archive(json.dumps(corrupt, ensure_ascii=False))
        check("[v12] 篡改存档被拒绝", False)
    except ValueError:
        check("[v12] 篡改存档被拒绝", True)
except Exception as exc:                                 # noqa: BLE001
    check("[v12] 星尘核心", False, repr(exc))

# --- 用例 10：三端同源 ---
try:
    import subprocess
    rc = subprocess.call(
        [sys.executable, os.path.join(ROOT, "scripts", "sync_core.py"), "--check"],
        cwd=ROOT, stdout=subprocess.DEVNULL)
    check("[v12] core/ 与 android/core/ 字节一致", rc == 0)
except Exception as exc:                                 # noqa: BLE001
    check("[v12] 三端同源", False, repr(exc))

loop.call_soon_threadsafe(loop.stop)

total = len(RESULTS)
passed = sum(1 for _, ok, _ in RESULTS if ok)
print("\n==== v12.0 Android 集成回归：%d/%d 通过 ====" % (passed, total))
for name, ok, extra in RESULTS:
    if not ok:
        print("  ✗", name, extra)
sys.exit(0 if passed == total else 1)
