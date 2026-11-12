# -*- coding: utf-8 -*-
"""自动化任务：定时 / 间隔执行提示词，结果入会话并提醒。

复刻 WorkBuddy 自动化工作流（本地简化版）：
- 任务 = 名称 + 提示词 + 触发方式（每天定时 / 每 N 分钟）+ 可选技能
- 到点后在后台执行一次对话，结果写入专用会话并弹出提醒
- 全部本地存储，无需常驻服务端

存储：配置目录下 automation.json
    {"tasks": [{"id", "name", "prompt", "mode", "time", "every",
                "skill", "enabled", "last_run", "created"}]}

触发计算为纯函数（next_run / due），便于测试；执行由应用层完成。
"""
import datetime
import json

from core import storage
import os
import time

from core.config import get_config_dir

AUTOMATION_FILE = "automation.json"

MODE_DAILY = "daily"        # 每天定时（HH:MM）
MODE_INTERVAL = "interval"  # 每隔 N 分钟

MODE_LABELS = {MODE_DAILY: "每天定时", MODE_INTERVAL: "每隔"}
DEFAULT_EVERY = 60          # 默认间隔（分钟）
MIN_EVERY = 5               # 最小间隔（分钟）
MAX_EVERY = 7 * 24 * 60     # 最大间隔（一周）


def _now():
    return int(time.time())


def _parse_hhmm(s):
    """'HH:MM' → (h, m)；非法返回 None"""
    try:
        parts = str(s or "").split(":")
        if len(parts) != 2:
            return None
        h, m = int(parts[0]), int(parts[1])
        if 0 <= h <= 23 and 0 <= m <= 59:
            return h, m
    except (TypeError, ValueError):
        pass
    return None


def next_run(task, now=None):
    """计算任务下次运行的时间戳。

    返回值 <= now 表示「已到点待运行」（补行场景）；
    禁用 / 非法配置返回 0。
    """
    if not task.get("enabled", True):
        return 0
    now = int(now if now is not None else time.time())
    mode = task.get("mode", MODE_DAILY)
    if mode == MODE_DAILY:
        hm = _parse_hhmm(task.get("time"))
        if hm is None:
            return 0
        h, m = hm
        dt = datetime.datetime.fromtimestamp(now)
        today_sched = dt.replace(hour=h, minute=m, second=0, microsecond=0)
        today_ts = int(today_sched.timestamp())
        if today_ts > now:
            return today_ts                       # 今天还没到点
        # 今天已到点：若今天尚未运行过 → 待补行；否则排到明天
        last = int(task.get("last_run") or 0)
        if last < today_ts:
            return today_ts
        return int((today_sched + datetime.timedelta(days=1)).timestamp())
    if mode == MODE_INTERVAL:
        try:
            every = int(task.get("every", DEFAULT_EVERY))
        except (TypeError, ValueError):
            return 0
        every = max(MIN_EVERY, min(MAX_EVERY, every)) * 60
        base = int(task.get("last_run") or task.get("created") or now)
        if base > now:             # 时钟回拨等异常：立即就绪一次
            return now
        # 错过多次只补一次：到点即执行，执行后由 mark_run 重置基准
        return base + every
    return 0


def describe(task):
    """人类可读的触发描述"""
    mode = task.get("mode", MODE_DAILY)
    if mode == MODE_DAILY:
        return "每天 %s" % (task.get("time") or "--:--")
    if mode == MODE_INTERVAL:
        every = int(task.get("every") or DEFAULT_EVERY)
        if every % 60 == 0 and every >= 60:
            return "每 %d 小时" % (every // 60)
        return "每 %d 分钟" % every
    return "未知"


class AutomationManager:
    """自动化任务存储（非线程安全：写操作仅在 UI 线程调用）"""

    def __init__(self, path=None):
        self.path = path or os.path.join(get_config_dir(), AUTOMATION_FILE)
        self.data = {"tasks": []}
        self._load()

    # ------------------------------------------------------------------
    # 持久化
    # ------------------------------------------------------------------
    def _load(self):
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict) and isinstance(data.get("tasks"), list):
                self.data = data
        except Exception:
            self.data = {"tasks": []}

    def save(self):
        # 统一走 core.storage 的原子写入（v7.2 去重）
        return storage.save_json(self.path, self.data)

    # ------------------------------------------------------------------
    # 查询
    # ------------------------------------------------------------------
    def tasks(self):
        return list(self.data.get("tasks") or [])

    def get(self, task_id):
        for t in self.data.get("tasks") or []:
            if t.get("id") == task_id:
                return t
        return None

    # ------------------------------------------------------------------
    # 变更
    # ------------------------------------------------------------------
    def add(self, name, prompt, mode=MODE_DAILY, time_str="09:00",
            every=DEFAULT_EVERY, skill=""):
        name = (name or "").strip() or "自动化任务"
        prompt = (prompt or "").strip()
        if not prompt:
            return None
        if mode not in (MODE_DAILY, MODE_INTERVAL):
            mode = MODE_DAILY
        task = {"id": "a_%d_%s" % (_now(), os.urandom(3).hex()),
                "name": name[:40], "prompt": prompt,
                "mode": mode,
                "time": time_str if mode == MODE_DAILY else "",
                "every": int(every) if mode == MODE_INTERVAL else DEFAULT_EVERY,
                "skill": skill or "",
                "enabled": True, "last_run": 0, "created": _now()}
        self.data.setdefault("tasks", []).append(task)
        self.save()
        return task

    def update(self, task_id, **fields):
        task = self.get(task_id)
        if task is None:
            return False
        for key in ("name", "prompt", "mode", "time", "every",
                    "skill", "enabled"):
            if key in fields and fields[key] is not None:
                task[key] = fields[key]
        if task.get("mode") == MODE_DAILY:
            task["every"] = DEFAULT_EVERY
        else:
            task["time"] = ""
        self.save()
        return True

    def remove(self, task_id):
        before = len(self.data.get("tasks") or [])
        self.data["tasks"] = [t for t in self.data.get("tasks") or []
                              if t.get("id") != task_id]
        if len(self.data["tasks"]) != before:
            self.save()
            return True
        return False

    def set_enabled(self, task_id, on):
        return self.update(task_id, enabled=bool(on))

    def clear(self):
        self.data["tasks"] = []
        self.save()

    def mark_run(self, task_id, ts=None):
        task = self.get(task_id)
        if task is None:
            return False
        task["last_run"] = int(ts if ts is not None else time.time())
        self.save()
        return True

    # ------------------------------------------------------------------
    # 触发（纯计算）
    # ------------------------------------------------------------------
    def due(self, now=None):
        """到点待执行的任务列表（按优先级：间隔任务优先）"""
        now = int(now if now is not None else time.time())
        out = []
        for t in self.data.get("tasks") or []:
            if not t.get("enabled", True):
                continue
            nxt = next_run(t, now)
            if nxt and nxt <= now:
                out.append(t)
        return out
