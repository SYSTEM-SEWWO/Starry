# -*- coding: utf-8 -*-
"""全局热键：任意位置唤起 / 隐藏聊天窗口。

- 优先使用 pynput（跨平台；Linux 需 X11 会话）
- 未安装 / 不支持时优雅降级：返回不可用原因，UI 提示
- 热键形如 "ctrl+shift+a"，可在设置中修改
"""
import os
import sys

DEFAULT_HOTKEY = "ctrl+shift+a"
DEFAULT_QUICK_HOTKEY = "ctrl+shift+q"          # v7.2：划词提问

# 允许的修饰键与主键
_MODIFIERS = {"ctrl", "alt", "shift", "cmd", "super", "win", "meta"}
_ALIASES = {
    "control": "ctrl", "ctl": "ctrl", "option": "alt",
    "windows": "cmd", "meta": "cmd", "escape": "esc",
}
_SPECIAL_KEYS = {
    "space", "enter", "esc", "tab", "up", "down", "left", "right",
    "home", "end", "page_up", "page_down", "insert", "delete",
    "f1", "f2", "f3", "f4", "f5", "f6", "f7", "f8", "f9",
    "f10", "f11", "f12",
}


def normalize_hotkey(text):
    """规范化热键字符串；非法返回 None"""
    parts = [p.strip().lower() for p in (text or "").split("+")]
    parts = [_ALIASES.get(p, p) for p in parts if p]
    if not parts or len(parts) > 4:
        return None
    mods, keys = [], []
    for p in parts:
        if p in _MODIFIERS:
            if p not in mods:
                mods.append(p)
        else:
            keys.append(p)
    if len(keys) != 1:
        return None
    key = keys[0]
    if len(key) == 1 and key.isalnum():
        pass
    elif key in _SPECIAL_KEYS:
        pass
    else:
        return None
    return "+".join(sorted(mods) + [key])


def pynput_available():
    try:
        from importlib.util import find_spec
        return find_spec("pynput") is not None
    except Exception:
        return False


class HotkeyManager:
    """全局热键管理（回调在 pynput 监听线程触发，需自行切回 UI 线程）"""

    def __init__(self, hotkey=None, callback=None):
        self.hotkey = normalize_hotkey(hotkey) or DEFAULT_HOTKEY
        self.callback = callback
        self._listener = None
        self._error = ""

    # ------------------------------------------------------------------
    def start(self):
        """注册热键。返回 (ok, 消息)"""
        self.stop()
        if not pynput_available():
            self._error = "未安装 pynput（pip install pynput），全局热键不可用"
            return False, self._error
        try:
            from pynput import keyboard

            def on_activate():
                if self.callback:
                    self.callback()

            self._listener = keyboard.GlobalHotKeys(
                {_to_pynput_hotkey(self.hotkey): on_activate})
            self._listener.daemon = True
            self._listener.start()
            return True, "全局热键 %s 已生效" % self.hotkey.upper()
        except Exception as e:  # noqa: BLE001
            self._error = "热键注册失败：%s" % e
            self._listener = None
            return False, self._error

    def stop(self):
        if self._listener is not None:
            try:
                self._listener.stop()
            except Exception:
                pass
            self._listener = None

    def set_hotkey(self, hotkey, restart=True):
        """修改热键；返回 (ok, 消息)"""
        norm = normalize_hotkey(hotkey)
        if norm is None:
            return False, "热键格式不正确，例如：ctrl+shift+a"
        self.hotkey = norm
        if restart and self._listener is not None:
            return self.start()
        return True, norm

    @property
    def active(self):
        return self._listener is not None

    @property
    def error(self):
        return self._error


def _to_pynput_hotkey(hotkey):
    """ctrl+shift+a → <ctrl>+<shift>+a（pynput GlobalHotKeys 语法）"""
    parts = hotkey.split("+")
    out = []
    for p in parts:
        if p in _MODIFIERS or p in _SPECIAL_KEYS:
            out.append("<%s>" % p)
        else:
            out.append(p)          # 单字符主键直接书写
    return "+".join(out)


def is_supported_platform():
    """Linux 非 X11（如纯 Wayland）下 pynput 通常不可用"""
    if sys.platform.startswith("linux"):
        return bool(os.environ.get("DISPLAY"))
    return True
