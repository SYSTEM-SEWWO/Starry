# -*- coding: utf-8 -*-
"""v13.9：悬浮球「不定时小表情 / 小动作」。

设计：纯绘制 + 状态机，不新增窗口、不抢焦点、不影响点击与拖动。

* 待机时每隔 12–28 秒随机触发一次，持续 1.6–3.2 秒；
* 表情：眨眼 / 微笑 / 惊讶 / 困倦 / 爱心眼 / 歪头 / 挥手 / 打哈欠；
* 动作：轻微上下浮动、左右摇摆、弹性缩放、眨眼、小星星迸发；
* 所有参数可通过 ``MoodController.enabled`` 与配置
  ``cfg.data["ball_moods"]`` 开关（默认开启）。
"""
import math
import random

from PyQt5.QtCore import QObject, QTimer
from PyQt5.QtGui import QColor, QPen, QBrush, QPolygonF
from PyQt5.QtCore import QPointF, QRectF, Qt

MOODS = ("blink", "smile", "surprise", "sleepy", "love",
         "tilt", "wave", "yawn")
MOOD_LABELS = {
    "blink": "眨眼", "smile": "微笑", "surprise": "呀！", "sleepy": "困…",
    "love": "♥", "tilt": "歪头", "wave": "嗨~", "yawn": "哈欠",
}


class MoodController(QObject):
    """挂在悬浮球上的表情控制器。"""

    def __init__(self, ball, enabled=True):
        super().__init__(ball)
        self._ball = ball
        self.enabled = bool(enabled)
        self.mood = ""
        self.phase = 0.0                 # 0→1 当前表情进度
        self.duration = 2.4
        self._next = random.uniform(6.0, 12.0)   # 首次稍快，让用户能看到
        self._elapsed = 0.0
        self._fps = 33                  # ms
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        if self.enabled:
            self._timer.start(self._fps)

    def set_enabled(self, on):
        self.enabled = bool(on)
        if self.enabled and not self._timer.isActive():
            self._timer.start(self._fps)
        elif not self.enabled:
            self._timer.stop()
            self.mood = ""
            self._refresh()

    def trigger(self, mood=None):
        """立即触发一个表情（命令面板 / 托盘可调用）。"""
        self.mood = mood or random.choice(MOODS)
        self.phase = 0.0
        self.duration = random.uniform(1.8, 3.2)
        self._refresh()

    def _tick(self):
        e = self._fps / 1000.0
        self._elapsed += e
        if self.mood:
            self.phase += e / self.duration
            if self.phase >= 1.0:
                self.mood = ""
                self.phase = 0.0
                self._next = random.uniform(12.0, 28.0)
                self._elapsed = 0.0
            self._refresh()
        elif self._elapsed >= self._next:
            # 只在待机态且非拖拽时表演，避免打扰用户
            st = getattr(self._ball, "_state", None)
            if st is not None and "idle" not in str(st).lower() and st != 0:
                self._elapsed = 0.0
                self._next = random.uniform(8.0, 16.0)
                return
            if getattr(self._ball, "_drag_pos", None) is not None:
                return
            self.trigger()

    def _refresh(self):
        try:
            self._ball.update()
        except Exception:                   # noqa: BLE001
            pass

    # ---------- 供 paintEvent 查询的动作参数 ----------
    def offsets(self):
        """返回 (dx, dy, rotate_deg, scale)。无表情时全部为 0/1。"""
        if not self.mood:
            return 0.0, 0.0, 0.0, 1.0
        t = min(1.0, max(0.0, self.phase))
        env = math.sin(math.pi * t)          # 0→1→0 平滑包络
        m = self.mood
        if m == "tilt":
            return 0.0, 0.0, 13.0 * env, 1.0
        if m == "wave":
            return 3.2 * math.sin(t * math.pi * 4) * env, 0.0, 7.0 * env, 1.0
        if m == "surprise":
            return 0.0, -3.0 * env, 0.0, 1.0 + 0.11 * env
        if m == "love":
            return 0.0, -2.0 * env, 0.0, 1.0 + 0.06 * env
        if m == "sleepy":
            return 0.0, 2.2 * env, -5.0 * env, 1.0 - 0.04 * env
        if m == "yawn":
            return 0.0, 1.5 * env, 0.0, 1.0 + 0.08 * env
        if m == "blink":
            return 0.0, 0.0, 0.0, 1.0 + 0.02 * env
        return 0.0, -1.8 * env, 0.0, 1.0 + 0.03 * env


def draw_mood(p, cx, cy, r, ctrl):
    """在球体中央绘制表情。返回是否绘制了内容。"""
    if not ctrl or not ctrl.mood:
        return False
    m = ctrl.mood
    t = min(1.0, max(0.0, ctrl.phase))
    env = math.sin(math.pi * t)
    if env < 0.08:
        return True

    ink = QColor(255, 255, 255, int(225 * env))
    p.setPen(Qt.NoPen)
    p.setBrush(QBrush(ink))
    eye_y = cy - r * 0.08
    eye_dx = r * 0.30
    eye_r = r * 0.075

    # 眨眼：眼睛变成横线
    if m == "blink":
        pen = QPen(ink, max(1.5, r * 0.055))
        pen.setCapStyle(Qt.RoundCap)
        p.setPen(pen); p.setBrush(Qt.NoBrush)
        for sx in (-1, 1):
            p.drawLine(QPointF(cx + sx * eye_dx - r * 0.09, eye_y),
                       QPointF(cx + sx * eye_dx + r * 0.09, eye_y))
        return True

    # 爱心眼
    if m == "love":
        for sx in (-1, 1):
            ex = cx + sx * eye_dx
            s = r * 0.13
            path = QPolygonF([
                QPointF(ex, eye_y + s * 0.85),
                QPointF(ex - s, eye_y - s * 0.1),
                QPointF(ex - s * 0.5, eye_y - s * 0.85),
                QPointF(ex, eye_y - s * 0.35),
                QPointF(ex + s * 0.5, eye_y - s * 0.85),
                QPointF(ex + s, eye_y - s * 0.1),
            ])
            p.drawPolygon(path)
        _draw_smile(p, cx, cy, r, ink, 0.30)
        return True

    # 困倦 / 哈欠：眼睛半闭
    if m in ("sleepy", "yawn"):
        pen = QPen(ink, max(1.2, r * 0.045))
        pen.setCapStyle(Qt.RoundCap)
        p.setPen(pen); p.setBrush(Qt.NoBrush)
        for sx in (-1, 1):
            ex = cx + sx * eye_dx
            p.drawLine(QPointF(ex - r * 0.09, eye_y + r * 0.02),
                       QPointF(ex + r * 0.09, eye_y + r * 0.02))
        if m == "yawn":
            p.setPen(Qt.NoPen); p.setBrush(QBrush(ink))
            p.drawEllipse(QRectF(cx - r * 0.10, cy + r * 0.16,
                                r * 0.20, r * 0.22 * env))
        elif _show_sleep_bubble(p, cx, cy, r, ink, t):
            pass
        return True

    # 惊讶：圆眼 + 小嘴
    if m == "surprise":
        for sx in (-1, 1):
            p.drawEllipse(QRectF(cx + sx * eye_dx - eye_r * 1.3,
                                eye_y - eye_r * 1.3,
                                eye_r * 2.6, eye_r * 2.6))
        p.drawEllipse(QRectF(cx - r * 0.07, cy + r * 0.20,
                            r * 0.14, r * 0.16))
        _draw_sparks(p, cx, cy, r, ink, t)
        return True

    # 默认（微笑 / 歪头 / 挥手）：圆眼 + 笑嘴
    for sx in (-1, 1):
        p.drawEllipse(QRectF(cx + sx * eye_dx - eye_r, eye_y - eye_r,
                            eye_r * 2, eye_r * 2))
    _draw_smile(p, cx, cy, r, ink, 0.32)
    if m == "wave":
        _draw_wave(p, cx, cy, r, ink, t)
    if m == "tilt":
        _draw_sparks(p, cx, cy, r, ink, t, count=2)
    return True


def _draw_smile(p, cx, cy, r, ink, width):
    pen = QPen(ink, max(1.4, r * 0.05))
    pen.setCapStyle(Qt.RoundCap)
    p.setPen(pen); p.setBrush(Qt.NoBrush)
    rect = QRectF(cx - r * width, cy + r * 0.06,
                  r * width * 2, r * 0.34)
    p.drawArc(rect, 200 * 16, 140 * 16)


def _draw_sparks(p, cx, cy, r, ink, t, count=4):
    p.setPen(Qt.NoPen); p.setBrush(QBrush(ink))
    for i in range(count):
        a = 2 * math.pi * i / count + t * 2
        rr = r * (0.78 + 0.16 * math.sin(math.pi * t))
        x = cx + math.cos(a) * rr
        y = cy + math.sin(a) * rr
        s = r * 0.055 * math.sin(math.pi * t)
        p.drawEllipse(QRectF(x - s, y - s, s * 2, s * 2))


def _draw_wave(p, cx, cy, r, ink, t):
    p.setPen(Qt.NoPen); p.setBrush(QBrush(ink))
    x = cx + r * 0.72
    y = cy + r * 0.18
    s = r * 0.10
    p.drawEllipse(QRectF(x - s, y - s, s * 2, s * 2 * (0.7 + 0.5 * t)))


def _show_sleep_bubble(p, cx, cy, r, ink, t):
    """困倦时画一个小小的 z。"""
    pen = QPen(ink, max(1.2, r * 0.04))
    p.setPen(pen); p.setBrush(Qt.NoBrush)
    x, y = cx + r * 0.55, cy - r * 0.62
    s = r * 0.14 * (0.6 + 0.6 * t)
    p.drawLine(QPointF(x, y), QPointF(x + s, y))
    p.drawLine(QPointF(x + s, y), QPointF(x, y + s))
    p.drawLine(QPointF(x, y + s), QPointF(x + s, y + s))
    return True
