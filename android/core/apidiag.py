# -*- coding: utf-8 -*-
"""星语 Starry · API 诊断记录（v13.2，脱敏 / 环形缓冲 / 可选审计落盘）。

真实 GUI 测评发现：启动时的 401 以 toast 一闪而过，用户事后无法查看
「刚才错在哪」，排查只能靠猜。本模块把每次 API 失败沉淀成**可追溯、
可复制、可导出**的脱敏诊断记录，供「API 诊断」面板与企业审计使用。

安全边界（硬性）：
  * 只接受 `core.apierrors` 产出的结构化错误；其中的 detail 已脱敏；
  * **绝不记录** API Key、Bearer Token、请求体、完整响应体、消息正文；
  * 落盘为 JSONL，默认关闭，仅当显式设置 `STARRY_API_LOG` 时启用；
  * 任何读写异常都静默收敛，绝不因诊断功能影响主流程。
"""
import json
import os
import threading
import time
from collections import deque

from core import apierrors

BUFFER_SIZE = 100
_LOCK = threading.Lock()
_BUFFER = deque(maxlen=BUFFER_SIZE)
_SEQ = [0]


def _safe(d):
    """只保留结构中的安全字段，杜绝调用方误传敏感字段。"""
    if not isinstance(d, dict):
        return {}
    keep = {}
    for k in ("operation", "kind", "status", "title", "detail", "severity",
              "retryable", "backoff", "action", "scope"):
        v = d.get(k)
        if isinstance(v, (str, int, float, bool, type(None))):
            keep[k] = v
    # advice 是固定文案列表，逐条再过一次脱敏
    if isinstance(d.get("advice"), list):
        keep["advice"] = [apierrors.redact(x, 200)
                          for x in d["advice"][:5] if isinstance(x, str)]
    return keep


def record(operation, err=None, scope="", **extra):
    """记录一次失败（或重要状态），返回该条记录；永不抛异常。"""
    try:
        err = err if isinstance(err, dict) else apierrors.from_exception(err, operation)
        item = _safe(err)
        item["operation"] = str(operation or item.get("operation") or "api")
        item["scope"] = str(scope or "")
        # extra 白名单：只允许少量标量与脱敏后的说明
        for k in ("url_host", "provider", "model", "attempt", "note"):
            if k in extra and isinstance(extra[k], (str, int, float, bool)):
                item[k] = apierrors.redact(extra[k], 120) if k == "note" else extra[k]
        with _LOCK:
            _SEQ[0] += 1
            item["seq"] = _SEQ[0]
            item["ts"] = time.time()
            item["time"] = time.strftime("%Y-%m-%d %H:%M:%S",
                                         time.localtime(item["ts"]))
            _BUFFER.append(item)
            snapshot = dict(item)
        _append_audit(snapshot)
        return snapshot
    except Exception:                                   # noqa: BLE001
        return {}


def _append_audit(item):
    """可选审计落盘：仅当 STARRY_API_LOG 显式设置时写 JSONL。"""
    path = os.environ.get("STARRY_API_LOG")
    if not path:
        return
    try:
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(item, ensure_ascii=False,
                               separators=(",", ":")) + "\n")
    except (OSError, ValueError, TypeError):
        pass


def recent(n=20):
    """返回最近 n 条（新→旧）的副本，不暴露内部对象。"""
    try:
        n = max(0, int(n))
    except (TypeError, ValueError):
        n = 20
    with _LOCK:
        return [dict(x) for x in list(_BUFFER)[-n:]][::-1] if n else []


def summary():
    """汇总：总数、按分类计数、最近一条。"""
    with _LOCK:
        items = list(_BUFFER)
    counts = {}
    for x in items:
        k = x.get("kind", apierrors.KIND_UNKNOWN)
        counts[k] = counts.get(k, 0) + 1
    return {"total": len(items), "by_kind": counts,
            "last": dict(items[-1]) if items else None}


def text_report(n=20):
    """可复制的诊断文本（脱敏、无密钥）。"""
    items = recent(n)
    if not items:
        return "暂无 API 失败记录。\n（仅记录失败与重要状态，不记录 API Key、请求体或聊天内容。）"
    lines = ["星语 Starry · API 诊断（脱敏）",
             "共 %d 条记录，显示最近 %d 条" % (summary()["total"], len(items)), ""]
    for x in items:
        lines.append("[%s] #%s %s · %s" % (
            x.get("time", ""), x.get("seq", ""),
            x.get("severity", ""), x.get("title", "")))
        lines.append("  操作：%s · 分类：%s · HTTP：%s" % (
            x.get("operation", ""), x.get("kind", ""),
            x.get("status") or "—"))
        if x.get("detail"):
            lines.append("  摘要：%s" % x["detail"])
        for a in (x.get("advice") or [])[:2]:
            lines.append("  建议：%s" % a)
        lines.append("")
    lines.append("说明：本记录不含 API Key、Bearer Token、请求体与聊天内容；"
                 "完整性校验（digest）不是签名认证。")
    return "\n".join(lines)


def clear():
    """清空内存记录（不影响已落盘的审计日志）。"""
    with _LOCK:
        _BUFFER.clear()


__all__ = ["BUFFER_SIZE", "record", "recent", "summary", "text_report", "clear"]
