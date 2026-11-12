# -*- coding: utf-8 -*-
"""后台工作线程：在非 UI 线程中执行流式 API 请求。"""
import threading

from PyQt5.QtCore import QThread, pyqtSignal



class ChatWorker(QThread):
    """流式对话线程。

    信号：
        reasoning(str)  思考过程增量
        content(str)    正文增量
        finished()      正常结束（含用户主动停止）
        failed(str)     出错信息
    """
    reasoning = pyqtSignal(str)
    content = pyqtSignal(str)
    finished = pyqtSignal()
    failed = pyqtSignal(str)

    def __init__(self, client, messages, parent=None):
        super().__init__(parent)
        self._client = client
        self._messages = messages
        self._stop = threading.Event()

    def stop(self):
        self._stop.set()

    def run(self):
        try:
            for kind, text in self._client.chat_stream(self._messages, self._stop.is_set):
                if kind == "reasoning":
                    self.reasoning.emit(text)
                else:
                    self.content.emit(text)
            self.finished.emit()
        except Exception as e:  # noqa: BLE001 - 统一转换为界面提示
            if not self._stop.is_set():
                self.failed.emit(str(e))
            else:
                self.finished.emit()


class AgentWorker(QThread):
    """智能体线程：驱动「模型 ↔ 工具」多轮循环。

    信号（在 ChatWorker 基础上增加）：
        tool_call(dict)  工具调用事件 {"name","args","result","running"}
        notice(str)      提示信息（降级 / 达到轮数上限）
    """
    reasoning = pyqtSignal(str)
    content = pyqtSignal(str)
    tool_call = pyqtSignal(dict)
    notice = pyqtSignal(str)
    finished = pyqtSignal()
    failed = pyqtSignal(str)

    def __init__(self, client, messages, enabled_tools=None,
                 max_iterations=6, parent=None):
        super().__init__(parent)
        self._client = client
        self._messages = messages
        self._enabled_tools = enabled_tools
        self._max_iterations = max_iterations
        self._stop = threading.Event()

    def stop(self):
        self._stop.set()

    def run(self):
        from core.agent.runtime import AgentRuntime
        runtime = AgentRuntime(self._client, self._enabled_tools,
                               self._max_iterations, self._stop.is_set)
        try:
            for kind, payload in runtime.run(self._messages):
                if kind == "reasoning":
                    self.reasoning.emit(payload)
                elif kind == "content":
                    self.content.emit(payload)
                elif kind == "tool":
                    self.tool_call.emit(payload)
                elif kind == "notice":
                    self.notice.emit(payload)
                elif kind == "error":
                    if not self._stop.is_set():
                        self.failed.emit(payload)
                    return
            self.finished.emit()
        except Exception as e:  # noqa: BLE001
            if not self._stop.is_set():
                self.failed.emit(str(e))
            else:
                self.finished.emit()
