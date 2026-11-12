# -*- coding: utf-8 -*-
"""专家会诊 / 多智能体协作控制器。

复刻 WorkBuddy 的多智能体协作（Colleague/Team）范式，并做了本地化升级：

- 并行会诊（parallel）：多位专家各自独立回答同一问题，互不可见，最后由
  「主持人」综合各方观点给出最终答案（原「专家会诊」能力，向后兼容）。
- 接力协作（relay）：专家**依次**作答，后一位能看到前几位已给出的回答，
  在其基础上补充 / 修正 / 提出不同意见 —— 这才是真正的「多智能体协作」
  （互相看见、分工推进），而非简单的并行投票。

两种模式都支持「跳过主持人汇总」（仅保留原始回答，省一次请求）。
"""
from PyQt5.QtCore import QObject, pyqtSignal

from core.workers import ChatWorker

MAX_EXPERTS = 4

MODE_PARALLEL = "parallel"
MODE_RELAY = "relay"

HOST_SYSTEM = (
    "你是一场专家会诊的主持人。多位专家已分别给出回答，"
    "请综合各方意见，去重、补全与调和分歧，给出条理清晰的最终答案："
    "1. 先给出一句话结论\n"
    "2. 再分点列出关键共识与重要分歧（注明来源专家）\n"
    "3. 最后给出可执行的建议\n"
    "如专家回答与问题无关，忽略该部分。")

# 接力模式下追加到专家人设之后的协作提示
RELAY_HINT = (
    "\n\n你正在参与一场多智能体接力协作。在你之前，已有其他专家就同一问题给出过回答"
    "（会在下方以【专家名 的回答】形式提供）。请阅读他们的回答，在其基础上："
    "补充被遗漏的关键点、纠正明显错误、或提出有依据的不同意见；不要简单重复已有内容。"
    "如果认同前人的结论，请明确说明并给出增量信息。")


class ExpertPanel(QObject):
    """多专家会诊 / 多智能体协作编排（UI 线程内使用，工作线程执行请求）"""

    expert_started = pyqtSignal(str)            # 专家名
    expert_finished = pyqtSignal(str, str)      # 专家名, 回答
    expert_failed = pyqtSignal(str, str)        # 专家名, 错误
    summary_started = pyqtSignal()
    summary_chunk = pyqtSignal(str)
    finished = pyqtSignal(str)                  # 最终答案（跳过汇总时为空串）
    failed = pyqtSignal(str)

    def __init__(self, client_factory, parent=None):
        """
        client_factory: () -> ChatClient，每次调用返回一个新客户端
        （专家之间互不共享连接状态）
        """
        super().__init__(parent)
        self._client_factory = client_factory
        self._mode = MODE_PARALLEL
        self.skip_summary = False
        self._workers = []
        self._answers = []
        self._pending = 0
        self._question = ""
        self._experts = []
        self._summary_worker = None
        self._summary_text = ""
        self._relay_index = 0
        self._relay_answers = []
        self._relay_worker = None
        self._stopped = False

    # ------------------------------------------------------------------
    @property
    def running(self):
        return (bool(self._workers) or self._summary_worker is not None
                or self._relay_worker is not None)

    def stop(self):
        self._stopped = True
        for w in self._workers:
            w.stop()
        if self._summary_worker is not None:
            self._summary_worker.stop()
        if self._relay_worker is not None:
            self._relay_worker.stop()

    @staticmethod
    def estimate_requests(expert_count, skip_summary=False):
        """会诊将发起的请求总数：N 位专家 + （1 次汇总，除非跳过）"""
        n = max(0, int(expert_count))
        return n + (0 if skip_summary else 1)

    # ------------------------------------------------------------------
    def run(self, question, experts, mode=MODE_PARALLEL, skip_summary=False):
        """启动会诊。

        experts: [{"id","name","prompt"}]，至少 1 位
        mode:    MODE_PARALLEL（独立并行）/ MODE_RELAY（接力协作）
        skip_summary: True 时仅保留专家原始回答，不调用主持人汇总
        """
        question = (question or "").strip()
        experts = [e for e in (experts or []) if e.get("prompt")][:MAX_EXPERTS]
        if not question or not experts:
            self.failed.emit("请填写问题并至少选择 1 位专家")
            return
        self._question = question
        self._experts = experts
        self._mode = mode
        self.skip_summary = skip_summary
        self._answers = []
        self._pending = len(experts)
        self._workers = []
        self._summary_worker = None
        self._summary_text = ""
        self._relay_answers = []
        self._relay_index = 0
        self._relay_worker = None
        self._stopped = False
        if mode == MODE_RELAY:
            self._start_relay(0)
        else:
            self._start_parallel()

    # ------------------------------------------------------------------
    # 并行会诊
    # ------------------------------------------------------------------
    def _start_parallel(self):
        for exp in self._experts:
            client = self._client_factory()
            history = [{"role": "system", "content": exp["prompt"]},
                       {"role": "user", "content": self._question}]
            worker = ChatWorker(client, history)
            name = exp.get("name", "专家")
            buffer = {"text": ""}
            worker.content.connect(
                lambda t, b=buffer: b.__setitem__("text", b["text"] + t))
            worker.finished.connect(
                lambda n=name, b=buffer: self._on_expert_done(n, b["text"]))
            worker.failed.connect(
                lambda err, n=name: self._on_expert_failed(n, err))
            self._workers.append(worker)
            self.expert_started.emit(name)
        for w in self._workers:
            w.start()

    def _on_expert_done(self, name, text):
        if self._stopped:
            return
        self._pending -= 1
        self._answers.append((name, text))
        self.expert_finished.emit(name, text)
        if self._pending <= 0:
            self._maybe_summary()

    def _on_expert_failed(self, name, err):
        if self._stopped:
            return
        self._pending -= 1
        self.expert_failed.emit(name, err)
        if self._pending <= 0:
            self._maybe_summary()

    # ------------------------------------------------------------------
    # 接力协作
    # ------------------------------------------------------------------
    def _start_relay(self, index):
        if self._stopped:
            return
        if index >= len(self._experts):
            self._maybe_summary()
            return
        exp = self._experts[index]
        name = exp.get("name", "专家")
        # 系统提示 = 人设 + 接力协作提示
        system = exp["prompt"]
        if system:
            system = system + RELAY_HINT
        else:
            system = RELAY_HINT.lstrip("\n")
        history = [{"role": "system", "content": system}]
        # 把前面专家的回答作为上下文喂给当前专家（互相可见 = 协作）
        for pname, ptext in self._relay_answers:
            history.append({"role": "user",
                            "content": "【%s 的回答】\n%s" % (pname, ptext)})
        history.append({"role": "user", "content": self._question})
        client = self._client_factory()
        worker = ChatWorker(client, history)
        buffer = {"text": ""}
        worker.content.connect(
            lambda t, b=buffer: b.__setitem__("text", b["text"] + t))
        worker.finished.connect(
            lambda n=name, b=buffer: self._on_relay_done(n, b["text"]))
        worker.failed.connect(
            lambda err, n=name: self._on_relay_failed(n, err))
        self._relay_worker = worker
        self.expert_started.emit(name)
        worker.start()

    def _on_relay_done(self, name, text):
        if self._stopped:
            return
        self._answers.append((name, text))
        self._relay_answers.append((name, text))
        self.expert_finished.emit(name, text)
        self._relay_index += 1
        self._start_relay(self._relay_index)

    def _on_relay_failed(self, name, err):
        if self._stopped:
            return
        self.expert_failed.emit(name, err)
        self._relay_index += 1
        self._start_relay(self._relay_index)

    # ------------------------------------------------------------------
    # 汇总
    # ------------------------------------------------------------------
    def _maybe_summary(self):
        if self._stopped:
            return
        self._workers = []
        self._relay_worker = None
        if not self._answers:
            self.failed.emit("所有专家均失败，无法生成结论")
            return
        if self.skip_summary:
            self.finished.emit("")
            return
        parts = []
        for name, text in self._answers:
            parts.append("【%s 的回答】\n%s" % (name, text))
        user_content = ("问题：%s\n\n%s\n\n请综合以上意见，给出最终答案。"
                        % (self._question, "\n\n".join(parts)))
        client = self._client_factory()
        history = [{"role": "system", "content": HOST_SYSTEM},
                   {"role": "user", "content": user_content}]
        worker = ChatWorker(client, history)
        self._summary_worker = worker
        self._summary_text = ""
        self.summary_started.emit()
        worker.content.connect(self._on_summary_chunk)
        worker.finished.connect(self._on_summary_done)
        worker.failed.connect(self.failed)
        worker.start()

    def _on_summary_chunk(self, text):
        self._summary_text += text
        self.summary_chunk.emit(text)

    def _on_summary_done(self):
        self._summary_worker = None
        self.finished.emit(self._summary_text)
        self._summary_text = ""
