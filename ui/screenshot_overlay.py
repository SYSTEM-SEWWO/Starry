# -*- coding: utf-8 -*-
"""全屏区域截图选择器（仿微信/QQ 截图）。

- 覆盖整个虚拟桌面，压暗背景，框选区域镂空
- 拖动选择，Esc / 右键取消，双击选择整屏
- 松开鼠标后通过 QScreen.grabWindow 抓取选区
"""
from PyQt5.QtCore import Qt, QRectF, QPoint, pyqtSignal
from PyQt5.QtGui import QGuiApplication, QPainter, QColor, QPen, QFont
from PyQt5.QtWidgets import QWidget, QApplication

from ui.theme import brand


class ScreenshotOverlay(QWidget):
    """全屏截图遮罩。captured(QImage) / cancelled() 二选一。"""

    captured = pyqtSignal(object)     # QImage
    cancelled = pyqtSignal()

    DIM_ALPHA = 100

    def __init__(self, parent=None, theme=None):
        super().__init__(parent)
        self._b = brand(theme)        # 选区画笔色随主题切换
        desktop = QApplication.desktop()
        self._virtual_geo = desktop.geometry()
        self.setGeometry(self._virtual_geo)
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint
                            | Qt.Tool | Qt.X11BypassWindowManagerHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setCursor(Qt.CrossCursor)
        self.setMouseTracking(True)

        self._origin = None            # 按下点（全局坐标）
        self._current = None           # 当前点（全局坐标）
        self._screen = None            # 按下时所在的屏幕
        self._selected = QRectF()

    # ------------------------------------------------------------------
    def _norm_rect(self):
        if self._origin is None or self._current is None:
            return QRectF()
        r = QRectF(self._origin, self._current).normalized()
        # 限制在按下时所在屏幕内（跨屏时以起始屏为准）
        if self._screen is not None:
            g = self._screen.geometry()
            r = r.intersected(QRectF(g))
        return r

    # ------------------------------------------------------------------
    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._origin = e.globalPos()
            self._current = self._origin
            self._screen = QGuiApplication.screenAt(self._origin) \
                or QGuiApplication.primaryScreen()
            e.accept()
        elif e.button() == Qt.RightButton:
            self.cancelled.emit()
            self.close()

    def mouseMoveEvent(self, e):
        if self._origin is not None:
            self._current = e.globalPos()
            self._selected = self._norm_rect()
            self.update()

    def mouseDoubleClickEvent(self, e):
        # 双击 = 选择整个屏幕
        if self._screen is None:
            self._screen = QGuiApplication.screenAt(e.globalPos()) \
                or QGuiApplication.primaryScreen()
        g = self._screen.geometry()
        self._selected = QRectF(g)
        self._capture()

    def mouseReleaseEvent(self, e):
        if e.button() != Qt.LeftButton or self._origin is None:
            return
        self._current = e.globalPos()
        self._selected = self._norm_rect()
        if self._selected.width() < 6 or self._selected.height() < 6:
            # 视为单击：取消
            self.cancelled.emit()
            self.close()
            return
        self._capture()

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Escape:
            self.cancelled.emit()
            self.close()

    # ------------------------------------------------------------------
    def _capture(self):
        r = self._selected
        if r.width() < 1 or r.height() < 1:
            self.cancelled.emit()
            self.close()
            return
        g = self._screen.geometry()
        pix = self._screen.grabWindow(
            0, int(r.x()) - g.x(), int(r.y()) - g.y(),
            int(r.width()), int(r.height()))
        self.hide()
        img = pix.toImage()
        self.captured.emit(img)
        self.close()

    # ------------------------------------------------------------------
    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)

        # 1) 压暗整个桌面
        p.fillRect(self.rect(), QColor(0, 0, 0, self.DIM_ALPHA))

        # 2) 选区镂空（露出桌面）
        if not self._selected.isNull() and self._selected.width() > 0:
            p.setCompositionMode(QPainter.CompositionMode_Clear)
            p.fillRect(self._selected, Qt.transparent)
            p.setCompositionMode(QPainter.CompositionMode_SourceOver)

            # 3) 选区边框 + 四角
            pen = QPen(QColor(self._b["main"]), 2)
            p.setPen(pen)
            p.setBrush(Qt.NoBrush)
            p.drawRect(self._selected)

            corner = 14
            p.setPen(QPen(QColor("#ffffff"), 3))
            r = self._selected
            for cx, cy, dx, dy in (
                (r.left(), r.top(), 1, 1), (r.right(), r.top(), -1, 1),
                (r.left(), r.bottom(), 1, -1), (r.right(), r.bottom(), -1, -1)):
                p.drawLine(QPoint(int(cx), int(cy)), QPoint(int(cx + dx * corner), int(cy)))
                p.drawLine(QPoint(int(cx), int(cy)), QPoint(int(cx), int(cy + dy * corner)))

            # 4) 尺寸提示
            label = "%d × %d" % (int(r.width()), int(r.height()))
            f = QFont()
            f.setPixelSize(13)
            p.setFont(f)
            tw = p.fontMetrics().width(label) + 14
            th = 24
            lx = int(r.left())
            ly = int(r.top()) - th - 6
            if ly < 2:
                ly = int(r.top()) + 6
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(20, 22, 30, 220))
            p.drawRoundedRect(QRectF(lx, ly, tw, th), 6, 6)
            p.setPen(QColor("#e8e9ee"))
            p.drawText(QRectF(lx, ly, tw, th), Qt.AlignCenter, label)

        # 5) 顶部操作提示
        hint = "拖动选择截图区域 · 双击选择整屏 · Esc 取消"
        f = QFont()
        f.setPixelSize(14)
        p.setFont(f)
        tw = p.fontMetrics().width(hint) + 28
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(20, 22, 30, 210))
        p.drawRoundedRect(QRectF(self.width() / 2 - tw / 2, 18, tw, 34), 8, 8)
        p.setPen(QColor("#e8e9ee"))
        p.drawText(QRectF(self.width() / 2 - tw / 2, 18, tw, 34),
                   Qt.AlignCenter, hint)
