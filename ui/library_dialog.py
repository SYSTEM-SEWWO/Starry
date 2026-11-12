# -*- coding: utf-8 -*-
"""资料库对话框：导入 / 粘贴 / 删除文档，试用检索。

复刻 WorkBuddy 资料库能力：
- 导入本地文本文件（txt/md/代码/配置等），或直接粘贴文本
- 列表展示文档与分块统计，可随时删除
- 内置检索试用框：输入问题即时查看命中片段与相关度
- 检索经智能体工具 search_library 按需调用，或在对话中自动注入上下文
"""
import os

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel,
                             QPushButton, QScrollArea, QWidget, QFrame,
                             QLineEdit, QTextEdit, QMessageBox, QFileDialog)

from ui.theme import build_qss, get_theme


def _fmt_size(n):
    if n < 1024:
        return "%d B" % n
    if n < 1024 * 1024:
        return "%.1f KB" % (n / 1024.0)
    return "%.1f MB" % (n / 1024.0 / 1024.0)


class DocRow(QFrame):
    """单个文档行"""

    deleted = pyqtSignal(str)

    def __init__(self, info, theme, font_size, parent=None):
        super().__init__(parent)
        self.info = info
        self._theme = theme
        self._fs = font_size
        self.setObjectName("DocRow")
        self._build_ui()
        self._apply_theme(theme, font_size)

    def _build_ui(self):
        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 7, 8, 7)
        lay.setSpacing(6)
        icon = "📄" if self.info.get("kind") == "file" else "📝"
        text_col = QVBoxLayout()
        text_col.setSpacing(2)
        self.name_label = QLabel("%s %s" % (icon, self.info.get("name", "")))
        self.meta_label = QLabel("%s · %d 个分块"
                                 % (_fmt_size(self.info.get("size", 0)),
                                    self.info.get("chunks", 0)))
        self.meta_label.setObjectName("MutedLabel")
        text_col.addWidget(self.name_label)
        text_col.addWidget(self.meta_label)
        del_btn = QPushButton("🗑")
        del_btn.setObjectName("FlatButton")
        del_btn.setToolTip("从资料库移除")
        del_btn.setCursor(Qt.PointingHandCursor)
        del_btn.setFixedSize(26, 26)
        del_btn.clicked.connect(self._confirm_delete)
        lay.addLayout(text_col, 1)
        lay.addWidget(del_btn)

    def _confirm_delete(self):
        ret = QMessageBox.question(
            self, "移除文档",
            "确定把「%s」从资料库移除吗？（不会删除本地文件）"
            % self.info.get("name"),
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if ret == QMessageBox.Yes:
            self.deleted.emit(self.info["id"])

    def _apply_theme(self, theme, font_size):
        self._theme = theme
        self._fs = font_size
        self.setStyleSheet(
            "QFrame#DocRow{background-color:%s;border:1px solid %s;"
            "border-radius:8px;}"
            % (theme["bubble_ai_bg"], theme["border"]))
        self.name_label.setStyleSheet(
            "color:%s;font-weight:bold;" % theme["text"])
        self.meta_label.setStyleSheet("color:%s;" % theme["muted"])


class LibraryDialog(QDialog):
    """资料库管理主对话框"""

    def __init__(self, kb, config, parent=None):
        super().__init__(parent)
        self.kb = kb
        self.cfg = config
        self._theme = get_theme(config.appearance.get("theme", "light"))
        self._fs = int(config.appearance.get("font_size", 14))
        self.setStyleSheet(build_qss(self._theme, self._fs))
        self.setWindowTitle("资料库")
        self.setMinimumWidth(540)
        self.setMinimumHeight(520)
        self._build_ui()
        self._reload()

    # ------------------------------------------------------------------
    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setSpacing(8)

        top = QHBoxLayout()
        title = QLabel("📚 资料库")
        title.setStyleSheet("font-size:%dpx;font-weight:bold;"
                            % (self._fs + 4))
        top.addWidget(title)
        top.addStretch(1)
        self.import_btn = QPushButton("＋ 导入文件")
        self.import_btn.setObjectName("AccentButton")
        self.import_btn.setCursor(Qt.PointingHandCursor)
        self.import_btn.clicked.connect(self._on_import)
        self.paste_btn = QPushButton("📝 粘贴文本")
        self.paste_btn.setCursor(Qt.PointingHandCursor)
        self.paste_btn.clicked.connect(self._on_paste)
        self.clear_btn = QPushButton("清空")
        self.clear_btn.setObjectName("FlatButton")
        self.clear_btn.setCursor(Qt.PointingHandCursor)
        self.clear_btn.clicked.connect(self._on_clear)
        top.addWidget(self.import_btn)
        top.addWidget(self.paste_btn)
        top.addWidget(self.clear_btn)
        root.addLayout(top)

        hint = QLabel("导入的文档将按段落分块；对话时模型可通过「资料库检索」"
                      "工具按需查找，相关问题会自动注入参考片段。"
                      "支持 txt / md / 代码 / 配置等文本格式（≤2MB）。")
        hint.setObjectName("MutedLabel")
        hint.setWordWrap(True)
        root.addWidget(hint)

        # 检索试用
        search_row = QHBoxLayout()
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("试用检索：输入问题，查看资料库命中片段 …")
        self.search_edit.returnPressed.connect(self._on_search)
        search_row.addWidget(self.search_edit, 1)
        search_btn = QPushButton("检索")
        search_btn.setCursor(Qt.PointingHandCursor)
        search_btn.clicked.connect(self._on_search)
        search_row.addWidget(search_btn)
        root.addLayout(search_row)

        self.result_edit = QTextEdit()
        self.result_edit.setReadOnly(True)
        self.result_edit.setPlaceholderText("命中片段将显示在这里（含来源文档与相关度）")
        self.result_edit.setMaximumHeight(130)
        root.addWidget(self.result_edit)

        # 文档列表
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
        docs = self.kb.docs()
        for info in docs:
            row = DocRow(info, self._theme, self._fs)
            row.deleted.connect(self._on_delete)
            self.list_layout.insertWidget(self.list_layout.count() - 1, row)
        self.count_label.setText("共 %d 个文档 · %d 个分块"
                                 % (len(docs), self.kb.total_chunks()))

    # ------------------------------------------------------------------
    def _on_import(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self, "选择要导入资料库的文件", os.path.expanduser("~"),
            "文本文件 (*.txt *.md *.py *.js *.ts *.json *.csv *.html *.css "
            "*.xml *.yaml *.yml *.ini *.log *.sql);;所有文件 (*)")
        added, errors = 0, []
        for p in paths:
            doc_id, err = self.kb.add_file(p)
            if doc_id:
                added += 1
            else:
                errors.append("%s：%s" % (os.path.basename(p), err))
        self._reload()
        if added:
            self.result_edit.setPlainText("已导入 %d 个文档。" % added)
        if errors:
            QMessageBox.warning(self, "部分文件导入失败",
                                "\n".join(errors[:8]))

    def _on_paste(self):
        from ui.text_input_dialog import TextInputDialog
        dlg = TextInputDialog(
            "粘贴文本导入资料库",
            "为这段文本起个名字：", "粘贴的文本内容…",
            "导入", parent=self)
        if dlg.exec_() == QDialog.Accepted:
            name, text = dlg.values()
            if text.strip():
                doc_id = self.kb.add_text(name, text)
                self._reload()
                if doc_id:
                    self.result_edit.setPlainText(
                        "已导入「%s」（%d 字）。" % (name, len(text)))

    def _on_clear(self):
        if not self.kb.docs():
            return
        ret = QMessageBox.question(
            self, "清空资料库",
            "确定移除全部 %d 个文档吗？（不会删除本地文件）"
            % len(self.kb.docs()),
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if ret == QMessageBox.Yes:
            self.kb.clear()
            self._reload()
            self.result_edit.clear()

    def _on_delete(self, doc_id):
        self.kb.remove(doc_id)
        self._reload()

    def _on_search(self):
        query = self.search_edit.text().strip()
        if not query:
            return
        if not self.kb.docs():
            self.result_edit.setPlainText("资料库为空，请先导入文档。")
            return
        hits = self.kb.search(query, top_k=3)
        if not hits:
            self.result_edit.setPlainText("未找到相关内容（可换几个关键词试试）。")
            return
        parts = []
        for i, h in enumerate(hits, 1):
            parts.append("%d. 【%s】相关度 %.2f\n%s"
                         % (i, h.get("doc", ""), h.get("score", 0),
                            h.get("text", "")))
        self.result_edit.setPlainText("\n\n".join(parts))

    # ------------------------------------------------------------------
    def apply_theme(self, theme_name, font_size):
        theme = get_theme(theme_name)
        self._theme = theme
        self._fs = int(font_size)
        self.setStyleSheet(build_qss(theme, self._fs))
        for row in self.list_widget.findChildren(DocRow):
            row._apply_theme(theme, self._fs)
        self._reload()
