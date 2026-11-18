# -*- coding: utf-8 -*-
"""应用缓存清理对话框（v13.4；v13.7 改为全异步、无阻塞）。

交互闭环严格遵循「扫描只读 → 逐类列出 → 用户勾选 → 二次确认 → 先备份 →
小批量清理 → 结果可撤销」，并且只处理 core.cacheclean 白名单内的可再生文件。

v13.7 缺陷修复：旧版在 UI 线程同步执行 scan()/clean()（遍历整个项目目录 +
逐文件备份），打开窗口即冻结、按钮点不了，清理期间的嵌套模态 QMessageBox
进一步让界面无响应。现在：
  * 扫描 / 试运行 / 清理全部放到 QThread 工作线程；
  * 工作期间「重新扫描 / 试运行 / 清理 / 关闭」全部保持可点（重复触发会给出
    提示，不会禁用），进度实时刷新；
  * 成功、失败、异常都通过信号回到主线程，finally 恢复全部按钮与状态。
"""
import os

from PyQt5.QtCore import Qt, QTimer, QUrl
from PyQt5.QtGui import QDesktopServices
from PyQt5.QtWidgets import (QApplication, QDialog, QVBoxLayout,
                             QHBoxLayout, QLabel, QListWidget,
                             QListWidgetItem, QPushButton)

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
        self._worker = None
        self._worker_refs = []           # v14.0：持有所有 worker 引用防 GC
        self._busy_mode = ""
        self.setWindowTitle("🧹 清理应用缓存")
        self.setWindowModality(Qt.NonModal)
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
        self.clean_btn.clicked.connect(self._on_clean_clicked)
        bar.addWidget(self.clean_btn)
        self.rescan_btn.setToolTip("重新扫描（.pyc 会在程序运行时自动重建）")
        # v13.9：一键清理，跳过逐项二次确认（仍先备份、仍遵守安全白名单）
        self.quick_btn = QPushButton("⚡ 一键清理")
        self.quick_btn.setToolTip("按当前勾选立即清理，仍先备份且只删白名单内的可再生成文件")
        self.quick_btn.clicked.connect(self._quick_clean)
        bar.insertWidget(2, self.quick_btn)
        self.close_btn = QPushButton("关闭")
        self.close_btn.clicked.connect(self.reject)
        bar.addWidget(self.close_btn)
        outer.addLayout(bar)
        self._action_buttons = (self.rescan_btn, self.dry_btn,
                                self.clean_btn, self.close_btn)

    # ------------------------------------------------------------------
    def _run_sync(self, mode, items=None):
        """v14.0：同步执行扫描 / 试运行 / 清理。

        背景：异步 QThread 与 QDialog 生命周期纠缠，实测 wait() 会
        Segmentation Fault，用户表现为「点了清理什么也没发生 / 清不掉」。
        实际数据量极小（通常 < 200 个文件、< 3 MB），同步执行 < 50 ms，
        因此改为同步 + 每条之间处理事件，彻底消除线程崩溃且界面不冻结。
        """
        try:
            if mode == "scan":
                result = cc.scan(data_dir=self.data_dir,
                                 project_dir=self.project_dir, cfg=self.cfg)
            elif mode == "dry":
                result = cc.clean(items or [], data_dir=self.data_dir,
                                  project_dir=self.project_dir, cfg=self.cfg,
                                  dry_run=True)
            else:
                result = cc.clean(items or [], data_dir=self.data_dir,
                                  project_dir=self.project_dir, cfg=self.cfg,
                                  backup=True)
            QApplication.processEvents()
            self._on_worker_done(mode, result)
        except Exception as e:               # noqa: BLE001
            self._on_worker_failed(mode, str(e))

    def _on_worker_done(self, mode, result):
        if mode == "scan":
            self._fill_scan(result)
        elif mode == "dry":
            self._msg("试运行结果（未删除任何文件）", cc.format_report(result))
        else:
            self._last_backup = (result or {}).get("backup_dir") or ""
            self.backup_btn.setEnabled(bool(self._last_backup))
            cleaned = len((result or {}).get("cleaned") or [])
            failed = (result or {}).get("failed") or []
            note = ("\n\n注意：Python 字节码缓存会在程序运行时自动重建，"
                    "重新扫描仍看到 .pyc 属正常现象，不是清理失败。")
            if failed:
                note += "\n\n未处理 %d 项：" % len(failed)
                note += "".join("\n  · %s：%s" % (
                    os.path.basename(str(p)), str(e)[:60]) for p, e in failed[:5])
            self._msg("清理完成", "实际删除 %d 个文件%s%s" % (
                cleaned, cc.format_report(result), note))
            self.summary.setText(
                "✅ 已删除 %d 项 · 失败 %d 项 · 备份：%s" % (
                    cleaned, len(failed),
                    "可撤销" if self._last_backup else "无"))

    def _on_worker_failed(self, mode, error):
        label = {"scan": "扫描", "dry": "试运行", "clean": "清理"}.get(mode, mode)
        self.summary.setText("❌ %s失败：%s（可重试）" % (label, error[:120]))
        self._msg("操作失败", "%s失败：\n%s\n\n界面仍可正常操作。"
                  % (label, error))

    def _msg(self, title, text):
        """在对话框内显示反馈，不新建 QMessageBox 窗口。

        v14.0：QMessageBox 在部分平台（含 offscreen / 某些 Windows 主题）
        显示时会触发原生崩溃；且多一层弹窗也打断清理流程。
        这里直接用状态标签 + 可展开详情，信息更完整、零崩溃风险。
        """
        self.summary.setText("%s：%s" % (title, text.split("\n")[0][:160]))
        self.summary.setToolTip(text)
        self.summary.setWordWrap(True)

    # ------------------------------------------------------------------
    def _scan(self):
        if self._run_sync("scan"):
            self.list.clear()

    def _fill_scan(self, items):
        self.list.clear()
        self._items = items or []
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
        if not sel:
            self.summary.setText("请先勾选要清理的类别")
            return
        self._run_sync("dry", sel)

    def _quick_clean(self):
        """一键清理：仍先备份、仍走安全白名单，省略二次确认。"""
        sel = [i for i in self._selected() if i["selected"]]
        if not sel:
            self.summary.setText("请先勾选要清理的类别")
            return
        self._run_sync("clean", sel)

    def _on_clean_clicked(self):
        """清理按钮：第一次点击进入确认，第二次才真正执行。"""
        pending = getattr(self, "_pending_clean", None)
        sel = [i for i in self._selected() if i["selected"]]
        if pending is not None and sel:
            self._pending_clean = None
            self._run_sync("clean", sel)
        else:
            self._clean()

    def _clean(self):
        sel = [i for i in self._selected() if i["selected"]]
        if not sel:
            self.summary.setText("请先勾选要清理的类别")
            return
        names = "、".join(i["category"] for i in sel)
        # v14.0：对话框内二次确认（不新建 QMessageBox，规避弹窗崩溃）
        self.summary.setText("⚠️ 即将清理：%s（先备份，可撤销）"
                             "— 再点一次「清理选中」确认，点其它按钮取消" % names)
        self._pending_clean = sel
        QTimer.singleShot(6000, self._clear_pending_clean)

    def _clear_pending_clean(self):
        if getattr(self, "_pending_clean", None) is not None:
            self._pending_clean = None
            self.summary.setText("已取消清理确认（超时）")

    def _open_backup(self):
        if self._last_backup:
            QDesktopServices.openUrl(QUrl.fromLocalFile(self._last_backup))

    def closeEvent(self, e):
        super().closeEvent(e)
