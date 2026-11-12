# -*- coding: utf-8 -*-
"""开发者调试面板（v13.5）。

实时查看 core.devlog 的分级日志、环境信息与配置摘要；日志一律脱敏，
不显示 API Key / Token。跨线程日志通过 Qt 信号转到 UI 线程，避免直接在
工作线程里操作控件。
"""
import os
import platform
import sys

from PyQt5.QtCore import pyqtSignal, QTimer
from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel,
                             QPlainTextEdit, QPushButton, QComboBox,
                             QCheckBox, QFileDialog, QApplication, QMessageBox)

from core import devlog
from core.config import APP_VERSION, get_config_dir


class DevToolsDialog(QDialog):
    """调试模式与日志输出窗口。"""

    record_received = pyqtSignal(dict)

    def __init__(self, cfg, parent=None):
        super().__init__(parent)
        self.cfg = cfg
        self.setWindowTitle("🛠 开发者调试面板 · 星语 Starry")
        self.resize(820, 560)
        self._build_ui()
        self.record_received.connect(self._append_record)
        devlog.add_sink(self._sink)
        self._reload()
        self._poll = QTimer(self)
        self._poll.setInterval(1000)
        self._poll.timeout.connect(self._refresh_status)
        self._poll.start()

    def _sink(self, item):
        # 可能来自工作线程：只发信号，不在本函数里碰 UI
        self.record_received.emit(item)

    # ------------------------------------------------------------------
    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(14, 12, 14, 12)
        outer.setSpacing(8)

        head = QLabel("🛠 开发者调试模式 · 分级日志（已脱敏，默认关闭不影响正式使用）")
        head.setStyleSheet("font-size:14px;font-weight:600;color:#16293c;")
        outer.addWidget(head)

        bar1 = QHBoxLayout()
        self.enable_check = QCheckBox("启用调试日志")
        self.enable_check.setChecked(bool(self.cfg.data.get("debug_mode", False)))
        self.enable_check.stateChanged.connect(self._on_toggle_debug)
        bar1.addWidget(self.enable_check)
        bar1.addWidget(QLabel("级别"))
        self.level_combo = QComboBox()
        for lv in ("DEBUG", "INFO", "WARN", "ERROR"):
            self.level_combo.addItem(lv)
        idx = self.level_combo.findText(
            str(self.cfg.data.get("log_level", "INFO")).upper())
        if idx >= 0:
            self.level_combo.setCurrentIndex(idx)
        self.level_combo.currentTextChanged.connect(self._on_level)
        bar1.addWidget(self.level_combo)
        bar1.addStretch(1)
        self.status = QLabel("")
        self.status.setStyleSheet("color:#5b7086;font-size:12px;")
        bar1.addWidget(self.status)
        outer.addLayout(bar1)

        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.log_view.setStyleSheet(
            "QPlainTextEdit{background:#11151c;color:#d7e0ea;"
            "border:1px solid #2b3440;border-radius:9px;"
            "font-family:Consolas,'Courier New',monospace;font-size:12px;"
            "padding:8px;}")
        outer.addWidget(self.log_view, 1)

        self.env_view = QLabel("")
        self.env_view.setWordWrap(True)
        self.env_view.setStyleSheet(
            "color:#5b7086;background:#f6f8fb;border:1px solid #e3e8ef;"
            "border-radius:8px;padding:7px 9px;font-size:12px;")
        outer.addWidget(self.env_view)

        bar2 = QHBoxLayout()
        bar2.addStretch(1)
        for text, slot in (("刷新", self._reload), ("复制日志", self._copy),
                           ("导出日志", self._export), ("清空", self._clear)):
            btn = QPushButton(text)
            btn.clicked.connect(slot)
            bar2.addWidget(btn)
        close_btn = QPushButton("关闭")
        close_btn.clicked.connect(self.reject)
        bar2.addWidget(close_btn)
        outer.addLayout(bar2)

    # ------------------------------------------------------------------
    def _line(self, r):
        extra = ""
        if r.get("extra"):
            import json
            extra = "  " + json.dumps(r["extra"], ensure_ascii=False)
        return "%s  %-5s  [%s]  %s%s" % (
            r.get("time", ""), r.get("level", ""), r.get("scope", ""),
            r.get("message", ""), extra)

    def _append_record(self, r):
        self.log_view.appendPlainText(self._line(r))

    def _reload(self):
        self.log_view.setPlainText(devlog.text_report(devlog.MAX_RECORDS))
        self._refresh_status()
        self.env_view.setText(self._env_text())

    def _env_text(self):
        try:
            has_key = bool(self.cfg.api_key(self.cfg.provider))
        except Exception:                               # noqa: BLE001
            has_key = False
        return ("版本 %s  ·  %s  ·  Python %s\n"
                "数据目录：%s\n"
                "服务商：%s  ·  模型：%s  ·  API Key：%s\n"
                "开关：调试=%s  自动缩放=%s  自动路由=%s  缓存自动清理=%s"
                % (APP_VERSION, platform.platform(),
                   sys.version.split()[0], get_config_dir(),
                   self.cfg.provider, self.cfg.model(),
                   "已配置" if has_key else "未配置",
                   self.cfg.data.get("debug_mode", False),
                   self.cfg.data.get("auto_ui_scale", False),
                   self.cfg.data.get("auto_route_model", False),
                   self.cfg.data.get("auto_clean_tmp", False)))

    def _refresh_status(self):
        s = devlog.summary()
        self.status.setText("缓冲 %d/%d  ·  %s  ·  级别 %s%s" % (
            s["buffered"], s["max_records"],
            "已启用" if s["enabled"] else "已关闭", s["level"],
            ("  ·  落盘 " + os.path.basename(s["path"])) if s["path"] else ""))

    def _on_toggle_debug(self, _state):
        on = self.enable_check.isChecked()
        self.cfg.data["debug_mode"] = on
        self.cfg.save()
        devlog.configure(enabled=on,
                         level=self.level_combo.currentText(),
                         cfg=self.cfg)
        if on:
            devlog.info("devtools", "开发者调试模式已开启",
                        version=APP_VERSION)
        self._reload()

    def _on_level(self, lv):
        self.cfg.data["log_level"] = lv
        self.cfg.save()
        devlog.set_level(lv)
        self._refresh_status()

    def _copy(self):
        QApplication.clipboard().setText(self.log_view.toPlainText())
        self.status.setText("已复制日志到剪贴板")

    def _export(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "导出调试日志", "starry-debug.log", "日志 (*.log *.txt)")
        if not path:
            return
        ok, detail = devlog.export_text(path)
        QMessageBox.information(self, "导出日志",
                                "已导出：%s" % detail if ok else "导出失败：%s" % detail)

    def _clear(self):
        devlog.clear()
        self._reload()

    def closeEvent(self, event):
        devlog.remove_sink(self._sink)
        try:
            self._poll.stop()
        except Exception:                               # noqa: BLE001
            pass
        super().closeEvent(event)
