# -*- coding: utf-8 -*-
"""液态玻璃（Liquid Glass）组件库 —— v6 视觉语言，v7.1 动效增强。

设计原则：
    - 纯 QPainter 自绘 + QVariantAnimation 驱动，无外部资源、offscreen 可渲染
    - 玻璃四要素：半透明磨砂底 / 顶部高光 / 1px 亮边 / 环境光晕
    - 动效统一走 ui.theme 的 OutCubic 缓动令牌，时长 fast/base/slow
    - 四主题（light/sky/dark/sky_dark）全部适配，深色下玻璃最通透

组件：
    LiquidGlass   玻璃面板基座（容器；v7.1 新增 hover 光泽扫过 sheen）
    LiquidCard    玻璃卡片（hover 时光晕增强、微浮起、光泽扫过；点击亦有反馈）
    GlowOrb       流动光斑（仪表盘/对话框背景氛围；v7.1 新增上浮微光粒子）
    StatusDot     呼吸状态灯
    MetricRing    圆环指标（v7.1 进度弧头部新增流星尾光点）
    Sparkline     时序折线（面积渐变 + 绘制动画；v7.1 末端脉冲光圈）
    NumberRoll    数字滚动（QVariantAnimation 插值）
    liquid_dialog_qss(theme)   玻璃对话框全局 QSS
"""
import math

from PyQt5.QtCore import (QEasingCurve, QPointF, QRectF, Qt, QTimer,
                          QVariantAnimation, pyqtProperty)
from PyQt5.QtGui import (QBrush, QColor, QFont, QLinearGradient, QPainter,
                         QPainterPath, QPen, QRadialGradient)
from PyQt5.QtWidgets import QFrame, QLabel, QVBoxLayout, QWidget

from ui import theme as T


# ---------------------------------------------------------------------------
# 颜色工具
# ---------------------------------------------------------------------------
def _hex_to_rgb(h):
    h = (h or "#000000").lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    try:
        return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    except (ValueError, IndexError):
        return 0, 0, 0


def rgba(h, alpha):
    """'#rrggbb' + alpha(0~1) -> 'rgba(r, g, b, a)'"""
    r, g, b = _hex_to_rgb(h)
    return "rgba(%d, %d, %d, %d)" % (r, g, b, int(round(alpha * 255)))


def _mix(h1, h2, t):
    r1, g1, b1 = _hex_to_rgb(h1)
    r2, g2, b2 = _hex_to_rgb(h2)
    return QColor(int(r1 + (r2 - r1) * t), int(g1 + (g2 - g1) * t),
                  int(b1 + (b2 - b1) * t))


def _is_dark(theme):
    """判断深色主题（容器底色明度低）"""
    r, g, b = _hex_to_rgb(theme.get("container_bg", "#ffffff"))
    return (0.299 * r + 0.587 * g + 0.114 * b) < 110


# ---------------------------------------------------------------------------
# 动画辅助
# ---------------------------------------------------------------------------
def _val_anim(parent, start, end, dur, on_value, easing=QEasingCurve.OutCubic,
              handle=None):
    # parent 可能已被删除（如对话框关闭后延迟触发的级联动效）——
    # 此时创建 QVariantAnimation 会抛 RuntimeError，PyQt 未捕获即 abort，故防御
    try:
        anim = QVariantAnimation(parent)
    except RuntimeError:
        return None
    # 重触发前先停止旧动画（评审 P1-2：避免多动画竞争同一属性导致抖动/泄漏）
    if handle is not None:
        prev = getattr(parent, handle, None)
        if prev is not None and prev is not anim:
            try:
                prev.stop()
            except RuntimeError:
                pass
        setattr(parent, handle, anim)
    anim.setStartValue(float(start))
    anim.setEndValue(float(end))
    anim.setDuration(int(dur))
    anim.setEasingCurve(easing)
    anim.valueChanged.connect(on_value)
    anim.start(QVariantAnimation.DeleteWhenStopped)
    return anim


# ---------------------------------------------------------------------------
# 玻璃面板基座
# ---------------------------------------------------------------------------
class LiquidGlass(QFrame):
    """半透明磨砂玻璃容器（四主题自适应）。

    子类/使用者往里 addWidget 即可；圆角与内边距由 paintEvent 保证。
    """

    def __init__(self, parent=None, radius=None):
        super().__init__(parent)
        self._theme = T.get_theme(T.DEFAULT_THEME)
        self._radius = T.RADIUS_L if radius is None else radius
        self._glow = 0.0                      # 0..1 环境光晕强度
        self._sheen = -1.0                    # <0 无扫过；0..1 光泽位置
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 16, 18, 16)
        lay.setSpacing(10)

    # -- 主题 -------------------------------------------------------------
    def apply_theme(self, t):
        self._theme = t or self._theme
        self.update()

    # -- 光晕（hover / 强调） --------------------------------------------
    def get_glow(self):
        return self._glow

    def set_glow(self, v):
        self._glow = max(0.0, min(1.0, float(v)))
        self.update()

    glow = pyqtProperty(float, fget=get_glow, fset=set_glow)

    def animate_glow(self, target, dur=None):
        _val_anim(self, self._glow, target,
                  dur or T.DUR_BASE, self.set_glow, handle="_anim")

    # -- 光泽扫过（v7.1：hover / 点击时一道斜向高光扫过玻璃表面） ----------
    def get_sheen(self):
        return self._sheen

    def set_sheen(self, v):
        v = float(v)
        if v >= 1.0:
            # 扫完即消（位置已在可视区外，无需残留）
            self._sheen = -1.0
        else:
            self._sheen = max(-1.0, min(1.0, v))
        self.update()

    sheen = pyqtProperty(float, fget=get_sheen, fset=set_sheen)

    def animate_sheen(self, dur=None):
        """一道高光从左下扫到右上（旗舰玻璃的「手感」来源）"""
        _val_anim(self, 0.0, 1.0, dur or T.DUR_BASE, self.set_sheen,
                  handle="_anim")

    # -- 绘制 -------------------------------------------------------------
    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        path = QPainterPath()
        path.addRoundedRect(r, self._radius, self._radius)
        p.setClipPath(path)

        dark = _is_dark(self._theme)
        # 1) 磨砂底
        base = QColor(self._theme["title_bg"])
        base.setAlphaF(0.86 if dark else 0.94)
        p.fillPath(path, base)
        # 2) 顶部高光（模拟光源在上的玻璃）
        hl = QLinearGradient(0, 0, 0, self.height() * 0.55)
        top = QColor(255, 255, 255, 70 if dark else 120)
        bottom = QColor(255, 255, 255, 0)
        hl.setColorAt(0.0, top)
        hl.setColorAt(1.0, bottom)
        p.fillPath(path, hl)
        # 3) 环境光晕（主题色，随 glow 强度）
        if self._glow > 0.01:
            gr, gg, gb = _hex_to_rgb(self._theme["accent"])
            halo = QRadialGradient(self.width() * 0.5, -self.height() * 0.25,
                                   self.width() * 0.85)
            halo.setColorAt(0.0, QColor(gr, gg, gb,
                                        int(46 * self._glow)))
            halo.setColorAt(1.0, QColor(gr, gg, gb, 0))
            p.fillPath(path, halo)
        # 3.5) 光泽扫过（v7.1：一道斜向高光带，从左下向右上扫过）
        if 0.0 <= self._sheen < 1.0:
            band = max(24.0, self.width() * 0.28)
            x0 = -band + self._sheen * (self.width() + band * 2)
            sheen_g = QLinearGradient(x0 - band, self.height(),
                                      x0 + band, 0)
            peak = 44 if dark else 62
            sheen_g.setColorAt(0.0, QColor(255, 255, 255, 0))
            sheen_g.setColorAt(0.5, QColor(255, 255, 255, peak))
            sheen_g.setColorAt(1.0, QColor(255, 255, 255, 0))
            p.fillPath(path, sheen_g)
        # 4) 亮边 + 描边
        edge = QPen()
        if dark:
            edge.setColor(QColor(255, 255, 255, 40 + int(60 * self._glow)))
        else:
            edge.setColor(_mix(self._theme["border"],
                               self._theme["accent"], 0.35 * self._glow))
        edge.setWidthF(1.0)
        p.setPen(edge)
        p.drawPath(path)
        p.end()
        super().paintEvent(e)


# ---------------------------------------------------------------------------
# 玻璃卡片（hover 浮起 + 光晕）
# ---------------------------------------------------------------------------
class LiquidCard(LiquidGlass):
    """可交互玻璃卡片：hover 时主题色光晕渐亮、光泽扫过；点击亦有反馈"""

    def __init__(self, parent=None, radius=None):
        super().__init__(parent, radius or T.RADIUS_M)
        self.setCursor(Qt.PointingHandCursor)
        self._hover = False
        self._anim = None                     # 单一动画句柄（review P1-2）

    def enterEvent(self, e):
        self._hover = True
        self.animate_glow(1.0, T.DUR_FAST)
        self.animate_sheen(T.DUR_SLOW)
        super().enterEvent(e)

    def leaveEvent(self, e):
        self._hover = False
        self.animate_glow(0.0, T.DUR_FAST)
        super().leaveEvent(e)

    def mousePressEvent(self, e):
        # 点击反馈：补一道快光泽（hover 带来的慢光泽可能已扫完）
        self.animate_sheen(T.DUR_FAST)
        super().mousePressEvent(e)


# ---------------------------------------------------------------------------
# 流动光斑（背景氛围）
# ---------------------------------------------------------------------------
class GlowOrb(QWidget):
    """慢速流动的主题色光斑（两个错位 radial gradient + 呼吸缩放）。

    作为对话框/仪表盘的最底层背景，制造「液态」流动感；
    30fps 自绘，CPU 占用可忽略。v7.1 新增上浮微光粒子（motes）。
    """

    def __init__(self, parent=None, colors=None):
        super().__init__(parent)
        self._theme = T.get_theme(T.DEFAULT_THEME)
        self._colors = colors                  # 覆盖色（默认用主题 accent 系）
        self._phase = 0.0
        # 微光粒子：x 相位 / 初相 / 速度 / 半径（确定性伪随机，免 random 依赖）
        self._motes = [((i * 37 % 100) / 100.0,
                        i * 1.31,
                        0.010 + (i % 4) * 0.0035,
                        0.8 + (i % 3) * 0.45) for i in range(9)]
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setAutoFillBackground(False)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(33)

    def apply_theme(self, t):
        self._theme = t or self._theme
        self.update()

    def _tick(self):
        if not self.isVisible():          # 评审 P1-3：隐藏即停重绘，杜绝空转
            return
        self._phase += 0.012
        if self._phase > 1e6:
            self._phase = 0.0
        self.update()

    def paintEvent(self, e):
        if self.width() <= 0 or self.height() <= 0:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        w, h = self.width(), self.height()
        dark = _is_dark(self._theme)
        base_alpha = 90 if dark else 55
        c1 = _hex_to_rgb(self._theme["accent"])
        c2 = _hex_to_rgb(self._theme.get("accent_2") or self._theme["accent"])
        blobs = [
            (0.30 + 0.10 * math.sin(self._phase),
             0.25 + 0.08 * math.cos(self._phase * 1.3),
             0.42 + 0.05 * math.sin(self._phase * 0.7), c1),
            (0.72 + 0.08 * math.cos(self._phase * 0.9),
             0.62 + 0.10 * math.sin(self._phase * 1.1),
             0.36 + 0.06 * math.cos(self._phase * 0.8), c2),
        ]
        for fx, fy, fr, (r, g, b) in blobs:
            grad = QRadialGradient(w * fx, h * fy, max(w, h) * fr)
            grad.setColorAt(0.0, QColor(r, g, b, base_alpha))
            grad.setColorAt(0.55, QColor(r, g, b, base_alpha // 3))
            grad.setColorAt(1.0, QColor(r, g, b, 0))
            p.fillRect(self.rect(), grad)
        # 上浮微光粒子（细白光点，缓慢上升 + 左右摇曳 + 上下边缘渐隐）
        mr, mg, mb = _hex_to_rgb(self._theme["accent_2"])
        for fx, ph, speed, r0 in self._motes:
            my = (0.92 - (self._phase * speed + ph * 0.11)) % 1.0
            mx = fx + 0.015 * math.sin(self._phase * 0.9 + ph)
            fade = math.sin(math.pi * my)
            alpha = int(60 * fade * (0.6 + 0.4 * dark))
            if alpha <= 2:
                continue
            rr = r0 * (0.7 + 0.5 * fade) * 3.0
            mote = QRadialGradient(w * mx, h * my, max(2.0, rr))
            mote.setColorAt(0.0, QColor(255, 255, 255, alpha))
            mote.setColorAt(0.4, QColor(mr, mg, mb, alpha // 2))
            mote.setColorAt(1.0, QColor(mr, mg, mb, 0))
            p.setPen(Qt.NoPen)
            p.setBrush(QBrush(mote))
            p.drawEllipse(QPointF(w * mx, h * my), max(2.0, rr), max(2.0, rr))
        p.end()


# ---------------------------------------------------------------------------
# 呼吸状态灯
# ---------------------------------------------------------------------------
class StatusDot(QWidget):
    """状态灯：online / limited / error / unconfigured / busy

    呼吸动画（透明度 0.5↔1.0 循环），颜色随状态。
    """

    COLORS = {
        "online": None,          # 运行时取 accent
        "limited": "#f5a623",
        "error": None,           # 运行时取 danger
        "unconfigured": None,    # 运行时取 muted
        "busy": None,            # 运行时取 accent_2
    }

    def __init__(self, parent=None, size=10):
        super().__init__(parent)
        self._theme = T.get_theme(T.DEFAULT_THEME)
        self._status = "unconfigured"
        self._pulse = 1.0
        self._size = size
        self.setFixedSize(size + 6, size + 6)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._t0 = 0.0
        self._timer.start(60)

    def apply_theme(self, t):
        self._theme = t or self._theme
        self.update()

    def set_status(self, status):
        self._status = status
        self.update()

    def _tick(self):
        if not self.isVisible():          # 评审 P1-3：隐藏即停重绘
            return
        self._t0 += 0.06
        self._pulse = 0.72 + 0.28 * (0.5 + 0.5 * math.sin(self._t0))
        self.update()

    def _color(self):
        s = self._status
        if s == "online":
            return self._theme["accent"]
        if s == "limited":
            return "#f5a623"
        if s == "error":
            return self._theme["danger"]
        if s == "busy":
            return self._theme["accent_2"]
        return self._theme["muted"]

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        c = self._color()
        cx, cy = self.width() / 2.0, self.height() / 2.0
        r = self._size / 2.0
        # 外圈光晕
        halo = QRadialGradient(cx, cy, r * 2.4)
        hr, hg, hb = _hex_to_rgb(c)
        halo.setColorAt(0.0, QColor(hr, hg, hb, int(110 * self._pulse)))
        halo.setColorAt(1.0, QColor(hr, hg, hb, 0))
        p.fillRect(self.rect(), halo)
        # 实心点
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(c))
        p.drawEllipse(QRectF(cx - r, cy - r, r * 2, r * 2))
        p.end()


# ---------------------------------------------------------------------------
# 圆环指标
# ---------------------------------------------------------------------------
class MetricRing(QWidget):
    """圆环进度指标（中间文字），数值变化时动画扫过"""

    def __init__(self, parent=None, size=86, thickness=8):
        super().__init__(parent)
        self._theme = T.get_theme(T.DEFAULT_THEME)
        self._value = 0.0
        self._target = 0.0
        self._text = ""
        self._sub = ""
        self._size = size
        self._th = thickness
        self.setFixedSize(size, size)

    def apply_theme(self, t):
        self._theme = t or self._theme
        self.update()

    def set_value(self, value, text=None, sub=None, animate=True):
        self._target = max(0.0, min(1.0, float(value or 0)))
        if text is not None:
            self._text = text
        if sub is not None:
            self._sub = sub
        if animate:
            _val_anim(self, self._value, self._target, T.DUR_SLOW,
                      self._on_anim, handle="_anim")
        else:
            self._value = self._target
            self.update()

    def _on_anim(self, v):
        self._value = float(v)
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        side = min(self.width(), self.height())
        rect = QRectF((self.width() - side) / 2 + self._th / 2 + 1,
                      (self.height() - side) / 2 + self._th / 2 + 1,
                      side - self._th - 2, side - self._th - 2)
        # 底环
        pen = QPen(QColor(self._theme["border"]))
        pen.setWidth(self._th)
        pen.setCapStyle(Qt.RoundCap)
        p.setPen(pen)
        p.drawArc(rect, 0, 360 * 16)
        # 进度弧（渐变）
        if self._value > 0.001:
            grad = QLinearGradient(rect.topLeft(), rect.bottomRight())
            grad.setColorAt(0.0, QColor(self._theme["accent"]))
            grad.setColorAt(1.0, QColor(self._theme["accent_2"]))
            pen.setBrush(grad)
            p.setPen(pen)
            p.drawArc(rect, 90 * 16, int(-self._value * 360 * 16))
            # v7.1：头部流星尾光点（白核 + 主题色晕）
            ang = math.radians(90.0 - self._value * 360.0)
            rcx, rcy = rect.center().x(), rect.center().y()
            rad = rect.width() / 2.0
            hx = rcx + rad * math.cos(ang)
            hy = rcy - rad * math.sin(ang)
            hr, hg, hb = _hex_to_rgb(self._theme["accent_2"])
            head = QRadialGradient(hx, hy, self._th * 1.15)
            head.setColorAt(0.0, QColor(255, 255, 255, 240))
            head.setColorAt(0.45, QColor(hr, hg, hb, 210))
            head.setColorAt(1.0, QColor(hr, hg, hb, 0))
            p.setPen(Qt.NoPen)
            p.setBrush(QBrush(head))
            p.drawEllipse(QRectF(hx - self._th * 1.15, hy - self._th * 1.15,
                                 self._th * 2.3, self._th * 2.3))
        # 中心文字
        if self._text:
            p.setPen(QColor(self._theme["text"]))
            f = QFont()
            f.setPixelSize(int(side * 0.22))
            f.setBold(True)
            p.setFont(f)
            p.drawText(QRectF(0, side * 0.30, self.width(), side * 0.26),
                       Qt.AlignCenter, self._text)
        if self._sub:
            p.setPen(QColor(self._theme["muted"]))
            f2 = QFont()
            f2.setPixelSize(max(9, int(side * 0.11)))
            p.setFont(f2)
            p.drawText(QRectF(0, side * 0.56, self.width(), side * 0.2),
                       Qt.AlignCenter, self._sub)
        p.end()


# ---------------------------------------------------------------------------
# 时序折线
# ---------------------------------------------------------------------------
class Sparkline(QWidget):
    """分钟级请求量/延迟折线：面积渐变 + 末端圆点 + 从左到右绘制动画"""

    def __init__(self, parent=None, height=96):
        super().__init__(parent)
        self._theme = T.get_theme(T.DEFAULT_THEME)
        self._points = []               # [{"t","n","lat"}]
        self._progress = 1.0
        self._metric = "n"
        self._noise = 0.0               # 末端点脉冲相位
        self.setMinimumHeight(height)
        # 末端脉冲：200ms 轻量时钟（仅画完时刷新，避免无谓重绘）
        self._pulse_timer = QTimer(self)
        self._pulse_timer.timeout.connect(self._pulse_tick)
        self._pulse_timer.start(200)

    def _pulse_tick(self):
        if not self.isVisible():          # 评审 P1-3：隐藏即停重绘
            return
        if self._points and self._progress > 0.98:
            self._noise += 0.6
            self.update()

    def apply_theme(self, t):
        self._theme = t or self._theme
        self.update()

    def set_data(self, points, metric="n"):
        self._points = points or []
        self._metric = metric
        self._progress = 0.0
        _val_anim(self, 0.0, 1.0, T.DUR_SLOW, self._on_anim, handle="_anim")

    def _on_anim(self, v):
        self._progress = float(v)
        self.update()

    def paintEvent(self, e):
        if not self._points:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        w, h = self.width(), self.height()
        pad_l, pad_r, pad_t, pad_b = 6, 6, 8, 8
        vals = [float(pt.get(self._metric, 0) or 0) for pt in self._points]
        vmax = max(vals) if vals else 0
        if vmax <= 0:
            vmax = 1
        n = len(vals)
        xs = [pad_l + (w - pad_l - pad_r) * (i / float(n - 1))
              for i in range(n)] if n > 1 else [w / 2]
        ys = [h - pad_b - (h - pad_t - pad_b) * (v / vmax) for v in vals]

        # 横向参考线（三条虚线）
        pen = QPen(QColor(self._theme["border"]))
        pen.setWidthF(0.8)
        pen.setDashPattern([3, 4])
        p.setPen(pen)
        for frac in (0.25, 0.55, 0.85):
            y = int(pad_t + (h - pad_t - pad_b) * frac)
            p.drawLine(pad_l, y, w - pad_r, y)

        # 按进度裁剪绘制
        clip_w = int(w * self._progress)
        p.save()
        p.setClipRect(0, 0, clip_w, h)
        # 折线
        line_pen = QPen(QColor(self._theme["accent"]))
        line_pen.setWidthF(2.0)
        line_pen.setJoinStyle(Qt.RoundJoin)
        p.setPen(line_pen)
        path = QPainterPath()
        path.moveTo(xs[0], ys[0])
        for i in range(1, n):
            path.lineTo(xs[i], ys[i])
        p.drawPath(path)
        # 面积
        area = QPainterPath(path)
        area.lineTo(xs[-1], h - pad_b)
        area.lineTo(xs[0], h - pad_b)
        area.closeSubpath()
        ag = QLinearGradient(0, pad_t, 0, h - pad_b)
        ar, ag_, ab = _hex_to_rgb(self._theme["accent"])
        ag.setColorAt(0.0, QColor(ar, ag_, ab, 70))
        ag.setColorAt(1.0, QColor(ar, ag_, ab, 0))
        p.fillPath(area, ag)
        # 末端点（v7.1：双层脉冲光圈）
        if self._progress > 0.98:
            ex, ey = xs[-1], ys[-1]
            pulse = 0.72 + 0.28 * math.sin(self._noise)
            p.setPen(Qt.NoPen)
            halo = QRadialGradient(ex, ey, 9.0)
            hr, hg, hb = _hex_to_rgb(self._theme["accent"])
            halo.setColorAt(0.0, QColor(hr, hg, hb, int(90 * pulse)))
            halo.setColorAt(1.0, QColor(hr, hg, hb, 0))
            p.setBrush(QBrush(halo))
            p.drawEllipse(QRectF(ex - 9, ey - 9, 18, 18))
            p.setBrush(QColor(self._theme["accent"]))
            p.drawEllipse(QRectF(ex - 3.2, ey - 3.2, 6.4, 6.4))
        p.restore()
        p.end()


# ---------------------------------------------------------------------------
# 数字滚动
# ---------------------------------------------------------------------------
class NumberRoll(QLabel):
    """数值变化时平滑滚动到目标值（而非瞬跳）"""

    def __init__(self, parent=None, text="0"):
        super().__init__(text, parent)
        self._theme = T.get_theme(T.DEFAULT_THEME)
        self._value = 0.0
        self._fmt = lambda v: "%.0f" % v
        f = self.font()
        f.setBold(True)

    def apply_theme(self, t):
        self._theme = t or self._theme
        self.update()

    def set_fmt(self, fmt):
        self._fmt = fmt
        self.refresh()

    def set_target(self, value, animate=True):
        value = float(value or 0)
        if not animate:
            self._value = value
            self.refresh()
            return
        _val_anim(self, self._value, value, T.DUR_BASE, self._on_anim,
                  handle="_anim")

    def _on_anim(self, v):
        self._value = float(v)
        self.refresh()

    def refresh(self):
        self.setText(self._fmt(self._value))


# ---------------------------------------------------------------------------
# 玻璃对话框 QSS
# ---------------------------------------------------------------------------
def liquid_dialog_qss(theme):
    """玻璃质感对话框全局样式（配合 LiquidGlass 容器使用）"""
    fs = 13
    return """
    QDialog { background-color: %(bg)s; }
    QWidget#GlassHost { background-color: %(bg)s; border-radius: %(radius)dpx; }
    QLabel { color: %(text)s; background: transparent; }
    QLabel#MutedLabel { color: %(muted)s; }
    QLabel#GlassTitle { font-size: %(fs)dpx; font-weight: bold; color: %(text)s; }
    QLabel#MetricValue { font-size: 20px; font-weight: bold; color: %(accent)s; }
    QLabel#MetricLabel { font-size: 11px; color: %(muted)s; }
    QLabel#ChipText { color: %(muted)s; font-size: 11px; }
    QPushButton {
        background-color: %(glass)s; color: %(text)s;
        border: 1px solid %(border)s; border-radius: %(r_s)dpx;
        padding: 5px 12px;
    }
    QPushButton:hover { border: 1px solid %(accent)s; color: %(accent)s; }
    QPushButton:pressed { background-color: %(hover)s; }
    QPushButton#AccentButton {
        background-color: %(accent)s; color: %(on_dark)s; border: none;
    }
    QPushButton#AccentButton:hover { background-color: %(accent_2)s; }
    QPushButton#FlatButton { background: transparent; border: none; color: %(muted)s; }
    QPushButton#FlatButton:hover { color: %(accent)s; }
    QPushButton#DangerButton {
        background: transparent; border: 1px solid %(danger)s; color: %(danger)s;
    }
    QLineEdit, QComboBox {
        background-color: %(glass)s; color: %(text)s;
        border: 1px solid %(border)s; border-radius: %(r_s)dpx; padding: 4px 8px;
    }
    QLineEdit:focus { border: 1px solid %(accent)s; }
    QComboBox::drop-down { border: none; width: 16px; }
    QComboBox QAbstractItemView {
        background-color: %(title)s; border: 1px solid %(border)s;
        selection-background-color: %(accent)s; selection-color: %(on_dark)s;
    }
    QListWidget {
        background-color: %(glass)s; border: 1px solid %(border)s;
        border-radius: %(r_s)dpx; color: %(text)s; outline: none;
    }
    QListWidget::item { padding: 6px 8px; border-radius: %(r_s)dpx; }
    QListWidget::item:selected { background-color: %(accent_soft)s; color: %(text)s; }
    QScrollBar:vertical { background: transparent; width: 8px; margin: 0; }
    QScrollBar::handle:vertical {
        background: %(border)s; border-radius: 4px; min-height: 32px;
    }
    QScrollBar::handle:vertical:hover { background: %(accent)s; }
    QScrollBar::add-line, QScrollBar::sub-line { height: 0; }
    QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }
    QToolTip {
        color: %(text)s; background-color: %(title)s;
        border: 1px solid %(border)s; padding: 4px 6px;
    }
    """ % {
        "bg": theme["container_bg"], "text": theme["text"],
        "muted": theme["muted"], "accent": theme["accent"],
        "accent_2": theme["accent_2"], "accent_soft": theme["accent_soft"],
        "border": theme["border"], "hover": theme["hover"],
        "danger": theme["danger"], "title": theme["title_bg"],
        "glass": rgba(theme["title_bg"], 0.55),
        "on_dark": theme["on_dark"],
        "radius": T.RADIUS_L, "r_s": T.RADIUS_S,
        "fs": fs,
    }
