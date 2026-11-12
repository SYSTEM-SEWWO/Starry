# -*- coding: utf-8 -*-
"""首次运行许可同意门（EULA）—— v7.3 企业商用合规。

- 仅当 `config.accepted_eula` 为 False 时弹出
- 毛玻璃面板 + 可滚动许可正文
- 「接受并继续」→ 写入 config.accepted_eula=True 并关闭
- 「拒绝」→ 拒绝信号，主程序退出（不授权不得使用）
"""
from PyQt5.QtCore import Qt, pyqtSignal, QRect
from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel,
                             QPushButton, QScrollArea, QTextEdit, QSizePolicy)

import hashlib

from core.config import APP_VERSION
from ui.theme import build_qss, get_theme, RADIUS_L
from ui.frost import FrostGlass


def eula_accept_token():
    """EULA 接受防篡改令牌：把许可正文与版本号一起哈希。

    仅置位 `accepted_eula=true` 而不写入正确令牌，将被主程序判定为
    「篡改/未完成」，重新弹出许可门（直编 config.json 已无法绕过）。
    """
    return hashlib.sha256(
        (EULA_TEXT + APP_VERSION).encode("utf-8")).hexdigest()


EULA_TEXT = """《星语 · Starry 软件许可协议》（商业版 · 摘要）

1. 授权范围
   本软件依据本商业许可向您提供使用授权。个人可免费用于非商业用途；
   企业或商业用途须获取有效许可密钥（License Key），并在「关于」中填写。

2. 权利保留
   © 2026 星语 Starry · 保留所有权利。未经书面授权，不得对本软件进行
   反向工程、再分发、转售或用于提供竞品服务。

3. 数据与隐私
   您的 API Key 与对话记录仅保存在本机，不会上传开发者服务器。
   用量统计为本地聚合数字，不涉及内容外传。

4. 第三方模型
   本软件仅作为本地客户端，调用您自行配置的第三方大模型 API；
   第三方服务的使用须遵守其各自的服务条款与计费规则。

5. 免责声明
   软件按「现状」提供，不保证无缺陷；因使用产生的任何损失，
   开发者不承担责任。详见随附 LICENSE 全文。

（点击「接受并继续」即表示您已阅读并同意上述条款。）
"""


class EulaDialog(QDialog):
    """首跑 EULA 同意门。accepted() 表示用户同意；rejected() 表示拒绝。"""

    accepted = pyqtSignal()
    rejected = pyqtSignal()

    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.cfg = config
        self._theme = get_theme(config.appearance.get("theme", "light"))
        self.setStyleSheet(build_qss(self._theme,
                                     int(config.appearance.get("font_size", 14))))
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Dialog)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setWindowTitle("许可协议 · 星语 Starry")
        self.setMinimumWidth(460)
        self.setMinimumHeight(420)
        self._build_ui()

    def _build_ui(self):
        shell = QVBoxLayout(self)
        shell.setContentsMargins(0, 0, 0, 0)
        glass = FrostGlass(self, radius=RADIUS_L)
        glass.setObjectName("FrostHost")
        glass.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        shell.addWidget(glass)
        lay = glass.layout()
        lay.setContentsMargins(22, 20, 22, 20)
        lay.setSpacing(12)

        title = QLabel("⚖ 软件许可协议")
        title.setStyleSheet("font-size:18px;font-weight:bold;")
        lay.addWidget(title)

        sub = QLabel("首次使用须阅读并同意以下条款（企业商用需有效许可密钥）")
        sub.setObjectName("MutedLabel")
        sub.setWordWrap(True)
        lay.addWidget(sub)

        sa = QScrollArea()
        sa.setWidgetResizable(True)
        sa.setFrameShape(sa.NoFrame)
        sa.setStyleSheet("QScrollArea{background:transparent;}")
        doc = QTextEdit()
        doc.setReadOnly(True)
        doc.setMarkdown(EULA_TEXT)
        doc.setStyleSheet("QTextEdit{background:transparent;border:none;}")
        sa.setWidget(doc)
        lay.addWidget(sa, 1)

        row = QHBoxLayout()
        row.setSpacing(10)
        btn_reject = QPushButton("拒绝")
        btn_reject.setObjectName("DangerButton")
        btn_reject.setCursor(Qt.PointingHandCursor)
        btn_reject.clicked.connect(self._on_reject)
        row.addWidget(btn_reject)
        row.addStretch(1)
        btn_accept = QPushButton("接受并继续")
        btn_accept.setObjectName("AccentButton")
        btn_accept.setCursor(Qt.PointingHandCursor)
        btn_accept.clicked.connect(self._on_accept)
        row.addWidget(btn_accept)
        lay.addLayout(row)

    def _on_accept(self):
        self.cfg.data["accepted_eula"] = True
        self.cfg.data["eula_accept_token"] = eula_accept_token()   # v7.5：防篡改
        try:
            self.cfg.save()
        except Exception:                      # noqa: BLE001
            pass
        self.accepted.emit()
        self.accept()

    def _on_reject(self):
        self.rejected.emit()
        self.reject()

    def showEvent(self, e):
        super().showEvent(e)
        parent = self.parent()
        if parent is not None:
            pr = parent.geometry()
            x = pr.x() + (pr.width() - self.width()) // 2
            y = pr.y() + (pr.height() - self.height()) // 2
        else:
            screen = self.screen()
            sg = screen.availableGeometry() if screen else QRect(0, 0, 800, 600)
            x = sg.x() + (sg.width() - self.width()) // 2
            y = sg.y() + (sg.height() - self.height()) // 2
        self.move(max(0, x), max(0, y))
