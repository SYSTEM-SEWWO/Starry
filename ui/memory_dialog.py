# -*- coding: utf-8 -*-
"""长期记忆管理对话框（V8.0）。

让用户查看 / 删除 / 清空已记住的内容，并开关「记忆」功能。
只读展示，不做任何执行；删除仅从本地 memory.json 移除。
"""

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (QCheckBox, QDialog, QHBoxLayout, QLabel,
                             QPushButton, QScrollArea, QVBoxLayout,
                             QWidget)
from core.memory import CATEGORIES, CATEGORY_LABELS


class MemoryDialog(QDialog):
    """长期记忆查看 / 管理。"""

    changed = pyqtSignal()   # 记忆增删 / 开关后通知外部刷新计数

    def __init__(self, store, parent=None):
        super().__init__(parent)
        self.store = store
        self.setWindowTitle("长期记忆 · 星语 Starry")
        self.setMinimumWidth(420)
        self.setMinimumHeight(360)
        self._build()

    # ------------------------------------------------------------------
    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(10)

        title = QLabel("星语会记住关于你与项目的信息，并在回答时参考。")
        title.setWordWrap(True)
        title.setObjectName("MutedLabel")
        root.addWidget(title)

        # 总开关
        self.toggle = QCheckBox("启用长期记忆（关闭后将不再学习，已记内容保留）")
        self.toggle.setChecked(self.store.enabled)
        self.toggle.toggled.connect(self._on_toggle)
        root.addWidget(self.toggle)

        # 列表区
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.list_widget = QWidget()
        self.list_layout = QVBoxLayout(self.list_widget)
        self.list_layout.setContentsMargins(0, 0, 0, 0)
        self.list_layout.setSpacing(6)
        self.scroll.setWidget(self.list_widget)
        root.addWidget(self.scroll, 1)
        self._reload()

        # 底部：清空 + 关闭
        bar = QHBoxLayout()
        bar.setSpacing(8)
        self.clear_btn = QPushButton("清空全部记忆")
        self.clear_btn.setObjectName("FlatButton")
        self.clear_btn.clicked.connect(self._on_clear)
        bar.addWidget(self.clear_btn)
        bar.addStretch(1)
        self.close_btn = QPushButton("关闭")
        self.close_btn.setObjectName("FlatButton")
        self.close_btn.clicked.connect(self.accept)
        bar.addWidget(self.close_btn)
        root.addLayout(bar)

    # ------------------------------------------------------------------
    def _reload(self):
        # 清空旧条目
        while self.list_layout.count():
            item = self.list_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        entries = self.store.list_all()
        if not entries:
            tip = QLabel("还没有记住任何内容。和它多聊几句，它会慢慢了解你。")
            tip.setWordWrap(True)
            tip.setObjectName("MutedLabel")
            self.list_layout.addWidget(tip)
            self.list_layout.addStretch(1)
            return
        for cat in CATEGORIES:
            items = self.store.by_category(cat)
            if not items:
                continue
            label = QLabel(CATEGORY_LABELS[cat])
            label.setObjectName("SectionLabel")
            self.list_layout.addWidget(label)
            for e in items:
                self.list_layout.addWidget(self._entry_row(e))
        self.list_layout.addStretch(1)

    def _entry_row(self, entry):
        row = QWidget()
        hl = QHBoxLayout(row)
        hl.setContentsMargins(4, 2, 4, 2)
        hl.setSpacing(8)
        text = QLabel(entry.get("text", ""))
        text.setWordWrap(True)
        hl.addWidget(text, 1)
        del_btn = QPushButton("忘记")
        del_btn.setObjectName("FlatButton")
        del_btn.setFixedSize(54, 26)
        del_btn.clicked.connect(lambda _=False, eid=entry.get("id"):
                                 self._on_forget(eid))
        hl.addWidget(del_btn)
        return row

    # ------------------------------------------------------------------
    def _on_toggle(self, on):
        self.store.set_enabled(bool(on))
        self._emit_changed()

    def _on_forget(self, eid):
        self.store.forget(eid)
        self._reload()
        self._emit_changed()

    def _on_clear(self):
        self.store.clear()
        self._reload()
        self._emit_changed()

    def _emit_changed(self):
        if callable(getattr(self, "changed", None)):
            self.changed.emit()
