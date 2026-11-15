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
from PyQt5.QtWidgets import (QDialog, QMessageBox, QFileDialog, QColorDialog,
                             QInputDialog, QProgressDialog)

from ui.frost import FrostGlass

_GLASS_FLAG = "_starry_glass_applied"
_RADIUS = 18
_SKIP_TYPES = (QMessageBox, QFileDialog, QColorDialog, QInputDialog,
               QProgressDialog)


class _Backdrop(FrostGlass):
    """只做背景绘制的 FrostGlass 子类：不吃鼠标、不抢焦点、不拦截子控件。"""

    def __init__(self, parent):
        super().__init__(parent, radius=_RADIUS)
        self.setObjectName("GlassBackdrop")
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setFocusPolicy(Qt.NoFocus)
        self.lower()

    def mousePressEvent(self, e):
        e.ignore()

    def mouseMoveEvent(self, e):
        e.ignore()

    def _grab(self):
        """背景层是子控件：``frameGeometry()`` 是相对父窗口的坐标，
        直接抓屏会抓到屏幕左上角错误区域。这里强制使用无屏依赖的
        faux 渐变玻璃（与主窗口 offscreen 降级路径一致），视觉统一且零风险。
        """
        self._bg = None
        self._faux = True
        self.update()


class _GlassInstaller(QObject):
    """全局 Show/Resize 事件过滤：任何 QDialog 首次显示即套玻璃。"""

    def __init__(self, theme_getter=None, parent=None):
        super().__init__(parent)
        self._theme_getter = theme_getter
        self._watched = set()

    def eventFilter(self, obj, e):
        try:
            if not isinstance(obj, QDialog):
                return False
            if e.type() == QEvent.Show:
                t = self._theme_getter() if self._theme_getter else None
                if apply_glass(obj, t):
                    self._watched.add(id(obj))
            elif e.type() == QEvent.Resize and id(obj) in self._watched:
                _fit_backdrop(obj)
        except Exception:                   # noqa: BLE001 - 绝不影响窗口显示
            pass
        return False


def _fit_backdrop(dlg):
    bd = dlg.findChild(_Backdrop, "GlassBackdrop")
    if bd is not None:
        bd.setGeometry(0, 0, dlg.width(), dlg.height())
        bd.lower()


def apply_glass(dlg, theme=None):
    """给对话框加圆角毛玻璃背景；**不改动任何原有布局/控件**。返回是否应用。"""
    if not isinstance(dlg, QDialog) or isinstance(dlg, _SKIP_TYPES):
        return False
    if getattr(dlg, _GLASS_FLAG, False):
        return False
    setattr(dlg, _GLASS_FLAG, True)
    if dlg.findChild(FrostGlass) is not None:
        return True                      # 关于/EULA/网关已自带玻璃

    bd = _Backdrop(dlg)
    bd.setGeometry(0, 0, dlg.width(), dlg.height())
    bd.lower()
    if theme is not None:
        try:
            bd.apply_theme(theme)
        except Exception:                   # noqa: BLE001
            pass
    bd.show()
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
