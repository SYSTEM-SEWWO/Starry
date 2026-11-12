# -*- coding: utf-8 -*-
"""收藏夹对话框（V11.3）：列出全部已收藏消息，双击跳转到对应会话。

- 数据来自 core.sessions.SessionStore.list_starred()
- 双击或点击「跳转」emit jump_requested(session_id)
"""
import time

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel,
                             QPushButton, QScrollArea, QWidget, QFrame,
                             QListWidget, QListWidgetItem)


def _fmt_time(ts):
    if not ts:
        return ""
    d = time.localtime(ts)
    today = time.localtime()
    if d[:3] == today[:3]:
        return "今天 %02d:%02d" % (d[3], d[4])
    return "%d-%02d-%02d %02d:%02d" % (d[0], d[1], d[2], d[3], d[4])


class StarredDialog(QDialog):
    """收藏夹：跨会话收藏消息总览与跳转。"""

    jump_requested = pyqtSignal(str)

    def __init__(self, sessions, parent=None):
        super().__init__(parent)
        self.sessions = sessions
        self.setWindowTitle("⭐ 收藏夹")
        self.resize(560, 460)
        self._build_ui()

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(14, 12, 14, 12)
        outer.setSpacing(8)

        head = QLabel("⭐ 已收藏的消息（双击跳转到所在会话）")
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
        self.list.itemActivated.connect(self._on_activate)
        outer.addWidget(self.list, 1)

        self.hint = QLabel("")
        self.hint.setStyleSheet("color:#5b7086;font-size:12px;")
        outer.addWidget(self.hint)

        bar = QHBoxLayout()
        bar.addStretch(1)
        close_btn = QPushButton("关闭")
        close_btn.clicked.connect(self.reject)
        bar.addWidget(close_btn)
        outer.addLayout(bar)

    def _reload(self):
        self.list.clear()
        items = self.sessions.list_starred()
        if not items:
            self.hint.setText("还没有收藏任何消息。在命令面板执行"
                              "「收藏最后回复」即可收藏当前会话的最后一条 AI 回复。")
            return
        self.hint.setText("共 %d 条收藏" % len(items))
        for it in items:
            role_icon = "🧑" if it["role"] == "user" else "✦"
            title = "%s %s  ｜  %s" % (role_icon, it["title"],
                                       _fmt_time(it["updated"]))
            item = QListWidgetItem(title)
            item.setToolTip(it["snippet"])
            item.setData(Qt.UserRole, it["session_id"])
            self.list.addItem(item)

    def _on_activate(self, item):
        if item is None:
            return
        sid = item.data(Qt.UserRole)
        self.jump_requested.emit(sid)
        self.accept()
