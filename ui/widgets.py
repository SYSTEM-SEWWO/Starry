# -*- coding: utf-8 -*-
"""自定义 UI 组件：
- ThinkingDots      三点跳动思考动画
- ShimmerBar        微光流动进度条（等待/思考状态）
- MarkdownView      自动高度的 Markdown 富文本视图
- ThinkingBox       可折叠的「思考过程」展示框
- UserBubble        用户消息气泡
- AssistantBubble   AI 消息气泡（思考框 + 正文 + 操作栏）
"""
import math
import time

from PyQt5.QtCore import Qt, QTimer, QRectF, QSize, pyqtSignal, QPropertyAnimation
from PyQt5.QtGui import QPainter, QColor, QPen, QBrush, QLinearGradient
from PyQt5.QtWidgets import (QWidget, QFrame, QHBoxLayout, QVBoxLayout, QLabel,
                             QPushButton, QTextBrowser, QSizePolicy, QApplication,
                             QGraphicsOpacityEffect)

from core.markdown_render import markdown_to_qt_html
from ui.theme import RADIUS_S, RADIUS_M


# ---------------------------------------------------------------------------
# 思考动画：三点跳动
# ---------------------------------------------------------------------------
class ThinkingDots(QWidget):
    """三个依次跳动的小圆点，表示「正在思考」"""

    def __init__(self, parent=None, diameter=6, color=QColor(120, 150, 255)):
        super().__init__(parent)
        self._phase = 0
        self._d = diameter
        self._color = color
        self.setFixedSize(diameter * 3 + 12, diameter + 8)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(110)

    def set_color(self, color):
        self._color = color

    def _tick(self):
        self._phase = (self._phase + 1) % 12
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        n = 3
        spacing = self.width() / n
        cy = self.height() / 2
        p.setPen(Qt.NoPen)
        for i in range(n):
            t = ((self._phase - i * 2) % 12) / 12.0
            wave = math.sin(t * math.pi)
            r = self._d / 2.0 * (0.55 + 0.45 * wave)
            c = QColor(self._color)
            c.setAlpha(int(110 + 145 * wave))
            p.setBrush(c)
            cx = spacing * (i + 0.5)
            p.drawEllipse(QRectF(cx - r, cy - r, 2 * r, 2 * r))


# ---------------------------------------------------------------------------
# 思考动画：微光进度条
# ---------------------------------------------------------------------------
class ShimmerBar(QWidget):
    """一条左右流动微光的进度条，表示模型正在生成"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(6)
        self._offset = 0.0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(45)

    def _tick(self):
        self._offset = (self._offset + 0.045) % 1.6
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(120, 130, 160, 55))
        p.drawRoundedRect(QRectF(0, 0, self.width(), self.height()), 3, 3)
        w = self.width()
        x = (self._offset - 0.3) * w
        grad = QLinearGradient(x, 0, x + w * 0.3, 0)
        grad.setColorAt(0.0, QColor(140, 170, 255, 0))
        grad.setColorAt(0.5, QColor(140, 170, 255, 200))
        grad.setColorAt(1.0, QColor(140, 170, 255, 0))
        p.setBrush(QBrush(grad))
        p.drawRoundedRect(QRectF(x, 0, w * 0.3, self.height()), 3, 3)


# ---------------------------------------------------------------------------
# 思考动画：文字微光 + 波形条
# ---------------------------------------------------------------------------
class ShimmerLabel(QLabel):
    """带流动微光效果的文字（用于「正在思考」标题）"""

    def __init__(self, text="", parent=None):
        super().__init__(text, parent)
        self._phase = 0.0
        self._active = False
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(45)

    def set_active(self, on):
        self._active = bool(on)
        self.update()

    def _tick(self):
        if self._active:
            self._phase = (self._phase + 0.028) % 1.7
            self.update()

    def paintEvent(self, event):
        if not self._active:
            super().paintEvent(event)
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        base = self.palette().text().color()
        w = self.width()
        offset = (self._phase - 0.35) * w
        grad = QLinearGradient(offset, 0, offset + w * 0.5, 0)
        grad.setColorAt(0.0, base)
        grad.setColorAt(0.5, QColor(255, 255, 255))
        grad.setColorAt(1.0, base)
        p.setPen(QPen(QBrush(grad), 1))
        p.setFont(self.font())
        p.drawText(self.rect(), self.alignment(), self.text())


class ThinkingWave(QWidget):
    """三条跳动的音浪柱，表示正在思考"""

    def __init__(self, parent=None, color=QColor(120, 150, 255)):
        super().__init__(parent)
        self._phase = 0.0
        self._color = color
        self.setFixedSize(20, 14)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(90)

    def set_color(self, color):
        self._color = color

    def _tick(self):
        self._phase += 0.55
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        n = 3
        bw = 3.2
        gap = (self.width() - bw * n) / (n - 1)
        for i in range(n):
            h_ratio = 0.30 + 0.70 * (0.5 + 0.5 * math.sin(self._phase + i * 1.0))
            bh = max(3.0, (self.height() - 2) * h_ratio)
            x = i * (bw + gap)
            y = (self.height() - bh) / 2
            c = QColor(self._color)
            c.setAlpha(int(140 + 110 * h_ratio))
            p.setBrush(c)
            p.drawRoundedRect(QRectF(x, y, bw, bh), 1.6, 1.6)


# ---------------------------------------------------------------------------
# 工具调用：旋转指示点 + 可展开 chip
# ---------------------------------------------------------------------------
class SpinnerDot(QWidget):
    """12px 旋转弧线指示点（工具执行中）"""

    def __init__(self, parent=None, color=QColor(120, 150, 255), size=14):
        super().__init__(parent)
        self._phase = 0.0
        self._color = color
        self.setFixedSize(size, size)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(80)

    def set_color(self, color):
        self._color = color

    def _tick(self):
        self._phase = (self._phase + 0.14) % 1.0
        self.update()

    def stop(self):
        self._timer.stop()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = min(self.width(), self.height()) / 2 - 2
        cx, cy = self.width() / 2, self.height() / 2
        p.setPen(QPen(QColor(self._color), 2))
        p.setBrush(Qt.NoBrush)
        rect = QRectF(cx - r, cy - r, 2 * r, 2 * r)
        p.drawArc(rect, 0, 360 * 16)                      # 底环
        c = QColor(self._color)
        p.setPen(QPen(c, 2))
        start = int(self._phase * 360 * 16)
        p.drawArc(rect, start, 70 * 16)                   # 旋转弧


def _fmt_args(args):
    """把工具参数压缩为一行预览：{'expression': '6*7'} → expression=6*7"""
    if isinstance(args, dict):
        parts = []
        for k, v in list(args.items())[:3]:
            if k == "_raw":
                continue
            s = str(v)
            parts.append("%s=%s" % (k, s if len(s) <= 24 else s[:24] + "…"))
        return "  ".join(parts)
    if isinstance(args, str):
        return args[:60]
    return ""


class _ClickRow(QWidget):
    """可点击行（QPushButton 内嵌 layout 的 sizeHint 异常，改用普通 QWidget）"""
    clicked = pyqtSignal()

    def mouseReleaseEvent(self, e):
        self.clicked.emit()
        super().mouseReleaseEvent(e)


class ToolCallChip(QWidget):
    """单次工具调用 chip：运行中显示旋转指示与参数，完成后可展开查看结果"""

    def __init__(self, name, args, theme, font_size, parent=None):
        super().__init__(parent)
        self._theme = theme
        self._fs = font_size
        self._name = name
        self._args = args
        self._done = False
        self._expanded = False
        self._build_ui()
        self.apply_theme(theme, font_size)

    def _build_ui(self):
        self.setObjectName("ToolChip")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(2)

        self.header = _ClickRow()
        self.header.setObjectName("ToolChipHeader")
        self.header.setCursor(Qt.PointingHandCursor)
        self.header.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.header.clicked.connect(self._toggle)
        hl = QHBoxLayout(self.header)
        hl.setContentsMargins(6, 2, 8, 2)
        hl.setSpacing(6)
        self.spinner = SpinnerDot(color=QColor(self._theme["accent"]))
        self.ok_label = QLabel("✓")
        self.ok_label.hide()
        self.name_label = QLabel("🔧 %s" % self._name)
        self.args_label = QLabel(_fmt_args(self._args))
        self.arrow_label = QLabel("▸")
        hl.addWidget(self.spinner)
        hl.addWidget(self.ok_label)
        hl.addWidget(self.name_label)
        hl.addWidget(self.args_label)
        hl.addStretch(1)
        hl.addWidget(self.arrow_label)
        lay.addWidget(self.header, 0, Qt.AlignLeft)

        self.body = MarkdownView()
        self.body.setMaximumHeight(0)
        lay.addWidget(self.body)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)

    # ---------------- 状态 ----------------
    def set_result(self, result, elapsed=None):
        self._done = True
        self.spinner.stop()
        self.spinner.hide()
        self.ok_label.show()
        self.arrow_label.show()
        if elapsed is not None:
            self.args_label.setText("用时 %.1fs" % elapsed)
        text = result if isinstance(result, str) else repr(result)
        self.body.custom_render = (
            lambda: '<pre style="margin:0;white-space:pre-wrap;'
            'word-break:break-all;color:%s;font-size:%dpx;">%s</pre>'
            % (self._theme.get("code_text", self._theme["text"]),
               max(11, self._fs - 2), _escape_html(text[:4000])))
        self.body._render()

    # ---------------- 折叠 ----------------
    def _toggle(self):
        self.set_expanded(not self._expanded)

    def set_expanded(self, expanded):
        self._expanded = expanded
        self.arrow_label.setText("▾" if expanded else "▸")
        target = self._content_height() if expanded else 0
        self._anim = QPropertyAnimation(self.body, b"maximumHeight", self)
        self._anim.setDuration(160)
        self._anim.setStartValue(self.body.maximumHeight())
        self._anim.setEndValue(target)
        self._anim.start()

    def _content_height(self):
        doc = self.body.document()
        try:
            doc.setTextWidth(self.body.viewport().width())
        except Exception:
            pass
        h = int(doc.size().height()) + 12
        return max(30, min(h, 220))

    # ---------------- 主题 ----------------
    def apply_theme(self, theme, font_size):
        self._theme = theme
        self._fs = font_size
        self.spinner.set_color(QColor(theme["accent"]))
        self.setStyleSheet(
            "QWidget#ToolChip{background-color:%s;border:1px solid %s;"
            "border-radius:%dpx;}"
            "QWidget#ToolChipHeader{background:transparent;border:none;"
            "color:%s;text-align:left;}"
            "QWidget#ToolChipHeader:hover{color:%s;}"
            % (theme["bubble_ai_bg"], theme["border"], RADIUS_M,
               theme["muted"], theme["text"]))
        self.name_label.setStyleSheet("color:%s;font-weight:bold;"
                                      % theme["accent"])
        self.args_label.setStyleSheet("color:%s;font-size:%dpx;"
                                      % (theme["muted"], max(10, self._fs - 2)))
        self.arrow_label.setStyleSheet("color:%s;" % theme["muted"])
        self.body.setStyleSheet(
            "background-color:%s;border-radius:%dpx;padding:6px 9px;"
            % (theme["code_bg"], RADIUS_S))
        if self._done:
            # 重渲染结果（主题可能已变）
            self.body.rerender()


def _escape_html(text):
    return (str(text).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;"))


# ---------------------------------------------------------------------------
# 通用：控件淡入
# ---------------------------------------------------------------------------
def fade_in_widget(widget, duration=200):
    """新消息气泡的淡入动画"""
    effect = QGraphicsOpacityEffect(widget)
    widget.setGraphicsEffect(effect)
    anim = QPropertyAnimation(effect, b"opacity", widget)
    anim.setStartValue(0.0)
    anim.setEndValue(1.0)
    anim.setDuration(duration)
    anim.finished.connect(lambda: widget.setGraphicsEffect(None))
    anim.start()
    widget._fade_anim = anim      # 防止被回收
    return anim


# ---------------------------------------------------------------------------
# 自动高度的 Markdown 视图
# ---------------------------------------------------------------------------
class MarkdownView(QTextBrowser):
    """随内容自动伸缩高度的只读 Markdown 富文本视图"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setReadOnly(True)
        self.setFrameShape(QFrame.NoFrame)
        self.setOpenExternalLinks(True)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        self.setViewportMargins(0, 0, 0, 0)
        self._buffer = ""
        self._theme = None
        self._fs = 14
        self._render_timer = None
        self.custom_render = None   # 可选：自定义渲染函数（错误提示等）
        self.document().documentLayout().documentSizeChanged.connect(self.updateGeometry)

    # ---------------- 渲染 ----------------
    def set_markdown(self, text, theme, font_size, throttle_ms=0):
        self._buffer = text
        self._theme = theme
        self._fs = font_size
        self.custom_render = None
        if throttle_ms:
            if self._render_timer is None:
                self._render_timer = QTimer(self)
                self._render_timer.setSingleShot(True)
                self._render_timer.timeout.connect(self._render)
                self._render_timer.start(throttle_ms)
        else:
            self._render()

    def append_markdown(self, text, throttle_ms=120):
        self._buffer += text
        self.set_markdown(self._buffer, self._theme, self._fs, throttle_ms=throttle_ms)

    def flush(self):
        if self._render_timer is not None:
            self._render_timer.stop()
            self._render_timer = None
        self._render()

    def rerender(self, theme=None, font_size=None):
        if theme is not None:
            self._theme = theme
        if font_size is not None:
            self._fs = font_size
        if self._buffer or self.custom_render is not None:
            self._render()

    def _render(self):
        self._render_timer = None
        if self.custom_render is not None:
            self.setHtml(self.custom_render())
            return
        html = markdown_to_qt_html(self._buffer, self._theme, self._fs)
        self.setHtml(html)

    def raw_text(self):
        return self._buffer

    # ---------------- 高度自适应 ----------------
    def sizeHint(self):
        w = super().sizeHint().width()
        return QSize(w, int(self.document().size().height()) + 10)

    def minimumSizeHint(self):
        return QSize(0, 0)


# ---------------------------------------------------------------------------
# 可折叠思考框
# ---------------------------------------------------------------------------
class ThinkingBox(QWidget):
    """「思考过程」折叠框：思考时展开并展示实时推理流，结束后自动折叠。"""

    def __init__(self, theme, font_size=14, parent=None):
        super().__init__(parent)
        self._theme = theme
        self._fs = font_size
        self._active = False
        self._ever_appended = False
        self._start_time = None
        self._expanded = False
        self._build_ui()
        self.apply_theme(theme, font_size)

    # ---------------- UI ----------------
    def _build_ui(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(2)

        self.header = QPushButton()
        self.header.setObjectName("ThinkingHeader")
        self.header.setCheckable(True)
        self.header.setChecked(False)
        self.header.setCursor(Qt.PointingHandCursor)
        self.header.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
        self.header.clicked.connect(self._toggle)
        hl = QHBoxLayout(self.header)
        hl.setContentsMargins(6, 2, 8, 2)
        hl.setSpacing(6)
        self.title_label = ShimmerLabel("思考过程")
        self.wave = ThinkingWave()
        self.wave.hide()
        self.time_label = QLabel("")
        self.arrow_label = QLabel("▸")
        hl.addWidget(self.title_label)
        hl.addWidget(self.wave)
        hl.addWidget(self.time_label)
        hl.addWidget(self.arrow_label)
        lay.addWidget(self.header, 0, Qt.AlignLeft)

        self.body = MarkdownView()
        self.body.setMaximumHeight(0)
        lay.addWidget(self.body)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)

    # ---------------- 状态 ----------------
    def start(self):
        """开始思考：展开框体，显示动画"""
        self._active = True
        self._ever_appended = False
        self._start_time = time.time()
        self.body.set_markdown("", self._theme, self._fs)
        self.title_label.setText("正在思考")
        self.title_label.set_active(True)
        self.wave.show()
        self.time_label.setText("")
        self.show()
        self.set_expanded(True)

    def append(self, text):
        if not self._active:
            return
        self._ever_appended = True
        self.body.append_markdown(text, throttle_ms=150)

    def finish(self):
        """思考结束：停动画、记录用时、自动折叠；无推理内容则整体隐藏"""
        if not self._active:
            return
        self._active = False
        self.title_label.set_active(False)
        self.wave.hide()
        if self._start_time is not None:
            elapsed = max(0.0, time.time() - self._start_time)
            self.time_label.setText("用时 %.1fs" % elapsed)
        if not self._ever_appended:
            self.hide()
            return
        self.title_label.setText("思考过程")
        self.body.flush()
        self.set_expanded(False)

    def skip(self):
        """完全不使用思考框时隐藏"""
        self._active = False
        self.title_label.set_active(False)
        self.wave.hide()
        self.hide()

    # ---------------- 折叠 ----------------
    def _toggle(self):
        self.set_expanded(not self._expanded)

    def set_expanded(self, expanded):
        self._expanded = expanded
        self.header.setChecked(expanded)
        self.arrow_label.setText("▾" if expanded else "▸")
        target = self._content_height() if expanded else 0
        self._anim = QPropertyAnimation(self.body, b"maximumHeight", self)
        self._anim.setDuration(180)
        self._anim.setStartValue(self.body.maximumHeight())
        self._anim.setEndValue(target)
        self._anim.start()

    def _content_height(self):
        doc = self.body.document()
        try:
            doc.setTextWidth(self.body.viewport().width())
        except Exception:
            pass
        h = int(doc.size().height()) + 12
        return max(40, min(h, 260))

    # ---------------- 主题 ----------------
    def apply_theme(self, theme, font_size=None):
        self._theme = theme
        if font_size is not None:
            self._fs = font_size
        self.wave.set_color(QColor(theme["accent"]))
        self.time_label.setStyleSheet("color:%s;" % theme["muted"])
        self.arrow_label.setStyleSheet("color:%s;" % theme["muted"])
        self.title_label.setStyleSheet("color:%s;" % theme["muted"])
        self.body.setStyleSheet(
            "background-color:%s;border:1px solid %s;border-radius:%dpx;padding:6px 9px;"
            % (theme["code_bg"], theme["border"], RADIUS_S))
        think_theme = dict(theme)
        think_theme["text"] = theme.get("thinking_text", theme["text"])
        if self._active or self._ever_appended:
            self.body.rerender(think_theme, self._fs)


# ---------------------------------------------------------------------------
# 消息气泡
# ---------------------------------------------------------------------------
class MessageBubble(QFrame):
    """气泡基类"""

    def __init__(self, theme, font_size):
        super().__init__()
        self._theme = theme
        self._fs = font_size
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)

    def apply_theme(self, theme, font_size):
        raise NotImplementedError


class UserBubble(MessageBubble):
    """用户消息（右侧蓝色气泡：文本 + 附件缩略图）"""

    def __init__(self, text, theme, font_size, attachments=None):
        super().__init__(theme, font_size)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addStretch(1)

        column = QWidget()
        col = QVBoxLayout(column)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(4)

        self._thumb_labels = []
        if attachments:
            att_row = QHBoxLayout()
            att_row.setContentsMargins(0, 0, 0, 0)
            att_row.setSpacing(4)
            for att in attachments[:4]:
                thumb = att.thumbnail(46)
                if thumb is not None:
                    lb = QLabel()
                    lb.setFixedSize(46, 46)
                    lb.setScaledContents(True)
                    lb.setPixmap(thumb)
                    lb.setStyleSheet("border-radius:%dpx;" % RADIUS_S)
                    att_row.addWidget(lb)
                    self._thumb_labels.append(lb)
                else:
                    chip = QLabel("📄 %s" % att.name)
                    chip.setStyleSheet(
                        "background-color:rgba(255,255,255,0.16);"
                        "border-radius:%dpx;padding:2px 8px;" % RADIUS_S)
                    att_row.addWidget(chip)
            if len(attachments) > 4:
                more = QLabel("+%d" % (len(attachments) - 4))
                more.setStyleSheet("padding:2px 4px;")
                att_row.addWidget(more)
            att_row.addStretch(1)
            col.addLayout(att_row)

        self.label = QLabel(text or "")
        self.label.setTextInteractionFlags(Qt.TextSelectableByMouse | Qt.TextBrowserInteraction)
        self.label.setWordWrap(True)
        self.label.setTextFormat(Qt.PlainText)
        self.label.setMaximumWidth(300)
        if not text:
            self.label.hide()
        col.addWidget(self.label)

        # 资料库引用角标（默认隐藏，命中知识库时由控制器点亮）
        self.badge = QLabel("")
        self.badge.setWordWrap(True)
        self.badge.hide()
        col.addWidget(self.badge)

        lay.addWidget(column)
        self.apply_theme(theme, font_size)

    def apply_theme(self, theme, font_size):
        self._theme = theme
        self._fs = font_size
        self.label.setStyleSheet(
            "background-color:%s;color:%s;border-radius:%dpx;padding:8px 12px;"
            % (theme["bubble_user_bg"], theme["bubble_user_text"], RADIUS_M))
        if self.badge.text():
            self.set_badge(self.badge.text())

    def set_badge(self, text):
        """设置资料库引用角标（空文本 = 隐藏）"""
        text = (text or "").strip()
        if not text:
            self.badge.hide()
            return
        self.badge.setText(text)
        self.badge.setStyleSheet(
            "background-color:%s;color:%s;border:1px solid %s;"
            "border-radius:%dpx;padding:2px 9px;font-size:11px;"
            % (self._theme.get("accent_soft", "#d9ecfb"),
               self._theme.get("accent", "#0b8bd8"),
               self._theme.get("border", "#d6e5f3"), RADIUS_S))
        self.badge.show()


class AssistantBubble(MessageBubble):
    """AI 消息（工具调用区 + 思考框 + Markdown 正文 + 操作栏）"""

    regenerate_requested = pyqtSignal()
    speak_requested = pyqtSignal(str)          # 朗读正文
    variant_selected = pyqtSignal(int)         # 切换回答变体

    _VARIANT_LABELS = "①②③④⑤⑥⑦⑧⑨⑩"

    def __init__(self, theme, font_size):
        super().__init__(theme, font_size)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)

        # 工具调用区（智能体模式）
        self.tools_box = QWidget()
        tlay = QVBoxLayout(self.tools_box)
        tlay.setContentsMargins(0, 0, 0, 0)
        tlay.setSpacing(4)
        self.tools_box.hide()
        lay.addWidget(self.tools_box)

        self.thinking = ThinkingBox(theme, font_size)
        lay.addWidget(self.thinking)

        self.content = MarkdownView()
        lay.addWidget(self.content)

        # 操作栏
        self.actions = QWidget()
        al = QHBoxLayout(self.actions)
        al.setContentsMargins(0, 0, 0, 0)
        al.setSpacing(2)
        self.copy_btn = QPushButton("复制")
        self.copy_btn.setObjectName("FlatButton")
        self.copy_btn.setCursor(Qt.PointingHandCursor)
        self.copy_btn.setFixedHeight(24)
        self.copy_btn.clicked.connect(self._copy)
        self.regen_btn = QPushButton("↻ 重新生成")
        self.regen_btn.setObjectName("FlatButton")
        self.regen_btn.setCursor(Qt.PointingHandCursor)
        self.regen_btn.setFixedHeight(24)
        self.regen_btn.clicked.connect(self.regenerate_requested)
        self.speak_btn = QPushButton("🔊 朗读")
        self.speak_btn.setObjectName("FlatButton")
        self.speak_btn.setCursor(Qt.PointingHandCursor)
        self.speak_btn.setFixedHeight(24)
        self.speak_btn.setToolTip("朗读本条回复（再次点击或 Esc 停止）")
        self.speak_btn.clicked.connect(
            lambda: self.speak_requested.emit(self.content.raw_text()))
        # 变体切换器（重新生成产生多个回答时显示）
        self.variant_box = QWidget()
        self.variant_box.setObjectName("VariantBox")
        vl = QHBoxLayout(self.variant_box)
        vl.setContentsMargins(0, 0, 0, 0)
        vl.setSpacing(2)
        self._variant_btns = []
        self.variant_box.hide()
        al.addWidget(self.copy_btn)
        al.addWidget(self.regen_btn)
        al.addWidget(self.speak_btn)
        al.addWidget(self.variant_box)
        al.addStretch(1)
        lay.addWidget(self.actions, 0, Qt.AlignLeft)

        self._variants = []
        self._active = 0

        self.content.set_markdown("", theme, font_size)

    # ---------------- 内容 ----------------
    def append_content(self, text):
        self.content.append_markdown(text, throttle_ms=120)

    # ---------------- 工具调用 ----------------
    def add_tool_call(self, name, args, elapsed=None):
        """新增一个运行中的工具调用 chip"""
        chip = ToolCallChip(name, args, self._theme, self._fs)
        chip.setProperty("running", True)
        self.tools_box.layout().addWidget(chip)
        self.tools_box.show()
        return chip

    def complete_tool_call(self, name, result):
        """把最后一个同名运行中 chip 标记为完成"""
        lay = self.tools_box.layout()
        for i in range(lay.count() - 1, -1, -1):
            item = lay.itemAt(i)
            chip = item.widget() if item is not None else None
            if isinstance(chip, ToolCallChip) and chip._name == name \
                    and not chip._done:
                chip.set_result(result)
                return chip
        return None

    def flush(self):
        self.content.flush()

    # ---------------- 回答变体（重新生成分支） ----------------
    def set_variants(self, variants, active=0):
        """设置多个回答变体并显示 ①② 切换器"""
        self._variants = [v for v in (variants or []) if v is not None]
        self._active = max(0, min(int(active), len(self._variants) - 1)) \
            if self._variants else 0
        self._rebuild_variant_buttons()
        self._show_variant(self._active)

    def _rebuild_variant_buttons(self):
        lay = self.variant_box.layout()
        while lay.count():
            item = lay.takeAt(0)
            w = item.widget() if item else None
            if w is not None:
                w.deleteLater()
        self._variant_btns = []
        if len(self._variants) <= 1:
            self.variant_box.hide()
            return
        for i in range(len(self._variants)):
            label = (self._VARIANT_LABELS[i] if i < len(self._VARIANT_LABELS)
                     else str(i + 1))
            btn = QPushButton(label)
            btn.setObjectName("VariantButton")
            btn.setCheckable(True)
            btn.setChecked(i == self._active)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setFixedSize(26, 24)
            btn.setToolTip("查看第 %d 个回答" % (i + 1))
            btn.clicked.connect(lambda _, i=i: self._on_variant_click(i))
            lay.addWidget(btn)
            self._variant_btns.append(btn)
        self._style_variant_buttons()
        self.variant_box.show()

    def _style_variant_buttons(self):
        for i, btn in enumerate(self._variant_btns):
            btn.setStyleSheet(
                "QPushButton{background:%s;color:%s;border:1px solid %s;"
                "border-radius:6px;font-size:13px;padding:0;}"
                "QPushButton:checked{background:%s;color:#ffffff;"
                "border-color:%s;}"
                % (self._theme.get("accent_soft", "#d9ecfb"),
                   self._theme.get("accent", "#0b8bd8"),
                   self._theme.get("border", "#d6e5f3"),
                   self._theme.get("accent", "#0b8bd8"),
                   self._theme.get("accent", "#0b8bd8")))

    def _on_variant_click(self, idx):
        if idx == self._active:
            return
        self._active = idx
        for i, btn in enumerate(self._variant_btns):
            btn.setChecked(i == idx)
        self._show_variant(idx)
        self.variant_selected.emit(idx)

    def _show_variant(self, idx):
        if not (0 <= idx < len(self._variants)):
            return
        self.content.set_markdown(self._variants[idx], self._theme, self._fs)

    def active_variant_index(self):
        return self._active

    def set_error(self, message):
        """展示错误信息（覆盖正文，且抗主题重渲染）"""
        self.thinking.finish()
        self.content.custom_render = (
            lambda: '<div style="color:%s;font-size:%dpx;">⚠ %s</div>'
            % (self._theme.get("danger", "#ff6b6b"), self._fs, message))
        self.content._render()

    def _copy(self):
        QApplication.clipboard().setText(self.content.raw_text())

    # ---------------- 主题 ----------------
    def apply_theme(self, theme, font_size):
        self._theme = theme
        self._fs = font_size
        self.thinking.apply_theme(theme, font_size)
        self.content.rerender(theme, font_size)
        if self._variant_btns:
            self._style_variant_buttons()
        lay = self.tools_box.layout()
        for i in range(lay.count()):
            item = lay.itemAt(i)
            chip = item.widget() if item is not None else None
            if isinstance(chip, ToolCallChip):
                chip.apply_theme(theme, font_size)
