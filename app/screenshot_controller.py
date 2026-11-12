# -*- coding: utf-8 -*-
"""截图提问流程控制器。

职责（从 AssistantApp 剥离的独立关注点）：
- 隐藏聊天窗与悬浮球 → 延时展示全屏选区遮罩
- 选区完成 → 生成图片附件回填输入框，提示发送给视觉模型
- 取消 / 完成 → 恢复此前的界面显隐状态
"""
from PyQt5.QtCore import QObject, QTimer

from core.attachment import image_attachment
from core.screen import capture_name
from ui.screenshot_overlay import ScreenshotOverlay


class ScreenshotController(QObject):
    """「截图提问」的界面流程编排（UI 线程内使用）"""

    def __init__(self, window, ball, parent=None, theme_provider=None):
        super().__init__(parent)
        self.window = window
        self.ball = ball
        self._theme_provider = theme_provider
        self._overlay = None
        self._was_window_visible = False
        self._pending_question = None       # 「看屏幕」待填入的预设问题

    def start(self):
        self._was_window_visible = self.window.isVisible()
        self.window.hide()
        self.ball.hide()
        QTimer.singleShot(220, self._show_overlay)

    # ------------------------------------------------------------------
    # 「看屏幕」问答：一键抓全屏（不用框选），可选直接填入预设问题
    # ------------------------------------------------------------------
    def capture_screen(self, question=None):
        """捕获整个屏幕作为附件；question 非空时一并填入输入框。

        对标 Moonwalker / Jini：省掉「先框选、再想问题」两步。
        """
        self._pending_question = question
        self._was_window_visible = self.window.isVisible()
        self.window.hide()
        self.ball.hide()
        QTimer.singleShot(220, self._grab_screen)

    def _grab_screen(self):
        from PyQt5.QtCore import QDateTime
        from PyQt5.QtWidgets import QApplication
        screen = QApplication.primaryScreen()
        img = screen.grabWindow(0) if screen is not None else None
        if img is None or img.isNull():
            self.window.show_hint("未能捕获屏幕画面")
        else:
            stamp = QDateTime.currentDateTime().toString("HHmmss")
            self.window.add_attachment(image_attachment(img, capture_name(stamp)))
            q = self._pending_question
            if q:
                self.window.input.setPlainText(q)
                self.window.show_hint("已捕获屏幕，问题已填入，可直接发送")
            else:
                self.window.show_hint(
                    "已捕获屏幕，输入问题后发送（图片将发给视觉模型）")
        self._pending_question = None
        self._restore()

    def _show_overlay(self):
        theme = self._theme_provider() if self._theme_provider else None
        self._overlay = ScreenshotOverlay(theme=theme)
        self._overlay.captured.connect(self._on_captured)
        self._overlay.cancelled.connect(self._restore)
        self._overlay.show()

    def _on_captured(self, image):
        if image is None or image.isNull():
            self.window.show_hint("截图失败")
        else:
            from PyQt5.QtCore import QDateTime
            name = "截图_%s.png" % QDateTime.currentDateTime().toString("HHmmss")
            att = image_attachment(image, name)
            self.window.add_attachment(att)
            self.window.show_hint("截图已就绪，输入问题后发送（图片将发给视觉模型）")
        self._restore()

    def _restore(self):
        if self._overlay is not None:
            self._overlay.close()
            self._overlay.deleteLater()
            self._overlay = None
        if self._was_window_visible:
            self.window.show()
            self.window.raise_()
            self.window.activateWindow()
            self.window.input.setFocus()
        else:
            self.ball.show()
            self.ball.raise_()
