# -*- coding: utf-8 -*-
"""星语 Starry v13.0 · 整体项目工作台（WorkBuddy 式，电脑端专属）。

把 v13 三层纯逻辑可视化为一处：
    整体项目（core.project）  →  左侧任务树 + 进度条
    多线并行（core.parallel） →  「并行执行」按依赖分波，结果回填
    自动更新（core.updatecheck）→ 「检查更新」校验本地 update.json

设计约束：
    - 本文件只做展示与交互，**不含任何业务逻辑**，逻辑全在 core 层；
    - 默认 worker 是离线确定性执行器，不联网、不需要 API Key，
      因此 Windows EXE / Linux deb 打开工作台即可跑完整流程；
    - 只用 PyQt5 现有部件，不引入第三方 UI 依赖；
    - 与 ui/insight_dialog.py 保持一致的浅色视觉语言。
"""
import os

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel,
                             QLineEdit, QPushButton, QTreeWidget,
                             QTreeWidgetItem, QTextBrowser, QSplitter,
                             QProgressBar, QFileDialog, QMessageBox,
                             QApplication, QInputDialog)

from core import project as pj
from core import parallel as pl
from core import updatecheck as uc
from core import config as cfg_mod

_HEAD = "font-size:13px;font-weight:600;color:#16293c;"
_SUB = "font-size:11px;color:#64748b;"
_BTN = ("QPushButton{padding:6px 14px;border:1px solid #cbd5e1;"
        "border-radius:8px;background:#ffffff;font-size:12px;}"
        "QPushButton:hover{background:#f1f5f9;}"
        "QPushButton:disabled{color:#94a3b8;}")
_PRIMARY = ("QPushButton{padding:6px 16px;border:0;border-radius:8px;"
            "background:#2563eb;color:#ffffff;font-size:12px;font-weight:600;}"
            "QPushButton:hover{background:#1d4ed8;}"
            "QPushButton:disabled{background:#93c5fd;}")
_TREE = ("QTreeWidget{background:#ffffff;border:1px solid #e3e8ef;"
         "border-radius:10px;font-size:12px;}")
_BROWSER = ("QTextBrowser{background:#fafbfc;border:1px solid #e3e8ef;"
            "border-radius:10px;padding:10px;font-size:12px;}")

_STATE_TEXT = {
    pj.TASK_PENDING: "· 待办",
    pj.TASK_RUNNING: "… 执行中",
    pj.TASK_DONE: "✓ 完成",
    pj.TASK_FAILED: "✗ 失败",
    pj.TASK_SKIPPED: "- 跳过",
}


class WorkbenchDialog(QDialog):
    """整体项目工作台：目标 → 任务树 → 分波并行 → 报告 / 存档 / 更新。"""

    def __init__(self, parent=None, initial_goal=""):
        super().__init__(parent)
        self.project = None
        self.waves = []
        self.report = None
        self.setWindowTitle("✦ 星语工作台 · 整体项目 / 多线并行 / 更新")
        self.resize(960, 640)
        self._build_ui()
        if initial_goal:
            self.goal_edit.setText(initial_goal)
            self._on_plan()

    # ------------------------------------------------------------------
    # 界面
    # ------------------------------------------------------------------
    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(14, 12, 14, 12)
        outer.setSpacing(9)

        title = QLabel("整体项目  →  多线并行  →  自动更新")
        title.setStyleSheet("font-size:16px;font-weight:700;color:#0f172a;")
        outer.addWidget(title)
        cap = QLabel(
            "星语 Starry %s · 默认离线执行，不消耗 token；"
            "任务按依赖自动分波，单线失败不影响其它线。" % cfg_mod.APP_VERSION)
        cap.setStyleSheet(_SUB)
        outer.addWidget(cap)

        row = QHBoxLayout()
        row.setSpacing(8)
        row.addWidget(QLabel("项目目标"))
        self.goal_edit = QLineEdit()
        self.goal_edit.setPlaceholderText(
            "输入一个目标，例如：调研并撰写 v13 发版方案")
        self.goal_edit.setStyleSheet(
            "QLineEdit{padding:7px 10px;border:1px solid #cbd5e1;"
            "border-radius:8px;font-size:12px;}")
        self.goal_edit.returnPressed.connect(self._on_plan)
        row.addWidget(self.goal_edit, 1)
        self.plan_btn = QPushButton("① 规划项目")
        self.plan_btn.setStyleSheet(_BTN)
        self.plan_btn.clicked.connect(self._on_plan)
        row.addWidget(self.plan_btn)
        self.run_btn = QPushButton("② 多线并行执行")
        self.run_btn.setStyleSheet(_PRIMARY)
        self.run_btn.clicked.connect(self._on_run)
        row.addWidget(self.run_btn)
        outer.addLayout(row)

        splitter = QSplitter(Qt.Horizontal)
        self.tree = QTreeWidget()
        self.tree.setColumnCount(4)
        self.tree.setHeaderLabels(["任务", "状态", "类型", "依赖"])
        self.tree.setRootIsDecorated(False)
        self.tree.setAlternatingRowColors(True)
        self.tree.setStyleSheet(_TREE)
        self.tree.setColumnWidth(0, 190)
        self.tree.setColumnWidth(1, 90)
        self.tree.setColumnWidth(2, 80)
        self.tree.itemDoubleClicked.connect(self._on_item_double_clicked)
        splitter.addWidget(self.tree)

        self.browser = QTextBrowser()
        self.browser.setStyleSheet(_BROWSER)
        splitter.addWidget(self.browser)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 1)
        outer.addWidget(splitter, 1)

        progress_row = QHBoxLayout()
        self.status = QLabel("尚未创建项目")
        self.status.setStyleSheet(_SUB)
        progress_row.addWidget(self.status, 1)
        self.bar = QProgressBar()
        self.bar.setFixedWidth(220)
        self.bar.setFormat("%p%")
        self.bar.setValue(0)
        self.bar.setStyleSheet(
            "QProgressBar{border:1px solid #e3e8ef;border-radius:7px;"
            "height:16px;text-align:center;font-size:11px;}"
            "QProgressBar::chunk{background:#2563eb;border-radius:6px;}")
        progress_row.addWidget(self.bar)
        outer.addLayout(progress_row)

        bar = QHBoxLayout()
        bar.setSpacing(7)
        for text, slot in (("保存 .starryproj", self._on_save),
                           ("载入项目", self._on_load),
                           ("导出报告 .md", self._on_export),
                           ("检查更新", self._on_update_check)):
            b = QPushButton(text)
            b.setStyleSheet(_BTN)
            b.clicked.connect(slot)
            bar.addWidget(b)
        bar.addStretch(1)
        close_btn = QPushButton("关闭")
        close_btn.setDefault(True)
        close_btn.setStyleSheet(_BTN)
        close_btn.clicked.connect(self.accept)
        bar.addWidget(close_btn)
        outer.addLayout(bar)

        self._render(intro=True)

    # ------------------------------------------------------------------
    # 渲染
    # ------------------------------------------------------------------
    def _render(self, intro=False):
        self.tree.clear()
        if self.project is None:
            if intro:
                self._set_markdown(
                    "# ✦ 星语工作台\n\n"
                    "这里是「整体项目」层：一次目标对应一个项目，"
                    "项目下的任务可以**多线并行**执行。\n\n"
                    "使用方法：\n\n"
                    "1. 在上方输入目标，点 **① 规划项目**（或按回车）；\n"
                    "2. 点 **② 多线并行执行**，观察任务树与进度条；\n"
                    "3. 用底部按钮保存 `.starryproj`、载入项目、导出报告或检查更新。\n\n"
                    "> 默认执行器完全离线、确定性，不联网、不消耗 token；"
                    "任务按依赖自动分波，单线异常被隔离。\n")
            self.bar.setValue(0)
            self.status.setText("尚未创建项目")
            self.run_btn.setEnabled(False)
            return

        prog = pj.project_progress(self.project)
        for t in self.project.get("tasks", []):
            item = QTreeWidgetItem([
                t.get("title", ""),
                _STATE_TEXT.get(t.get("status"), "?"),
                t.get("kind", ""),
                ", ".join(t.get("depends") or []) or "—",
            ])
            item.setData(0, Qt.UserRole, t.get("id"))
            if t.get("status") == pj.TASK_DONE:
                item.setForeground(1, Qt.darkGreen)
            elif t.get("status") in (pj.TASK_FAILED, pj.TASK_SKIPPED):
                item.setForeground(1, Qt.red)
            self.tree.addTopLevelItem(item)
        self.bar.setValue(prog["percent"])
        self.status.setText(
            "进度 %d%% · 完成 %d / %d · 失败 %d · 待办 %d%s"
            % (prog["percent"], prog["done"], prog["total"], prog["failed"],
               prog["pending"],
               " · 共 %d 波并行" % len(self.waves) if self.waves else ""))
        self.run_btn.setEnabled(prog["pending"] > 0)

        md = pj.render_project_markdown(self.project, self.report)
        if self.waves:
            md += "\n" + pl.merge_results(
                self.report, "多线并行汇总（%d 波）" % len(self.waves))
        self._set_markdown(md)

    def _set_markdown(self, text):
        try:
            self.browser.setMarkdown(text)
        except Exception:                                  # noqa: BLE001
            self.browser.setPlainText(text)

    # ------------------------------------------------------------------
    # 动作
    # ------------------------------------------------------------------
    def _on_plan(self):
        goal = self.goal_edit.text().strip()
        if not goal:
            QMessageBox.information(self, "需要目标", "请先输入项目目标。")
            return
        self.project = pj.plan_from_goal(goal)
        self.waves, self.report = [], None
        self._render()

    def _on_run(self):
        if self.project is None:
            return
        if not pj.ready_tasks(self.project):
            self.status.setText("没有可执行的待办任务（可能已完成或存在循环依赖）")
            return
        self.run_btn.setEnabled(False)
        self.status.setText("多线并行执行中…")
        QApplication.processEvents()
        try:
            self.project, self.waves = pl.run_project(
                self.project, worker=pl.local_worker,
                max_workers=4, timeout=None, retries=0)
            merged = {
                "workers": 4,
                "ok": sum(w["ok"] for w in self.waves),
                "failed": sum(w["failed"] for w in self.waves),
                "total": sum(w["total"] for w in self.waves),
                "elapsed_ms": sum(w["elapsed_ms"] for w in self.waves),
                "timed_out": any(w["timed_out"] for w in self.waves),
                "results": [r for w in self.waves for r in w["results"]],
            }
            self.report = merged
        except Exception as exc:                            # noqa: BLE001
            QMessageBox.warning(self, "执行失败", "并行执行异常：%s" % exc)
        self._render()

    def _on_item_double_clicked(self, item, _col):
        tid = item.data(0, Qt.UserRole)
        t = pj.find_task(self.project, tid)
        if not t:
            return
        detail = ["任务：%s" % t.get("title"),
                  "状态：%s" % _STATE_TEXT.get(t.get("status"), "?"),
                  "类型：%s" % t.get("kind"),
                  "依赖：%s" % (", ".join(t.get("depends") or []) or "无"),
                  ""]
        if t.get("error"):
            detail.append("错误：%s" % t["error"])
        if t.get("result") is not None:
            import json
            detail.append("结果：\n%s" % json.dumps(
                t["result"], ensure_ascii=False, indent=2)[:2000])
        else:
            detail.append("结果：（尚未执行）")
        self._set_markdown("\n".join(detail))

    def _on_save(self):
        if self.project is None:
            QMessageBox.information(self, "无项目", "请先规划一个项目。")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "保存整体项目", "星语项目.starryproj",
            "星语项目 (*.starryproj);;所有文件 (*)")
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(pj.pack_project(self.project))
            self.status.setText("已保存：%s" % path)
        except OSError as exc:
            QMessageBox.warning(self, "保存失败", "无法写入文件：%s" % exc)

    def _on_load(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "载入整体项目", "",
            "星语项目 (*.starryproj);;所有文件 (*)")
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                self.project = pj.unpack_project(f.read())
        except ValueError as exc:
            QMessageBox.warning(self, "拒绝载入", str(exc))
            return
        except OSError as exc:
            QMessageBox.warning(self, "读取失败", str(exc))
            return
        self.goal_edit.setText(self.project.get("goal") or "")
        self.waves, self.report = [], None
        self._render()

    def _on_export(self):
        if self.project is None:
            QMessageBox.information(self, "无项目", "请先规划一个项目。")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "导出项目报告", "星语-项目报告.md",
            "Markdown (*.md);;所有文件 (*)")
        if not path:
            return
        text = pj.render_project_markdown(self.project, self.report)
        if self.waves:
            text += "\n" + pl.merge_results(self.report)
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(text)
            self.status.setText("已导出报告：%s" % path)
        except OSError as exc:
            QMessageBox.warning(self, "导出失败", "无法写入文件：%s" % exc)

    def _on_update_check(self):
        """离线优先：选本地 update.json；未选则给出配置指引。"""
        from core.platforms import detect_platform
        path, _ = QFileDialog.getOpenFileName(
            self, "选择 update.json（取消则查看离线说明）", "",
            "更新清单 (*.json);;所有文件 (*)")
        lines = ["# 自动更新检查", "",
                 "- 当前版本：**%s**" % cfg_mod.APP_VERSION,
                 "- 平台：**%s**" % detect_platform(),
                 "- 清单格式：`update.json` v%s" % uc.MANIFEST_VERSION, ""]
        if not path:
            url = uc.configured_manifest_url()
            lines += [
                "更新源：%s" % (url or "未配置（离线模式）"),
                "",
                "本工作台**只做完整性判定**，不自动下载或替换程序。",
                "",
                "配置方式：",
                "",
                "1. 选择一个本地 `update.json` 离线校验（本按钮）；",
                "2. 命令行：`starry --update-check --update-manifest update.json`；",
                "3. 远程清单：`starry --update-url https://.../update.json` "
                "或设置 `STARRY_UPDATE_URL`。",
                "",
                "> 安全边界：digest 与 asset.sha256 是完整性校验，不是签名认证；"
                "请只使用可信来源（HTTPS / GitHub Releases）的清单。",
            ]
            self._set_markdown("\n".join(lines))
            return
        try:
            manifest = uc.load_manifest(path)
        except ValueError as exc:
            QMessageBox.warning(self, "读取失败", str(exc))
            return
        res = uc.check_update(cfg_mod.APP_VERSION, manifest, detect_platform())
        lines += [
            "清单来源：`%s`" % path,
            "清单校验：%s" % ("通过" if res["manifest_valid"] else "失败"),
            "最新版本：%s" % (res["latest"] or "未知"),
            "结论：**%s**" % (res["reason"] or "无可用结论"), "",
        ]
        if res["update_available"] and res["asset"]:
            a = res["asset"]
            lines += ["## 可更新资产", "",
                      "- 名称：`%s`" % a.get("name"),
                      "- 大小：%s 字节" % a.get("size"),
                      "- 地址：%s" % a.get("url"),
                      "- SHA-256：`%s`" % a.get("sha256"), "",
                      "> 请从可信来源下载后核对哈希；本工具不自动替换程序。"]
        elif not res["manifest_valid"]:
            lines.append("> 清单校验未通过，其中的版本与资产信息已被忽略。")
        self._set_markdown("\n".join(lines))
