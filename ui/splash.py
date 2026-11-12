# -*- coding: utf-8 -*-
"""开屏动画：液态玻璃风格「旋转 → 合并 → 浮现」—— v7.3 资深动态升级。

叙事（分镜）：
  0.00 深空极光淡入 + 多层视差星尘（不同景深漂移）
  0.10 三枚半透明玻璃珠绕中心旋转（锥形渐变光泽流动）
  0.50 玻璃珠螺旋汇聚、融合为一颗液态玻璃球（冲击涟漪 + 星尘迸发）
  0.72 合并球浮现 ✦ 标志（多层 bloom 光晕）+ 高光弧扫过
  0.86 标题「逐字 kinetic」上升淡入 + 流光扫过；副标题渐显
  全程 底部「微光进度条」+ 循环状态微文案（装配中…）
  结尾 整体淡出，交棒悬浮球。点击任意处立即跳过。

交互：任意点击立即跳过。纯 QPainter 程序化绘制，无外部资源；字体走
      ui.theme.GLOBAL_FONT 回退链（雅黑 / 苹方 / Noto CJK），避免跨平台方块。
"""
import math

from PyQt5.QtCore import (Qt, QTimer, QPointF, QRectF, pyqtSignal,
                          QVariantAnimation, QEasingCurve, QRect)
from PyQt5.QtGui import (QPainter, QColor, QRadialGradient, QConicalGradient,
                         QLinearGradient, QPen, QBrush, QPainterPath,
                         QPolygonF, QFont)
from PyQt5.QtWidgets import QWidget, QApplication

from ui.theme import brand, GLOBAL_FONT

DURATION_MS = 3000          # 主动画时长（略延长，留给分镜呼吸）
FADE_MS = 460               # 淡出时长

# 字体回退：取 GLOBAL_FONT 首选家族（缺失时 Qt 用 SansSerif 回退含 CJK）
_FONT_FAMILY = GLOBAL_FONT.split(",")[0].strip().strip('"')


def _font(size, weight=QFont.DemiBold):
    f = QFont(_FONT_FAMILY, size)
    f.setWeight(weight)
    f.setStyleHint(QFont.SansSerif)        # 缺失首选字体时仍能渲染 CJK
    return f


def _ease_in_out_cubic(t):
    return 4 * t * t * t if t < 0.5 else 1 - (-2 * t + 2) ** 3 / 2


def _ease_out_cubic(t):
    return 1 - (1 - t) ** 3


def _ease_out_back(t):
    c1, c3 = 1.70158, 2.70158
    return 1 + c3 * (t - 1) ** 3 + c1 * (t - 1) ** 2


def _clamp(v, lo=0.0, hi=1.0):
    return max(lo, min(hi, v))


class SplashWindow(QWidget):
    """全屏开屏动画。finished 信号发出后由主程序接管。"""

    finished = pyqtSignal()

    def __init__(self, screen=None, parent=None, theme=None):
        super().__init__(parent)
        self._b = brand(theme)      # 品牌渐变色（随主题切换）
        self.setWindowFlags(Qt.FramelessWindowHint
                            | Qt.WindowStaysOnTopHint
                            | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setCursor(Qt.PointingHandCursor)

        screen = screen or (QApplication.primaryScreen()
                            if QApplication.instance() else None)
        geo = screen.availableGeometry() if screen else None
        if geo is not None:
            self.setGeometry(geo)
        else:
            self.resize(1280, 800)

        self._progress = 0.0
        self._clock = 0.0
        self._fading_out = False
        self._finished_emitted = False
        self._anim = None
        self._fade_anim = None

        # 视差星尘：景深 depth 决定大小/亮度/漂移速度（远小近大）
        self._dust = []
        for i in range(46):
            depth = (i * 37 % 100) / 100.0
            self._dust.append({
                "x": (i * 89 % 100) / 100.0,
                "y": (i * 53 % 100) / 100.0,
                "depth": depth,
                "r": 0.6 + depth * 2.6,
                "phase": i * 0.91,
                "speed": 0.004 + depth * 0.020,
            })

        # 极光团（缓慢漂移的大色块）
        self._blobs = [
            (0.30, 0.32, self._b["main"], 0.17),
            (0.70, 0.60, self._b["aux"], 0.15),
            (0.52, 0.82, self._b["deep"], 0.09),
            (0.16, 0.74, self._b["aux"], 0.06),
        ]

        self._status_lines = [
            "正在装配智能体内核 …",
            "正在挂载 21 家大模型服务商 …",
            "正在校准液态玻璃材质 …",
            "正在点亮桌面伙伴 …",
        ]

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(33)

    # ------------------------------------------------------------------
    # 动画控制
    # ------------------------------------------------------------------
    def start(self):
        self._progress = 0.0
        self._anim = QVariantAnimation(self)
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(1.0)
        self._anim.setDuration(DURATION_MS)
        self._anim.setEasingCurve(QEasingCurve.InOutQuad)
        self._anim.valueChanged.connect(self._set_progress)
        self._anim.finished.connect(self._fade_out)
        self._anim.start()

    def _set_progress(self, v):
        self._progress = float(v)
        self.update()

    def _tick(self):
        self._clock += 0.033
        if self._progress > 0.82 or self._fading_out:
            self.update()

    def skip(self):
        """点击跳过"""
        if self._fading_out:
            return
        if self._anim is not None and self._anim.state() == QVariantAnimation.Running:
            self._anim.stop()
        self._set_progress(1.0)
        self._fade_out()

    def _fade_out(self):
        if self._fading_out:
            return
        self._fading_out = True
        self._set_progress(1.0)
        self._fade_anim = QVariantAnimation(self)
        self._fade_anim.setStartValue(1.0)
        self._fade_anim.setEndValue(0.0)
        self._fade_anim.setDuration(FADE_MS)
        self._fade_anim.setEasingCurve(QEasingCurve.OutCubic)
        self._fade_anim.valueChanged.connect(self.setWindowOpacity)
        self._fade_anim.finished.connect(self._emit_finished)
        self._fade_anim.start()

    def _emit_finished(self):
        if self._finished_emitted:
            return
        self._finished_emitted = True
        self._timer.stop()
        self.finished.emit()

    # ------------------------------------------------------------------
    # 绘制
    # ------------------------------------------------------------------
    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)

        w, h = self.width(), self.height()
        cx, cy = w / 2.0, h / 2.0
        t = self._progress

        self._paint_backdrop(p, w, h, cx, cy, t)
        if t < 0.78:
            self._paint_orbiting(p, cx, cy, t)
        else:
            self._paint_merged(p, cx, cy, t)
            if t > 0.86:
                self._paint_title(p, w, h, t)
        self._paint_progress(p, w, h, t)
        p.end()

    # ---------------- 背景：极光 + 视差星尘 + 暗角 ----------------
    def _paint_backdrop(self, p, w, h, cx, cy, t):
        p.fillRect(0, 0, w, h, QColor(*self._b["bg"]))

        appear = _clamp(t / 0.15)
        # 极光团（缓慢漂移）
        for i, (fx, fy, col, a) in enumerate(self._blobs):
            drift = 0.02 * math.sin(self._clock * 0.4 + i * 2.1)
            g = QRadialGradient(w * (fx + drift), h * (fy - drift),
                                max(w, h) * 0.42)
            c = QColor(col)
            c.setAlpha(int(255 * a * appear))
            g.setColorAt(0.0, c)
            c2 = QColor(col)
            c2.setAlpha(0)
            g.setColorAt(1.0, c2)
            p.setPen(Qt.NoPen)
            p.setBrush(QBrush(g))
            p.drawEllipse(QPointF(w * (fx + drift), h * (fy - drift)),
                          max(w, h) * 0.42, max(w, h) * 0.42)

        # 视差星尘（景深：远小慢暗、近大快亮）
        for d in self._dust:
            dy = (d["y"] - self._clock * d["speed"]) % 1.0
            dx = d["x"] + 0.012 * math.sin(self._clock * 0.8 + d["phase"])
            a = int((26 + 70 * d["depth"]) * appear
                    * (0.5 + 0.5 * math.sin(d["phase"] + self._clock)))
            a = max(0, a)
            rr = d["r"] * (0.7 + 0.3 * math.sin(self._clock + d["phase"]))
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(255, 255, 255, a))
            p.drawEllipse(QPointF(w * dx, h * dy), rr, rr)
        p.setBrush(Qt.NoBrush)

        # 聚焦柔光
        glow = QRadialGradient(cx, cy, min(w, h) * 0.40)
        gc = QColor(*self._b["glow"])
        glow.setColorAt(0.0, QColor(gc.red(), gc.green(), gc.blue(),
                                    int(46 * appear)))
        glow.setColorAt(0.35, QColor(gc.red(), gc.green(), gc.blue(),
                                     int(22 * appear)))
        glow.setColorAt(0.65, QColor(gc.red(), gc.green(), gc.blue(),
                                     int(8 * appear)))
        glow.setColorAt(1.0, QColor(gc.red(), gc.green(), gc.blue(), 0))
        p.setBrush(QBrush(glow))
        p.drawEllipse(QPointF(cx, cy), min(w, h) * 0.40, min(w, h) * 0.40)

        # 暗角（vignette，聚焦中心）
        vig = QRadialGradient(cx, cy, min(w, h) * 0.62)
        vig.setColorAt(0.55, QColor(0, 0, 0, 0))
        vig.setColorAt(1.0, QColor(0, 0, 0, int(120 * appear)))
        p.setBrush(QBrush(vig))
        p.fillRect(QRect(0, 0, w, h), QBrush(vig))
        p.setBrush(Qt.NoBrush)

    # ---------------- 阶段一/二：旋转 + 合并 ----------------
    def _paint_orbiting(self, p, cx, cy, t):
        spin_t = _clamp((t - 0.10) / 0.45)
        merge_t = _clamp((t - 0.50) / 0.28)
        merge_e = _ease_in_out_cubic(merge_t)

        base_r = min(self.width(), self.height()) * 0.085
        orbit_r = min(self.width(), self.height()) * (0.16 - 0.10 * merge_e)
        orb_r = base_r * (1.0 + 0.55 * merge_e)

        if merge_t > 0.02:
            ripple_t = (t - 0.50) / 0.5
            if 0 < ripple_t < 1:
                rr = orb_r * (1.2 + 2.6 * ripple_t)
                alpha = int(110 * (1 - ripple_t))
                p.setPen(QPen(QColor(*self._b["particle"], max(0, alpha)), 2.2))
                p.setBrush(Qt.NoBrush)
                p.drawEllipse(QRectF(cx - rr, cy - rr, 2 * rr, 2 * rr))

        if 0.02 < merge_t < 0.85:
            dust_t = _ease_out_cubic(min(1.0, merge_t / 0.55))
            for k in range(12):
                ang = k * (math.pi / 6.0) + 0.35
                dd = orb_r * (0.5 + 2.4 * dust_t)
                px = cx + dd * math.cos(ang)
                py = cy + dd * math.sin(ang)
                a = int(170 * (1.0 - merge_t / 0.85))
                if a <= 3:
                    continue
                dr = 1.7 * (1.0 - merge_t / 0.85) + 0.4
                p.setPen(Qt.NoPen)
                p.setBrush(QColor(255, 255, 255, a))
                p.drawEllipse(QPointF(px, py), dr, dr)

        for i in range(3):
            ang = (spin_t * math.pi * 2.2) + i * (math.pi * 2 / 3)
            dist = orbit_r * (1 - merge_e)
            ox = cx + dist * math.cos(ang)
            oy = cy + dist * math.sin(ang)
            self._draw_glass_orb(p, ox, oy, orb_r,
                                 phase=self._clock * 1.4 + i * 1.7,
                                 scale_in=_clamp((t - 0.06) / 0.12),
                                 alpha=1.0)

        if merge_t > 0.92:
            self._paint_merged(p, cx, cy, 0.78)

    # ---------------- 阶段三：合并后的液态玻璃球 ----------------
    def _paint_merged(self, p, cx, cy, t):
        appear = _clamp((t - 0.78) / 0.12)
        pop = _ease_out_back(_clamp((t - 0.76) / 0.18))
        base_r = min(self.width(), self.height()) * 0.085
        r = base_r * (1.55 + 0.10 * math.sin(self._clock * 1.8)) * (0.6 + 0.4 * pop)

        # 外圈光环（呼吸）
        halo = QRadialGradient(cx, cy, r * 1.9)
        hc = QColor(*self._b["glow"], int(60 * appear))
        halo.setColorAt(0.0, hc)
        halo.setColorAt(1.0, QColor(*self._b["glow"], 0))
        p.setBrush(QBrush(halo))
        p.drawEllipse(QPointF(cx, cy), r * 1.9, r * 1.9)

        self._draw_glass_orb(p, cx, cy, r, phase=self._clock * 1.1,
                             scale_in=appear, alpha=appear)

        ring_t = _clamp((t - 0.78) / 0.28)
        if ring_t > 0:
            rr = r * (1.42 + 0.42 * _ease_out_cubic(ring_t))
            p.setPen(QPen(QColor(150, 175, 235,
                                 int(66 * (1 - 0.45 * ring_t) * appear)), 1.2))
            p.setBrush(Qt.NoBrush)
            p.drawEllipse(QPointF(cx, cy), rr, rr)

        sweep_t = _clamp((t - 0.80) / 0.12)
        if 0 < sweep_t < 1:
            ang = -math.pi * 0.85 + sweep_t * math.pi * 0.7
            pen = QPen(QColor(255, 255, 255, int(200 * math.sin(sweep_t * math.pi))), 3)
            pen.setCapStyle(Qt.RoundCap)
            p.setPen(pen)
            p.setBrush(Qt.NoBrush)
            rr = r * 0.86
            p.drawArc(QRectF(cx - rr, cy - rr, 2 * rr, 2 * rr),
                      int(ang / math.pi * 180 * 16), int(38 * 16))

        # ✦ 四角星（弹性进入 + 多层 bloom 光晕）
        star_t = _clamp((t - 0.84) / 0.14)
        if star_t > 0:
            s = _ease_out_back(star_t)
            star_alpha = int(245 * min(1.0, star_t * 1.4))
            # bloom：大柔光晕
            bloom = QRadialGradient(cx, cy, r * 1.15)
            bc = QColor(255, 255, 255, int(60 * min(1.0, star_t * 1.6)))
            bloom.setColorAt(0.0, bc)
            bc.setAlpha(0)
            bloom.setColorAt(1.0, bc)
            p.setBrush(QBrush(bloom))
            p.drawEllipse(QPointF(cx, cy), r * 1.15, r * 1.15)
            self._draw_sparkle(p, cx, cy, r * 0.44 * s, alpha=star_alpha)

    # ---------------- 玻璃珠 ----------------
    def _draw_glass_orb(self, p, cx, cy, r, phase=0.0, scale_in=1.0, alpha=1.0):
        if r <= 0 or scale_in <= 0:
            return
        r *= scale_in

        sh = QRadialGradient(cx, cy + r * 0.35, r * 1.3)
        sc = QColor(5, 8, 20, int(110 * alpha))
        sh.setColorAt(0.0, sc)
        sc.setAlpha(0)
        sh.setColorAt(1.0, sc)
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(sh))
        p.drawEllipse(QPointF(cx, cy + r * 0.35), r * 1.3, r * 1.0)

        body = QRadialGradient(cx - r * 0.30, cy - r * 0.38, r * 1.30)
        c0 = QColor(200, 218, 255, int(235 * alpha))
        c1 = QColor(self._b["light"])
        c1.setAlpha(int(215 * alpha))
        c2 = QColor(self._b["aux"])
        c2.setAlpha(int(225 * alpha))
        body.setColorAt(0.0, c0)
        body.setColorAt(0.45, c1)
        body.setColorAt(1.0, c2)
        p.setBrush(QBrush(body))
        p.drawEllipse(QPointF(cx, cy), r, r)

        cone = QConicalGradient(cx, cy, math.degrees(phase * 40) % 360)
        cone.setColorAt(0.0, QColor(255, 255, 255, int(70 * alpha)))
        cone.setColorAt(0.25, QColor(255, 255, 255, 0))
        cone.setColorAt(0.5, QColor(255, 255, 255, int(46 * alpha)))
        cone.setColorAt(0.75, QColor(255, 255, 255, 0))
        cone.setColorAt(1.0, QColor(255, 255, 255, int(70 * alpha)))
        p.setBrush(QBrush(cone))
        p.drawEllipse(QPointF(cx, cy), r, r)

        inner = QRadialGradient(cx, cy + r * 0.55, r * 0.95)
        ic = QColor(self._b["deep"])
        ic.setAlpha(int(120 * alpha))
        inner.setColorAt(0.0, ic)
        ic.setAlpha(0)
        inner.setColorAt(1.0, ic)
        p.setBrush(QBrush(inner))
        p.drawEllipse(QPointF(cx, cy), r, r)

        rim = QLinearGradient(cx - r, cy - r, cx + r, cy + r)
        rim.setColorAt(0.0, QColor(255, 255, 255, int(220 * alpha)))
        rim.setColorAt(0.45, QColor(255, 255, 255, int(40 * alpha)))
        rim.setColorAt(1.0, QColor(200, 215, 255, int(150 * alpha)))
        p.setPen(QPen(QBrush(rim), 1.6))
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(QPointF(cx, cy), r, r)

        hl = QRadialGradient(cx - r * 0.38, cy - r * 0.46, r * 0.55)
        hl.setColorAt(0.0, QColor(255, 255, 255, int(190 * alpha)))
        hl.setColorAt(1.0, QColor(255, 255, 255, 0))
        p.setBrush(QBrush(hl))
        p.drawEllipse(QPointF(cx - r * 0.38, cy - r * 0.46), r * 0.55, r * 0.42)

        hl2 = QRadialGradient(cx + r * 0.42, cy + r * 0.40, r * 0.20)
        hl2.setColorAt(0.0, QColor(255, 255, 255, int(70 * alpha)))
        hl2.setColorAt(1.0, QColor(255, 255, 255, 0))
        p.setBrush(QBrush(hl2))
        p.drawEllipse(QPointF(cx + r * 0.42, cy + r * 0.40), r * 0.20, r * 0.16)

    # ---------------- 文字（逐字 kinetic 上升淡入） ----------------
    def _paint_title(self, p, w, h, t):
        line_t = _clamp((t - 0.86) / 0.14)
        cy = h * 0.5 + min(w, h) * 0.085 + 66
        text = "星语 · Starry"
        p.setFont(_font(26))

        chars = list(text)
        n = len(chars)
        total_adv = 0.0
        advs = []
        for ch in chars:
            a = p.fontMetrics().horizontalAdvance(ch)
            advs.append(a)
            total_adv += a
        gap = 2
        total_adv += gap * (n - 1)
        x0 = w / 2.0 - total_adv / 2.0
        # 流光位置（随时间游走）
        sweep = (math.sin(self._clock * 0.9) + 1) / 2

        base = QColor(*self._b["title_base"], int(255 * line_t))
        hot = QColor(255, 255, 255, 255)
        x = x0
        for i, ch in enumerate(chars):
            # 逐字错峰上升 + 淡入
            delay = i * 0.05
            ct = _clamp((line_t - delay) / 0.5)
            e = _ease_out_cubic(ct)
            yoff = (1 - e) * 18
            alpha = int(255 * e)
            # 流光扫过该字时变亮
            char_center = (x + advs[i] / 2 - x0) / max(1.0, total_adv)
            d = abs(char_center - sweep)
            lit = max(0.0, 1.0 - d / 0.18)
            col = QColor(
                int(base.red() + (hot.red() - base.red()) * lit),
                int(base.green() + (hot.green() - base.green()) * lit),
                int(base.blue() + (hot.blue() - base.blue()) * lit),
                alpha)
            p.setPen(QPen(col, 1))
            p.drawText(QPointF(x, cy - yoff), ch)
            x += advs[i] + gap

        # 副标题（渐显）
        p.setFont(_font(13, QFont.Normal))
        sub = "液态玻璃 · 智能体 · 你的桌面伙伴"
        sw = p.fontMetrics().horizontalAdvance(sub)
        sc = QColor(*self._b["title_sub"], int(200 * line_t))
        p.setPen(QPen(sc, 1))
        p.drawText(QPointF(w / 2 - sw / 2, cy + 30), sub)

    # ---------------- 底部进度微光条 + 状态微文案 ----------------
    def _paint_progress(self, p, w, h, t):
        bar_w = min(w * 0.42, 420)
        bar_x = (w - bar_w) / 2.0
        bar_y = h * 0.5 + min(w, h) * 0.085 + 118
        bar_h = 4.0
        appear = _clamp(t / 0.1)
        if appear <= 0.01:
            return

        # 轨道
        track = QRectF(bar_x, bar_y, bar_w, bar_h)
        tp = QPainterPath()
        tp.addRoundedRect(track, bar_h / 2, bar_h / 2)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(255, 255, 255, int(26 * appear)))
        p.fillPath(tp, p.brush())

        # 填充（圆角裁切）
        fill_w = max(bar_h, bar_w * t)
        fp = QPainterPath()
        fp.addRoundedRect(QRectF(bar_x, bar_y, fill_w, bar_h),
                          bar_h / 2, bar_h / 2)
        p.setClipPath(fp)
        grad = QLinearGradient(bar_x, 0, bar_x + bar_w, 0)
        grad.setColorAt(0.0, QColor(self._b["main"]))
        grad.setColorAt(1.0, QColor(self._b["aux"]))
        p.setBrush(QBrush(grad))
        p.fillRect(QRectF(bar_x, bar_y, bar_w, bar_h), p.brush())
        # 游标微光
        if t < 0.999:
            shine = QRadialGradient(bar_x + fill_w, bar_y + bar_h / 2,
                                    bar_h * 2.4)
            shine.setColorAt(0.0, QColor(255, 255, 255, int(200 * appear)))
            shine.setColorAt(1.0, QColor(255, 255, 255, 0))
            p.setBrush(QBrush(shine))
            p.fillRect(QRectF(bar_x, bar_y - bar_h, bar_w, bar_h * 3), p.brush())
        p.setClipping(False)

        # 循环状态微文案
        if t < 0.86:
            idx = int(self._clock * 0.9) % len(self._status_lines)
            line = self._status_lines[idx]
            p.setFont(_font(11, QFont.Normal))
            mw = p.fontMetrics().horizontalAdvance(line)
            mc = QColor(*self._b["title_sub"], int(170 * appear))
            p.setPen(QPen(mc, 1))
            p.drawText(QPointF(w / 2 - mw / 2, bar_y + 22), line)

    def _draw_sparkle(self, p, cx, cy, r, alpha=245):
        if r <= 1:
            return
        path = QPainterPath()
        pts = []
        for i in range(8):
            ang = math.pi / 4.0 * i - math.pi / 2.0
            rad = r if i % 2 == 0 else r * 0.36
            pts.append(QPointF(cx + rad * math.cos(ang), cy + rad * math.sin(ang)))
        path.addPolygon(QPolygonF(pts))
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(255, 255, 255, alpha))
        p.drawPath(path)

    # ------------------------------------------------------------------
    def mousePressEvent(self, e):
        self.skip()
