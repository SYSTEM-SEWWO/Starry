# -*- coding: utf-8 -*-
"""星语 Starry v13.2 · Skills Hub（电脑端 GUI，兼容主流 Skills 生态）。

一处浏览 GitHub / DeepSeek / Claude Code / WorkBuddy / 星语自有的技能与提示词模板，
支持搜索、查看正文、导入技能库、导出 hub.json、检查技能更新，
以及查看生效配置与扫描诊断（配置告警 / 异常边界可视化）。

设计约束（与 ui/workbench_dialog.py 一致）：
    - 本文件只做展示与交互，**不含业务逻辑**，逻辑全在 core.hub；
    - 只读发现；不联网、不自动下载、不执行技能正文；
    - 唯一写操作是用户点击「导入」或「导出」时显式触发；
    - 只用 PyQt5 现有部件，与整体项目工作台保持同一套浅色视觉语言。
"""
import json
import os

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel,
                             QLineEdit, QPushButton, QTreeWidget,
                             QTreeWidgetItem, QTextBrowser, QSplitter,
                             QFileDialog, QMessageBox, QApplication)

from core import hub as hb
from core import config as cfg_mod

_HEAD = "font-size:13px;font-weight:600;color:#16293c;"
_SUB = "font-size:11px;color:#64748b;"
_BTN = ("QPushButton{padding:6px 14px;border:1px solid #cbd5e1;"
        "border-radius:8px;background:#ffffff;font-size:12px;}"
        "QPushButton:hover{background:#f1f5f9;}"
        "QPushButton:disabled{color:#94a3b8;}")
_PRIMARY = ("QPushButton{padding:6px 16px;border:0;border-radius:8px;"
            "background:#2563eb;color:#ffffff;font-size:12px;font-weight:600;}"
            "QPushButton:hover{background:#1d4ed8;}")
_TREE = ("QTreeWidget{background:#ffffff;border:1px solid #e3e8ef;"
         "border-radius:10px;font-size:12px;}")
_BROWSER = ("QTextBrowser{background:#fafbfc;border:1px solid #e3e8ef;"
            "border-radius:10px;padding:10px;font-size:12px;}")


class HubDialog(QDialog):
    """技能中心：左侧多生态技能列表，右侧正文，底部导入 / 更新 / 导出。"""

    def __init__(self, parent=None, cfg=None, hub=None):
        super().__init__(parent)
        self.cfg = cfg or cfg_mod.AppConfig.load()
        # v13.2：与 CLI 共用同一份 config.json 的 hub 配置（来源开关 /
        # DeepSeek 内联 prompts / 扫描深度 / 导入开关），避免两处行为漂移。
        self.hub = hub or hb.Hub.from_config(
            self.cfg, starry_skills=(self.cfg.data.get("skills") or []))
        self._skills = []
        self.setWindowTitle(
            "✦ 星语 Skills Hub · GitHub / DeepSeek / Claude Code / WorkBuddy")
        self.resize(980, 640)
        self._build_ui()
        self._refresh()

    # ------------------------------------------------------------------
    # 界面
    # ------------------------------------------------------------------
    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(14, 12, 14, 12)
        outer.setSpacing(9)

        title = QLabel("Skills Hub  →  多生态技能  →  技能更新")
        title.setStyleSheet("font-size:16px;font-weight:700;color:#0f172a;")
        outer.addWidget(title)
        cap = QLabel(
            "星语 Starry %s · GitHub / Claude Code / WorkBuddy 的 SKILL.md + "
            "DeepSeek 提示词模板（deepseek.json / *.deepseek.md）；"
            "只读发现，不联网、不调用 DeepSeek API、不执行技能正文。"
            % cfg_mod.APP_VERSION)
        cap.setStyleSheet(_SUB)
        outer.addWidget(cap)

        row = QHBoxLayout()
        row.setSpacing(8)
        row.addWidget(QLabel("搜索技能"))
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText(
            "按名称 / 描述 / 标签 / 正文搜索，例如：api、发版、offline")
        self.search_edit.setStyleSheet(
            "QLineEdit{padding:7px 10px;border:1px solid #cbd5e1;"
            "border-radius:8px;font-size:12px;}")
        self.search_edit.textChanged.connect(self._on_search)
        row.addWidget(self.search_edit, 1)

        self.btn_refresh = QPushButton("🔄 刷新")
        self.btn_add = QPushButton("📁 添加源")
        for b in (self.btn_refresh, self.btn_add):
            b.setStyleSheet(_BTN)
        self.btn_refresh.clicked.connect(self._refresh)
        self.btn_add.clicked.connect(self._on_add_source)
        row.addWidget(self.btn_refresh)
        row.addWidget(self.btn_add)
        outer.addLayout(row)

        splitter = QSplitter(Qt.Horizontal)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["来源", "名称", "版本", "说明"])
        self.tree.setColumnWidth(0, 110)
        self.tree.setColumnWidth(1, 190)
        self.tree.setColumnWidth(2, 80)
        self.tree.setStyleSheet(_TREE)
        self.tree.setRootIsDecorated(False)
        self.tree.itemSelectionChanged.connect(self._on_selected)
        splitter.addWidget(self.tree)

        self.detail = QTextBrowser()
        self.detail.setStyleSheet(_BROWSER)
        self.detail.setPlainText("从左侧选择一个技能查看说明与指令正文。")
        splitter.addWidget(self.detail)
        splitter.setStretchFactor(0, 5)
        splitter.setStretchFactor(1, 6)
        outer.addWidget(splitter, 1)

        self.status = QLabel("—")
        self.status.setStyleSheet(_SUB)
        outer.addWidget(self.status)

        bottom = QHBoxLayout()
        bottom.setSpacing(8)
        bottom.addStretch(1)
        self.btn_import = QPushButton("⬇ 导入为星语技能")
        self.btn_update = QPushButton("🔄 检查技能更新")
        self.btn_export = QPushButton("📤 导出 hub.json")
        self.btn_config = QPushButton("⚙ 生效配置")
        self.btn_diag = QPushButton("🩺 扫描诊断")
        btn_close = QPushButton("关闭")
        all_btns = (self.btn_import, self.btn_update, self.btn_export,
                    self.btn_config, self.btn_diag, btn_close)
        for b in all_btns:
            b.setStyleSheet(_BTN)
        self.btn_import.setStyleSheet(_PRIMARY)
        self.btn_import.clicked.connect(self._on_import)
        self.btn_update.clicked.connect(self._on_check_update)
        self.btn_export.clicked.connect(self._on_export)
        self.btn_config.clicked.connect(self._on_config)
        self.btn_diag.clicked.connect(self._on_diagnostics)
        btn_close.clicked.connect(self.accept)
        for b in all_btns:
            bottom.addWidget(b)
        outer.addLayout(bottom)

    # ------------------------------------------------------------------
    # 数据
    # ------------------------------------------------------------------
    def _refresh(self):
        self._skills = self.hub.discover(refresh=True)
        self._render_list(self.search_edit.text())
        enabled = "、".join(self.hub.config["sources"]) or "（全部关闭）"
        extra = ""
        if self.hub.warnings or self.hub.errors:
            extra = " · 配置告警 %d / 扫描异常 %d（点「🩺 扫描诊断」查看）" % (
                len(self.hub.warnings), len(self.hub.errors))
        self.status.setText(
            "共发现 %d 个技能 · 启用来源：%s%s" % (
                len(self._skills), enabled, extra))

    def _render_list(self, query=""):
        self.tree.clear()
        found = hb.search(self._skills, query)
        for s in found:
            item = QTreeWidgetItem([
                s.get("source", ""), s.get("name", ""),
                s.get("version") or "—",
                str(s.get("description") or "")[:80].replace("\n", " ")])
            item.setData(0, Qt.UserRole, s.get("id"))
            self.tree.addTopLevelItem(item)
        if found:
            self.tree.setCurrentItem(self.tree.topLevelItem(0))
        else:
            self.detail.setPlainText("没有匹配的技能。")
        return found

    def _current(self):
        item = self.tree.currentItem()
        if item is None:
            return None
        sid = item.data(0, Qt.UserRole)
        return self.hub.get(sid)

    def _set_markdown(self, text):
        # 技能正文是**提示词原文**：原样展示便于复制/核对，也避免 Markdown
        # 渲染把 frontmatter 指令符吞掉（GUI EXE 的 offscreen 自检依赖原文）。
        self.detail.setPlainText(text)

    # ------------------------------------------------------------------
    # 交互
    # ------------------------------------------------------------------
    def _on_search(self, text):
        found = self._render_list(text)
        self.status.setText(
            "命中 %d / 共 %d 个技能" % (len(found), len(self._skills)))

    def _on_selected(self):
        s = self._current()
        if s:
            self._set_markdown(hb.render_skill(s))

    def _on_add_source(self):
        path = QFileDialog.getExistingDirectory(self, "选择技能源目录")
        if not path:
            return
        if self.hub.add_source(path, "local"):
            self._refresh()
            QMessageBox.information(self, "Skills Hub",
                                    "已添加技能源：\n%s" % path)
        else:
            QMessageBox.warning(self, "Skills Hub", "目录不存在，未添加。")

    def _on_config(self):
        """v13.2：显示生效配置，便于核对来源开关与 DeepSeek 配置项。"""
        diag = self.hub.diagnostics()
        payload = {
            "version": cfg_mod.APP_VERSION,
            "config": diag["config"],
            "config_warnings": diag["warnings"],
            "sources": diag["sources"],
        }
        QMessageBox.information(
            self, "Skills Hub · 生效配置",
            json.dumps(payload, ensure_ascii=False, indent=2))

    def _on_diagnostics(self):
        """v13.2：把异常处理边界可视化（生效来源 / 告警 / 逐条扫描异常）。"""
        diag = self.hub.diagnostics()
        lines = ["技能数：%d · 生效来源：%d" % (
            diag["skills"], len(diag["sources"])), ""]
        for item in diag["sources"]:
            lines.append("  · %s  %s" % (item["source"], item["path"]))
        lines += ["", "配置告警：%d" % len(diag["warnings"])]
        for w in diag["warnings"]:
            lines.append("  ! %s" % w)
        lines += ["", "扫描异常：%d" % len(diag["errors"])]
        for e in diag["errors"][:20]:
            lines.append("  x [%s] %s：%s"
                         % (e.get("stage"), e.get("path"), e.get("reason")))
        if len(diag["errors"]) > 20:
            lines.append("  … 其余 %d 条已截断" % (len(diag["errors"]) - 20))
        lines += ["", "说明：目录不存在 / 文件损坏 / 单条缺字段一律跳过并记录，"
                      "不会中断扫描；digest 是完整性校验，不是签名认证。"]
        QMessageBox.information(self, "Skills Hub · 扫描诊断", "\n".join(lines))

    def _on_import(self):
        if not self.hub.can_import():
            QMessageBox.warning(
                self, "Skills Hub",
                "当前 hub 配置 allow_import=false，已拒绝导入。\n"
                "可在「⚙ 生效配置」查看，或修改 config.json 的 hub 段。")
            return
        s = self._current()
        if not s:
            return
        conv = hb.to_starry_skill(s)
        if not str(conv.get("prompt") or "").strip():
            QMessageBox.warning(
                self, "Skills Hub",
                "该技能只有元数据、没有指令正文，无法导入。\n"
                "请从技能原始仓库获取正文后再试。")
            return
        from core.agent.skills import SkillManager
        saved = SkillManager(self.cfg).add_custom(
            conv["name"], conv["prompt"], conv["description"],
            conv["icon"], conv["id"])
        if not saved:
            QMessageBox.warning(self, "Skills Hub", "导入失败：名称或正文为空。")
            return
        QMessageBox.information(
            self, "Skills Hub",
            "已导入技能：%s\nid：%s\n\n可在「技能」菜单中选用。"
            % (saved["name"], saved["id"]))
        self._refresh()

    def _on_check_update(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "选择 hub.json（本地清单，离线校验）", "", "JSON (*.json)")
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                manifest = json.load(f)
        except (OSError, ValueError, UnicodeError) as exc:
            QMessageBox.warning(self, "Skills Hub", "读取清单失败：%s" % exc)
            return
        res = hb.check_hub_update(self._skills, manifest)
        lines = ["清单校验：%s" % ("通过" if res["manifest_valid"] else "失败"),
                 "Hub 版本：%s" % (res["hub_version"] or "未知"),
                 "", res["reason"]]
        if res["update_available"]:
            for label, key in (("新增", "added"), ("变更", "changed"),
                               ("移除", "removed")):
                if res[key]:
                    lines.append("  %s %d：%s" % (
                        label, len(res[key]),
                        ", ".join(str(x.get("name", "")) for x in res[key])))
        lines += ["", "提示：digest 是完整性校验，不是签名认证；"
                      "Hub 不会自动下载或安装技能。"]
        QMessageBox.information(self, "Skills Hub 更新检查", "\n".join(lines))

    def _on_export(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "导出 hub.json", "hub.json", "JSON (*.json)")
        if not path:
            return
        manifest = hb.build_hub_manifest(
            self._skills, hub_version=cfg_mod.APP_VERSION,
            notes="由星语 Skills Hub 导出（只含元数据与内容摘要）")
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(manifest, f, ensure_ascii=False, indent=2)
        except OSError as exc:
            QMessageBox.warning(self, "Skills Hub", "导出失败：%s" % exc)
            return
        ok, _ = hb.validate_hub_manifest(manifest)
        QMessageBox.information(
            self, "Skills Hub",
            "已导出 %d 个技能到：\n%s\n自校验：%s"
            % (len(self._skills), path, "通过" if ok else "失败"))


def offscreen_check():
    """无显示器自检：供 GUI EXE 的 --selftest 使用，不弹窗、不写文件。"""
    results = []

    def ck(name, cond):
        results.append((name, bool(cond)))

    dlg = HubDialog()
    ck("HubDialog 装配成功", dlg.tree is not None and dlg.detail is not None)
    ck("发现至少 3 个随包技能", len(dlg._skills) >= 3)
    ck("列表已填充", dlg.tree.topLevelItemCount() >= 3)
    ck("选中项展示正文", "## 指令正文" in dlg.detail.toPlainText()
       or "# 技能" in dlg.detail.toPlainText())

    dlg.search_edit.setText("api")
    ck("搜索 api 命中列表", dlg.tree.topLevelItemCount() >= 1)
    ck("搜索结果含 api-contract-review",
       "api-contract-review" in dlg.detail.toPlainText()
       or any(dlg.tree.topLevelItem(i).text(1) == "api-contract-review"
              for i in range(dlg.tree.topLevelItemCount())))
    dlg.search_edit.setText("")
    ck("清空搜索恢复全部", dlg.tree.topLevelItemCount() == len(dlg._skills))

    # v13.2：DeepSeek 来源 + 配置项 + 异常边界在 GUI 层也要可见
    ck("DeepSeek 技能出现在列表",
       any(s["source"] == "deepseek" for s in dlg._skills))
    ck("Hub 由 config.json 的 hub 段装配",
       isinstance(dlg.hub.config, dict) and "deepseek" in dlg.hub.config)
    ck("生效配置按钮存在", dlg.btn_config is not None)
    ck("扫描诊断按钮存在", dlg.btn_diag is not None)
    diag = dlg.hub.diagnostics()
    ck("诊断含五项结构", all(
        k in diag for k in ("config", "sources", "warnings", "errors", "skills")))
    ck("扫描无未处理异常", diag["errors"] == [])

    manifest = hb.build_hub_manifest(dlg._skills)
    ck("导出清单结构合法", hb.validate_hub_manifest(manifest)[0])
    res = hb.check_hub_update(dlg._skills, manifest)
    ck("同版本清单判定为无更新", res["manifest_valid"]
       and not res["update_available"])
    dlg.close()
    return results


if __name__ == "__main__":
    import sys
    app = QApplication(sys.argv)
    results = offscreen_check()
    for name, ok in results:
        print(("PASS" if ok else "FAIL"), "-", name)
    bad = [n for n, ok in results if not ok]
    print("\n==== HubDialog offscreen：%d/%d 通过 ===="
          % (len(results) - len(bad), len(results)))
    sys.exit(1 if bad else 0)
