# -*- coding: utf-8 -*-
"""星语 Starry · API 诊断面板（v13.2 企业级，电脑端 GUI）。

真实 GUI 测评发现：启动时 401 以 toast 一闪而过，用户事后无法查看
「刚才错在哪」。本面板把 `core.apidiag` 的脱敏记录展示出来，支持
复制诊断文本给支持人员、清空内存记录。

设计约束：
  - 只展示 `core.apierrors` 已脱敏的结构化记录；
  - **不展示** API Key、Bearer Token、请求体、完整响应体、聊天内容；
  - 只读 + 两个本地操作（复制 / 清空），不联网、不发请求。
"""
from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel,
                             QPushButton, QTextBrowser, QApplication,
                             QMessageBox)

from core import apidiag
from core import config as cfg_mod

_BTN = ("QPushButton{padding:6px 14px;border:1px solid #cbd5e1;"
        "border-radius:8px;background:#ffffff;font-size:12px;}"
        "QPushButton:hover{background:#f1f5f9;}")
_BROWSER = ("QTextBrowser{background:#fafbfc;border:1px solid #e3e8ef;"
            "border-radius:10px;padding:10px;font-size:12px;"
            "font-family:Consolas,'Microsoft YaHei',monospace;}")
_SUB = "font-size:11px;color:#64748b;"


class ApiDiagDialog(QDialog):
    """显示最近 API 失败的脱敏分类、原因与逐条建议。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("✦ 星语 API 诊断 · 脱敏记录")
        self.resize(760, 520)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(14, 12, 14, 12)
        outer.setSpacing(9)

        title = QLabel("API 诊断 · 最近失败记录")
        title.setStyleSheet("font-size:16px;font-weight:700;color:#0f172a;")
        outer.addWidget(title)
        cap = QLabel(
            "星语 Starry %s · 仅记录失败状态与脱敏摘要，"
            "不含 API Key / Bearer Token / 请求体 / 聊天内容。"
            % cfg_mod.APP_VERSION)
        cap.setStyleSheet(_SUB)
        outer.addWidget(cap)

        self.browser = QTextBrowser()
        self.browser.setStyleSheet(_BROWSER)
        outer.addWidget(self.browser, 1)

        self.status = QLabel("—")
        self.status.setStyleSheet(_SUB)
        outer.addWidget(self.status)

        row = QHBoxLayout()
        row.addStretch(1)
        self.btn_refresh = QPushButton("🔄 刷新")
        self.btn_copy = QPushButton("📋 复制诊断")
        self.btn_clear = QPushButton("🧹 清空记录")
        btn_close = QPushButton("关闭")
        for b in (self.btn_refresh, self.btn_copy, self.btn_clear, btn_close):
            b.setStyleSheet(_BTN)
        self.btn_refresh.clicked.connect(self._refresh)
        self.btn_copy.clicked.connect(self._copy)
        self.btn_clear.clicked.connect(self._clear)
        btn_close.clicked.connect(self.accept)
        for b in (self.btn_refresh, self.btn_copy, self.btn_clear, btn_close):
            row.addWidget(b)
        outer.addLayout(row)
        self._refresh()

    def _refresh(self):
        self.browser.setPlainText(apidiag.text_report(30))
        s = apidiag.summary()
        kinds = "、".join("%s %d" % (k, v)
                         for k, v in sorted(s["by_kind"].items())) or "无"
        self.status.setText("共 %d 条记录 · 分类：%s" % (s["total"], kinds))

    def _copy(self):
        QApplication.clipboard().setText(apidiag.text_report(30))
        self.status.setText("已复制脱敏诊断文本到剪贴板。")

    def _clear(self):
        apidiag.clear()
        self._refresh()
        self.status.setText("内存诊断记录已清空（不影响已落盘的审计日志）。")


def offscreen_check():
    """无显示器自检：供 GUI EXE 的 --selftest 使用。"""
    results = []

    def ck(name, cond):
        results.append((name, bool(cond)))

    apidiag.record("selftest", {"kind": "auth", "title": "自检样例",
                                "advice": ["仅用于装配自检"],
                                "operation": "selftest", "detail": ""},
                   scope="selftest")
    dlg = ApiDiagDialog()
    ck("ApiDiagDialog 装配成功", dlg.browser is not None)
    ck("诊断文本非空", len(dlg.browser.toPlainText()) > 20)
    ck("诊断汇总可用", apidiag.summary()["total"] >= 1)
    ck("诊断文本不含测试密钥标记", "SECRET" not in dlg.browser.toPlainText())
    apidiag.clear()
    dlg.close()
    return results


if __name__ == "__main__":
    import sys
    app = QApplication(sys.argv)
    res = offscreen_check()
    for name, ok in res:
        print(("PASS" if ok else "FAIL"), "-", name)
    bad = [n for n, ok in res if not ok]
    print("\n==== ApiDiagDialog offscreen：%d/%d 通过 ===="
          % (len(res) - len(bad), len(res)))
    sys.exit(1 if bad else 0)
