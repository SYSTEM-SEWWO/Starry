# -*- coding: utf-8 -*-
"""语音朗读（TTS）：把 AI 回复读出来。

设计要点：
- 依赖 pyqt5 之外的 pyttsx3（离线 TTS，系统级 espeak / SAPI 合成）
- 未安装 pyttsx3 时优雅降级：available() 返回 False，调用方给出提示
- 合成在独立守护线程中执行，避免阻塞 UI；stop() 可随时打断
"""
import re
import sys
import threading

try:
    import pyttsx3
    _HAS_TTS = True
except Exception:                                   # 未安装 / 平台不支持
    pyttsx3 = None
    _HAS_TTS = False

# 一次性编译：朗读前剥离 Markdown 记号
_MD_PATTERNS = [
    (re.compile(r"```.*?```", re.S), " 代码块 "),
    (re.compile(r"`([^`]*)`"), r"\1"),
    (re.compile(r"\*\*([^*]*)\*\*"), r"\1"),
    (re.compile(r"!\[[^\]]*\]\([^)]*\)"), " 图片 "),
    (re.compile(r"\[([^\]]*)\]\([^)]*\)"), r"\1"),
    (re.compile(r"^#{1,6}\s*", re.M), ""),
    (re.compile(r"^\s*[-*+]\s+", re.M), ""),
    (re.compile(r"^\s*>\s?", re.M), ""),
    (re.compile(r"^\s*\|.*\|\s*$", re.M), " 表格 "),
    (re.compile(r"https?://\S+"), " 链接 "),
]


def strip_markdown(text):
    """把 Markdown 文本转为适合朗读的纯文本"""
    out = text or ""
    for pat, repl in _MD_PATTERNS:
        out = pat.sub(repl, out)
    out = re.sub(r"\s+", " ", out).strip()
    return out


def tts_guidance():
    """分平台安装指引（设置页与 README 共用）"""
    if not _HAS_TTS:
        base = "未安装 pyttsx3，请先执行：pip install pyttsx3。"
    else:
        base = "pyttsx3 已安装。"
    if sys.platform.startswith("win"):
        return base + "Windows 已内置 SAPI5 语音引擎，无需额外配置。"
    if sys.platform == "darwin":
        return base + "macOS 已内置语音合成，无需额外配置。"
    return base + ("Linux 还需系统语音引擎：sudo apt install espeak"
                   "（或 pip install pyttsx3-espeak）后重启本程序。")


class Speaker:
    """单例式朗读器（内部维护一个合成线程）"""

    def __init__(self):
        self._lock = threading.Lock()
        self._thread = None
        self._engine = None

    def available(self):
        return _HAS_TTS

    def speak(self, text, rate=None):
        """后台朗读文本；返回是否成功开始"""
        if not _HAS_TTS:
            return False
        text = strip_markdown(text)
        if not text:
            return False
        # 中文按 350 字/分钟截断，避免超长回复读不完
        if len(text) > 1200:
            text = text[:1200] + "……后续内容请直接阅读"
        with self._lock:
            self._stop_locked()
            self._thread = threading.Thread(
                target=self._run, args=(text, rate), daemon=True)
            self._thread.start()
        return True

    def stop(self):
        with self._lock:
            self._stop_locked()

    def is_speaking(self):
        t = self._thread
        return bool(t and t.is_alive())

    # ------------------------------------------------------------------
    def _stop_locked(self):
        if self._engine is not None:
            try:
                self._engine.stop()
            except Exception:
                pass
        self._thread = None

    def _run(self, text, rate):
        try:
            if self._engine is None:
                self._engine = pyttsx3.init()
            self._engine.setProperty("rate", rate or 210)
            self._engine.say(text)
            self._engine.runAndWait()
        except Exception:
            self._engine = None
