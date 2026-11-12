# -*- coding: utf-8 -*-
"""自动化任务对话框：定时 / 间隔执行提示词，结果入会话并提醒。

复刻 WorkBuddy 自动化工作流（本地简化版）：
- 新建 / 编辑 / 删除 / 启停自动化任务
- 「立即运行」不等触发时间，马上执行一次
- 任务到点后由主程序在后台执行对话，结果写入「⚙ 自动化」会话
"""
import time

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel,
                             QPushButton, QScrollArea, QWidget, QFrame,
                             QLineEdit, QTextEdit, QComboBox, QSpinBox,
                             QMessageBox)

from core.automation import (MODE_DAILY, MODE_INTERVAL,
                             MODE_LABELS, MIN_EVERY, MAX_EVERY, describe,
                             next_run)
from ui.theme import build_qss, get_theme


def _fmt_ts(ts):
    if not ts:
        return "从未运行"
    d = time.localtime(ts)
    return "%d-%02d-%02d %02d:%02d" % (d[0], d[1], d[2], d[3], d[4])


class TaskRow(QFrame):
    """单个自动化任务行"""

    enabled_changed = pyqtSignal(str, bool)
    edit_requested = pyqtSignal(str)
    delete_requested = pyqtSignal(str)
    run_requested = pyqtSignal(str)

    def __init__(self, task, theme, font_size, parent=None):
        super().__init__(parent)
        self.task = task
        self._theme = theme
        self._fs = font_size
        self.setObjectName("TaskRow")
        self._build_ui()
        self._apply_theme(theme, font_size)

    def _build_ui(self):
        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 8, 8, 8)
        lay.setSpacing(6)

        text_col = QVBoxLayout()
        text_col.setSpacing(2)
        self.name_label = QLabel("%s %s" % (
            "⏰" if self.task.get("enabled", True) else "⏸",
            self.task.get("name", "")))
        nxt = next_run(self.task)
        meta = "%s · 下次 %s" % (describe(self.task),
                                 _fmt_ts(nxt) if nxt else "—")
        self.meta_label = QLabel(meta)
        self.meta_label.setObjectName("MutedLabel")
        self.prompt_label = QLabel(self.task.get("prompt", "")[:60])
        self.prompt_label.setObjectName("MutedLabel")
        text_col.addWidget(self.name_label)
        text_col.addWidget(self.meta_label)
        text_col.addWidget(self.prompt_label)

        btn_col = QVBoxLayout()
        btn_col.setSpacing(3)
        self.run_btn = QPushButton("▶ 立即运行")
        self.run_btn.setObjectName("FlatButton")
        self.run_btn.setCursor(Qt.PointingHandCursor)
        self.run_btn.setFixedHeight(24)
        self.run_btn.clicked.connect(
            lambda: self.run_requested.emit(self.task["id"]))
        self.toggle_btn = QPushButton("已启用" if self.task.get("enabled", True)
                                      else "已停用")
        self.toggle_btn.setObjectName("FlatButton")
        self.toggle_btn.setCursor(Qt.PointingHandCursor)
        self.toggle_btn.setFixedHeight(24)
        self.toggle_btn.clicked.connect(self._on_toggle)
        row2 = QHBoxLayout()
        row2.setSpacing(3)
        self.edit_btn = QPushButton("✎")
        self.edit_btn.setObjectName("FlatButton")
        self.edit_btn.setToolTip("编辑")
        self.edit_btn.setCursor(Qt.PointingHandCursor)
        self.edit_btn.setFixedSize(24, 24)
        self.edit_btn.clicked.connect(
            lambda: self.edit_requested.emit(self.task["id"]))
        self.del_btn = QPushButton("🗑")
        self.del_btn.setObjectName("FlatButton")
        self.del_btn.setToolTip("删除")
        self.del_btn.setCursor(Qt.PointingHandCursor)
        self.del_btn.setFixedSize(24, 24)
        self.del_btn.clicked.connect(self._confirm_delete)
        row2.addWidget(self.edit_btn)
        row2.addWidget(self.del_btn)
        btn_col.addWidget(self.run_btn)
        btn_col.addWidget(self.toggle_btn)
        btn_col.addLayout(row2)

        lay.addLayout(text_col, 1)
        lay.addLayout(btn_col)

    def _on_toggle(self):
        on = not self.task.get("enabled", True)
        self.enabled_changed.emit(self.task["id"], on)

    def _confirm_delete(self):
        ret = QMessageBox.question(
            self, "删除任务",
            "确定删除自动化任务「%s」吗？" % self.task.get("name"),
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if ret == QMessageBox.Yes:
            self.delete_requested.emit(self.task["id"])

    def _apply_theme(self, theme, font_size):
        self._theme = theme
        self._fs = font_size
        self.setStyleSheet(
            "QFrame#TaskRow{background-color:%s;border:1px solid %s;"
            "border-radius:8px;}"
            % (theme["bubble_ai_bg"], theme["border"]))
        self.name_label.setStyleSheet(
            "color:%s;font-weight:bold;" % theme["text"])
        self.meta_label.setStyleSheet("color:%s;" % theme["muted"])
        self.prompt_label.setStyleSheet(
            "color:%s;font-size:%dpx;" % (theme["muted"], max(10, self._fs - 2)))


class AutomationEditDialog(QDialog):
    """新建 / 编辑自动化任务的表单"""

    def __init__(self, skills, task=None, parent=None):
        super().__init__(parent)
        self.skills = skills          # SkillManager
        self.task = task or {}
        cfg = parent.cfg if parent is not None and hasattr(parent, "cfg") else None
        theme_name = (cfg.appearance.get("theme", "light")
                      if cfg is not None else "light")
        self._theme = get_theme(theme_name)
        self._fs = int(cfg.appearance.get("font_size", 14)) if cfg else 14
        self.setStyleSheet(build_qss(self._theme, self._fs))
        self.setWindowTitle("编辑自动化任务" if task else "新建自动化任务")
        self.setMinimumWidth(460)
        self._build_ui()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setSpacing(8)

        root.addWidget(QLabel("任务名称"))
        self.name_edit = QLineEdit(self.task.get("name", ""))
        self.name_edit.setPlaceholderText("例如：早间行业简报")
        root.addWidget(self.name_edit)

        root.addWidget(QLabel("提示词（到点后发送给 AI 的内容）"))
        self.prompt_edit = QTextEdit()
        self.prompt_edit.setPlainText(self.task.get("prompt", ""))
        self.prompt_edit.setPlaceholderText(
            "例如：检索今天 AI 领域的重要新闻，用 5 条要点汇总")
        self.prompt_edit.setMaximumHeight(110)
        root.addWidget(self.prompt_edit)

        mode_row = QHBoxLayout()
        mode_row.addWidget(QLabel("触发方式"))
        self.mode_combo = QComboBox()
        self.mode_combo.addItem(MODE_LABELS[MODE_DAILY], MODE_DAILY)
        self.mode_combo.addItem(MODE_LABELS[MODE_INTERVAL], MODE_INTERVAL)
        cur_mode = self.task.get("mode", MODE_DAILY)
        self.mode_combo.setCurrentIndex(
            0 if cur_mode == MODE_DAILY else 1)
        self.mode_combo.currentIndexChanged.connect(self._on_mode_changed)
        mode_row.addWidget(self.mode_combo)
        mode_row.addSpacing(12)
        self.time_label = QLabel("时间")
        self.time_edit = QLineEdit(self.task.get("time") or "09:00")
        self.time_edit.setPlaceholderText("HH:MM")
        self.time_edit.setFixedWidth(70)
        self.every_label = QLabel("间隔（分钟）")
        self.every_spin = QSpinBox()
        self.every_spin.setRange(MIN_EVERY, MAX_EVERY)
        self.every_spin.setValue(int(self.task.get("every") or 60))
        mode_row.addWidget(self.time_label)
        mode_row.addWidget(self.time_edit)
        mode_row.addWidget(self.every_label)
        mode_row.addWidget(self.every_spin)
        mode_row.addStretch(1)
        root.addLayout(mode_row)

        root.addWidget(QLabel("技能（可选，选择后以该专家身份执行）"))
        self.skill_combo = QComboBox()
        self.skill_combo.addItem("不使用技能", "")
        for sk in self.skills.all_skills():
            self.skill_combo.addItem(
                "%s %s" % (sk.get("icon", ""), sk.get("name", "")),
                sk.get("id", ""))
        cur_skill = self.task.get("skill", "")
        if cur_skill:
            idx = self.skill_combo.findData(cur_skill)
            if idx >= 0:
                self.skill_combo.setCurrentIndex(idx)
        root.addWidget(self.skill_combo)

        row = QHBoxLayout()
        row.addStretch(1)
        cancel_btn = QPushButton("取消")
        cancel_btn.clicked.connect(self.reject)
        ok_btn = QPushButton("保存")
        ok_btn.setObjectName("AccentButton")
        ok_btn.setCursor(Qt.PointingHandCursor)
        ok_btn.clicked.connect(self._on_accept)
        row.addWidget(cancel_btn)
        row.addWidget(ok_btn)
        root.addLayout(row)

        self._on_mode_changed()

    def _on_mode_changed(self):
        daily = self.mode_combo.currentData() == MODE_DAILY
        self.time_label.setVisible(daily)
        self.time_edit.setVisible(daily)
        self.every_label.setVisible(not daily)
        self.every_spin.setVisible(not daily)

    def _on_accept(self):
        if not self.prompt_edit.toPlainText().strip():
            QMessageBox.information(self, "提示", "请填写任务提示词")
            return
        if self.mode_combo.currentData() == MODE_DAILY:
            t = self.time_edit.text().strip()
            parts = t.split(":")
            if len(parts) != 2 or not (parts[0].isdigit() and parts[1].isdigit()) \
                    or not (0 <= int(parts[0]) <= 23 and 0 <= int(parts[1]) <= 59):
                QMessageBox.information(self, "提示",
                                        "时间格式应为 HH:MM（如 09:00）")
                return
        self.accept()

    def values(self):
        return {
            "name": self.name_edit.text().strip() or "自动化任务",
            "prompt": self.prompt_edit.toPlainText().strip(),
            "mode": self.mode_combo.currentData(),
            "time": self.time_edit.text().strip(),
            "every": self.every_spin.value(),
            "skill": self.skill_combo.currentData() or "",
        }


class AutomationDialog(QDialog):
    """自动化任务管理主对话框"""

    run_now_requested = pyqtSignal(str)     # 立即运行任务 id

    def __init__(self, manager, skills, config, parent=None):
        super().__init__(parent)
        self.manager = manager
        self.skills = skills
        self.cfg = config
        self._theme = get_theme(config.appearance.get("theme", "light"))
        self._fs = int(config.appearance.get("font_size", 14))
        self.setStyleSheet(build_qss(self._theme, self._fs))
        self.setWindowTitle("自动化任务")
        self.setMinimumWidth(560)
        self.setMinimumHeight(480)
        self._build_ui()
        self._reload()

    # ------------------------------------------------------------------
    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setSpacing(8)

        top = QHBoxLayout()
        title = QLabel("⏰ 自动化任务")
        title.setStyleSheet("font-size:%dpx;font-weight:bold;"
                            % (self._fs + 4))
        top.addWidget(title)
        top.addStretch(1)
        self.add_btn = QPushButton("＋ 新建任务")
        self.add_btn.setObjectName("AccentButton")
        self.add_btn.setCursor(Qt.PointingHandCursor)
        self.add_btn.clicked.connect(self._on_add)
        top.addWidget(self.add_btn)
        root.addLayout(top)

        hint = QLabel("到点后自动向 AI 发送任务提示词，结果写入「⚙ 自动化」会话。"
                      "关闭软件期间错过的任务，将在下次启动后补行一次。")
        hint.setObjectName("MutedLabel")
        hint.setWordWrap(True)
        root.addWidget(hint)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.list_widget = QWidget()
        self.list_layout = QVBoxLayout(self.list_widget)
        self.list_layout.setContentsMargins(2, 2, 2, 2)
        self.list_layout.setSpacing(6)
        self.list_layout.addStretch(1)
        scroll.setWidget(self.list_widget)
        root.addWidget(scroll, 1)

        bottom = QHBoxLayout()
        self.count_label = QLabel("")
        self.count_label.setObjectName("MutedLabel")
        bottom.addWidget(self.count_label, 1)
        close_btn = QPushButton("关闭")
        close_btn.clicked.connect(self.accept)
        bottom.addWidget(close_btn)
        root.addLayout(bottom)

    # ------------------------------------------------------------------
    def _reload(self):
        while self.list_layout.count() > 1:
            item = self.list_layout.takeAt(0)
            w = item.widget() if item else None
            if w is not None:
                w.deleteLater()
        tasks = self.manager.tasks()
        for task in tasks:
            row = TaskRow(task, self._theme, self._fs)
            row.enabled_changed.connect(self._on_enable)
            row.edit_requested.connect(self._on_edit)
            row.delete_requested.connect(self._on_delete)
            row.run_requested.connect(self.run_now_requested)
            self.list_layout.insertWidget(self.list_layout.count() - 1, row)
        active = len([t for t in tasks if t.get("enabled", True)])
        self.count_label.setText("共 %d 个任务 · %d 个已启用"
                                 % (len(tasks), active))

    # ------------------------------------------------------------------
    def _on_add(self):
        dlg = AutomationEditDialog(self.skills, parent=self)
        if dlg.exec_() == QDialog.Accepted:
            v = dlg.values()
            self.manager.add(v["name"], v["prompt"], v["mode"],
                             v["time"], v["every"], v["skill"])
            self._reload()

    def _on_edit(self, task_id):
        task = self.manager.get(task_id)
        if task is None:
            return
        dlg = AutomationEditDialog(self.skills, task=task, parent=self)
        if dlg.exec_() == QDialog.Accepted:
            v = dlg.values()
            self.manager.update(task_id, **v)
            self._reload()

    def _on_delete(self, task_id):
        self.manager.remove(task_id)
        self._reload()

    def _on_enable(self, task_id, on):
        self.manager.set_enabled(task_id, on)
        self._reload()

    # ------------------------------------------------------------------
    def apply_theme(self, theme_name, font_size):
        theme = get_theme(theme_name)
        self._theme = theme
        self._fs = int(font_size)
        self.setStyleSheet(build_qss(theme, self._fs))
        for row in self.list_widget.findChildren(TaskRow):
            row._apply_theme(theme, self._fs)
        self._reload()
