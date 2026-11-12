# -*- coding: utf-8 -*-
"""全局搜索对话框（v13.3）。

借鉴 Cherry Studio「find content across your conversations and knowledge
bases」：一个输入框同时召回会话、资料库、提示词库、长期记忆、收藏夹，
双击结果直接跳到对应位置。

数据流：core.globalsearch.search_all（纯逻辑）→ 本对话框（展示）
      → open_requested(ref) → app.assistant 负责跳转。
"""
from PyQt5.QtCore import Qt, pyqtSignal, QTimer
from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel,
                             QLineEdit, QComboBox, QListWidget,
                             QListWidgetItem, QPushButton, QApplication)

from core import globalsearch as gs


class GlobalSearchDialog(QDialog):
    """跨数据源全局搜索窗口。"""

    open_requested = pyqtSignal(dict)     # 携带 globalsearch 结果里的 ref

    def __init__(self, sessions=None, library=None, prompts=None,
                 memory=None, parent=None, theme=None):
        super().__init__(parent)
        self.sessions = sessions
        self.library = library
        self.prompts = prompts
        self.memory = memory
        self._theme = theme or {}
        self._results = []
        self.setWindowTitle("🔎 全局搜索 · 星语 Starry")
        self.resize(680, 520)
        self._build_ui()

    # ------------------------------------------------------------------
    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(14, 12, 14, 12)
        outer.setSpacing(8)

        head = QLabel("🔎 一次搜完：会话 · 资料库 · 提示词 · 长期记忆 · 收藏")
        head.setStyleSheet("font-size:14px;font-weight:600;color:#16293c;")
        outer.addWidget(head)

        row = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText(
            "输入关键词实时搜索…（↑↓ 选择 · Enter 打开 · Esc 关闭）")
        self.search.textChanged.connect(self._on_text_changed)
        row.addWidget(self.search, 1)
        self.source = QComboBox()
        self.source.addItem("全部数据源", None)
        for src in gs.ALL_SOURCES:
            self.source.addItem("%s %s" % (gs.SOURCE_ICONS[src],
                                          gs.SOURCE_LABELS[src]), src)
        self.source.currentIndexChanged.connect(self._reload)
        row.addWidget(self.source)
        outer.addLayout(row)

        self.list = QListWidget()
        self.list.setStyleSheet(
            "QListWidget{background:#fafbfc;border:1px solid #e3e8ef;"
            "border-radius:10px;outline:0;}"
            "QListWidget::item{border-radius:8px;padding:6px 10px;"
            "border-bottom:1px solid #eef1f5;}"
            "QListWidget::item:selected{background:#e6f2ff;}"
            "QListWidget::item:hover{background:#f0f6ff;}")
        self.list.itemActivated.connect(self._on_activate)
        outer.addWidget(self.list, 1)

        self.hint = QLabel("输入关键词开始搜索")
        self.hint.setStyleSheet("color:#5b7086;font-size:12px;")
        outer.addWidget(self.hint)

        bar = QHBoxLayout()
        self.counts = QLabel("")
        self.counts.setStyleSheet("color:#5b7086;font-size:12px;")
        bar.addWidget(self.counts)
        bar.addStretch(1)
        copy_btn = QPushButton("复制结果")
        copy_btn.clicked.connect(self._copy_results)
        bar.addWidget(copy_btn)
        open_btn = QPushButton("打开")
        open_btn.clicked.connect(self._open_current)
        bar.addWidget(open_btn)
        close_btn = QPushButton("关闭")
        close_btn.clicked.connect(self.reject)
        bar.addWidget(close_btn)
        outer.addLayout(bar)

        # 输入防抖：连续打字时只触发最后一次检索
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(160)
        self._debounce.timeout.connect(self._reload)
        QTimer.singleShot(0, self.search.setFocus)

    # ------------------------------------------------------------------
    def _on_text_changed(self, _text):
        self._debounce.start()

    def _reload(self, *_args):
        """按当前关键词 / 数据源过滤重新检索（可外部直接调用）。"""
        q = self.search.text().strip()
        src = self.source.currentData()
        sources = [src] if src else None
        self._results = gs.search_all(
            q, sessions=self.sessions, library=self.library,
            prompts=self.prompts, memory=self.memory, sources=sources)
        self.list.clear()
        for r in self._results:
            item = QListWidgetItem("%s [%s] %s\n    %s" % (
                r["icon"], r["label"], r["title"], r["snippet"]))
            item.setData(Qt.UserRole, r)
            self.list.addItem(item)
        if not q:
            self.hint.setText("输入关键词开始搜索")
        elif not self._results:
            self.hint.setText("没有找到匹配内容，换个关键词试试")
        else:
            self.hint.setText("共 %d 条结果 · 双击打开" % len(self._results))
        c = gs.source_counts(self._results)
        self.counts.setText("  ".join(
            "%s %d" % (gs.SOURCE_LABELS[s], c[s])
            for s in gs.ALL_SOURCES if c[s]))

    def apply_query(self, query):
        """从命令面板 / 托盘带关键词打开时用。"""
        self.search.setText(query or "")
        self._debounce.stop()
        self._reload()

    # ------------------------------------------------------------------
    def _current_result(self):
        item = self.list.currentItem()
        if item is None:
            return None
        return item.data(Qt.UserRole)

    def _on_activate(self, _item):
        self._open_current()

    def _open_current(self):
        r = self._current_result()
        if not r:
            self.hint.setText("请先选中一条结果")
            return
        self.open_requested.emit(dict(r.get("ref") or {}) | {
            "source": r.get("source"), "title": r.get("title")})

    def _copy_results(self):
        text = gs.format_results(self._results)
        try:
            QApplication.clipboard().setText(text)
            self.hint.setText("已复制 %d 条结果到剪贴板" % len(self._results))
        except Exception:                               # noqa: BLE001
            self.hint.setText("剪贴板不可用，请手动选择复制")
