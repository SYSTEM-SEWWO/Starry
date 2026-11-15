# -*- coding: utf-8 -*-
"""v13.8：所有二级窗口（设置 / 会话 / 缓存 / 关于等）统一毛玻璃圆角。

低侵入、可反复调用、绝不破坏原有布局与交互：

* ``apply_glass(dlg, theme=None)`` 把对话框已有布局里的**全部条目**搬进一个
  ``FrostGlass`` 圆角底板（真实磨砂模糊 + 顶部高光 + 1px 亮边 + 投影），
  原有控件、布局、信号、按钮盒全部保留，所有权不发生转移冲突。
* 保留系统标题栏与原生关闭/移动能力（不设 FramelessWindowHint），因此
  ``exec_()``、Esc、QDialogButtonBox 等既有行为零回归。
* 已经自带玻璃（关于 / EULA / 网关）或原生对话框（QMessageBox /
  QFileDialog / QColorDialog / QInputDialog）跳过，避免二次包裹。
* ``install_glass_hook(app, theme_getter)`` 在 QApplication 上装 Show 事件
  过滤器，任何 QDialog 首次显示时自动应用 —— 覆盖未来新增的窗口。
"""
from PyQt5.QtCore import Qt, QEvent, QObject
from PyQt5.QtGui import QColor
from PyQt5.QtWidgets import (QDialog, QGraphicsDropShadowEffect, QVBoxLayout,
                             QMessageBox, QFileDialog, QColorDialog,
                             QInputDialog, QProgressDialog)

from ui.frost import FrostGlass

_GLASS_FLAG = "_starry_glass_applied"
_RADIUS = 18
_SKIP_TYPES = (QMessageBox, QFileDialog, QColorDialog, QInputDialog,
               QProgressDialog)


class _GlassInstaller(QObject):
    """全局 Show 事件过滤：任何 QDialog 首次显示即套玻璃。"""

    def __init__(self, theme_getter=None, parent=None):
        super().__init__(parent)
        self._theme_getter = theme_getter

    def eventFilter(self, obj, e):
        if e.type() == QEvent.Show and isinstance(obj, QDialog):
            try:
                t = self._theme_getter() if self._theme_getter else None
                apply_glass(obj, t)
            except Exception:                   # noqa: BLE001 - 绝不影响窗口显示
                pass
        return False


def apply_glass(dlg, theme=None):
    """把对话框内容包进圆角毛玻璃底板；幂等，可重复调用。返回是否应用。"""
    if not isinstance(dlg, QDialog) or isinstance(dlg, _SKIP_TYPES):
        return False
    if getattr(dlg, _GLASS_FLAG, False):
        return False
    old = dlg.layout()
    if old is None:
        return False
    if dlg.findChild(FrostGlass) is not None:
        # 已有自己的毛玻璃（关于 / EULA / 网关）→ 只补投影，不二次包裹
        setattr(dlg, _GLASS_FLAG, True)
        _add_shadow(dlg.findChild(FrostGlass))
        return True

    setattr(dlg, _GLASS_FLAG, True)

    # 1) 逐项摘出原有布局内容（所有权清晰，不触发 Qt 的 layout 冲突）
    items = []
    while old.count():
        it = old.takeAt(0)
        if it is not None:
            items.append(it)
    margins = old.contentsMargins()
    spacing = old.spacing()

    # 2) 对话框本身透明，留出投影空间
    dlg.setAttribute(Qt.WA_TranslucentBackground, True)
    dlg.setStyleSheet(
        (dlg.styleSheet() or "") +
        "\nQDialog{background:transparent;border:none;}"
        "\nQDialog > FrostGlass{border-radius:%dpx;}" % _RADIUS)
    old.setContentsMargins(10, 10, 10, 12)
    old.setSpacing(0)

    # 3) 圆角毛玻璃底板
    glass = FrostGlass(dlg, radius=_RADIUS)
    glass.setObjectName("FrostHost")
    inner = QVBoxLayout()
    inner.setContentsMargins(margins)
    inner.setSpacing(spacing)
    for it in items:
        inner.addItem(it)
    glass.setLayout(inner)
    old.addWidget(glass)
    _add_shadow(glass)

    if theme is not None:
        try:
            glass.apply_theme(theme)
        except Exception:                       # noqa: BLE001
            pass
    return True


def _add_shadow(widget):
    try:
        eff = QGraphicsDropShadowEffect(widget)
        eff.setBlurRadius(24)
        eff.setColor(QColor(0, 0, 0, 96))
        eff.setOffset(0, 3)
        widget.setGraphicsEffect(eff)
    except Exception:                           # noqa: BLE001
        pass


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
