# -*- coding: utf-8 -*-
"""应用内「申请 API Key」引导对话框（v13.4）。

分服务商展示注册 → 创建 Key → 填入 → 校验的完整过程，内容来自
``core.apikey_guide``（纯数据、零联网）；网页版 / 本地模型会明确告知「无需 Key」。
"""
from PyQt5.QtCore import pyqtSignal, QUrl
from PyQt5.QtGui import QDesktopServices
from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel,
                             QListWidget, QListWidgetItem, QTextBrowser,
                             QPushButton, QApplication)

from core.apikey_guide import all_guides, guide_for, format_guide


class ApiKeyGuideDialog(QDialog):
    """API Key 申请过程说明窗口。"""

    open_settings_requested = pyqtSignal()

    def __init__(self, cfg, parent=None, provider=None):
        super().__init__(parent)
        self.cfg = cfg
        self._current = provider or ""
        self.setWindowTitle("🔑 申请 API Key · 完整步骤")
        self.resize(760, 560)
        self._build_ui()
        self._reload()

    def _api_keys(self):
        try:
            return dict(self.cfg.data.get("api_keys") or {})
        except Exception:                               # noqa: BLE001
            return {}

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(14, 12, 14, 12)
        outer.setSpacing(8)

        head = QLabel("🔑 不知道 API Key 从哪来？按下面的步骤走一遍即可（全程在本地说明，不联网）")
        head.setStyleSheet("font-size:14px;font-weight:600;color:#16293c;")
        outer.addWidget(head)

        body = QHBoxLayout()
        self.provider_list = QListWidget()
        self.provider_list.setMaximumWidth(230)
        self.provider_list.setStyleSheet(
            "QListWidget{background:#fafbfc;border:1px solid #e3e8ef;"
            "border-radius:10px;outline:0;}"
            "QListWidget::item{border-radius:8px;padding:7px 9px;}"
            "QListWidget::item:selected{background:#e6f2ff;}")
        self.provider_list.currentItemChanged.connect(self._on_provider_changed)
        body.addWidget(self.provider_list)

        self.browser = QTextBrowser()
        self.browser.setOpenExternalLinks(True)
        self.browser.setStyleSheet(
            "QTextBrowser{background:#ffffff;border:1px solid #e3e8ef;"
            "border-radius:10px;padding:10px;font-size:13px;}")
        body.addWidget(self.browser, 1)
        outer.addLayout(body, 1)

        self.status = QLabel("")
        self.status.setStyleSheet("color:#5b7086;font-size:12px;")
        outer.addWidget(self.status)

        bar = QHBoxLayout()
        bar.addStretch(1)
        self.copy_btn = QPushButton("复制完整说明")
        self.copy_btn.clicked.connect(self._copy_guide)
        bar.addWidget(self.copy_btn)
        self.open_url_btn = QPushButton("打开申请地址")
        self.open_url_btn.clicked.connect(self._open_url)
        bar.addWidget(self.open_url_btn)
        go_btn = QPushButton("去设置填写")
        go_btn.clicked.connect(self.open_settings_requested.emit)
        bar.addWidget(go_btn)
        close_btn = QPushButton("关闭")
        close_btn.clicked.connect(self.reject)
        bar.addWidget(close_btn)
        outer.addLayout(bar)

    # ------------------------------------------------------------------
    def _reload(self):
        keys = self._api_keys()
        guides = all_guides(keys)
        self.provider_list.clear()
        selected_row = 0
        for i, g in enumerate(guides):
            item = QListWidgetItem(("%s %s" % (
                "🔓" if not g["needs_key"] else "🔑", g["name"])))
            item.setData(0x0100, g["key"])              # Qt.UserRole
            self.provider_list.addItem(item)
            if g["key"] == (self._current or self.cfg.provider):
                selected_row = i
        if self.provider_list.count():
            self.provider_list.setCurrentRow(selected_row)
        else:
            self.browser.setPlainText("暂无服务商配置。")

    def _on_provider_changed(self, cur, _prev=None):
        if cur is None:
            return
        key = cur.data(0x0100)
        g = guide_for(key, self._api_keys().get(key))
        self._current = key
        self.browser.setHtml(_to_html(g))
        self.status.setText("%s · %s" % (g["name"], g["key_hint"]))
        self.open_url_btn.setEnabled(bool(g["key_url"]))

    def _copy_guide(self):
        key = self._current or self.cfg.provider
        text = format_guide(key, self._api_keys().get(key))
        try:
            QApplication.clipboard().setText(text)
            self.status.setText("已复制「%s」的完整申请说明" % key)
        except Exception:                               # noqa: BLE001
            self.status.setText("剪贴板不可用，请手动选中复制")

    def _open_url(self):
        g = guide_for(self._current or self.cfg.provider)
        if g["key_url"]:
            QDesktopServices.openUrl(QUrl(g["key_url"]))
            self.status.setText("已在浏览器打开申请地址：%s" % g["key_url"])


def _to_html(g):
    """把结构化引导渲染为 Qt 富文本（不引入额外依赖）。"""
    import html
    esc = html.escape
    out = ["<h2 style='margin:0 0 8px;'>%s</h2>" % esc(g["name"])]
    if g["desc"]:
        out.append("<p style='color:#5b7086;'>%s</p>" % esc(g["desc"]))
    if g["key_url"]:
        out.append("<p>申请地址：<a href='%s'>%s</a></p>"
                   % (esc(g["key_url"]), esc(g["key_url"])))
    if g["base_url"]:
        out.append("<p>Base URL：<code>%s</code></p>" % esc(g["base_url"]))
    out.append("<p><b>当前 Key 状态：%s</b></p>" % esc(g["key_hint"]))
    out.append("<h3>申请步骤</h3><ol>")
    for title, text in g["steps"]:
        out.append("<li><b>%s</b><br/>%s</li>" % (esc(title), esc(text)))
    out.append("</ol><h3>注意事项</h3><ul>")
    for n in g["notes"]:
        out.append("<li>%s</li>" % esc(n))
    out.append("</ul>")
    return "".join(out)
