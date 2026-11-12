# -*- coding: utf-8 -*-
"""专家会诊对话框：多位专家并行回答，主持人汇总。

复刻 WorkBuddy 多专家并行协作：
- 勾选 2-4 位专家（来自技能系统的人设）
- 填写问题后开始会诊：实时展示每位专家的进度与回答
- 全部完成后由「主持人」流式输出综合答案
"""
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel,
                             QPushButton, QScrollArea, QWidget, QCheckBox,
                             QTextEdit, QTextBrowser, QProgressBar, QComboBox)

from app.panel import (ExpertPanel, MAX_EXPERTS, MODE_PARALLEL, MODE_RELAY)
from ui.theme import build_qss, get_theme


class ExpertPanelDialog(QDialog):
    """专家会诊主对话框"""

    def __init__(self, skills, client_factory, config, parent=None):
        super().__init__(parent)
        self.skills = skills
        self._client_factory = client_factory
        self.cfg = config
        self._theme = get_theme(config.appearance.get("theme", "light"))
        self._fs = int(config.appearance.get("font_size", 14))
        self.setStyleSheet(build_qss(self._theme, self._fs))
        self.setWindowTitle("专家会诊")
        self.setMinimumWidth(560)
        self.setMinimumHeight(560)
        self._panel = None
        self._build_ui()

    # ------------------------------------------------------------------
    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setSpacing(8)

        title = QLabel("🎭 专家会诊")
        title.setStyleSheet("font-size:%dpx;font-weight:bold;"
                            % (self._fs + 4))
        root.addWidget(title)

        hint = QLabel("选择 %d 位以内专家并行回答，最后由主持 AI 综合成最终答案。"
                      % MAX_EXPERTS)
        hint.setObjectName("MutedLabel")
        hint.setWordWrap(True)
        root.addWidget(hint)

        # ---- 专家勾选 ----
        root.addWidget(QLabel("选择专家："))
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setMaximumHeight(150)
        exp_widget = QWidget()
        exp_layout = QVBoxLayout(exp_widget)
        exp_layout.setContentsMargins(2, 2, 2, 2)
        exp_layout.setSpacing(4)
        self._checks = []
        all_skills = self.skills.all_skills()
        for i, sk in enumerate(all_skills):
            cb = QCheckBox("%s %s — %s" % (sk.get("icon", ""),
                                           sk.get("name", ""),
                                           sk.get("description", "")[:40]))
            cb.setChecked(i < 3)     # 默认勾选前 3 位
            cb.setProperty("skill_id", sk.get("id", ""))
            cb.setToolTip(sk.get("prompt", "")[:120])
            exp_layout.addWidget(cb)
            self._checks.append(cb)
            cb.toggled.connect(self._update_cost)
        exp_layout.addStretch(1)
        scroll.setWidget(exp_widget)
        root.addWidget(scroll)

        # ---- 问题 ----
        root.addWidget(QLabel("会诊问题："))
        self.question_edit = QTextEdit()
        self.question_edit.setPlaceholderText("输入要让多位专家共同分析的问题 …")
        self.question_edit.setMaximumHeight(80)
        root.addWidget(self.question_edit)

        # ---- 协作方式（多智能体协作模式） ----
        mode_row = QHBoxLayout()
        mode_row.addWidget(QLabel("协作方式："))
        self.mode_combo = QComboBox()
        self.mode_combo.addItem("并行会诊（各自独立回答）", MODE_PARALLEL)
        self.mode_combo.addItem("接力协作（后位可见前位、分工推进）", MODE_RELAY)
        self.mode_combo.setCurrentIndex(0)
        self.mode_combo.currentIndexChanged.connect(self._update_cost)
        mode_row.addWidget(self.mode_combo)
        mode_row.addStretch(1)
        root.addLayout(mode_row)

        opt_row = QHBoxLayout()
        self.skip_check = QCheckBox("跳过主持人汇总（仅保留专家原始回答）")
        self.skip_check.toggled.connect(self._update_cost)
        opt_row.addWidget(self.skip_check)
        self.cost_label = QLabel("")
        self.cost_label.setObjectName("MutedLabel")
        opt_row.addWidget(self.cost_label)
        opt_row.addStretch(1)
        root.addLayout(opt_row)
        self._update_cost()

        # ---- 控制 ----
        ctrl = QHBoxLayout()
        self.start_btn = QPushButton("▶ 开始会诊")
        self.start_btn.setObjectName("AccentButton")
        self.start_btn.setCursor(Qt.PointingHandCursor)
        self.start_btn.clicked.connect(self._on_start)
        self.stop_btn = QPushButton("■ 停止")
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self._on_stop)
        self.progress = QProgressBar()
        self.progress.setFixedWidth(160)
        self.progress.setVisible(False)
        ctrl.addWidget(self.start_btn)
        ctrl.addWidget(self.stop_btn)
        ctrl.addWidget(self.progress)
        ctrl.addStretch(1)
        root.addLayout(ctrl)

        # ---- 结果 ----
        self.result_browser = QTextBrowser()
        self.result_browser.setOpenExternalLinks(False)
        self.result_browser.setPlaceholderText(
            "会诊开始后，这里实时显示各专家回答与最终综合结论。")
        root.addWidget(self.result_browser, 1)

    # ------------------------------------------------------------------
    def _selected_experts(self):
        out = []
        for cb in self._checks:
            if cb.isChecked():
                sk = self.skills.get(cb.property("skill_id"))
                if sk:
                    out.append(sk)
        return out[:MAX_EXPERTS]

    def _update_cost(self):
        n = len(self._selected_experts())
        reqs = ExpertPanel.estimate_requests(n, self.skip_check.isChecked())
        self.cost_label.setText(
            "将发起 %d 次请求（%d 位专家%s）"
            % (reqs, n, " + 1 次汇总" if not self.skip_check.isChecked() else ""))

    def _on_start(self):
        if self._panel is not None and self._panel.running:
            return
        question = self.question_edit.toPlainText().strip()
        if not question:
            self.result_browser.setPlainText("请先输入会诊问题。")
            return
        experts = self._selected_experts()
        if not experts:
            self.result_browser.setPlainText("请至少选择 1 位专家。")
            return
        self.result_browser.clear()
        self._expert_done = 0
        self._expert_total = len(experts)
        self.progress.setVisible(True)
        self.progress.setRange(0, self._expert_total)
        self.progress.setValue(0)
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)

        self._panel = ExpertPanel(self._client_factory, self)
        self._panel.expert_started.connect(self._on_expert_started)
        self._panel.expert_finished.connect(self._on_expert_finished)
        self._panel.expert_failed.connect(self._on_expert_failed)
        self._panel.summary_started.connect(self._on_summary_started)
        self._panel.summary_chunk.connect(self._on_summary_chunk)
        self._panel.finished.connect(self._on_finished)
        self._panel.failed.connect(self._on_failed)
        mode = self.mode_combo.currentData() or MODE_PARALLEL
        skip = self.skip_check.isChecked()
        self._panel.run(question, experts, mode=mode, skip_summary=skip)

    def _on_stop(self):
        if self._panel is not None:
            self._panel.stop()
        self._reset_controls()
        self.result_browser.append("\n⏹ 已停止。")

    def _reset_controls(self):
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.progress.setVisible(False)

    # ---- 面板事件 → 界面 ----
    def _on_expert_started(self, name):
        tag = "（接力）" if self.mode_combo.currentData() == MODE_RELAY else ""
        self.result_browser.append("🔍 【%s】%s思考中…" % (name, tag))

    def _on_expert_finished(self, name, text):
        self._expert_done += 1
        self.progress.setValue(self._expert_done)
        self.result_browser.append("✅ 【%s】已回答：" % name)
        self.result_browser.append(text)
        self.result_browser.append("")

    def _on_expert_failed(self, name, err):
        self._expert_done += 1
        self.progress.setValue(self._expert_done)
        self.result_browser.append("⚠️ 【%s】失败：%s" % (name, err))

    def _on_summary_started(self):
        self.result_browser.append("🧠 主持人综合各方意见…\n")

    def _on_summary_chunk(self, text):
        # 追加纯文本（QTextBrowser 保留换行）
        cursor = self.result_browser.textCursor()
        cursor.movePosition(cursor.End)
        cursor.insertText(text)
        self.result_browser.setTextCursor(cursor)

    def _on_finished(self, text):
        self._reset_controls()
        if self._panel is not None and self._panel.skip_summary:
            self.result_browser.append(
                "\n—— 以上为各位专家的原始回答（未做汇总）——")
        else:
            self.result_browser.append("\n—— 以上为最终综合结论 ——")

    def _on_failed(self, err):
        self._reset_controls()
        self.result_browser.append("\n⚠️ 会诊失败：%s" % err)

    # ------------------------------------------------------------------
    def apply_theme(self, theme_name, font_size):
        self._theme = get_theme(theme_name)
        self._fs = int(font_size)
        self.setStyleSheet(build_qss(self._theme, self._fs))
