# -*- coding: utf-8 -*-
"""应用缓存清理对话框（v13.4）。

交互闭环严格遵循「扫描只读 → 逐类列出 → 用户勾选 → 二次确认 → 先备份 →
小批量清理 → 结果可撤销」，并且只处理 core.cacheclean 白名单内的可再生文件。
"""
from PyQt5.QtCore import Qt, QUrl
from PyQt5.QtGui import QDesktopServices
from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel,
                             QListWidget, QListWidgetItem, QPushButton,
                             QMessageBox)

from core import cacheclean as cc


class CacheDialog(QDialog):
    """清理所有应用缓存（不触碰用户数据）。"""

    def __init__(self, cfg, parent=None, data_dir=None, project_dir=None):
        super().__init__(parent)
        self.cfg = cfg
        self.data_dir = data_dir
        self.project_dir = project_dir
        self._items = []
        self._last_backup = ""
        self.setWindowTitle("🧹 清理应用缓存")
        self.resize(720, 520)
        self._build_ui()
        self._scan()

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(14, 12, 14, 12)
        outer.setSpacing(8)

        head = QLabel("🧹 只清理应用自身产生的可再生缓存（字节码 / 临时文件 / 日志 / 列表缓存）")
        head.setStyleSheet("font-size:14px;font-weight:600;color:#16293c;")
        outer.addWidget(head)

        protect = QLabel(
            "🔒 永不清理：config.json（含 API Key）、会话、资料库、长期记忆、"
            "自动化、统计、GGUF 模型与浏览器登录态。")
        protect.setWordWrap(True)
        protect.setStyleSheet(
            "color:#8a5a00;background:#fff8e6;border:1px solid #f0dca8;"
            "border-radius:8px;padding:7px 10px;font-size:12px;")
        outer.addWidget(protect)

        self.list = QListWidget()
        self.list.setStyleSheet(
            "QListWidget{background:#fafbfc;border:1px solid #e3e8ef;"
            "border-radius:10px;outline:0;}"
            "QListWidget::item{border-radius:8px;padding:7px 10px;"
            "border-bottom:1px solid #eef1f5;}"
            "QListWidget::item:selected{background:#e6f2ff;}")
        self.list.itemChanged.connect(self._update_summary)
        outer.addWidget(self.list, 1)

        self.summary = QLabel("")
        self.summary.setStyleSheet("color:#5b7086;font-size:12px;")
        outer.addWidget(self.summary)

        bar = QHBoxLayout()
        bar.addStretch(1)
        self.rescan_btn = QPushButton("重新扫描")
        self.rescan_btn.clicked.connect(self._scan)
        bar.addWidget(self.rescan_btn)
        self.dry_btn = QPushButton("试运行")
        self.dry_btn.setToolTip("只校验与统计，不删除任何文件")
        self.dry_btn.clicked.connect(self._dry_run)
        bar.addWidget(self.dry_btn)
        self.backup_btn = QPushButton("打开备份目录")
        self.backup_btn.setEnabled(False)
        self.backup_btn.clicked.connect(self._open_backup)
        bar.addWidget(self.backup_btn)
        self.clean_btn = QPushButton("清理选中（先备份）")
        self.clean_btn.clicked.connect(self._clean)
        bar.addWidget(self.clean_btn)
        close_btn = QPushButton("关闭")
        close_btn.clicked.connect(self.reject)
        bar.addWidget(close_btn)
        outer.addLayout(bar)

    # ------------------------------------------------------------------
    def _scan(self):
        self.list.clear()
        self._items = cc.scan(data_dir=self.data_dir,
                              project_dir=self.project_dir, cfg=self.cfg)
        for it in self._items:
            label = "%s · %d 项 · %s\n    %s" % (
                it["category"], it["count"], cc._fmt_size(it["size"]), it["desc"])
            item = QListWidgetItem(label)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked if it["default_selected"]
                               else Qt.Unchecked)
            item.setData(Qt.UserRole, it["id"])
            self.list.addItem(item)
        if not self._items:
            self.summary.setText("✅ 没有发现可清理的应用缓存，无需操作。")
        self._update_summary()

    def _selected(self):
        chosen = set()
        for i in range(self.list.count()):
            item = self.list.item(i)
            if item.checkState() == Qt.Checked:
                chosen.add(item.data(Qt.UserRole))
        out = []
        for it in self._items:
            copy = dict(it)
            copy["selected"] = it["id"] in chosen
            out.append(copy)
        return out

    def _update_summary(self, *_args):
        sel = [i for i in self._selected() if i["selected"]]
        if not self._items:
            return
        self.summary.setText("已选 %d 类 · 预计释放 %s · 清理前会自动备份，可撤销" % (
            len(sel), cc._fmt_size(sum(i["size"] for i in sel))))
        self.clean_btn.setEnabled(bool(sel))

    # ------------------------------------------------------------------
    def _dry_run(self):
        sel = [i for i in self._selected() if i["selected"]]
        report = cc.clean(sel, data_dir=self.data_dir,
                          project_dir=self.project_dir, cfg=self.cfg,
                          dry_run=True)
        QMessageBox.information(self, "试运行结果（未删除任何文件）",
                                cc.format_report(report))

    def _clean(self):
        sel = [i for i in self._selected() if i["selected"]]
        if not sel:
            self.summary.setText("请先勾选要清理的类别")
            return
        names = "\n".join("  · %s（%d 项）" % (i["category"], i["count"])
                          for i in sel)
        box = QMessageBox(self)
        box.setWindowTitle("确认清理应用缓存")
        box.setIcon(QMessageBox.Warning)
        box.setText("<b>⚠️ 此操作非常危险，可能导致不可逆的数据损失！</b>")
        box.setInformativeText(
            "即将清理以下缓存：\n%s\n\n"
            "• 清理前会自动完整备份到 数据目录/cache_backup/，可撤销；\n"
            "• 每批最多 10 个文件，任一失败立即停止；\n"
            "• 只删除明确的单个缓存文件，不递归删除目录；\n"
            "• 用户数据与 API Key 不在清理范围。\n\n"
            "确定继续吗？" % names)
        box.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
        box.setDefaultButton(QMessageBox.No)
        if box.exec_() != QMessageBox.Yes:
            self.summary.setText("已取消，未删除任何文件")
            return
        report = cc.clean(sel, data_dir=self.data_dir,
                          project_dir=self.project_dir, cfg=self.cfg,
                          backup=True)
        self._last_backup = report.get("backup_dir") or ""
        self.backup_btn.setEnabled(bool(self._last_backup))
        QMessageBox.information(self, "清理完成", cc.format_report(report))
        self._scan()

    def _open_backup(self):
        if self._last_backup:
            QDesktopServices.openUrl(QUrl.fromLocalFile(self._last_backup))
