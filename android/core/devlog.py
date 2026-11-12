# -*- coding: utf-8 -*-
"""开发者调试模式与分级日志（v13.5）。

零第三方依赖、纯逻辑，桌面 / CLI / 安卓可同源复用。设计要点：

- **默认完全静默**：不开启调试模式时 ``log()`` 几乎零开销、不写文件、不打印，
  正式用户不受影响；开启后才收集与输出。
- **分级 + 环形缓冲**：DEBUG/INFO/WARN/ERROR，内存保留最近 500 条，
  UI 面板与 CLI 直接读缓冲，不必读文件。
- **脱敏**：所有对外文本过 ``core.apierrors.redact``，绝不记录 API Key /
  Bearer Token / 上游原始响应体。
- **可选落盘**：只有显式给出 ``STARRY_LOG_FILE``（或调用 configure(path=...)）
  才写 JSONL；日志目录由产品内缓存清理统一管理。

开关优先级：显式参数 > 环境变量 > cfg.data > 默认关闭。
环境变量：``STARRY_DEBUG=1`` / ``STARRY_LOG_LEVEL=DEBUG`` / ``STARRY_LOG_FILE=...``
"""
import json
import os
import time
from collections import deque

from core.apierrors import redact

LEVELS = {"DEBUG": 10, "INFO": 20, "WARN": 30, "ERROR": 40}
LEVEL_LABELS = {10: "DEBUG", 20: "INFO", 30: "WARN", 40: "ERROR"}
MAX_RECORDS = 500
MAX_TEXT = 300

_enabled = False
_level = LEVELS["INFO"]
_path = ""
_buffer = deque(maxlen=MAX_RECORDS)
_sinks = []


def _env_bool(name):
    return (os.environ.get(name) or "").strip().lower() in ("1", "true", "yes", "on")


def configure(enabled=None, level=None, path=None, cfg=None):
    """配置调试日志。返回生效状态字典（供 UI / CLI 展示）。

    ``cfg`` 为可选 AppConfig；读 ``cfg.data["debug_mode"]`` 与 ``["log_level"]``。
    """
    global _enabled, _level, _path
    if enabled is None:
        if _env_bool("STARRY_DEBUG"):
            enabled = True
        elif cfg is not None:
            enabled = bool(cfg.data.get("debug_mode", False))
        else:
            enabled = False
    if level is None:
        level = (os.environ.get("STARRY_LOG_LEVEL")
                 or (cfg.data.get("log_level") if cfg is not None else "")
                 or "INFO")
    if path is None:
        path = os.environ.get("STARRY_LOG_FILE") or ""
    _enabled = bool(enabled)
    _level = LEVELS.get(str(level).upper(), LEVELS["INFO"])
    _path = str(path or "")
    return state()


def state():
    return {"enabled": _enabled, "level": LEVEL_LABELS.get(_level, "INFO"),
            "level_value": _level, "path": _path,
            "buffered": len(_buffer), "max_records": MAX_RECORDS}


def is_enabled():
    return _enabled


def set_level(level):
    global _level
    _level = LEVELS.get(str(level).upper(), _level)
    return state()


def add_sink(fn):
    """注册实时回调（调试面板用）：每次记录时收到该条 dict。"""
    if callable(fn) and fn not in _sinks:
        _sinks.append(fn)


def remove_sink(fn):
    if fn in _sinks:
        _sinks.remove(fn)


def log(level, scope, message, **extra):
    """记录一条日志。未开启或低于级别时直接返回 None（零副作用）。"""
    if not _enabled:
        return None
    code = LEVELS.get(str(level).upper(), LEVELS["INFO"])
    if code < _level:
        return None
    item = {
        "ts": time.time(),
        "time": time.strftime("%H:%M:%S"),
        "level": LEVEL_LABELS.get(code, "INFO"),
        "scope": redact(str(scope or "app"), 60),
        "message": redact(str(message or ""), MAX_TEXT),
        "extra": {k: redact(str(v), 120) for k, v in (extra or {}).items()},
    }
    _buffer.append(item)
    for fn in list(_sinks):
        try:
            fn(item)
        except Exception:                               # noqa: BLE001
            pass
    if _path:
        _append(item)
    return item


def _append(item):
    try:
        d = os.path.dirname(os.path.abspath(_path))
        if d:
            os.makedirs(d, exist_ok=True)
        with open(_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")
    except Exception:                                   # noqa: BLE001
        pass                    # 日志失败绝不影响主流程


def debug(scope, message, **extra):
    return log("DEBUG", scope, message, **extra)


def info(scope, message, **extra):
    return log("INFO", scope, message, **extra)


def warn(scope, message, **extra):
    return log("WARN", scope, message, **extra)


def error(scope, message, **extra):
    return log("ERROR", scope, message, **extra)


def recent(n=100, min_level=None):
    rows = list(_buffer)
    if min_level:
        threshold = LEVELS.get(str(min_level).upper(), 0)
        rows = [r for r in rows if LEVELS.get(r["level"], 0) >= threshold]
    return rows[-max(1, int(n)):]


def summary():
    counts = {k: 0 for k in LEVEL_LABELS.values()}
    for r in _buffer:
        counts[r["level"]] = counts.get(r["level"], 0) + 1
    return {"total": len(_buffer), "counts": counts, **state()}


def text_report(n=100):
    rows = recent(n)
    if not rows:
        return "暂无日志记录（调试模式可能未开启）。"
    lines = []
    for r in rows:
        lines.append("%s  %-5s  [%s]  %s" % (
            r["time"], r["level"], r["scope"], r["message"]))
        if r.get("extra"):
            lines[-1] += "  %s" % json.dumps(
                r["extra"], ensure_ascii=False)
    return "\n".join(lines)


def clear():
    _buffer.clear()


def export_text(path):
    """把当前缓冲导出为纯文本（调试面板「导出」用）。"""
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(text_report(MAX_RECORDS))
        return True, path
    except Exception as e:                              # noqa: BLE001
        return False, str(e)[:150]
