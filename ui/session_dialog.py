# -*- coding: utf-8 -*-
"""会话管理对话框：搜索 / 新建 / 重命名 / 删除 / 置顶 / 切换 / 导出。

- 双击或点击「切换」载入对应会话
- 导出由主程序完成（emit export_requested）
"""
import time

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel,
                             QPushButton, QScrollArea, QWidget, QFrame,
                             QLineEdit, QInputDialog, QMessageBox, QComboBox)

from ui.theme import build_qss, get_theme


def _fmt_time(ts):
    if not ts:
        return ""
    d = time.localtime(ts)
    today = time.localtime()
    if d[:3] == today[:3]:
        return "今天 %02d:%02d" % (d[3], d[4])
    return "%d-%02d-%02d %02d:%02d" % (d[0], d[1], d[2], d[3], d[4])


class SessionRow(QFrame):
    """单个会话行"""

    switched = pyqtSignal(str)
    renamed = pyqtSignal(str)
    deleted = pyqtSignal(str)
    pinned = pyqtSignal(str, bool)
    tags_changed = pyqtSignal(str)            # V11.2：编辑标签

    def __init__(self, info, is_current, theme, font_size, parent=None):
        super().__init__(parent)
        self.info = info
        self._theme = theme
        self._fs = font_size
        self.setObjectName("SessionRow")
        self._build_ui(is_current)
        self._apply_theme(theme, font_size)

    def _build_ui(self, is_current):
        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 7, 8, 7)
        lay.setSpacing(6)

        text_col = QVBoxLayout()
        text_col.setSpacing(2)
        self.title_label = QLabel(("📌 " if self.info.get("pinned") else "")
                                  + self.info.get("title", "未命名"))
        tags = self.info.get("tags") or []
        tagtxt = (" · " + " ".join("#" + t for t in tags)) if tags else ""
        self.meta_label = QLabel("%s · %d 条消息%s%s"
                                 % (_fmt_time(self.info.get("updated")),
                                    self.info.get("count", 0),
                                    " · 当前" if is_current else "",
                                    tagtxt))
        self.meta_label.setObjectName("MutedLabel")
        text_col.addWidget(self.title_label)
        text_col.addWidget(self.meta_label)
        # V11.1：检索时展示命中摘要片段（search_ranked 附带 snippet）
        snippet = self.info.get("snippet")
        if snippet:
            self.snippet_label = QLabel(snippet.replace("⚡", ""))
            self.snippet_label.setObjectName("MutedLabel")
            self.snippet_label.setWordWrap(True)
            text_col.addWidget(self.snippet_label)

        self.open_btn = QPushButton("打开" if not is_current else "✓ 当前")
        self.open_btn.setObjectName("AccentButton" if not is_current
                                    else "FlatButton")
        self.open_btn.setCursor(Qt.PointingHandCursor)
        self.open_btn.setFixedHeight(26)
        self.open_btn.clicked.connect(
            lambda: self.switched.emit(self.info["id"]))

        self.rename_btn = QPushButton("✎")
        self.rename_btn.setObjectName("FlatButton")
        self.rename_btn.setToolTip("重命名")
        self.rename_btn.setCursor(Qt.PointingHandCursor)
        self.rename_btn.setFixedSize(26, 26)
        self.rename_btn.clicked.connect(
            lambda: self.renamed.emit(self.info["id"]))

        self.tag_btn = QPushButton("🏷")
        self.tag_btn.setObjectName("FlatButton")
        self.tag_btn.setToolTip("编辑标签")
        self.tag_btn.setCursor(Qt.PointingHandCursor)
        self.tag_btn.setFixedSize(26, 26)
        self.tag_btn.clicked.connect(
            lambda: self.tags_changed.emit(self.info["id"]))

        self.pin_btn = QPushButton("📌" if not self.info.get("pinned") else "📍")
        self.pin_btn.setObjectName("FlatButton")
        self.pin_btn.setToolTip("置顶 / 取消置顶")
        self.pin_btn.setCursor(Qt.PointingHandCursor)
        self.pin_btn.setFixedSize(26, 26)
        self.pin_btn.clicked.connect(
            lambda: self.pinned.emit(self.info["id"],
                                     not self.info.get("pinned")))

        self.del_btn = QPushButton("🗑")
        self.del_btn.setObjectName("FlatButton")
        self.del_btn.setToolTip("删除会话")
        self.del_btn.setCursor(Qt.PointingHandCursor)
        self.del_btn.setFixedSize(26, 26)
        self.del_btn.clicked.connect(self._confirm_delete)

        lay.addLayout(text_col, 1)
        lay.addWidget(self.open_btn)
        lay.addWidget(self.rename_btn)
        lay.addWidget(self.tag_btn)
        lay.addWidget(self.pin_btn)
        lay.addWidget(self.del_btn)

    def _confirm_delete(self):
        ret = QMessageBox.question(
            self, "删除会话",
            "确定删除会话「%s」吗？其中的 %d 条消息将一并删除，且不可恢复。"
            % (self.info.get("title"), self.info.get("count", 0)),
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if ret == QMessageBox.Yes:
            self.deleted.emit(self.info["id"])

    def _apply_theme(self, theme, font_size):
        self._theme = theme
        self._fs = font_size
        self.setStyleSheet(
            "QFrame#SessionRow{background-color:%s;border:1px solid %s;"
            "border-radius:10px;}"
            % (theme["bubble_ai_bg"], theme["border"]))
        self.title_label.setStyleSheet(
            "color:%s;font-weight:bold;" % theme["text"])
        self.meta_label.setStyleSheet("color:%s;" % theme["muted"])


class SessionDialog(QDialog):
    """会话管理主对话框"""

    session_selected = pyqtSignal(str)     # 切换会话
    export_requested = pyqtSignal()        # 导出当前对话

    def __init__(self, store, config, parent=None):
        super().__init__(parent)
        self.store = store
        self.cfg = config
        self._theme = get_theme(config.appearance.get("theme", "light"))
        self._fs = int(config.appearance.get("font_size", 14))
        self.setStyleSheet(build_qss(self._theme, self._fs))
        self.setWindowTitle("会话管理")
        self.setMinimumWidth(520)
        self.setMinimumHeight(480)
        self._build_ui()
        self._reload()

    # ------------------------------------------------------------------
    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setSpacing(8)

        top = QHBoxLayout()
        title = QLabel("💬 会话管理")
        title.setStyleSheet("font-size:%dpx;font-weight:bold;"
                            % (self._fs + 4))
        top.addWidget(title)
        top.addStretch(1)
        self.new_btn = QPushButton("＋ 新建会话")
        self.new_btn.setObjectName("AccentButton")
        self.new_btn.setCursor(Qt.PointingHandCursor)
        self.new_btn.clicked.connect(self._on_new)
        top.addWidget(self.new_btn)
        root.addLayout(top)

        search_row = QHBoxLayout()
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("搜索会话标题或内容 …")
        self.search_edit.textChanged.connect(self._reload)
        search_row.addWidget(self.search_edit, 1)
        # V11.2：标签筛选
        self.tag_combo = QComboBox()
        self.tag_combo.setMinimumWidth(120)
        self.tag_combo.setCursor(Qt.PointingHandCursor)
        self.tag_combo.setToolTip("按标签筛选会话")
        self.tag_combo.currentTextChanged.connect(self._reload)
        search_row.addWidget(self.tag_combo)
        root.addLayout(search_row)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.list_widget = QWidget()
        self.list_layout = QVBoxLayout(self.list_widget)
        self.list_layout.setContentsMargins(2, 2, 2, 2)
        self.list_layout.setSpacing(6)
        self.list_layout.addStretch(1)
        scroll.setWidget(self.list_widget)
        root.addWidget(scroll, 1)

        bottom = QHBoxLayout()
        self.count_label = QLabel("")
        self.count_label.setObjectName("MutedLabel")
        bottom.addWidget(self.count_label, 1)
        self.export_btn = QPushButton("⬇ 导出当前对话 (Markdown)")
        self.export_btn.setCursor(Qt.PointingHandCursor)
        self.export_btn.clicked.connect(self.export_requested)
        bottom.addWidget(self.export_btn)
        close_btn = QPushButton("关闭")
        close_btn.clicked.connect(self.accept)
        bottom.addWidget(close_btn)
        root.addLayout(bottom)

    # ------------------------------------------------------------------
    def _reload(self):
        while self.list_layout.count() > 1:
            item = self.list_layout.takeAt(0)
            w = item.widget() if item else None
            if w is not None:
                w.deleteLater()
        query = self.search_edit.text()
        # 刷新标签下拉（保留当前选择），避免误触发递归
        cur = self.tag_combo.currentText()
        self.tag_combo.blockSignals(True)
        self.tag_combo.clear()
        self.tag_combo.addItem("全部标签")
        for t, _ in self.store.list_tags():
            self.tag_combo.addItem("#" + t)
        idx = self.tag_combo.findText(cur)
        self.tag_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self.tag_combo.blockSignals(False)
        tag = self.tag_combo.currentText()
        tag = None if tag in ("", "全部标签") else tag[1:]  # 去掉 "#" 前缀
        items = self.store.search(query, tag=tag)
        current_id = self.store.current_id()
        for info in items:
            row = SessionRow(info, info["id"] == current_id,
                             self._theme, self._fs)
            row.switched.connect(self._on_switch)
            row.renamed.connect(self._on_rename)
            row.deleted.connect(self._on_delete)
            row.pinned.connect(self._on_pin)
            row.tags_changed.connect(self._on_tags)
            self.list_layout.insertWidget(self.list_layout.count() - 1, row)
        self.count_label.setText("共 %d 个会话" % len(items))

    # ------------------------------------------------------------------
    def _on_new(self):
        session = self.store.create()
        self.session_selected.emit(session["id"])
        self._reload()

    def _on_switch(self, session_id):
        self.session_selected.emit(session_id)
        self._reload()

    def _on_rename(self, session_id):
        session = self.store.get(session_id)
        if session is None:
            return
        text, ok = QInputDialog.getText(
            self, "重命名会话", "会话名称：",
            text=session.get("title", ""))
        if ok and text.strip():
            self.store.rename(session_id, text.strip())
            self._reload()

    def _on_delete(self, session_id):
        was_current = self.store.current_id() == session_id
        self.store.delete(session_id)
        if was_current:
            # 删除的是当前会话 → 切到剩下的第一个
            cur = self.store.current()
            if cur is not None:
                self.session_selected.emit(cur["id"])
        self._reload()

    def _on_pin(self, session_id, pinned):
        self.store.set_pinned(session_id, pinned)
        self._reload()

    def _on_tags(self, session_id):
        """V11.2：编辑会话标签（逗号分隔，去重）"""
        session = self.store.get(session_id)
        if session is None:
            return
        cur = ", ".join(session.get("tags") or [])
        text, ok = QInputDialog.getText(
            self, "编辑标签", "用逗号分隔多个标签（如：工作, 学习, 灵感）：",
            text=cur)
        if ok:
            self.store.set_tags(session_id, text)
            self._reload()

    # ------------------------------------------------------------------
    def apply_theme(self, theme_name=None, font_size=None):
        if theme_name:
            self._theme = get_theme(theme_name)
        if font_size:
            self._fs = int(font_size)
        self.setStyleSheet(build_qss(self._theme, self._fs))
        self._reload()
