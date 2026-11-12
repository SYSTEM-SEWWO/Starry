# -*- coding: utf-8 -*-
"""本地用量统计（隐私优先：仅聚合数字，绝不上传、不记录内容）。

持久化：配置目录下 stats.json
    {
      "messages_sent": 128,        # 发送的消息数
      "tool_calls": 42,            # 智能体工具调用次数
      "sessions_created": 7,       # 创建的会话数
      "chars_sent": 52310,         # 发送的字符数（含附件文本）
      "est_tokens": 32694,         # 估算 token（chars / 1.6，仅中文近似）
      "active_days": ["2026-10-21"],  # 活跃日期（UTC+8，去重）
      "first_run": 1792596000,     # 首次运行时间戳
      "last_active": 1792596000
    }
"""
import json

from core import storage
import os
import time

from core.config import get_config_dir

STATS_FILE = "stats.json"
CHARS_PER_TOKEN = 1.6          # 中文字符 ≈ 1.6 字符/token 的粗略估算


def _today():
    # UTC+8 日期，与国内用户感知一致
    return time.strftime("%Y-%m-%d", time.gmtime(time.time() + 8 * 3600))


class UsageStats:
    """聚合用量统计（UI 线程使用）"""

    def __init__(self, path=None):
        self.path = path or os.path.join(get_config_dir(), STATS_FILE)
        self.data = self._default()
        self._load()

    @staticmethod
    def _default():
        return {"messages_sent": 0, "tool_calls": 0, "sessions_created": 0,
                "chars_sent": 0, "est_tokens": 0, "active_days": [],
                "first_run": int(time.time()), "last_active": int(time.time())}

    # ------------------------------------------------------------------
    def _load(self):
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                for k in self._default():
                    if k in data:
                        self.data[k] = data[k]
        except Exception:
            pass

    def save(self):
        # 统一走 core.storage 的原子写入（v7.2 去重）
        return storage.save_json(self.path, self.data)

    # ------------------------------------------------------------------
    # 埋点
    # ------------------------------------------------------------------
    def record_message(self, text):
        """发送一条消息（text 为纯文本，附件文本已并入）"""
        n = len(text or "")
        self.data["messages_sent"] += 1
        self.data["chars_sent"] += n
        self.data["est_tokens"] += int(n / CHARS_PER_TOKEN)
        self._touch()
        self.save()

    def record_tool_call(self):
        self.data["tool_calls"] += 1
        self._touch()
        self.save()

    def record_session(self):
        self.data["sessions_created"] += 1
        self._touch()
        self.save()

    def _touch(self):
        self.data["last_active"] = int(time.time())
        today = _today()
        days = self.data.setdefault("active_days", [])
        if today not in days:
            days.append(today)
            # 只保留最近 400 天，防止文件无限增长
            self.data["active_days"] = days[-400:]

    # ------------------------------------------------------------------
    # 展示
    # ------------------------------------------------------------------
    def summary(self):
        """关于对话框用的摘要行"""
        d = self.data
        return {
            "messages": d.get("messages_sent", 0),
            "tool_calls": d.get("tool_calls", 0),
            "sessions": d.get("sessions_created", 0),
            "chars": d.get("chars_sent", 0),
            "est_tokens": d.get("est_tokens", 0),
            "active_days": len(d.get("active_days") or []),
            "first_run": d.get("first_run", 0),
        }

    def is_active_today(self):
        """今天是否活跃（状态栏展示用）"""
        return _today() in (self.data.get("active_days") or [])

    def reset(self):
        self.data = self._default()
        self.save()
