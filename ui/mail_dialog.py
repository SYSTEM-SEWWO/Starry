# -*- coding: utf-8 -*-
"""Agent Mail 对话框：配置 IMAP 账户，收取并让 AI 摘要 / 草拟回复。

本地优先、零新依赖（IMAP 走标准库），凭据仅存于本机配置，与现有 api_keys
同机同权；UI 明确提示使用「应用专用密码」。
"""
import threading

from PyQt5.QtCore import Qt, pyqtSignal, QThread
from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel,
                             QPushButton, QLineEdit, QTextBrowser, QCheckBox,
                             QGroupBox, QSpinBox, QProgressBar, QFrame)

from core.mail import MailClient, summarize_messages, draft_reply
from ui.theme import build_qss, get_theme


class MailWorker(QThread):
    """后台线程：连邮箱 → 收件 → 逐封摘要 + 总览。"""
    progress = pyqtSignal(str)
    message_summary = pyqtSignal(dict, str)
    overall_chunk = pyqtSignal(str)
    finished = pyqtSignal(str)
    failed = pyqtSignal(str)

    def __init__(self, account, chat_factory, limit, parent=None):
        super().__init__(parent)
        self._account = account
        self._chat_factory = chat_factory
        self._limit = limit
        self._stop = threading.Event()

    def stop(self):
        self._stop.set()

    def run(self):
        try:
            client = MailClient(**self._account)
            self.progress.emit("正在连接邮箱 %s …" % self._account.get("host"))
            messages = client.fetch_recent(self._limit)
            client.close()
            if not messages:
                self.failed.emit("未取到邮件（请检查文件夹或凭据）。")
                return
            self.progress.emit("已收取 %d 封邮件，开始摘要 …" % len(messages))

            def on_message(m, s):
                if not self._stop.is_set():
                    self.message_summary.emit(m, s)

            def on_overall(t):
                if not self._stop.is_set():
                    self.overall_chunk.emit(t)

            summarize_messages(
                messages, self._chat_factory, overall=True,
                should_stop=self._stop.is_set,
                on_message=on_message, on_overall=on_overall)
            if not self._stop.is_set():
                self.finished.emit("")
        except Exception as e:  # noqa: BLE001
            if not self._stop.is_set():
                self.failed.emit(str(e))


def _hr():
    f = QFrame()
    f.setFrameShape(QFrame.HLine)
    f.setFrameShadow(QFrame.Sunken)
    return f


class MailDialog(QDialog):
    """Agent Mail 主对话框"""

    def __init__(self, cfg, chat_factory, parent=None):
        super().__init__(parent)
        self.cfg = cfg
        self._chat_factory = chat_factory
        self._worker = None
        self._theme = get_theme(cfg.appearance.get("theme", "light"))
        self._fs = int(cfg.appearance.get("font_size", 14))
        self._account = {}
        self._load_account()
        self.setStyleSheet(build_qss(self._theme, self._fs))
        self.setWindowTitle("Agent Mail · 邮件智能体")
        self.setMinimumWidth(640)
        self.setMinimumHeight(560)
        self._build_ui()

    # ------------------------------------------------------------------
    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setSpacing(8)

        title = QLabel("✉️ Agent Mail · 邮件智能体")
        title.setStyleSheet("font-size:%dpx;font-weight:bold;" % (self._fs + 4))
        root.addWidget(title)

        hint = QLabel("本地优先：凭据仅存于本机配置（与 API Key 同机同权），"
                      "不上传任何第三方。建议使用邮箱服务商的「应用专用密码」。"
                      "IMAP 走系统标准库，零新依赖。")
        hint.setObjectName("MutedLabel")
        hint.setWordWrap(True)
        root.addWidget(hint)

        # ---- 账户配置 ----
        box = QGroupBox("IMAP 账户")
        bg = QVBoxLayout(box)
        bg.setSpacing(6)

        def row(label, widget):
            r = QHBoxLayout()
            r.addWidget(QLabel(label))
            r.addWidget(widget, 1)
            return r

        self.host_edit = QLineEdit(self._account.get("host", "imap.gmail.com"))
        self.port_edit = QLineEdit(str(self._account.get("port", 993)))
        self.user_edit = QLineEdit(self._account.get("user", ""))
        self.pass_edit = QLineEdit(self._account.get("password", ""))
        self.pass_edit.setEchoMode(QLineEdit.Password)
        self.folder_edit = QLineEdit(self._account.get("folder", "INBOX"))
        self.ssl_check = QCheckBox("使用 SSL/TLS")
        self.ssl_check.setChecked(bool(self._account.get("use_ssl", True)))

        bg.addLayout(row("服务器", self.host_edit))
        bg.addLayout(row("端口", self.port_edit))
        bg.addLayout(row("邮箱账号", self.user_edit))
        bg.addLayout(row("应用专用密码", self.pass_edit))
        bg.addLayout(row("文件夹", self.folder_edit))
        bg.addWidget(self.ssl_check)
        root.addWidget(box)

        # ---- 控制 ----
        ctrl = QHBoxLayout()
        self.limit_spin = QSpinBox()
        self.limit_spin.setRange(1, 50)
        self.limit_spin.setValue(8)
        ctrl.addWidget(QLabel("收取最近"))
        ctrl.addWidget(self.limit_spin)
        ctrl.addWidget(QLabel("封"))
        self.test_btn = QPushButton("测试连接")
        self.test_btn.clicked.connect(self._on_test)
        self.fetch_btn = QPushButton("收取并摘要")
        self.fetch_btn.setObjectName("AccentButton")
        self.fetch_btn.clicked.connect(self._on_fetch)
        self.stop_btn = QPushButton("■ 停止")
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self._on_stop)
        ctrl.addWidget(self.test_btn)
        ctrl.addWidget(self.fetch_btn)
        ctrl.addWidget(self.stop_btn)
        ctrl.addStretch(1)
        root.addLayout(ctrl)

        self.status = QLabel("")
        self.status.setObjectName("MutedLabel")
        root.addWidget(self.status)

        self.result_browser = QTextBrowser()
        self.result_browser.setOpenExternalLinks(False)
        self.result_browser.setPlaceholderText(
            "配置账户后点击「收取并摘要」，这里会逐封展示 AI 摘要与总览。")
        root.addWidget(self.result_browser, 1)

    # ------------------------------------------------------------------
    def _load_account(self):
        m = self.cfg.data.get("mail") or {}
        self._account = {
            "host": m.get("host", "imap.gmail.com"),
            "port": m.get("port", 993),
            "user": m.get("user", ""),
            "password": m.get("password", ""),
            "use_ssl": m.get("use_ssl", True),
            "folder": m.get("folder", "INBOX"),
        }

    def _save_account(self):
        try:
            port = int(self.port_edit.text().strip() or 993)
        except ValueError:
            port = 993
        self.cfg.data["mail"] = {
            "host": self.host_edit.text().strip(),
            "port": port,
            "user": self.user_edit.text().strip(),
            "password": self.pass_edit.text(),
            "use_ssl": self.ssl_check.isChecked(),
            "folder": self.folder_edit.text().strip() or "INBOX",
        }
        self.cfg.save()

    def _account_dict(self):
        try:
            port = int(self.port_edit.text().strip() or 993)
        except ValueError:
            port = 993
        return {
            "host": self.host_edit.text().strip(),
            "port": port,
            "user": self.user_edit.text().strip(),
            "password": self.pass_edit.text(),
            "use_ssl": self.ssl_check.isChecked(),
            "folder": self.folder_edit.text().strip() or "INBOX",
        }

    # ------------------------------------------------------------------
    def _on_test(self):
        self._save_account()
        acc = self._account_dict()
        if not acc["host"] or not acc["user"] or not acc["password"]:
            self.status.setText("请先填写服务器、账号与密码。")
            return
        try:
            c = MailClient(**acc)
            c.connect()
            c.close()
            self.status.setText("✅ 连接成功：%s" % acc["host"])
        except Exception as e:  # noqa: BLE001
            self.status.setText("❌ 连接失败：%s" % e)

    def _on_fetch(self):
        if self._worker is not None and self._worker.isRunning():
            return
        self._save_account()
        acc = self._account_dict()
        if not acc["host"] or not acc["user"] or not acc["password"]:
            self.status.setText("请先填写服务器、账号与密码。")
            return
        self.result_browser.clear()
        self.status.setText("正在工作 …")
        self.fetch_btn.setEnabled(False)
        self.test_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self._worker = MailWorker(acc, self._chat_factory,
                                 self.limit_spin.value(), self)
        self._worker.progress.connect(self._on_progress)
        self._worker.message_summary.connect(self._on_message_summary)
        self._worker.overall_chunk.connect(self._on_overall)
        self._worker.finished.connect(self._on_finished)
        self._worker.failed.connect(self._on_failed)
        self._worker.start()

    def _on_stop(self):
        if self._worker is not None:
            self._worker.stop()
        self._reset_controls()
        self.result_browser.append("\n⏹ 已停止。")

    def _reset_controls(self):
        self.fetch_btn.setEnabled(True)
        self.test_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)

    # ---- 面板事件 → 界面 ----
    def _on_progress(self, text):
        self.status.setText(text)

    def _on_message_summary(self, m, summary):
        self.result_browser.append("✉️ 【%s】" % (m.get("subject") or "(无主题)"))
        self.result_browser.append("发件人：%s" % (m.get("from") or ""))
        self.result_browser.append(summary)
        self.result_browser.append("")

    def _on_overall(self, text):
        if text:
            self.result_browser.append("📌 总览 / 待办清单：")
            self.result_browser.append(text)
            self.result_browser.append("")

    def _on_finished(self, _text):
        self._reset_controls()
        self.status.setText("✅ 完成。")

    def _on_failed(self, err):
        self._reset_controls()
        self.status.setText("❌ %s" % err)
        self.result_browser.append("\n⚠️ 失败：%s" % err)

    # ------------------------------------------------------------------
    def apply_theme(self, theme_name, font_size):
        self._theme = get_theme(theme_name)
        self._fs = int(font_size)
        self.setStyleSheet(build_qss(self._theme, self._fs))
