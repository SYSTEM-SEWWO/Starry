# -*- coding: utf-8 -*-
"""V11.5 洞察面板：展示统计 / 分支对比 / 合并报告的 Markdown 文本。

一个通用只读展示框：core.insights 生成 Markdown，本框负责渲染与
「复制到剪贴板 / 另存为 .md」，不参与任何业务逻辑（桌面与安卓同源）。
样式与 ui/message_picker_dialog.py、ui/starred_dialog.py 保持一致。
"""
from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel,
                             QPushButton, QTextBrowser, QFileDialog,
                             QMessageBox, QApplication)


class InsightDialog(QDialog):
    """只读 Markdown 洞察面板。"""

    def __init__(self, markdown, title="📊 对话洞察", parent=None):
        super().__init__(parent)
        self.markdown = markdown or ""
        self.setWindowTitle(title)
        self.resize(700, 580)
        self._build_ui()

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(14, 12, 14, 12)
        outer.setSpacing(8)

        head = QLabel("以下结果由 core.insights 纯逻辑生成，可复制或另存为 Markdown。")
        head.setStyleSheet("font-size:13px;font-weight:600;color:#16293c;")
        outer.addWidget(head)

        self.browser = QTextBrowser()
        self.browser.setStyleSheet(
            "QTextBrowser{background:#fafbfc;border:1px solid #e3e8ef;"
            "border-radius:10px;padding:10px;font-size:13px;}")
        # PyQt5 >= 5.14 支持 setMarkdown；老版本退化为纯文本，绝不因此崩溃
        try:
            self.browser.setMarkdown(self.markdown)
        except Exception:
            self.browser.setPlainText(self.markdown)
        outer.addWidget(self.browser, 1)

        bar = QHBoxLayout()
        bar.addStretch(1)
        copy_btn = QPushButton("复制内容")
        copy_btn.clicked.connect(self._on_copy)
        bar.addWidget(copy_btn)
        save_btn = QPushButton("另存为 .md")
        save_btn.clicked.connect(self._on_save)
        bar.addWidget(save_btn)
        close_btn = QPushButton("关闭")
        close_btn.setDefault(True)
        close_btn.clicked.connect(self.accept)
        bar.addWidget(close_btn)
        outer.addLayout(bar)

    def _on_copy(self):
        clipboard = QApplication.clipboard()
        if clipboard is not None:
            clipboard.setText(self.markdown)

    def _on_save(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "保存洞察报告", "星语-洞察报告.md",
            "Markdown (*.md);;文本 (*.txt);;全部文件 (*)")
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(self.markdown)
        except OSError as exc:
            QMessageBox.warning(self, "保存失败", "无法写入文件：%s" % exc)
