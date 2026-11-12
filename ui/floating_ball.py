# -*- coding: utf-8 -*-
"""悬浮小球：最小化形态，仿豆包桌面助手，带状态动画系统。

状态：
- IDLE      待机：呼吸微光 + 底部投影 + 极光弧（v7.1）
- THINKING  思考中：旋转弧 + 双轨道粒子 + 双层脉冲波纹 + 反向细弧（v7.1）
- SPEAKING  输出中：旋转虚线弧 + 三音浪均衡器（含峰值帽，v7.1）

交互：单击展开/收起，拖动移动，右键菜单；悬停放大，点击涟漪，入场弹跳。
"""
import math
import random

from PyQt5.QtCore import (Qt, QTimer, QPointF, QRect, QRectF, pyqtSignal,
                          QPropertyAnimation, QEasingCurve)
from PyQt5.QtGui import (QPainter, QColor, QLinearGradient, QRadialGradient,
                         QPen, QBrush, QPolygonF, QPainterPath,
                         QConicalGradient)
from PyQt5.QtWidgets import QApplication, QWidget, QMenu

from ui.theme import brand


class BallState:
    IDLE = 0
    THINKING = 1
    SPEAKING = 2


def peak_hold(cur, level, dt, rise=8.0, fall=1.1):
    """音频表峰值保持（纯函数）：瞬时上冲，缓慢下落。

    用于输出态均衡器的「峰值帽」——真实音频表的标志性语言。
    """
    if level >= cur:
        return max(0.0, min(1.0, level))
    return max(level, cur - fall * dt)


# 待机行为阈值（秒）
ROAM_AFTER = 8.0        # 闲置多久开始慢慢溜达
ROAM_GAP = 11.0         # 两次溜达之间的间隔
ROAM_RANGE = 130        # 单次漂移的最大半径（px）
TIP_AFTER = 22.0        # 闲置多久冒第一句
TIP_GAP = 26.0          # 两次提示之间的间隔
TIP_LIFE = 4.6          # 气泡存活时长


class TipBubble(QWidget):
    """悬浮球上方的留言气泡（自绘圆角 + 小尾巴，淡入淡出）。

    不抢鼠标事件，超时自动消失；灵感来自 clippy 的 speech bubble。
    """

    def __init__(self, parent=None):
        super().__init__(None)
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Tool
                            | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self._text = ""
        self._life = -1.0               # <0 表示未激活
        self._dur = TIP_LIFE
        self._brand = brand()           # 顶部光条用品牌色
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(33)
        self.hide()

    def show_tip(self, text, parent_pos=None, duration=TIP_LIFE):
        """在 parent_pos（球的位置/尺寸）上方弹出气泡"""
        self._text = (text or "").strip()
        if not self._text:
            return
        self._life = 0.0
        self._dur = duration
        fm = self.fontMetrics()
        # 自适应宽度（上限 360），超长自动换行并按换行后高度算窗口
        tw = fm.horizontalAdvance(self._text)
        w = min(360, max(150, tw + 40))
        text_w = w - 36
        bound = fm.boundingRect(QRect(0, 0, text_w, 600),
                                Qt.TextWordWrap, self._text)
        h = max(fm.height() + 26, bound.height() + 26)
        self.resize(int(w), int(h))
        if parent_pos is not None:
            px, py, pw = parent_pos
            x = int(px + pw / 2 - w / 2)
            y = int(py - h - 10)
            x = max(4, x)
            y = max(4, y)
            self.move(x, y)
        self.show()
        self.raise_()

    def hide_tip(self):
        self._life = -1.0
        self.hide()

    def _tick(self):
        if self._life < 0:
            return
        self._life += 0.033
        if self._life >= self._dur:
            self.hide_tip()
            return
        self.update()

    def _alpha(self):
        """淡入淡出包络：0→1（0.3s）→ 保持 → 1→0（末 0.6s）"""
        if self._life < 0:
            return 0.0
        if self._life < 0.3:
            return max(0.0, self._life / 0.3)
        left = self._dur - self._life
        if left < 0.6:
            return max(0.0, left / 0.6)
        return 1.0

    def paintEvent(self, e):
        a = self._alpha()
        if a <= 0.01:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        r = QRectF(8, 2, self.width() - 16, self.height() - 20)
        path = QPainterPath()
        path.addRoundedRect(r, 12, 12)
        # 小尾巴（指向下方球体）
        tail = QPolygonF([QPointF(self.width() / 2 - 7, r.bottom() - 1),
                          QPointF(self.width() / 2 + 7, r.bottom() - 1),
                          QPointF(self.width() / 2, r.bottom() + 9)])
        path.addPolygon(tail)
        # 微蓝玻璃底（白底上也有轮廓），顶部一道主题色细光
        bg = QColor(247, 251, 255, int(244 * a))
        p.fillPath(path, QBrush(bg))
        top = QLinearGradient(0, r.top(), 0, r.top() + 3)
        br, bgc, bb = self._brand["particle_mid"]
        top.setColorAt(0.0, QColor(br, bgc, bb, int(210 * a)))
        top.setColorAt(1.0, QColor(br, bgc, bb, 0))
        p.save()
        p.setClipPath(path)
        p.fillRect(QRectF(r.left(), r.top(), r.width(), 3), top)
        p.restore()
        p.setPen(QPen(QColor(30, 60, 90, int(38 * a)), 1))
        p.drawPath(path)
        p.setPen(QColor(42, 56, 72, int(255 * a)))
        p.drawText(QRectF(16, 8, self.width() - 32, self.height() - 22),
                   Qt.AlignVCenter | Qt.AlignLeft | Qt.TextWordWrap,
                   self._text)
        p.end()


class ThinkingCaption(QWidget):
    """v9.0 实时思考字幕：悬浮球上方的「液态玻璃」小卡，呈现流动中的思考片段，
    并带一道循环微光扫掠。不参与鼠标交互，思考停止后自动淡出。
    """

    def __init__(self, parent=None):
        super().__init__(None)
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Tool
                            | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self._text = ""
        self._life = -1.0               # <0 表示未激活
        self._dur = 2.2                 # 无新思考输入后的淡出时长（秒）
        self._t = 0.0
        self._brand = brand()           # 品牌色（随主题切换）
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(33)
        self.hide()

    def show_text(self, text, parent_pos=None):
        t = (text or "").strip()
        if not t:
            return
        self._text = t
        self._life = 0.0
        self._resize_for()
        if parent_pos is not None:
            px, py, pw = parent_pos
            x = int(px + pw / 2 - self.width() / 2)
            y = int(py - self.height() - 10)
            x = max(4, x)
            y = max(4, y)
            self.move(x, y)
        self.show()
        self.raise_()

    def _resize_for(self):
        fm = self.fontMetrics()
        maxw = 264
        bound = fm.boundingRect(QRect(0, 0, maxw - 24, 220),
                               Qt.TextWordWrap, self._text)
        w = min(maxw, max(90, bound.width() + 26))
        h = max(36, bound.height() + 22)
        self.resize(int(w), int(h))

    def _tick(self):
        if self._life < 0:
            return
        self._t += 0.033
        self._life += 0.033
        if self._life >= self._dur:
            self._life = -1.0
            self.hide()
            return
        self.update()

    def _alpha(self):
        if self._life < 0:
            return 0.0
        if self._life < 0.3:
            return max(0.0, self._life / 0.3)
        left = self._dur - self._life
        if left < 0.5:
            return max(0.0, left / 0.5)
        return 1.0

    def paintEvent(self, e):
        a = self._alpha()
        if a <= 0.01:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        r = QRectF(4, 2, self.width() - 8, self.height() - 10)
        path = QPainterPath()
        path.addRoundedRect(r, 11, 11)
        # 液态玻璃底：上半透白、下半品牌色淡染
        bg = QLinearGradient(0, r.top(), 0, r.bottom())
        base = QColor(self._brand["main"])
        base.setAlpha(int(150 * a))
        bg.setColorAt(0.0, QColor(255, 255, 255, int(238 * a)))
        bg.setColorAt(1.0, base)
        p.fillPath(path, QBrush(bg))
        # 微光扫掠：在卡内循环移动的一道光带
        p.save()
        p.setClipPath(path)
        sweep = (self._t * 130) % (self.width() + 120) - 60
        sg = QLinearGradient(sweep - 46, 0, sweep + 46, 0)
        sg.setColorAt(0.0, QColor(255, 255, 255, 0))
        sg.setColorAt(0.5, QColor(255, 255, 255, int(130 * a)))
        sg.setColorAt(1.0, QColor(255, 255, 255, 0))
        p.fillRect(QRectF(r.left(), r.top(), self.width(), r.height()), sg)
        p.restore()
        p.setPen(QPen(QColor(255, 255, 255, int(190 * a)), 1))
        p.drawPath(path)
        p.setPen(QColor(38, 50, 66, int(232 * a)))
        p.drawText(QRectF(r.left() + 11, r.top() + 7, r.width() - 22,
                          r.height() - 14),
                   Qt.AlignVCenter | Qt.AlignLeft | Qt.TextWordWrap,
                   self._text)
        p.end()


class FloatingBall(QWidget):
    clicked = pyqtSignal()
    settings_requested = pyqtSignal()
    quit_requested = pyqtSignal()
    position_changed = pyqtSignal(int, int)

    FPS_MS = 33

    def __init__(self, size=56, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.FramelessWindowHint
                            | Qt.WindowStaysOnTopHint
                            | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFixedSize(size, size)
        self.setCursor(Qt.PointingHandCursor)
        self._size = size
        self._state = BallState.IDLE
        self._brand = brand()           # 品牌渐变色（随主题切换）

        # 动画时钟
        self._t = random.uniform(0, 10)        # 错开多个动画的相位
        self._entrance = 0.0                   # 入场进度 0→1
        self._hover_scale = 1.0
        self._hover_target = 1.0
        self._ripple = -1.0                    # <0 表示无涟漪
        self._peaks = [0.0, 0.0, 0.0]          # 均衡器峰值帽（v7.1）
        # v7.2 待机行为：漫游 + 随机提示
        self._roam = False
        self._idle = 0.0
        self._roam_from = None
        self._roam_to = None
        self._roam_t = 0.0
        self._roam_next = 0.0                  # 下一次漫游的倒计时
        self._tip_next = TIP_AFTER
        self._tip_history = []
        self._bubble = None                    # 懒创建（避免测试/静默时弹窗）
        self._caption = None                   # v9.0 实时思考字幕（懒创建）
        self._think_text = ""                  # v9.0 最近一次流式思考片段

        self._drag_pos = None
        self._moved = False

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(self.FPS_MS)

        self._menu = self._build_menu()
        self._update_tooltip()

    # ------------------------------------------------------------------
    def _build_menu(self):
        menu = QMenu()
        menu.addAction("打开对话", self.clicked.emit)
        menu.addAction("设置", self.settings_requested.emit)
        menu.addSeparator()
        menu.addAction("退出", self.quit_requested.emit)
        return menu

    def _update_tooltip(self):
        state_txt = {BallState.IDLE: "待命", BallState.THINKING: "思考中…",
                     BallState.SPEAKING: "输出中…"}[self._state]
        self.setToolTip("星语 · Starry · %s\n单击：打开 / 收起对话\n拖动：移动位置\n右键：更多操作"
                        % state_txt)

    # ------------------------------------------------------------------
    # 状态
    # ------------------------------------------------------------------
    def set_state(self, state):
        if state != self._state:
            prev = self._state
            self._state = state
            self._update_tooltip()
            # v9.0：离开思考态时让思考字幕快速淡出
            if prev == BallState.THINKING and state != BallState.THINKING:
                self._fade_think_caption()
            self.update()

    # v9.0：实时思考字幕（液态玻璃 + 微光）
    def show_thinking_text(self, text):
        """把流式推理片段推到悬浮球上方的思考字幕卡（思考过程可见）。"""
        self._think_text = (text or "").strip()
        if not self._think_text:
            return
        if self._caption is None:
            self._caption = ThinkingCaption()
        self._caption.show_text(self._think_text,
                                (self.x(), self.y(), self.width()))

    def _fade_think_caption(self):
        if self._caption is not None and self._caption._life >= 0:
            self._caption._life = max(0.0, self._caption._dur - 0.45)

    # 兼容旧接口
    def set_thinking(self, on):
        self.set_state(BallState.THINKING if on else BallState.IDLE)

    def set_speaking(self, on):
        self.set_state(BallState.SPEAKING if on else BallState.IDLE)

    def set_always_on_top(self, on):
        self.setWindowFlag(Qt.WindowStaysOnTopHint, bool(on))
        self.show()

    def set_theme(self, name):
        """切换品牌色系（翠绿 / 天蓝）"""
        self._brand = brand(name)
        self.update()

    # ------------------------------------------------------------------
    # v7.2 待机行为：漫游 + 随机提示（灵感：clippy 的 Idle Roaming / Tips）
    # ------------------------------------------------------------------
    def set_roam(self, on):
        """开关「闲置时慢慢溜达」，返回当前状态"""
        self._roam = bool(on)
        if not self._roam:
            self._roam_to = None
            self._roam_from = None
        return self._roam

    def roam(self):
        return self._roam

    def _reset_idle(self):
        """用户一旦有动作就停止「发呆计数」并放弃当前漫游目标"""
        self._idle = 0.0
        self._roam_to = None
        self._roam_from = None
        if self._bubble is not None:
            self._bubble.hide_tip()
        self._tip_next = TIP_AFTER

    def idle_seconds(self):
        return self._idle

    def close_bubble(self):
        """关闭提示气泡并停止其定时器（退出/清理用）"""
        if self._bubble is not None:
            try:
                self._bubble.hide_tip()
                self._bubble._timer.stop()
                self._bubble.close()
            except Exception:                      # noqa: BLE001
                pass
        if self._caption is not None:
            try:
                self._caption._timer.stop()
                self._caption.close()
            except Exception:                      # noqa: BLE001
                pass

    def _tip_timer(self):
        return self._tip_next

    def _tick_roam(self, dt):
        """发呆计数 + 漫游 + 提示气泡"""
        busy = (self._hover_target > 1.0 or self._drag_pos is not None
                or self._state != BallState.IDLE)
        if busy:
            self._reset_idle()
            return
        self._idle += dt

        # 溜达：每 ROAM_GAP 换一个附近的目标点，缓动走过去
        if not self._roam:
            pass
        elif self._roam_to is None:
            self._roam_next -= dt
            if self._idle > ROAM_AFTER and self._roam_next <= 0:
                self._start_roam()
        else:
            self._roam_t = min(1.0, self._roam_t + dt / 2.6)
            e = self._ease_out_cubic_soft(self._roam_t)
            x = self._roam_from.x() + (self._roam_to.x() - self._roam_from.x()) * e
            y = self._roam_from.y() + (self._roam_to.y() - self._roam_from.y()) * e
            # 走动时的轻微浮动（像踩着弹簧）
            bob = 2.0 * math.sin(self._roam_t * math.pi * 3.0) * (1 - self._roam_t)
            self.move(int(x), int(y + bob))
            if self._roam_t >= 1.0:
                self._roam_to = None
                self._roam_from = None
                self._roam_next = ROAM_GAP

        # 提示气泡
        self._tip_next -= dt
        if self._idle > TIP_AFTER and self._tip_next <= 0:
            self._pop_tip()

    def _start_roam(self):
        import random as _rnd
        screen = self.screen() or (QApplication.primaryScreen()
                                   if QApplication.instance() else None)
        geo = screen.availableGeometry() if screen is not None else None
        dx = _rnd.randint(-ROAM_RANGE, ROAM_RANGE)
        dy = _rnd.randint(-ROAM_RANGE // 2, ROAM_RANGE // 2)
        tx, ty = self.x() + dx, self.y() + dy
        if geo is not None:
            tx = max(geo.left() + 4, min(tx, geo.right() - self.width() - 4))
            ty = max(geo.top() + 4, min(ty, geo.bottom() - self.height() - 4))
        self._roam_from = self.pos()
        self._roam_to = QPointF(tx, ty)
        self._roam_t = 0.0

    def _roam_target(self):
        return self._roam_to

    def _pop_tip(self):
        from core import idle_tips as tips
        import datetime as _dt
        text = tips.pick_tip(_dt.datetime.now().hour, self._tip_history)
        self._tip_history.append(text)
        self._tip_history = self._tip_history[-8:]
        if self._bubble is None:
            self._bubble = TipBubble()
        self._bubble.show_tip(text, (self.x(), self.y(), self.width()))
        self._tip_next = TIP_GAP

    @staticmethod
    def _ease_out_cubic_soft(t):
        return 1 - (1 - t) ** 3

    # ------------------------------------------------------------------
    # 动画驱动
    # ------------------------------------------------------------------
    def _tick(self):
        dt = self.FPS_MS / 1000.0
        self._t += dt

        # 入场弹跳（easeOutBack）
        if self._entrance < 1.0:
            self._entrance = min(1.0, self._entrance + dt / 0.55)

        # 悬停缩放平滑过渡
        diff = self._hover_target - self._hover_scale
        if abs(diff) > 0.001:
            self._hover_scale += diff * 0.25
        else:
            self._hover_scale = self._hover_target

        # 点击涟漪
        if self._ripple >= 0.0:
            self._ripple += dt / 0.5
            if self._ripple > 1.0:
                self._ripple = -1.0

        # 均衡器峰值帽（v7.1）：与绘制用同一 wave 公式，上冲快、下落慢
        if self._state == BallState.SPEAKING:
            for i in range(3):
                wave = 0.5 + 0.5 * math.sin(self._t * 5.0 + i * 1.9)
                self._peaks[i] = peak_hold(self._peaks[i], wave, dt)
        else:
            # 非输出态缓慢归零，避免残留
            self._peaks = [max(0.0, p - dt * 1.6) for p in self._peaks]

        # v7.2 待机行为（漫游 + 随机提示）
        self._tick_roam(dt)

        self.update()

    @staticmethod
    def _ease_out_back(t):
        c1, c3 = 1.70158, 2.70158
        return 1 + c3 * (t - 1) ** 3 + c1 * (t - 1) ** 2

    def fade_in(self):
        self._entrance = 0.0
        self.setWindowOpacity(0.0)
        self.show()
        anim = QPropertyAnimation(self, b"windowOpacity", self)
        anim.setDuration(380)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setEasingCurve(QEasingCurve.OutCubic)
        anim.start()
        self._fade_anim = anim

    # ------------------------------------------------------------------
    # 绘制
    # ------------------------------------------------------------------
    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)

        w, h = self.width(), self.height()
        cx, cy = w / 2.0, h / 2.0
        r_base = min(w, h) / 2.0 - 4

        # 综合缩放：入场弹跳 × 悬停放大
        s = self._ease_out_back(self._entrance) * self._hover_scale
        r = r_base * s

        # ---------- 底部投影（悬浮感） ----------
        shadow = QRadialGradient(cx, cy + r * 0.28, r * 1.15)
        shadow.setColorAt(0.0, QColor(*self._brand["shadow"], 90))
        shadow.setColorAt(1.0, QColor(*self._brand["shadow"], 0))
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(shadow))
        p.drawEllipse(QRectF(cx - r * 1.15, cy - r * 0.9, r * 2.3, r * 1.9))

        # ---------- 状态特效 ----------
        if self._state == BallState.IDLE:
            self._paint_aurora(p, cx, cy, r_base)
        elif self._state == BallState.THINKING:
            self._paint_thinking(p, cx, cy, r_base)
        elif self._state == BallState.SPEAKING:
            self._paint_speaking(p, cx, cy, r_base)

        # ---------- 主体 ----------
        breathe = 1.0 + 0.022 * math.sin(self._t * 1.7)
        r_body = r * breathe

        # 外发光
        glow = QRadialGradient(cx, cy, r_body * 1.7)
        glow.setColorAt(0.0, QColor(*self._brand["glow"], 70))
        glow.setColorAt(0.55, QColor(*self._brand["glow"], 22))
        glow.setColorAt(1.0, QColor(*self._brand["glow"], 0))
        p.setBrush(QBrush(glow))
        p.drawEllipse(QRectF(cx - r_body * 1.7, cy - r_body * 1.7,
                             r_body * 3.4, r_body * 3.4))

        # 渐变球体
        grad = QRadialGradient(cx - r_body * 0.32, cy - r_body * 0.42, r_body * 1.35)
        grad.setColorAt(0.0, QColor(self._brand["light"]))
        grad.setColorAt(0.5, QColor(self._brand["main"]))
        grad.setColorAt(1.0, QColor(self._brand["aux"]))
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(grad))
        p.drawEllipse(QRectF(cx - r_body, cy - r_body, 2 * r_body, 2 * r_body))

        # 顶部高光
        hl = QRadialGradient(cx - r_body * 0.35, cy - r_body * 0.45, r_body * 0.6)
        hl.setColorAt(0, QColor(255, 255, 255, 120))
        hl.setColorAt(1, QColor(255, 255, 255, 0))
        p.setBrush(QBrush(hl))
        p.drawEllipse(QRectF(cx - r_body, cy - r_body, 2 * r_body, 2 * r_body))

        # v9.0：思考态「液态玻璃 + 微光」覆盖层（折射高光 + 循环扫掠）
        if self._state == BallState.THINKING:
            self._paint_glass_overlay(p, cx, cy, r_body)

        # ---------- 点击涟漪 ----------
        if self._ripple >= 0.0:
            t = self._ripple
            alpha = int(150 * (1 - t))
            rr = r_base * (0.5 + 1.1 * t)
            p.setPen(QPen(QColor(255, 255, 255, max(0, alpha)), 2.5 * (1 - t) + 0.5))
            p.setBrush(Qt.NoBrush)
            p.drawEllipse(QRectF(cx - rr, cy - rr, 2 * rr, 2 * rr))

        # ---------- 四角星 ----------
        self._draw_sparkle(p, cx, cy, r_body * 0.5)

    def _paint_aurora(self, p, cx, cy, r_base):
        """v7.1 待机极光弧：一道锥形渐变弧环绕球体缓慢旋转（生命感）"""
        rr = r_base * 1.14
        cone = QConicalGradient(cx, cy, math.degrees(self._t * 16) % 360)
        pr, pg, pb = self._brand["particle_mid"]
        br, bg_, bb = self._brand["particle_bright"]
        cone.setColorAt(0.0, QColor(pr, pg, pb, 0))
        cone.setColorAt(0.18, QColor(pr, pg, pb, 140))
        cone.setColorAt(0.38, QColor(pr, pg, pb, 0))
        cone.setColorAt(0.62, QColor(br, bg_, bb, 120))
        cone.setColorAt(0.82, QColor(pr, pg, pb, 0))
        cone.setColorAt(1.0, QColor(pr, pg, pb, 0))
        pen = QPen(QBrush(cone), 2.4)
        pen.setCapStyle(Qt.RoundCap)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        p.drawArc(QRectF(cx - rr, cy - rr, 2 * rr, 2 * rr),
                  0, 300 * 16)

    def _paint_thinking(self, p, cx, cy, r_base):
        t = self._t

        # 双层脉冲波纹（错相位外扩）
        for i in range(2):
            phase = (t * 0.55 + i * 0.5) % 1.0
            rr = r_base + 3 + phase * 12
            alpha = int(90 * (1 - phase))
            p.setPen(QPen(QColor(*self._brand["particle"], max(0, alpha)), 2))
            p.setBrush(Qt.NoBrush)
            p.drawEllipse(QRectF(cx - rr, cy - rr, 2 * rr, 2 * rr))

        # 双轨道粒子（带拖尾）
        for i in range(2):
            ang = t * (2.4 + i * 1.1) + i * math.pi
            rr = r_base + 6
            px, py = cx + rr * math.cos(ang), cy + rr * math.sin(ang)
            pr = 2.4
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(*self._brand["particle_bright"], 230))
            p.drawEllipse(QRectF(px - pr, py - pr, 2 * pr, 2 * pr))
            ang2 = ang - 0.35
            tx, ty = cx + rr * math.cos(ang2), cy + rr * math.sin(ang2)
            p.setBrush(QColor(*self._brand["glow"], 90))
            p.drawEllipse(QRectF(tx - 1.6, ty - 1.6, 3.2, 3.2))

        # 旋转弧
        pen = QPen(QColor(255, 255, 255, 235), 2.5)
        pen.setCapStyle(Qt.RoundCap)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        rr = r_base + 3
        p.drawArc(QRectF(cx - rr, cy - rr, 2 * rr, 2 * rr),
                  int((t * 260) % 360 * 16), 105 * 16)

        # v7.1：反向细弧（双引擎转动感）
        pen_r = QPen(QColor(*self._brand["particle_mid"], 170), 1.6)
        pen_r.setCapStyle(Qt.RoundCap)
        p.setPen(pen_r)
        rr2 = r_base + 8.5
        p.drawArc(QRectF(cx - rr2, cy - rr2, 2 * rr2, 2 * rr2),
                  int((360 - t * 150) % 360 * 16), 70 * 16)

    def _paint_glass_overlay(self, p, cx, cy, r):
        """v9.0 液态玻璃 + 微光：在思考球内部叠加旋转折射高光与一道循环扫掠亮带。"""
        t = self._t
        clip = QPainterPath()
        clip.addEllipse(QRectF(cx - r, cy - r, 2 * r, 2 * r))
        p.save()
        p.setClipPath(clip)
        # 旋转锥形折射高光
        cone = QConicalGradient(cx, cy, (math.degrees(t * 0.6)) % 360)
        cone.setColorAt(0.0, QColor(255, 255, 255, 0))
        cone.setColorAt(0.12, QColor(255, 255, 255, 55))
        cone.setColorAt(0.28, QColor(255, 255, 255, 0))
        cone.setColorAt(0.62, QColor(255, 255, 255, 30))
        cone.setColorAt(0.80, QColor(255, 255, 255, 0))
        p.setBrush(QBrush(cone))
        p.setPen(Qt.NoPen)
        p.drawEllipse(QRectF(cx - r, cy - r, 2 * r, 2 * r))
        # 微光扫掠亮带
        sweep = (t * 90) % (2 * r + 80) - 40
        sg = QLinearGradient(cx - r + sweep - 28, cy - r,
                            cx - r + sweep + 28, cy + r)
        sg.setColorAt(0.0, QColor(255, 255, 255, 0))
        sg.setColorAt(0.5, QColor(255, 255, 255, 72))
        sg.setColorAt(1.0, QColor(255, 255, 255, 0))
        p.fillRect(QRectF(cx - r, cy - r, 2 * r, 2 * r), QBrush(sg))
        p.restore()

    def _paint_speaking(self, p, cx, cy, r_base):
        t = self._t

        # 旋转虚线弧
        pen = QPen(QColor(255, 255, 255, 220), 2)
        pen.setDashPattern([4, 5])
        pen.setCapStyle(Qt.RoundCap)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        rr = r_base + 4
        p.drawArc(QRectF(cx - rr, cy - rr, 2 * rr, 2 * rr),
                  int((t * 180) % 360 * 16), 360 * 16)

        # 三音浪均衡器（内圈三条弧，亮度依次起伏）
        for i in range(3):
            wave = 0.5 + 0.5 * math.sin(t * 5.0 + i * 1.9)
            alpha = int(90 + 150 * wave)
            pen2 = QPen(QColor(*self._brand["particle_mid"], alpha), 2.2)
            pen2.setCapStyle(Qt.RoundCap)
            p.setPen(pen2)
            rr2 = r_base - 3 - i * 2.5
            span = 40 + 30 * wave
            start = int((t * 120 + i * 120) % 360 * 16)
            p.drawArc(QRectF(cx - rr2, cy - rr2, 2 * rr2, 2 * rr2),
                      start, int(span * 16))

            # v7.1：峰值帽（音频表语言：瞬时上冲、缓慢下落的小白点）
            peak = self._peaks[i] if i < len(self._peaks) else 0.0
            if peak > 0.02:
                cap_r = 1.5 + 1.1 * peak
                cap_y = cy - rr2 * (0.62 + 0.38 * peak)
                cap_a = int(150 + 90 * peak)
                p.setPen(Qt.NoPen)
                p.setBrush(QColor(255, 255, 255, min(255, cap_a)))
                p.drawEllipse(QRectF(cx - cap_r, cap_y - cap_r,
                                     2 * cap_r, 2 * cap_r))

    def _draw_sparkle(self, p, cx, cy, r):
        path = QPainterPath()
        pts = []
        for i in range(8):
            ang = math.pi / 4.0 * i - math.pi / 2.0
            rad = r if i % 2 == 0 else r * 0.36
            pts.append(QPointF(cx + rad * math.cos(ang), cy + rad * math.sin(ang)))
        path.addPolygon(QPolygonF(pts))
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(255, 255, 255, 240))
        p.drawPath(path)

    # ------------------------------------------------------------------
    # 鼠标交互
    # ------------------------------------------------------------------
    def enterEvent(self, e):
        self._hover_target = 1.09
        self._reset_idle()

    def leaveEvent(self, e):
        self._hover_target = 1.0

    def mousePressEvent(self, e):
        self._drag_pos = None
        self._moved = False
        self._reset_idle()
        if e.button() == Qt.LeftButton:
            self._drag_pos = e.globalPos() - self.frameGeometry().topLeft()
            self._moved = False
            e.accept()

    def mouseMoveEvent(self, e):
        if self._drag_pos is not None and (e.buttons() & Qt.LeftButton):
            self._reset_idle()
            if (e.globalPos() - self._drag_pos - self.pos()).manhattanLength() > 4:
                self._moved = True
            self.move(e.globalPos() - self._drag_pos)
            e.accept()

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton:
            if self._moved:
                self.position_changed.emit(self.x(), self.y())
            else:
                self._ripple = 0.0
                self.clicked.emit()
            self._drag_pos = None

    def contextMenuEvent(self, e):
        self._menu.exec_(e.globalPos())
