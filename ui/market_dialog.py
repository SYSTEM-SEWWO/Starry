# -*- coding: utf-8 -*-
"""插件市场对话框：浏览 / 安装 / 卸载 / 开关 智能体插件。

- tool  工具包：直接开关（内置包默认开启）
- skill 技能包：安装后技能进入聊天窗技能下拉框，可卸载
- code  代码插件：远程下发、安装前强制安全警示，沙箱受限执行
"""
from PyQt5.QtCore import Qt, pyqtSignal, QThread
from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel,
                             QPushButton, QScrollArea, QWidget, QFrame,
                             QCheckBox, QPlainTextEdit)

from ui.theme import build_qss, get_theme

_TYPE_META = {
    "tool":  ("🔧", "工具包"),
    "skill": ("🎓", "技能包"),
    "code":  ("⚡", "代码插件"),
}


class CodePluginWarningDialog(QDialog):
    """代码插件安装确认：展示来源信息 + 源码全文，勾选确认后才能安装。"""

    def __init__(self, plugin, source_url, theme, font_size, parent=None):
        super().__init__(parent)
        self._theme = theme
        self._fs = font_size
        self.setStyleSheet(build_qss(theme, font_size))
        self.setWindowTitle("安全警示 · 安装代码插件")
        self.setMinimumWidth(520)
        self.setMinimumHeight(420)
        self._build_ui(plugin, source_url)

    def _build_ui(self, plugin, source_url):
        lay = QVBoxLayout(self)
        lay.setSpacing(8)

        warn = QLabel("⚠️ 即将安装代码插件「%s」" % plugin.get("name", ""))
        warn.setStyleSheet("font-weight:bold;font-size:%dpx;"
                           % (self._fs + 2))
        lay.addWidget(warn)

        info = QLabel(
            "该插件包含可执行代码。虽然它运行在受限沙箱中"
            "（仅允许白名单模块、禁止危险导入、禁止文件与网络外的系统访问），"
            "但沙箱不是安全边界。\n"
            "请只安装来自可信来源的插件，并在下方审阅源码。")
        info.setWordWrap(True)
        info.setObjectName("MutedLabel")
        lay.addWidget(info)

        meta = QLabel("来源：%s ｜ 作者：%s ｜ 版本：%s"
                      % (source_url or "未知",
                         plugin.get("author", "未知"),
                         plugin.get("version", "1.0")))
        meta.setObjectName("MutedLabel")
        meta.setWordWrap(True)
        lay.addWidget(meta)

        code_label = QLabel("插件源码（请审阅）：")
        lay.addWidget(code_label)
        self.code_view = QPlainTextEdit()
        self.code_view.setReadOnly(True)
        self.code_view.setPlainText(plugin.get("code") or "（无代码）")
        self.code_view.setMaximumHeight(240)
        lay.addWidget(self.code_view, 1)

        self.confirm_check = QCheckBox("我已阅读并理解上述代码，确认安装")
        self.confirm_check.setCursor(Qt.PointingHandCursor)
        lay.addWidget(self.confirm_check)

        btns = QHBoxLayout()
        btns.addStretch(1)
        cancel = QPushButton("取消")
        cancel.clicked.connect(self.reject)
        btns.addWidget(cancel)
        self.install_btn = QPushButton("安装")
        self.install_btn.setObjectName("AccentButton")
        self.install_btn.setEnabled(False)
        self.install_btn.clicked.connect(self.accept)
        btns.addWidget(self.install_btn)
        lay.addLayout(btns)

        self.confirm_check.toggled.connect(
            lambda on: self.install_btn.setEnabled(bool(on)))


class _RefreshWorker(QThread):
    done = pyqtSignal(bool, str)

    def __init__(self, market, parent=None):
        super().__init__(parent)
        self._market = market

    def run(self):
        try:
            ok, msg = self._market.refresh_remote()
        except Exception as e:  # noqa: BLE001
            ok, msg = False, str(e)
        self.done.emit(ok, msg)


class PluginCard(QFrame):
    """单个插件的卡片"""

    toggled = pyqtSignal(str, bool)       # (plugin_id, on)
    install = pyqtSignal(str)             # plugin_id
    uninstall = pyqtSignal(str)           # plugin_id

    def __init__(self, plugin, market, theme, font_size, parent=None):
        super().__init__(parent)
        self.plugin = plugin
        self.market = market
        self._theme = theme
        self._fs = font_size
        self.setObjectName("PluginCard")
        self._build_ui()
        self._refresh_state()

    # ------------------------------------------------------------------
    def _build_ui(self):
        p = self.plugin
        icon, type_name = _TYPE_META.get(p.get("type"), ("📦", "插件"))
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(4)

        # 标题行
        top = QHBoxLayout()
        top.setSpacing(8)
        self.icon_label = QLabel(icon)
        self.name_label = QLabel(p.get("name", p.get("id")))
        self.badge = QLabel("%s · v%s · %s" % (
            type_name, p.get("version", "1.0"), p.get("author", "未知")))
        self.badge.setObjectName("MutedLabel")
        top.addWidget(self.icon_label)
        top.addWidget(self.name_label)
        top.addWidget(self.badge)
        top.addStretch(1)

        self.toggle = QCheckBox("启用")
        self.toggle.setCursor(Qt.PointingHandCursor)
        self.toggle.toggled.connect(self._on_toggle)
        top.addWidget(self.toggle)

        self.install_btn = QPushButton("安装")
        self.install_btn.setObjectName("AccentButton")
        self.install_btn.setCursor(Qt.PointingHandCursor)
        self.install_btn.setFixedHeight(28)
        self.install_btn.clicked.connect(lambda: self.install.emit(p["id"]))
        top.addWidget(self.install_btn)

        self.uninstall_btn = QPushButton("卸载")
        self.uninstall_btn.setCursor(Qt.PointingHandCursor)
        self.uninstall_btn.setFixedHeight(28)
        self.uninstall_btn.clicked.connect(lambda: self.uninstall.emit(p["id"]))
        top.addWidget(self.uninstall_btn)
        lay.addLayout(top)

        # 描述
        self.desc_label = QLabel(p.get("description", ""))
        self.desc_label.setWordWrap(True)
        self.desc_label.setObjectName("MutedLabel")
        lay.addWidget(self.desc_label)

        # 内容清单
        detail = []
        if p.get("tools"):
            detail.append("工具：%s" % "、".join(p["tools"]))
        for sk in (p.get("skills") or []):
            if isinstance(sk, dict):
                detail.append("技能：%s %s" % (sk.get("icon", "🧩"),
                                              sk.get("name", "")))
            else:
                detail.append("技能：%s" % sk)
        if detail:
            self.detail_label = QLabel("｜".join(detail))
            self.detail_label.setWordWrap(True)
            lay.addWidget(self.detail_label)

        # 标签
        if p.get("tags"):
            self.tags_label = QLabel(" ".join("#%s" % t for t in p["tags"]))
            self.tags_label.setObjectName("MutedLabel")
            lay.addWidget(self.tags_label)

        self._apply_theme(self._theme, self._fs)

    # ------------------------------------------------------------------
    def _refresh_state(self):
        """按安装/启用状态刷新按钮可见性"""
        p = self.plugin
        ptype = p.get("type", "tool")
        installed = self.market.is_installed(p["id"])
        enabled = self.market.pack_enabled(p["id"])

        self.toggle.setChecked(enabled)
        if ptype == "tool":
            # 工具包：开关即安装，无需单独安装按钮
            self.toggle.show()
            self.install_btn.hide()
            self.uninstall_btn.hide()
        elif installed:
            self.toggle.show()
            self.install_btn.hide()
            self.uninstall_btn.show()
        else:
            self.toggle.hide()
            self.install_btn.show()
            self.uninstall_btn.hide()

        state = "已启用" if enabled else ("已安装（未启用）" if installed else "未安装")
        if ptype == "tool" and not installed and enabled:
            state = "默认启用"
        self.badge.setText("%s · v%s · %s · %s" % (
            _TYPE_META.get(ptype, ("", "插件"))[1], p.get("version", "1.0"),
            p.get("author", "未知"), state))

    def _on_toggle(self, on):
        self.toggled.emit(self.plugin["id"], bool(on))

    # ------------------------------------------------------------------
    def _apply_theme(self, theme, font_size):
        self._theme = theme
        self._fs = font_size
        self.setStyleSheet(
            "QFrame#PluginCard{background-color:%s;border:1px solid %s;"
            "border-radius:12px;}"
            % (theme["bubble_ai_bg"], theme["border"]))
        self.name_label.setStyleSheet(
            "color:%s;font-weight:bold;font-size:%dpx;"
            % (theme["text"], font_size + 1))
        self.detail_label.setStyleSheet("color:%s;font-size:%dpx;"
                                        % (theme["muted"], max(10, font_size - 2)))


class MarketDialog(QDialog):
    """插件市场主对话框"""

    changed = pyqtSignal()      # 安装/开关变化，通知外部刷新智能体栏

    def __init__(self, market, config, parent=None):
        super().__init__(parent)
        self.market = market
        self.cfg = config
        self._theme = get_theme(config.appearance.get("theme", "light"))
        self._fs = int(config.appearance.get("font_size", 14))
        self.setStyleSheet(build_qss(self._theme, self._fs))
        self.setWindowTitle("智能体插件市场")
        self.setMinimumWidth(520)
        self.setMinimumHeight(560)
        self._refresh_worker = None
        self._build_ui()
        self._load_cards()

    # ------------------------------------------------------------------
    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setSpacing(8)

        # 顶部说明 + 刷新
        top = QHBoxLayout()
        title = QLabel("🧩 智能体插件市场")
        title.setStyleSheet("font-size:%dpx;font-weight:bold;"
                            % (self._fs + 4))
        top.addWidget(title)
        top.addStretch(1)
        self.cache_label = QLabel("")
        self.cache_label.setObjectName("MutedLabel")
        top.addWidget(self.cache_label)
        self.refresh_btn = QPushButton("↻ 刷新远程索引")
        self.refresh_btn.setCursor(Qt.PointingHandCursor)
        self.refresh_btn.setToolTip("从市场地址拉取最新插件索引（失败时使用内置索引）")
        self.refresh_btn.clicked.connect(self._on_refresh)
        top.addWidget(self.refresh_btn)
        root.addLayout(top)

        tip = QLabel("工具包决定 AI 能调用哪些能力；技能包安装后出现在聊天窗技能下拉框。"
                     "⚠️ 代码插件可执行任意 Python，请只安装可信来源；"
                     "安装前会显示安全警示与完整源码，请审阅后再确认。")
        tip.setObjectName("MutedLabel")
        tip.setWordWrap(True)
        root.addWidget(tip)

        # 插件卡片滚动区
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.list_widget = QWidget()
        self.list_layout = QVBoxLayout(self.list_widget)
        self.list_layout.setContentsMargins(2, 2, 2, 2)
        self.list_layout.setSpacing(8)
        self.list_layout.addStretch(1)
        scroll.setWidget(self.list_widget)
        root.addWidget(scroll, 1)

        # 底部
        bottom = QHBoxLayout()
        self.status_label = QLabel("")
        self.status_label.setObjectName("MutedLabel")
        bottom.addWidget(self.status_label, 1)
        close_btn = QPushButton("关闭")
        close_btn.setObjectName("AccentButton")
        close_btn.clicked.connect(self.accept)
        bottom.addWidget(close_btn)
        root.addLayout(bottom)

        self._update_cache_label()

    # ------------------------------------------------------------------
    def _load_cards(self):
        # 清空（保留尾部 stretch）
        while self.list_layout.count() > 1:
            item = self.list_layout.takeAt(0)
            w = item.widget() if item else None
            if w is not None:
                w.deleteLater()
        for plugin in self.market.all_plugins():
            card = PluginCard(plugin, self.market, self._theme, self._fs)
            card.toggled.connect(self._on_toggle)
            card.install.connect(self._on_install)
            card.uninstall.connect(self._on_uninstall)
            self.list_layout.insertWidget(self.list_layout.count() - 1, card)

    def _update_cache_label(self):
        age = self.market.cache_age_str()
        url = self.market.market_url()
        self.cache_label.setText(("远程索引：%s" % age) if age else "内置索引（未拉取远程）")
        self.cache_label.setToolTip(url)

    # ------------------------------------------------------------------
    def _on_toggle(self, plugin_id, on):
        ok, msg = self.market.set_pack_enabled(plugin_id, on)
        if not ok:
            self.status_label.setText(msg)
        self._reload()
        self.changed.emit()

    def _on_install(self, plugin_id):
        plugin = self.market.get(plugin_id) or {}
        ptype = plugin.get("type", "tool")
        if ptype == "code":
            # 代码插件：源码预览 + 勾选确认后才能安装
            source = self.market.market_url()
            if not (self.cfg.data.get("market_cache") or {}).get("plugins"):
                source = "内置索引（未拉取远程）"
            dlg = CodePluginWarningDialog(plugin, source,
                                          self._theme, self._fs, self)
            if dlg.exec_() != QDialog.Accepted:
                return
        ok, msg = self.market.install(plugin_id)
        self.status_label.setText(msg)
        self._reload()
        if ok:
            self.changed.emit()

    def _on_uninstall(self, plugin_id):
        ok, msg = self.market.uninstall(plugin_id)
        self.status_label.setText(msg)
        self._reload()
        if ok:
            self.changed.emit()

    def _on_refresh(self):
        self.refresh_btn.setEnabled(False)
        self.status_label.setText("正在拉取远程索引 ...")
        self._refresh_worker = _RefreshWorker(self.market, self)
        self._refresh_worker.done.connect(self._on_refreshed)
        self._refresh_worker.start()

    def _on_refreshed(self, ok, msg):
        self.refresh_btn.setEnabled(True)
        self.status_label.setText(msg if not ok else "✓ " + msg)
        self._update_cache_label()
        self._reload()
        self.changed.emit()

    def _reload(self):
        self._load_cards()
        self._update_cache_label()

    # ------------------------------------------------------------------
    def apply_theme(self, theme_name=None, font_size=None):
        if theme_name:
            self._theme = get_theme(theme_name)
        if font_size:
            self._fs = int(font_size)
        self.setStyleSheet(build_qss(self._theme, self._fs))
        self._reload()
