# -*- coding: utf-8 -*-
"""消息选择器对话框（V11.4）：引用 / 分支对话共用。

- 列出当前会话的全部非 system 消息（显示 #下标 · 角色 · 摘要）
- 两种模式：
    quote  —— 选择一条消息作为引用，并可输入针对它的问题
    branch —— 选择一条消息作为分支点（复制到该处开新会话）
- 双击或点「确定」emit picked(int index, str extra_text)
  其中 index 为消息在会话 messages 中的真实下标（含 system 偏移）

数据来自 core.sessions，零额外依赖；样式与收藏夹对话框保持一致。
"""
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel,
                             QPushButton, QListWidget, QListWidgetItem,
                             QLineEdit)

from core.sessions import message_text

_ROLE_LABEL = {
    "user": "我",
    "assistant": "助手",
    "system": "系统",
    "tool": "工具",
}


class MessagePickerDialog(QDialog):
    """引用 / 分支共用的消息选择器。"""

    picked = pyqtSignal(int, str)

    def __init__(self, sessions, mode="quote", parent=None):
        super().__init__(parent)
        self.sessions = sessions
        self.mode = mode if mode in ("quote", "branch") else "quote"
        is_quote = self.mode == "quote"
        self.setWindowTitle("💬 引用消息追问" if is_quote else "🌿 分支对话")
        self.resize(600, 460)
        self._build_ui()

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(14, 12, 14, 12)
        outer.setSpacing(8)

        is_quote = self.mode == "quote"
        head_text = ("💬 选择一条历史消息作为引用（双击或选后点确定）"
                     if is_quote else
                     "🌿 选择分支点：将从该消息（含）处复制出一个新会话")
        head = QLabel(head_text)
        head.setStyleSheet("font-size:14px;font-weight:600;color:#16293c;")
        outer.addWidget(head)

        self.list = QListWidget()
        self.list.setStyleSheet(
            "QListWidget{background:#fafbfc;border:1px solid #e3e8ef;"
            "border-radius:10px;outline:0;}"
            "QListWidget::item{border-radius:8px;padding:8px 10px;"
            "border-bottom:1px solid #eef1f5;}"
            "QListWidget::item:selected{background:#e6f2ff;}"
            "QListWidget::item:hover{background:#f0f6ff;}")
        self.list.itemActivated.connect(lambda _it: self._on_confirm())
        outer.addWidget(self.list, 1)

        self.input = None
        if is_quote:
            tip = QLabel("针对它的新问题 / 追问（可留空，让模型续写或说明）：")
            tip.setStyleSheet("color:#5b7086;font-size:12px;")
            outer.addWidget(tip)
            self.input = QLineEdit()
            self.input.setPlaceholderText("例如：那它和经典计算到底有什么区别？")
            self.input.setStyleSheet(
                "QLineEdit{border:1px solid #d8e0ea;border-radius:8px;"
                "padding:8px 10px;font-size:13px;background:#fff;}")
            outer.addWidget(self.input)

        self.hint = QLabel("")
        self.hint.setStyleSheet("color:#5b7086;font-size:12px;")
        outer.addWidget(self.hint)

        bar = QHBoxLayout()
        bar.addStretch(1)
        cancel = QPushButton("取消")
        cancel.clicked.connect(self.reject)
        bar.addWidget(cancel)
        ok = QPushButton("确定引用" if is_quote else "从此处创建分支")
        ok.setDefault(True)
        ok.clicked.connect(self._on_confirm)
        bar.addWidget(ok)
        outer.addLayout(bar)

    def _reload(self):
        self.list.clear()
        msgs = self.sessions.messages()
        rows = 0
        for i, m in enumerate(msgs):
            if m.get("role") == "system":
                continue
            label = _ROLE_LABEL.get(m.get("role", ""), m.get("role") or "消息")
            text = " ".join(message_text(m).split())
            snippet = text[:48] + ("…" if len(text) > 48 else "")
            item = QListWidgetItem("#%d · %s · %s" % (i, label, snippet or "（空）"))
            item.setToolTip(text[:300])
            item.setData(Qt.UserRole, i)
            self.list.addItem(item)
            rows += 1
        if rows == 0:
            self.hint.setText("当前会话还没有可选择的消息。")
        else:
            self.hint.setText("共 %d 条消息" % rows)
            self.list.setCurrentRow(0)

    def _on_confirm(self):
        item = self.list.currentItem()
        if item is None:
            self.hint.setText("请先选择一条消息。")
            return
        index = int(item.data(Qt.UserRole))
        extra = self.input.text() if self.input is not None else ""
        self.picked.emit(index, extra)
        self.accept()
