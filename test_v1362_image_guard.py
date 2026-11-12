# -*- coding: utf-8 -*-
"""V13.6.2 回归：携带图片但当前/可用模型均不支持视觉时，不得把图片发往模型。

直接复现用户报错场景：
  provider=lmstudio, model=minicpm5-1b（纯文本），附加一张图片 → 发送。
历史 bug：ensure_vision_model() 在无视觉模型可切换时仅提示并放行，导致图片仍被
塞进请求，服务端返回 HTTP 400（"does not support image inputs"）。
修复后：on_send 在发送前守卫，allow_images=False 时本地下掉图片、仅发文字并明确提示。
"""
import os
import sys
import json
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PyQt5.QtWidgets import QApplication
from core.config import AppConfig
from app.model_controller import ModelController
from app.assistant import AssistantApp  # 仅取类，不跑 __init__


def fake_window():
    """最小 ChatWindow 接口（与 ModelController / on_send 交互所需）。"""
    class _W:
        def __init__(self):
            self.hints = []
            self.last_user_msg = None
        def show_hint(self, msg, msecs=0):
            self.hints.append(msg)
        def set_models(self, *a, **k):
            pass
        def set_deep_thinking(self, *a, **k):
            pass
        def _update_status(self, *a, **k):
            pass
        def add_user_message(self, text, attachments=None):
            self.last_user_msg = (text, attachments)
        def fail_message(self, *a, **k):
            pass
    return _W()


def make_assistant(model_cache, current_model, ready=True):
    """构造一个绕过 __init__ 的 AssistantApp 实例，仅挂 on_send 需要的属性。"""
    inst = AssistantApp.__new__(AssistantApp)
    inst.worker = None
    inst.history = []
    inst.sessions = []
    inst.window = fake_window()

    cfg = AppConfig({})
    cfg.set_provider("lmstudio")
    cfg.data["model_cache"] = {"lmstudio": {"models": list(model_cache), "ts": 0}}
    cfg.data["models"]["lmstudio"] = ""
    cfg.set_model(current_model)
    if not ready:
        cfg.is_ready = lambda: False
    else:
        cfg.is_ready = lambda: True

    inst.cfg = cfg
    inst.models = ModelController(cfg, inst.window)
    inst.stats = type("S", (), {"record_message": lambda *a: None,
                               "save": lambda *a: None})()
    inst._start_worker = lambda: None   # 不真正起 worker
    inst.open_settings = lambda: None
    return inst


def content_has_image(content):
    """content 里是否含 image_url 部件。"""
    if isinstance(content, list):
        return any(p.get("type") == "image_url" for p in content)
    return False


def run():
    results = []
    def check(name, cond, extra=""):
        results.append((name, bool(cond)))
        print(("PASS " if cond else "FAIL ") + name + (("  -> " + extra) if extra else ""))

    # 复现用户场景：仅 minicpm5-1b（文本模型）
    print("=== 场景 1：lmstudio + minicpm5-1b + 图片（应忽略图片、仅发文字）===")
    a = make_assistant(["minicpm5-1b"], "minicpm5-1b")
    from core.attachment import Attachment
    img = Attachment(Attachment.IMAGE, "shot.png")
    a.on_send("这张图里有什么？", [img])
    content = a.history[-1]["content"]
    check("minicpm5-1b 被判为不支持视觉",
          __import__("core.models", fromlist=["models"]).is_vision_model("minicpm5-1b", "lmstudio") is False)
    check("发送内容不含 image_url（未把图片发往文本模型）",
          not content_has_image(content), repr(content)[:120])
    check("用户消息仍记录文字", "这张图里有什么？" in (content if isinstance(content, str) else json.dumps(content, ensure_ascii=False)))
    check("给出「已忽略图片」的明确提示",
          any("不支持图片" in h and "已忽略" in h for h in a.window.hints),
          str(a.window.hints))

    # 场景 2：池子里有视觉模型 → 应自动切换并带上图片
    print("\n=== 场景 2：池子含 llama-3.2-vision（应自动切换并带图）===")
    b = make_assistant(["minicpm5-1b", "llama-3.2-vision"], "minicpm5-1b")
    b.on_send("看看这张图", [img])
    check("自动切换到视觉模型 llama-3.2-vision",
          b.cfg.model() == "llama-3.2-vision", b.cfg.model())
    check("发送内容含 image_url（图片被正确发出）",
          content_has_image(b.history[-1]["content"]))

    # 场景 3：当前已是视觉模型，无需切换、正常带图
    print("\n=== 场景 3：当前已是 glm-4v-flash（应直接带图）===")
    c = make_assistant(["glm-4v-flash"], "glm-4v-flash")
    c.cfg.set_provider("zhipu")
    c.cfg.data["model_cache"]["zhipu"] = {"models": ["glm-4v-flash"], "ts": 0}
    c.cfg.set_model("glm-4v-flash")
    c.on_send("描述图片", [img])
    check("视觉模型不会被切换走", c.cfg.model() == "glm-4v-flash", c.cfg.model())
    check("视觉模型发送内容含 image_url",
          content_has_image(c.history[-1]["content"]))

    # 场景 4：纯文本无图，正常发文字
    print("\n=== 场景 4：无图片（不应受影响）===")
    d = make_assistant(["minicpm5-1b"], "minicpm5-1b")
    d.on_send("你好")
    check("无图场景正常工作",
          isinstance(d.history[-1]["content"], str) and d.history[-1]["content"] == "你好")

    passed = sum(1 for _, ok in results if ok)
    print("\n=== 结果：%d/%d 通过 ===" % (passed, len(results)))
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    app = QApplication(sys.argv)
    sys.exit(run())
