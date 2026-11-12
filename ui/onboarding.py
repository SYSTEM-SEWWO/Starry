# -*- coding: utf-8 -*-
"""新手引导：首次启动的聚光灯漫游。

形态：全屏透明覆盖层 + 玻璃质感提示卡。
交互：聚光灯呼吸脉冲、步骤间聚光灯矩形平滑过渡、卡片淡入；
      点击暗区下一步，Esc 跳过，←/→ 翻页，Enter 下一步。
持久化：完成或跳过后写入 cfg.data["onboarded"]，不再自动出现；
        设置中可手动重新触发。
"""
from PyQt5.QtCore import (Qt, QTimer, QRect, QRectF, QPoint, pyqtSignal,
                          QVariantAnimation, QEasingCurve, QPropertyAnimation)
from PyQt5.QtGui import QPainter, QPainterPath, QColor
import math
from PyQt5.QtWidgets import (QWidget, QFrame, QLabel, QPushButton, QHBoxLayout,
                             QVBoxLayout, QApplication)

from ui.theme import brand, onboard


class OnboardingOverlay(QWidget):
    finished = pyqtSignal()

    CARD_W = 300

    def __init__(self, app, parent=None):
        super().__init__(parent)
        self.app = app
        # 品牌色系（跟随当前主题：翠绿 / 天蓝）
        theme = "light"
        try:
            theme = self.app.cfg.appearance.get("theme", "light")
        except Exception:
            pass
        self._b = brand(theme)
        self._on = onboard(theme)
        self.setWindowFlags(Qt.FramelessWindowHint
                            | Qt.WindowStaysOnTopHint
                            | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setCursor(Qt.ArrowCursor)

        screen = QApplication.primaryScreen()
        self.setGeometry(screen.availableGeometry())

        self._steps = []
        self._idx = 0
        self._spot = QRect()          # 当前聚光灯（覆盖层局部坐标）
        self._spot_from = QRect()
        self._spot_to = QRect()
        self._spot_anim = None
        self._pulse = 0.0
        self._running = False

        self._build_card()

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(40)

    # ------------------------------------------------------------------
    # 提示卡
    # ------------------------------------------------------------------
    def _build_card(self):
        self.card = QFrame()
        self.card.setObjectName("OnboardCard")
        self.card.setFixedWidth(self.CARD_W)
        self.card.setStyleSheet("""
            QFrame#OnboardCard {
                background-color: %(card)s;
                border: 1px solid %(card_border)s;
                border-radius: 16px;
            }
            QLabel#OnboardTitle { color: %(title)s; font-size: 15px; font-weight: bold; }
            QLabel#OnboardBody { color: %(body)s; font-size: 12.5px; }
            QLabel#OnboardDots { color: %(dots)s; font-size: 9px; letter-spacing: 3px; }
            QPushButton {
                background-color: %(btn_bg)s;
                border: 1px solid %(btn_border)s;
                border-radius: 8px; color: %(btn_text)s; padding: 5px 14px; font-size: 12px;
            }
            QPushButton:hover { background-color: %(btn_hover)s; }
            QPushButton#OnboardPrimary {
                background-color: %(primary)s; border: none; color: #ffffff;
                padding: 5px 18px; font-weight: bold;
            }
            QPushButton#OnboardPrimary:hover { background-color: %(primary_hover)s; }
            QPushButton#OnboardSkip { border: none; background: transparent; color: %(skip)s; }
            QPushButton#OnboardSkip:hover { color: %(skip_hover)s; }
        """ % self._on)

        lay = QVBoxLayout(self.card)
        lay.setContentsMargins(18, 16, 18, 14)
        lay.setSpacing(8)

        top = QHBoxLayout()
        top.setSpacing(4)
        self.title_lb = QLabel("")
        self.title_lb.setObjectName("OnboardTitle")
        top.addWidget(self.title_lb)
        top.addStretch(1)
        self.skip_btn = QPushButton("跳过")
        self.skip_btn.setObjectName("OnboardSkip")
        self.skip_btn.setCursor(Qt.PointingHandCursor)
        self.skip_btn.clicked.connect(self._finish)
        top.addWidget(self.skip_btn)
        lay.addLayout(top)

        self.body_lb = QLabel("")
        self.body_lb.setObjectName("OnboardBody")
        self.body_lb.setWordWrap(True)
        self.body_lb.setFixedWidth(self.CARD_W - 36)
        lay.addWidget(self.body_lb)

        bottom = QHBoxLayout()
        self.dots_lb = QLabel("")
        self.dots_lb.setObjectName("OnboardDots")
        bottom.addWidget(self.dots_lb)
        bottom.addStretch(1)
        self.prev_btn = QPushButton("上一步")
        self.prev_btn.setCursor(Qt.PointingHandCursor)
        self.prev_btn.clicked.connect(self.prev_step)
        bottom.addWidget(self.prev_btn)
        self.next_btn = QPushButton("下一步")
        self.next_btn.setObjectName("OnboardPrimary")
        self.next_btn.setCursor(Qt.PointingHandCursor)
        self.next_btn.clicked.connect(self.next_step)
        bottom.addWidget(self.next_btn)
        lay.addLayout(bottom)

        self.card.setParent(self)
        self.card.hide()

    # ------------------------------------------------------------------
    # 步骤定义（延迟到 start() 构建，保证控件已就绪）
    # ------------------------------------------------------------------
    def _build_steps(self):
        app = self.app
        win = app.window
        return [
            {"target": None, "center": True,
             "title": "欢迎使用 星语 · Starry ✦",
             "body": "一个液态玻璃风格的桌面 AI 伙伴：\n"
                     "· 免费 API 与本地模型（Ollama / LM Studio）\n"
                     "· 思考过程实时呈现，支持深度思考\n"
                     "· 文件 / 图片 / 截图多模态提问\n"
                     "· 智能体与插件市场，能力可扩展"},
            {"target": lambda: app.ball, "title": "你的桌面伙伴",
             "body": "这是悬浮小球：待机时会呼吸发光。\n"
                     "单击展开 / 收起对话，拖动可移动位置，右键查看更多操作。"},
            {"target": lambda: win.input, "open_window": True,
             "title": "在这里输入问题",
             "body": "Enter 发送，Shift+Enter 换行。\n"
                     "生成过程中可以随时点击「■ 停止生成」，回复支持一键复制与重新生成。"},
            {"target": lambda: win.deep_btn, "title": "🧠 深度思考",
             "body": "开启后自动切换到推理模型（如 DeepSeek-R1、QwQ），"
                     "完整思考过程实时可见，再点一次即可切回。"},
            {"rect": lambda: win.attach_buttons_rect(),
             "title": "发送文件 / 图片 / 截图",
             "body": "📎 选择文件（文本 / 代码 / PDF 自动解析），🖼 选择图片，"
                     "✂ 区域截图（或 Ctrl+Shift+S）。也可以直接拖入窗口、Ctrl+V 粘贴图片。"},
            {"target": lambda: win.model_combo, "title": "随时切换模型",
             "body": "标题栏下拉框一键切换模型；带「免费」徽标的是免费模型。\n"
                     "启动时会自动拉取最新模型列表，并探测本地 Ollama / LM Studio。"},
            {"target": lambda: win.skill_combo, "open_window": True,
             "title": "🧩 智能体：技能与工具",
             "body": "输入区上方可切换「技能」（翻译 / 代码审查 / 面试官等专家人设）；\n"
                     "「🧰 工具」开关计算器、联网搜索、文件读取等能力；\n"
                     "「🧩 插件市场」可安装技能包与代码插件，让 AI 真正会干活。"},
            {"target": lambda: win.library_btn, "open_window": True,
             "title": "📚 资料库 · ⏰ 自动化 · 🎭 会诊",
             "body": "📚 资料库：导入你的文档，AI 回答时自动参考相关内容；\n"
                     "⏰ 自动化：定时 / 间隔自动执行任务，结果写入专属会话；\n"
                     "🎭 会诊：多位专家并行分析同一个问题，主持人汇总最终答案。"},
            {"target": lambda: win.sessions_btn, "open_window": True,
             "title": "💬 多会话与提示词库",
             "body": "标题栏 💬 管理多个对话：新建 / 切换 / 搜索 / 置顶，"
                     "并可导出为 Markdown；\n"
                     "输入区 📖 内置 18 条常用提示词一键插入，"
                     "也能把自己的输入存为个人提示词。"},
            {"target": None, "center": True,
             "title": "开始探索吧 🎉",
             "body": "点击右上角 ⚙ 可配置服务商、外观与全局热键。\n"
                     "随时按 Ctrl+Shift+A 从任何位置唤起窗口。"},
        ]

    # ------------------------------------------------------------------
    # 流程控制
    # ------------------------------------------------------------------
    def start(self):
        self._steps = self._build_steps()
        self._idx = 0
        self._running = True
        self.show()
        self.raise_()
        self._apply_step(animate=False)

    def _current(self):
        return self._steps[self._idx] if 0 <= self._idx < len(self._steps) else None

    def next_step(self):
        if self._idx >= len(self._steps) - 1:
            self._finish()
            return
        self._idx += 1
        self._apply_step(animate=True)

    def prev_step(self):
        if self._idx > 0:
            self._idx -= 1
            self._apply_step(animate=True)

    def _apply_step(self, animate=False):
        step = self._current()
        if step is None:
            return

        # 需要聊天窗口可见的步骤：自动展开
        if step.get("open_window") and not self.app.window.isVisible():
            self.app.toggle_window()

        # 目标矩形（全局 → 局部）
        target_rect = QRect()
        getter = step.get("target")
        rect_getter = step.get("rect")
        if rect_getter is not None:
            r = rect_getter()
            if r is not None and not r.isEmpty():
                pad = 8
                target_rect = QRect(r).adjusted(-pad, -pad, pad, pad)
        elif getter is not None:
            w = getter()
            if w is not None and w.isVisible():
                tl = w.mapToGlobal(QPoint(0, 0))
                target_rect = QRect(tl, w.size())
                pad = 8
                target_rect = target_rect.adjusted(-pad, -pad, pad, pad)

        if step.get("center") or target_rect.isEmpty():
            self._spot_to = QRect()
        else:
            self._spot_to = target_rect.translated(self.geometry().topLeft())

        if animate and not self._spot_to.isNull():
            self._spot_from = self._spot
            self._spot_anim = QVariantAnimation(self)
            self._spot_anim.setStartValue(self._spot_from)
            self._spot_anim.setEndValue(self._spot_to)
            self._spot_anim.setDuration(320)
            self._spot_anim.setEasingCurve(QEasingCurve.OutCubic)
            self._spot_anim.valueChanged.connect(self._on_spot_anim)
            self._spot_anim.start()
        else:
            self._spot = self._spot_to

        # 文案与按钮
        self.title_lb.setText(step["title"])
        self.body_lb.setText(step["body"])
        self.dots_lb.setText(" ".join(
            "●" if i == self._idx else "○" for i in range(len(self._steps))))
        self.prev_btn.setVisible(self._idx > 0)
        last = self._idx == len(self._steps) - 1
        self.next_btn.setText("完成" if last else "下一步")
        self.card.adjustSize()
        self._place_card()
        self._fade_card_in()

    def _on_spot_anim(self, v):
        self._spot = v
        self.update()

    def _fade_card_in(self):
        self.card.show()
        self.card.raise_()
        anim = QPropertyAnimation(self.card, b"windowOpacity", self)
        anim.setDuration(220)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setEasingCurve(QEasingCurve.OutCubic)
        anim.start()
        self._card_anim = anim

    def _place_card(self):
        """把提示卡放到聚光灯下方（空间不足时上方/居中）"""
        screen = self.geometry()
        cw, ch = self.card.width(), self.card.height()
        if self._spot_to.isNull():
            x = screen.x() + (screen.width() - cw) // 2
            y = screen.y() + int(screen.height() * 0.68)
        else:
            x = self._spot_to.center().x() - cw // 2
            y = self._spot_to.bottom() + 16
            if y + ch > screen.bottom() - 20:
                y = self._spot_to.top() - ch - 16
            if y < screen.y() + 20:
                y = self._spot_to.bottom() + 16
        x = max(screen.x() + 16, min(x, screen.right() - cw - 16))
        y = max(screen.y() + 16, min(y, screen.bottom() - ch - 16))
        self.card.move(x, y)

    def _tick(self):
        if self._running:
            self._pulse = (self._pulse + 0.03) % 1.0
            if not self._spot.isNull():
                self.update()

    # ------------------------------------------------------------------
    # 结束
    # ------------------------------------------------------------------
    def _finish(self):
        if not self._running:
            return
        self._running = False
        try:
            self.app.cfg.data["onboarded"] = True
            self.app.cfg.save()
        except Exception:
            pass
        self.finished.emit()
        self.close()

    # ------------------------------------------------------------------
    # 绘制：暗角 + 聚光灯
    # ------------------------------------------------------------------
    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        path = QPainterPath()
        path.setFillRule(Qt.OddEvenFill)
        path.addRect(QRectF(self.rect()))
        if not self._spot.isNull():
            path.addRoundedRect(QRectF(self._spot), 12, 12)
        dim = QColor(*self._b["bg"], 150)
        p.fillPath(path, dim)

        if not self._spot.isNull():
            # 呼吸边框
            breathe = 0.5 + 0.5 * math.sin(self._pulse * 6.283)
            alpha = int(90 + 90 * breathe)
            p.setPen(QColor(*self._b["particle"], alpha))
            p.drawRoundedRect(QRectF(self._spot), 12, 12)
        p.end()

    # ------------------------------------------------------------------
    # 交互
    # ------------------------------------------------------------------
    def mousePressEvent(self, e):
        # 点击暗区 → 下一步（卡片区域除外，由按钮自身处理）
        if not self.card.geometry().contains(e.pos()):
            self.next_step()

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Escape:
            self._finish()
        elif e.key() in (Qt.Key_Right, Qt.Key_Return, Qt.Key_Space):
            self.next_step()
        elif e.key() == Qt.Key_Left:
            self.prev_step()
