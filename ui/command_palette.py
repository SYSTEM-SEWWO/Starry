# -*- coding: utf-8 -*-
"""命令面板（Ctrl+K）：Raycast / VSCode 式全局快捷入口。

- 居中无边框浮层，毛玻璃背景
- 顶部搜索框（实时过滤），下方命令列表（键盘 ↑↓ 选择，回车执行，Esc 关闭）
- 命令由控制器注册：(id, icon, 标题, 说明, 分组)
"""
from PyQt5.QtCore import Qt, pyqtSignal, QTimer
from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QLineEdit,
                             QListWidget, QListWidgetItem, QLabel, QWidget,
                             QApplication)


class CommandPalette(QDialog):
    """命令面板对话框"""

    command_triggered = pyqtSignal(str)      # 命令 id

    def __init__(self, commands, parent=None, theme=None):
        super().__init__(parent)
        self._commands = list(commands or [])
        self._theme = theme or {}
        self._filtered = list(self._commands)
        self.setWindowTitle("命令面板")
        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setModal(False)
        self._build_ui()
        self._reload("")
        # 自动聚焦搜索框（show 后）
        QTimer.singleShot(0, self.search.setFocus)

    # ------------------------------------------------------------------
    # ------------------------------------------------------------------
    def _accent_rgba(self, alpha=0.10):
        """把主题 accent 转为 rgba 字符串（hover 底色用）"""
        hexc = (self._theme.get("accent") or "#0b8bd8").lstrip("#")
        try:
            r, g, b = (int(hexc[i:i + 2], 16) for i in (0, 2, 4))
            return "rgba(%d,%d,%d,%.2f)" % (r, g, b, alpha)
        except Exception:
            return "rgba(11,139,216,0.10)"

    def apply_theme(self, theme):
        """主题热切换"""
        self._theme = theme or {}
        self.card.setStyleSheet(self._card_qss())
        self.search.setStyleSheet(
            "QLineEdit{background:transparent;border:none;color:%s;"
            "font-size:15px;padding:6px 4px;}"
            % self._theme.get("text", "#16293c"))
        self.list.setStyleSheet(
            "QListWidget{background:transparent;border:none;outline:0;}"
            "QListWidget::item{border-radius:8px;padding:7px 10px;color:%s;}"
            "QListWidget::item:selected{background-color:%s;color:#ffffff;}"
            "QListWidget::item:hover{background-color:%s;}"
            % (self._theme.get("text", "#16293c"),
               self._theme.get("accent", "#0b8bd8"), self._accent_rgba()))

    def _card_qss(self):
        return ("#PaletteCard{background-color:%s;border:1px solid %s;"
                "border-radius:14px;}"
                % (self._theme.get("title_bg", "#ffffff"),
                   self._theme.get("border", "#dbe7f3")))

    def _build_ui(self):
        t = self._theme

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        self.card = QWidget(self)
        self.card.setObjectName("PaletteCard")
        self.card.setStyleSheet(self._card_qss())
        lay = QVBoxLayout(self.card)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(8)

        self.search = QLineEdit()
        self.search.setPlaceholderText("搜索命令…  （↑↓ 选择 · Enter 执行 · Esc 关闭）")
        self.search.setStyleSheet(
            "QLineEdit{background:transparent;border:none;color:%s;"
            "font-size:15px;padding:6px 4px;}" % t.get("text", "#16293c"))
        self.search.textChanged.connect(self._reload)
        lay.addWidget(self.search)

        self.list = QListWidget()
        self.list.setStyleSheet(
            "QListWidget{background:transparent;border:none;outline:0;}"
            "QListWidget::item{border-radius:8px;padding:7px 10px;color:%s;}"
            "QListWidget::item:selected{background-color:%s;color:#ffffff;}"
            "QListWidget::item:hover{background-color:%s;}"
            % (t.get("text", "#16293c"), t.get("accent", "#0b8bd8"),
               self._accent_rgba()))
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.list.setFixedHeight(min(360, 56 * max(1, len(self._commands))))
        self.list.itemActivated.connect(lambda it: self._trigger(it))
        lay.addWidget(self.list)

        hint = QLabel("✨ 命令面板 · 让每个功能一键可达")
        hint.setStyleSheet("color:%s;font-size:11px;"
                           % t.get("muted", "#5b7086"))
        lay.addWidget(hint)

        outer.addWidget(self.card)
        self.setFixedWidth(520)
        self.setMinimumHeight(120)

        # 键盘：Enter 在列表焦点时触发；全局 Esc 关闭
        self.search.installEventFilter(self)

    # ------------------------------------------------------------------
    def _reload(self, text):
        q = (text or "").strip().lower()
        self._filtered = [c for c in self._commands
                          if not q or q in c[2].lower() or q in c[3].lower()
                          or q in c[4].lower()]
        self.list.clear()
        for cid, icon, title, sub, group in self._filtered:
            item = QListWidgetItem("%s  %s" % (icon, title))
            item.setToolTip("%s · %s" % (group, sub))
            item.setData(Qt.UserRole, cid)
            self.list.addItem(item)
        if self.list.count():
            self.list.setCurrentRow(0)
        self.list.setFixedHeight(min(360, 52 * max(1, self.list.count())))
        self.adjustSize()

    def _trigger(self, item):
        if item is None:
            return
        cid = item.data(Qt.UserRole)
        self.command_triggered.emit(cid)
        self.accept()

    def eventFilter(self, obj, ev):
        if obj is self.search and ev.type() == ev.KeyPress:
            key = ev.key()
            if key in (Qt.Key_Up, Qt.Key_Down):
                row = self.list.currentRow()
                n = self.list.count()
                if n:
                    row = (row + (-1 if key == Qt.Key_Up else 1)) % n
                    self.list.setCurrentRow(row)
                return True
            if key in (Qt.Key_Return, Qt.Key_Enter):
                self._trigger(self.list.currentItem())
                return True
        return super().eventFilter(obj, ev)

    def keyPressEvent(self, ev):
        if ev.key() == Qt.Key_Escape:
            self.reject()
            return
        super().keyPressEvent(ev)

    def showEvent(self, ev):
        super().showEvent(ev)
        # 居中于父窗口（或屏幕）
        if self.parent() is not None:
            geo = self.parent().geometry()
        else:
            geo = QApplication.desktop().availableGeometry()
        self.move(geo.center().x() - self.width() // 2,
                  max(geo.top() + 60,
                      geo.center().y() - self.height() // 2 - 40))
