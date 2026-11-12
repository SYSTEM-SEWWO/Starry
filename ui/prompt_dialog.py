# -*- coding: utf-8 -*-
"""提示词库对话框：浏览 / 搜索 / 插入输入框 / 保存自定义。

- 内置 18 条常用提示词（写作 / 编程 / 学习 / 办公 / 生活）
- 自定义提示词保存在本地配置中
- 点击「插入」把提示词写入输入框（光标处）
"""
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel,
                             QPushButton, QScrollArea, QWidget, QFrame,
                             QLineEdit, QComboBox, QInputDialog, QMessageBox)

from core.prompts import PromptLibrary
from ui.theme import build_qss, get_theme


class PromptRow(QFrame):
    """单条提示词"""

    inserted = pyqtSignal(str)
    deleted = pyqtSignal(str)

    def __init__(self, prompt, theme, font_size, parent=None):
        super().__init__(parent)
        self.prompt = prompt
        self._theme = theme
        self._fs = font_size
        self.setObjectName("PromptRow")
        self._build_ui()
        self._apply_theme(theme, font_size)

    def _build_ui(self):
        p = self.prompt
        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 7, 8, 7)
        lay.setSpacing(6)

        text_col = QVBoxLayout()
        text_col.setSpacing(2)
        self.title_label = QLabel("%s %s" % (p.get("category", "自定义"),
                                             p.get("title", "")))
        preview = " ".join((p.get("content") or "").split())
        self.content_label = QLabel(preview[:60] + ("…" if len(preview) > 60
                                                    else ""))
        self.content_label.setObjectName("MutedLabel")
        text_col.addWidget(self.title_label)
        text_col.addWidget(self.content_label)

        self.insert_btn = QPushButton("插入")
        self.insert_btn.setObjectName("AccentButton")
        self.insert_btn.setCursor(Qt.PointingHandCursor)
        self.insert_btn.setFixedHeight(26)
        self.insert_btn.clicked.connect(
            lambda: self.inserted.emit(self.prompt.get("content", "")))

        lay.addLayout(text_col, 1)
        lay.addWidget(self.insert_btn)

        if p.get("custom"):
            self.del_btn = QPushButton("🗑")
            self.del_btn.setObjectName("FlatButton")
            self.del_btn.setToolTip("删除自定义提示词")
            self.del_btn.setCursor(Qt.PointingHandCursor)
            self.del_btn.setFixedSize(26, 26)
            self.del_btn.clicked.connect(
                lambda: self.deleted.emit(self.prompt["id"]))
            lay.addWidget(self.del_btn)

    def _apply_theme(self, theme, font_size):
        self._theme = theme
        self._fs = font_size
        self.setStyleSheet(
            "QFrame#PromptRow{background-color:%s;border:1px solid %s;"
            "border-radius:10px;}"
            % (theme["bubble_ai_bg"], theme["border"]))
        self.title_label.setStyleSheet(
            "color:%s;font-weight:bold;" % theme["text"])
        self.content_label.setStyleSheet("color:%s;" % theme["muted"])


class PromptDialog(QDialog):
    """提示词库主对话框"""

    prompt_inserted = pyqtSignal(str)

    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.cfg = config
        self.lib = PromptLibrary(config)
        self._theme = get_theme(config.appearance.get("theme", "light"))
        self._fs = int(config.appearance.get("font_size", 14))
        self.setStyleSheet(build_qss(self._theme, self._fs))
        self.setWindowTitle("提示词库")
        self.setMinimumWidth(480)
        self.setMinimumHeight(460)
        self._current_text = ""
        self._build_ui()
        self._reload()

    # ------------------------------------------------------------------
    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setSpacing(8)

        top = QHBoxLayout()
        title = QLabel("📖 提示词库")
        title.setStyleSheet("font-size:%dpx;font-weight:bold;"
                            % (self._fs + 4))
        top.addWidget(title)
        top.addStretch(1)
        self.save_btn = QPushButton("＋ 存当前输入为提示词")
        self.save_btn.setCursor(Qt.PointingHandCursor)
        self.save_btn.setToolTip("把输入框中的内容保存为个人提示词，下次一键插入")
        self.save_btn.clicked.connect(self._on_save_current)
        top.addWidget(self.save_btn)
        root.addLayout(top)

        row = QHBoxLayout()
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("搜索提示词 …")
        self.search_edit.textChanged.connect(self._reload)
        row.addWidget(self.search_edit, 2)
        self.cat_combo = QComboBox()
        self.cat_combo.addItem("全部分类")
        for c in self.lib.categories():
            self.cat_combo.addItem(c)
        self.cat_combo.currentIndexChanged.connect(self._reload)
        row.addWidget(self.cat_combo, 1)
        root.addLayout(row)

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
        prompts = self.lib.search(query)
        cat = self.cat_combo.currentText()
        if cat and cat != "全部分类":
            prompts = [p for p in prompts if p.get("category", "自定义") == cat]
        for p in prompts:
            row = PromptRow(p, self._theme, self._fs)
            row.inserted.connect(self._on_insert)
            row.deleted.connect(self._on_delete)
            self.list_layout.insertWidget(self.list_layout.count() - 1, row)
        self.count_label.setText("共 %d 条" % len(prompts))

    # ------------------------------------------------------------------
    def _on_insert(self, content):
        self.prompt_inserted.emit(content)
        self.accept()

    def _on_delete(self, prompt_id):
        self.lib.remove(prompt_id)
        self._reload()

    def _on_save_current(self):
        """把主程序传入的当前输入文本存为提示词"""
        text = (self._current_text or "").strip()
        if not text:
            QMessageBox.information(self, "提示",
                                    "输入框还是空的，先输入要保存的内容吧。")
            return
        title, ok = QInputDialog.getText(
            self, "保存提示词", "给这条提示词起个名字：",
            text=text.splitlines()[0][:20])
        if not ok or not title.strip():
            return
        self.lib.add(title.strip(), text if text.endswith("\n")
                     else text + "\n\n")
        self.cat_combo.clear()
        self.cat_combo.addItem("全部分类")
        for c in self.lib.categories():
            self.cat_combo.addItem(c)
        self._reload()
        self.count_label.setText("已保存：%s" % title.strip())

    # ------------------------------------------------------------------
    def set_current_text(self, text):
        """主程序在打开前传入当前输入框内容（供「存为提示词」使用）"""
        self._current_text = text or ""

    def apply_theme(self, theme_name=None, font_size=None):
        if theme_name:
            self._theme = get_theme(theme_name)
        if font_size:
            self._fs = int(font_size)
        self.setStyleSheet(build_qss(self._theme, self._fs))
        self._reload()
