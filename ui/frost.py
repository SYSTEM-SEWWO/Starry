# -*- coding: utf-8 -*-
"""真·毛玻璃（Frosted Glass）基底 —— v7.3 视觉语言核心。

设计目标（来自 v7.3 评审 P1-1「伪玻璃」修复）：
    - 抓取窗后像素 → 降采样 → 高斯模糊 → 圆角合成 → 叠加主题 tint
    - 玻璃四要素与液态玻璃一致：磨砂底 / 顶部高光 / 1px 亮边 / 环境光晕
    - offscreen / headless（自测、无显示器）自动降级为 faux 玻璃（渐变 + 微噪）
    - 不常驻定时器：仅在 show / resize / 移动「停稳」后防抖重抓一次
    - 提供 pause()/resume() 与可见性守卫，杜绝后台空转（评审 P1-3）

典型用法：
    glass = FrostGlass(radius=20, blur=22)
    lay = QVBoxLayout(glass)          # FrostGlass 自带 QVBoxLayout，直接复用
    ...
"""
import os

from PyQt5.QtCore import (Qt, QRectF, QTimer, pyqtProperty,
                          QByteArray, QBuffer, QIODevice)
from PyQt5.QtGui import (QColor, QPainter, QPainterPath, QPen,
                         QPixmap, QRadialGradient, QLinearGradient)
from PyQt5.QtWidgets import QApplication, QFrame, QVBoxLayout

from ui import theme as T
from ui.liquid import _is_dark, _hex_to_rgb

# 在 offscreen 平台无需抓屏，直接走 faux 降级（自测稳定、零意外）
_OFFSCREEN = os.environ.get("QT_QPA_PLATFORM", "") == "offscreen"

try:                                    # Pillow 在运行环境预装；缺失则仅用降采样柔化
    from PIL import Image, ImageFilter
    _HAVE_PIL = True
except Exception:                       # noqa: BLE001
    _HAVE_PIL = False


# ---------------------------------------------------------------------------
# 模糊辅助
# ---------------------------------------------------------------------------
def _blur_pixmap(pm, radius):
    """把抓到的屏幕图变「毛」：降采样(廉价) + 可选高斯模糊(更润)。

    降采样到 1/5 再以平滑变换放大，本身就产生柔化；PIL 在场时再叠一层
    高斯模糊，得到接近系统 acrylic/mica 的质感。全部只发生一次（show/停稳后）。
    """
    w, h = pm.width(), pm.height()
    if w <= 0 or h <= 0:
        return pm
    small = pm.scaled(max(1, w // 5), max(1, h // 5),
                      Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
    if _HAVE_PIL and radius > 0:
        try:
            ba = QByteArray()
            buf = QBuffer(ba)
            buf.open(QIODevice.WriteOnly)
            small.save(buf, "PNG")
            buf.close()
            im = Image.open(__import__("io").BytesIO(ba.data())).convert("RGBA")
            im = im.filter(ImageFilter.GaussianBlur(max(1.0, radius / 2.2)))
            out = QPixmap()
            ba2 = QByteArray()
            buf2 = QBuffer(ba2)
            buf2.open(QIODevice.WriteOnly)
            # Pillow → QPixmap 通过内存 PNG 往返，跨版本最稳
            from io import BytesIO as _BS
            tmp = _BS()
            im.save(tmp, format="PNG")
            out.loadFromData(QByteArray(tmp.getvalue()))
            if not out.isNull():
                return out
        except Exception:              # noqa: BLE001
            pass
    return small


# ---------------------------------------------------------------------------
# 毛玻璃基底
# ---------------------------------------------------------------------------
class FrostGlass(QFrame):
    """半透明磨砂玻璃容器（真实 backdrop-blur 版液态玻璃）。

    子类/使用者往里 addWidget / setLayout 即可；圆角与内边距由 paintEvent 保证。
    与 LiquidGlass 的区别：LiquidGlass 是「轻量伪玻璃」（内层小组件用，无抓屏，
    零成本）；FrostGlass 是「真实毛玻璃」（顶层对话框/窗口用，抓取并模糊窗后）。
    """

    def __init__(self, parent=None, radius=None, blur=22, tint_alpha=None):
        super().__init__(parent)
        self._theme = T.get_theme(T.DEFAULT_THEME)
        self._radius = radius if radius is not None else T.RADIUS_L
        self._blur = int(blur)
        self._tint_alpha = tint_alpha       # None → 跟随主题自动选
        self._glow = 0.0
        self._bg = None                     # 缓存的模糊后背景 QPixmap
        self._faux = False                  # 是否走了降级
        self._paused = False
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 16, 18, 16)
        lay.setSpacing(10)
        # 防抖重抓（show/resize 立即；移动停稳后一次）
        self._refresh = QTimer(self)
        self._refresh.setSingleShot(True)
        self._refresh.timeout.connect(self._grab)

    # -- 主题 -------------------------------------------------------------
    def apply_theme(self, t):
        self._theme = t or self._theme
        self._regrab()

    def set_radius(self, r):
        self._radius = int(r)
        self.update()

    # -- 光晕（hover / 强调，与 LiquidGlass 同语言） -----------------------
    def get_glow(self):
        return self._glow

    def set_glow(self, v):
        self._glow = max(0.0, min(1.0, float(v)))
        self.update()

    glow = pyqtProperty(float, fget=get_glow, fset=set_glow)

    # -- 暂停 / 恢复（避免隐藏时后台抓屏空转） -----------------------------
    def pause(self):
        self._paused = True
        self._refresh.stop()

    def resume(self):
        self._paused = False
        if self.isVisible():
            self._regrab()

    def setVisible(self, v):
        super().setVisible(v)
        if v:
            self._regrab()
        else:
            self._refresh.stop()

    # -- 几何变化 → 防抖重抓 ------------------------------------------------
    def showEvent(self, e):
        super().showEvent(e)
        self._regrab()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._regrab(immediate=True)

    def moveEvent(self, e):
        super().moveEvent(e)
        self._regrab(immediate=False)      # 移动中只重置计时，停稳后才抓

    def _regrab(self, immediate=False):
        if self._paused or not self.isVisible():
            return
        if _OFFSCREEN:
            self._bg = None
            self._faux = True
            self.update()
            return
        self._refresh.start(40 if immediate else 150)

    def _grab(self):
        try:
            if self._paused or not self.isVisible():
                return
            geo = self.frameGeometry()
            x, y, w, h = geo.x(), geo.y(), geo.width(), geo.height()
            if w <= 0 or h <= 0:
                raise RuntimeError("invalid geometry")
            screen = self.screen()
            if screen is None:
                screen = QApplication.primaryScreen()
            if screen is None:
                raise RuntimeError("no screen")
            pm = screen.grabWindow(0, x, y, w, h)
            if pm.isNull() or pm.width() == 0:
                raise RuntimeError("null grab")
            self._bg = _blur_pixmap(pm, self._blur)
            self._faux = False
        except Exception:                  # noqa: BLE001
            self._bg = None
            self._faux = True
        self.update()

    # -- 绘制 -------------------------------------------------------------
    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        path = QPainterPath()
        path.addRoundedRect(r, self._radius, self._radius)
        p.setClipPath(path)

        if self._bg is not None and not self._bg.isNull():
            p.drawPixmap(self.rect(), self._bg, self._bg.rect())
        else:
            self._paint_faux(p, self.rect())

        dark = _is_dark(self._theme)
        alpha = self._tint_alpha
        if alpha is None:
            alpha = 0.52 if dark else 0.60
        # 磨砂 tint（极轻，让窗后内容透出来 → 真·毛玻璃）
        base = QColor(self._theme["title_bg"])
        base.setAlphaF(alpha)
        p.fillPath(path, base)

        # 顶部高光（光源在上的玻璃）
        hl = QLinearGradient(0, 0, 0, self.height() * 0.55)
        top = QColor(255, 255, 255, 70 if dark else 118)
        bottom = QColor(255, 255, 255, 0)
        hl.setColorAt(0.0, top)
        hl.setColorAt(1.0, bottom)
        p.fillPath(path, hl)

        # 底部内阴影（增强玻璃厚度/纵深感 —— 液态玻璃关键细节，v7.5 美术复审落地）
        sh = QLinearGradient(0, self.height() * 0.62, 0, self.height())
        sh.setColorAt(0.0, QColor(0, 0, 0, 0))
        sh.setColorAt(1.0, QColor(0, 0, 0, 26 if dark else 14))
        p.fillPath(path, sh)

        # 环境光晕（主题色，随 glow 强度）
        if self._glow > 0.01:
            gr, gg, gb = _hex_to_rgb(self._theme["accent"])
            halo = QRadialGradient(self.width() * 0.5, -self.height() * 0.25,
                                   self.width() * 0.85)
            halo.setColorAt(0.0, QColor(gr, gg, gb, int(46 * self._glow)))
            halo.setColorAt(1.0, QColor(gr, gg, gb, 0))
            p.fillPath(path, halo)

        # 1px 亮边 + 描边
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

    def _paint_faux(self, p, rect):
        """降级玻璃：主题色竖向渐变 + 两枚柔和色团，保证无屏环境也好看。"""
        dark = _is_dark(self._theme)
        base = QColor(self._theme["title_bg"])
        base.setAlphaF(0.96 if dark else 0.98)
        p.fillRect(rect, base)
        gr, gg, gb = _hex_to_rgb(self._theme["accent"])
        blobs = [(0.28, 0.18, 0.30), (0.74, 0.72, 0.26)]
        for fx, fy, fr in blobs:
            g = QRadialGradient(rect.width() * fx, rect.height() * fy,
                                max(rect.width(), rect.height()) * fr)
            g.setColorAt(0.0, QColor(gr, gg, gb, 40 if dark else 28))
            g.setColorAt(1.0, QColor(gr, gg, gb, 0))
            p.fillRect(rect, g)


def _mix(h1, h2, t):
    r1, g1, b1 = _hex_to_rgb(h1)
    r2, g2, b2 = _hex_to_rgb(h2)
    return QColor(int(r1 + (r2 - r1) * t), int(g1 + (g2 - g1) * t),
                  int(b1 + (b2 - b1) * t))
