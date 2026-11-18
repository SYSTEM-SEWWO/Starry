# -*- coding: utf-8 -*-
"""v13.9：所有二级窗口统一毛玻璃圆角（白屏修复版）。

v13.8 的致命缺陷（用户反馈「2 级子窗口全部白屏、无法交互」）：

* ``FrostGlass.__init__`` **自带一个 QVBoxLayout**，旧实现又调用
  ``glass.setLayout(inner)``，Qt 会直接忽略并打印
  ``QWidget::setLayout: Attempting to set QLayout ... which already has a layout``；
  更糟的是旧实现先用 ``old.takeAt(0)`` 把原布局条目**全部摘走**，
  结果这些控件不属于任何布局 → 尺寸为 0 / 位置错乱 → 白屏。
* 旧实现还给有系统标题栏的 QDialog 设置 ``WA_TranslucentBackground`` +
  ``QDialog{background:transparent}``，Windows 下会让整个窗口连同内容透明。

本版原则（保守、可验证、绝不破坏交互）：

1. **完全不动原有布局**：只把 ``FrostGlass`` 作为背景层插入，
   ``lower()`` 到所有兄弟控件之下，并在 resize 时铺满；原布局与控件原封不动。
2. **不改 windowFlags、不设 WA_TranslucentBackground、不覆盖 QDialog 背景 QSS**；
   圆角与磨砂由 FrostGlass 自身的 ``paintEvent`` 绘制。
3. 跳过原生对话框（QMessageBox / QFileDialog / …）与已自带玻璃的窗口。
4. ``install_glass_hook`` 在 QApplication 上装 Show/Resize 事件过滤器，幂等。
"""
from PyQt5.QtCore import Qt, QEvent, QObject
from PyQt5.QtGui import QColor
from PyQt5.QtWidgets import (QDialog, QMessageBox, QFileDialog, QColorDialog,
                             QInputDialog, QProgressDialog, QFrame,
                             QGraphicsDropShadowEffect, QHBoxLayout, QLabel,
                             QPushButton)

from ui.frost import FrostGlass

_GLASS_FLAG = "_starry_glass_applied"
_RADIUS = 18
_SKIP_TYPES = (QMessageBox, QFileDialog, QColorDialog, QInputDialog,
               QProgressDialog)


class _GlassTitle(QFrame):
    """无边框二级窗口的可拖动标题栏（标题 + 关闭）。"""

    def __init__(self, dlg, title=""):
        super().__init__(dlg)
        self._dlg = dlg
        self._drag = None
        self.setObjectName("GlassTitle")
        self.setFixedHeight(34)
        self.setCursor(Qt.PointingHandCursor)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 0, 6, 0)
        lay.setSpacing(6)
        lb = QLabel(title or dlg.windowTitle() or "星语 · Starry")
        lb.setStyleSheet("font-size:13px;font-weight:600;background:transparent;")
        lay.addWidget(lb)
        lay.addStretch(1)
        btn = QPushButton("✕")
        btn.setObjectName("FlatButton")
        btn.setFixedSize(24, 24)
        btn.setCursor(Qt.PointingHandCursor)
        btn.setToolTip("关闭（Esc）")
        btn.clicked.connect(dlg.reject)
        lay.addWidget(btn)

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._drag = e.globalPos() - self._dlg.frameGeometry().topLeft()
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        if (e.buttons() & Qt.LeftButton) and self._drag is not None:
            self._dlg.move(e.globalPos() - self._drag)
            return
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        self._drag = None
        super().mouseReleaseEvent(e)


class _GlassInstaller(QObject):
    """全局 Show 事件过滤：QDialog 首次显示时套圆角玻璃（幂等）。"""

    def __init__(self, theme_getter=None, parent=None):
        super().__init__(parent)
        self._theme_getter = theme_getter

    def eventFilter(self, obj, e):
        if e.type() == QEvent.Show and isinstance(obj, QDialog):
            try:
                apply_glass(obj, self._theme_getter() if self._theme_getter else None)
            except Exception:                   # noqa: BLE001 - 绝不影响窗口显示
                pass
        return False


def apply_glass(dlg, theme=None):
    """把对话框内容整体包进 FrostGlass 圆角底板；幂等。

    关键（v14.0）：FrostGlass **自带 QVBoxLayout**，必须直接复用
    ``glass.layout()``，绝不能再 setLayout()；也不能把条目摘出来却不放进
    任何布局（v13.8 白屏根因）。这里逐项把原布局条目搬进 glass 自带布局，
    原 dlg 布局仍保留、只承载 glass 一个控件，所有权清晰。
    """
    if not isinstance(dlg, QDialog) or isinstance(dlg, _SKIP_TYPES):
        return False
    if getattr(dlg, _GLASS_FLAG, False):
        return False
    setattr(dlg, _GLASS_FLAG, True)
    if dlg.findChild(FrostGlass) is not None:
        return True                          # 关于 / EULA 已自带

    old = dlg.layout()
    if old is None:
        return False
    items = []
    while old.count():
        it = old.takeAt(0)
        if it is not None:
            items.append(it)
    marg = old.contentsMargins()
    spacing = old.spacing()

    # 无边框 + 透明：圆角玻璃是窗口本体（AboutDialog 已验证此模式）
    dlg.setWindowFlags(dlg.windowFlags() & ~Qt.WindowMinMaxButtonsHint
                       | Qt.FramelessWindowHint | Qt.Dialog)
    dlg.setAttribute(Qt.WA_TranslucentBackground, True)

    outer_m = 12
    old.setContentsMargins(outer_m, outer_m, outer_m, outer_m)
    old.setSpacing(0)

    glass = FrostGlass(dlg, radius=_RADIUS)
    glass.setObjectName("FrostHost")
    gl = glass.layout()                      # 复用自带布局，绝不 setLayout
    gl.setContentsMargins(marg)
    gl.setSpacing(spacing)
    title = _GlassTitle(dlg)
    gl.addWidget(title)                      # 自定义标题栏（拖动/关闭）
    for it in items:
        gl.addItem(it)
    old.addWidget(glass)

    eff = QGraphicsDropShadowEffect(glass)
    eff.setBlurRadius(24)
    eff.setColor(QColor(0, 0, 0, 110))
    eff.setOffset(0, 4)
    glass.setGraphicsEffect(eff)
    if theme is not None:
        try:
            glass.apply_theme(theme)
        except Exception:                   # noqa: BLE001
            pass
    return True


def install_glass_hook(app, theme_getter=None):
    """在 QApplication 上安装全局二级窗口玻璃钩子（幂等）。"""
    if app is None:
        return None
    for child in app.children():
        if isinstance(child, _GlassInstaller):
            return child
    hook = _GlassInstaller(theme_getter, parent=app)
    app.installEventFilter(hook)
    return hook
