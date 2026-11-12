# -*- coding: utf-8 -*-
"""通用双输入框对话框（单行标题 + 多行正文）。

用于「粘贴文本导入资料库」等需要同时收集名称与长文本的场景。
"""
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QLabel, QLineEdit,
                             QTextEdit, QHBoxLayout, QPushButton)

from ui.theme import build_qss, get_theme


class TextInputDialog(QDialog):
    """双输入对话框：values() → (name, text)"""

    def __init__(self, title, name_label, text_placeholder,
                 ok_text="确定", parent=None, theme_name=None):
        super().__init__(parent)
        cfg = parent.cfg if parent is not None and hasattr(parent, "cfg") else None
        theme_name = theme_name or (cfg.appearance.get("theme", "light")
                                    if cfg is not None else "light")
        self._theme = get_theme(theme_name)
        self._fs = int(cfg.appearance.get("font_size", 14)) if cfg else 14
        self.setStyleSheet(build_qss(self._theme, self._fs))
        self.setWindowTitle(title)
        self.setMinimumWidth(460)
        self.setMinimumHeight(340)
        self._build_ui(name_label, text_placeholder, ok_text)

    def _build_ui(self, name_label, text_placeholder, ok_text):
        root = QVBoxLayout(self)
        root.setSpacing(8)

        root.addWidget(QLabel(name_label))
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("可选，留空自动命名")
        root.addWidget(self.name_edit)

        root.addWidget(QLabel("内容："))
        self.text_edit = QTextEdit()
        self.text_edit.setPlaceholderText(text_placeholder)
        root.addWidget(self.text_edit, 1)

        row = QHBoxLayout()
        row.addStretch(1)
        cancel_btn = QPushButton("取消")
        cancel_btn.clicked.connect(self.reject)
        ok_btn = QPushButton(ok_text)
        ok_btn.setObjectName("AccentButton")
        ok_btn.setCursor(Qt.PointingHandCursor)
        ok_btn.clicked.connect(self.accept)
        row.addWidget(cancel_btn)
        row.addWidget(ok_btn)
        root.addLayout(row)

    def values(self):
        name = self.name_edit.text().strip()
        if not name:
            text = self.text_edit.toPlainText().strip()
            name = (text[:18] + "…") if len(text) > 18 else (text or "未命名文档")
        return name, self.text_edit.toPlainText()

    def apply_theme(self, theme_name, font_size):
        self._theme = get_theme(theme_name)
        self._fs = int(font_size)
        self.setStyleSheet(build_qss(self._theme, self._fs))
