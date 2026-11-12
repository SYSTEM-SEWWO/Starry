# -*- coding: utf-8 -*-
"""划词提问迷你窗：选中文字 → 点一个动作 → 直接问出好问题。

对应 Cherry Studio「划词助手」的形态，但更轻：不常驻浮动工具栏，
而是用一个可召唤的迷你窗（Ctrl+Shift+Q 或命令面板）完成。
"""
from PyQt5.QtCore import Qt, QPoint, pyqtSignal
from PyQt5.QtGui import QCursor
from PyQt5.QtWidgets import (QGridLayout, QHBoxLayout, QLabel, QLineEdit,
                             QPushButton, QSizePolicy, QVBoxLayout, QWidget)

from ui import theme as T
from ui.liquid import liquid_dialog_qss
from ui.frost import FrostGlass


class QuickAskWindow(QWidget):
    """玻璃质感迷你提问窗。submitted(str) 发出拼好的提示词。"""

    submitted = pyqtSignal(str)

    def __init__(self, cfg=None, parent=None, theme=None):
        super().__init__(parent)
        from core import quickask as qa
        self.qa = qa
        self.cfg = cfg
        self._snippet = ""
        self._action_buttons = {}
        self.setWindowFlags(Qt.FramelessWindowHint
                            | Qt.WindowStaysOnTopHint
                            | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setWindowTitle("划词提问")

        t = T.get_theme(theme or (cfg.appearance.get("theme")
                                  if cfg else T.DEFAULT_THEME))
        self._theme = t
        # 字体回退链：Windows 雅黑 / macOS 苹方 / Linux Noto CJK
        self.setStyleSheet(liquid_dialog_qss(t) + """
            QLabel, QPushButton, QLineEdit, QComboBox {
                font-family: "Microsoft YaHei", "PingFang SC",
                             "Noto Sans CJK SC", "Source Han Sans SC", sans-serif;
            }
        """)

        # v7.3：玻璃底改为真·毛玻璃（FrostGlass），背后内容经抓屏模糊透出
        glass = FrostGlass(self, radius=T.RADIUS_M, blur=16, tint_alpha=0.66)
        # FrostGlass 自带一个 QVBoxLayout，直接复用（不要再新建一个）
        lay = glass.layout()
        lay.setContentsMargins(16, 14, 16, 14)
        lay.setSpacing(8)

        # 标题行
        top = QHBoxLayout()
        title = QLabel("划词提问")
        title.setObjectName("GlassTitle")
        self.lang_combo_placeholder = None
        top.addWidget(title)
        top.addStretch(1)
        btn_close = QPushButton("✕")
        btn_close.setObjectName("FlatButton")
        btn_close.setFixedWidth(28)
        btn_close.clicked.connect(self.close)
        top.addWidget(btn_close)
        lay.addLayout(top)

        # 选中内容预览
        self.preview = QLabel("（还没有选中文字：复制一段文字再召唤）")
        self.preview.setObjectName("MutedLabel")
        self.preview.setWordWrap(True)
        self.preview.setStyleSheet("font-size: 12px;")
        self.preview.setMinimumHeight(52)
        self.preview.setMaximumHeight(88)
        self.preview.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        lay.addWidget(self.preview)

        # 动作按钮网格
        grid = QGridLayout()
        grid.setSpacing(6)
        row = col = 0
        for act in qa.ACTIONS:
            b = QPushButton(act.label)
            b.setToolTip(act.hint)
            b.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            b.clicked.connect(lambda _=False, k=act.key: self._run(k))
            grid.addWidget(b, row, col)
            self._action_buttons[act.key] = b
            col += 1
            if col > 2:
                col, row = 0, row + 1
        lay.addLayout(grid)

        # 目标语言（翻译用）
        lang_row = QHBoxLayout()
        lang_row.setSpacing(6)
        lab = QLabel("翻译目标")
        lab.setObjectName("ChipText")
        lang_row.addWidget(lab)
        self.target_edit = QLineEdit("中文")
        self.target_edit.setMaximumWidth(90)
        lang_row.addWidget(self.target_edit)
        lang_row.addStretch(1)
        extra_lab = QLabel("补充要求（可选）")
        extra_lab.setObjectName("ChipText")
        lang_row.addWidget(extra_lab)
        lay.addLayout(lang_row)

        self.extra_edit = QLineEdit()
        self.extra_edit.setPlaceholderText(
            "比如：用表格输出 / 写给初中生看 / 只回答关键数字")
        self.extra_edit.returnPressed.connect(
            lambda: self._run("explain") if self.extra_edit.text().strip()
            else None)
        lay.addWidget(self.extra_edit)

        # 隐私说明（HR v7.2 P0：读取选区的边界必须在产品内可见）
        privacy = QLabel("只在你点下动作时读取一次选区：不常驻监听、不记录、不上传")
        privacy.setObjectName("ChipText")
        privacy.setWordWrap(True)
        lay.addWidget(privacy)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(glass)
        self.resize(420, 288)

    # ------------------------------------------------------------------
    def set_snippet(self, text):
        """载入选中的文字（UI 只负责展示，拼接逻辑在 core.quickask）"""
        clean = self.qa.clean_snippet(text)
        self._snippet = clean
        if clean:
            self.preview.setText(self.qa.snippet_preview(clean))
        else:
            self.preview.setText("（剪贴板里没有文本：复制或选中一段文字再试）")
        # 代码片段时把「审阅」高亮
        code = self.qa.is_code_like(clean)
        for key, b in self._action_buttons.items():
            accent = (key == "review" and code) or (key == "explain" and not code)
            b.setObjectName("AccentButton" if accent else "")
            b.style().polish(b)

    def snippet(self):
        return self._snippet

    def _run(self, action_key):
        prompt = self.qa.build_prompt(action_key, self._snippet,
                                      self.target_edit.text().strip(),
                                      self.extra_edit.text().strip())
        if not prompt:
            self.preview.setText("⚠ 先选中/复制一段文字，再点动作")
            return
        self.submitted.emit(prompt)

    # ------------------------------------------------------------------
    def popup(self):
        """召唤：靠近光标定位 → 显示 → 抢占焦点"""
        self.move(self._near_cursor_pos())
        self.show()
        self.raise_()
        self.activateWindow()
        self.extra_edit.setFocus()

    def _near_cursor_pos(self):
        try:
            pos = QCursor.pos()
        except Exception:                       # noqa: BLE001
            pos = QPoint(200, 200)
        x = max(8, min(pos.x() - self.width() // 2, 4000))
        y = max(8, min(pos.y() + 16, 3000))
        return QPoint(int(x), int(y))

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Escape:
            self.close()
            return
        super().keyPressEvent(e)
