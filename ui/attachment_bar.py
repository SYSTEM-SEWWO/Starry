# -*- coding: utf-8 -*-
"""输入框上方的附件栏：图片缩略图 / 文件芯片，可移除。"""
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (QWidget, QHBoxLayout, QVBoxLayout, QLabel,
                             QPushButton, QFrame)


class AttachmentChip(QFrame):
    """单个附件芯片"""
    remove_clicked = pyqtSignal()

    def __init__(self, attachment, parent=None):
        super().__init__(parent)
        self.attachment = attachment
        self.setFixedHeight(54)
        self.setObjectName("AttachChip")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(6, 4, 4, 4)
        lay.setSpacing(6)

        # 图标 / 缩略图
        thumb = attachment.thumbnail(38)
        if thumb is not None:
            icon = QLabel()
            icon.setFixedSize(38, 38)
            icon.setScaledContents(True)
            icon.setPixmap(thumb)
            icon.setStyleSheet("border-radius:6px;")
        else:
            icon = QLabel("📄")
            icon.setFixedSize(38, 38)
            icon.setStyleSheet("font-size:22px;")
            icon.setAlignment(Qt.AlignCenter)
        lay.addWidget(icon, 0, Qt.AlignVCenter)

        # 名称 + 大小
        col = QVBoxLayout()
        col.setSpacing(0)
        name = QLabel(attachment.name)
        name.setObjectName("AttachName")
        size = QLabel(attachment.size_str())
        size.setObjectName("AttachSize")
        col.addWidget(name)
        col.addWidget(size)
        lay.addLayout(col, 1)

        # 移除按钮
        btn = QPushButton("✕")
        btn.setObjectName("FlatButton")
        btn.setFixedSize(22, 22)
        btn.setCursor(Qt.PointingHandCursor)
        btn.setToolTip("移除附件")
        btn.clicked.connect(self.remove_clicked)
        lay.addWidget(btn, 0, Qt.AlignVCenter)


class AttachmentBar(QWidget):
    """附件栏（无附件时隐藏）"""
    remove_requested = pyqtSignal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 4, 10, 4)
        lay.setSpacing(6)
        self._chips = []
        lay.addStretch(1)
        self.hide()

    def add_attachment(self, attachment):
        chip = AttachmentChip(attachment)
        idx = len(self._chips)
        chip.remove_clicked.connect(lambda: self.remove_requested.emit(idx))
        self.layout().insertWidget(self.layout().count() - 1, chip)
        self._chips.append(chip)
        self.show()
        return chip

    def count(self):
        return len(self._chips)

    def clear(self):
        for chip in self._chips:
            chip.deleteLater()
        self._chips = []
        self.hide()
