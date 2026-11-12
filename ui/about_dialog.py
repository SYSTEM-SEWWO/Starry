# -*- coding: utf-8 -*-
"""关于对话框：产品身份（名称 / 版本 / 更新）、使用统计、快捷键、数据目录、反馈。

对应 HR 评估 P0-1 / P0-2 / P1-5 的落地：
- 版本号 + 检查更新（打开 GitHub Releases，失败有提示）
- 本地用量统计（只读，隐私优先）
- 全局热键状态显示
- 数据目录一键打开
"""
import os
import time
import webbrowser

from PyQt5.QtCore import Qt, pyqtSignal, QRect
from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel,
                             QPushButton, QFrame, QGridLayout, QSizePolicy,
                             QApplication, QLineEdit)

from core.config import APP_VERSION, get_config_dir, is_license_valid
from ui.theme import build_qss, get_theme, RADIUS_L
from ui.frost import FrostGlass
from ui.liquid import LiquidGlass

APP_NAME = "星语 · Starry"
APP_SLOGAN = "液态玻璃桌面 AI 伙伴"
REPO_URL = "https://github.com/ai-desktop-assistant/ai-assistant"
RELEASES_URL = REPO_URL + "/releases"
ISSUES_URL = REPO_URL + "/issues"


def _fmt_ts(ts):
    if not ts:
        return "—"
    return time.strftime("%Y-%m-%d", time.localtime(ts))


class AboutDialog(QDialog):
    """关于 + 使用统计"""

    data_dir_requested = pyqtSignal()

    def __init__(self, config, stats=None, hotkey=None, parent=None):
        super().__init__(parent)
        self.cfg = config
        self.stats = stats
        self.hotkey = hotkey
        self._theme = get_theme(config.appearance.get("theme", "light"))
        self._fs = int(config.appearance.get("font_size", 14))
        self.setStyleSheet(build_qss(self._theme, self._fs))
        self.setWindowTitle("关于 · %s" % APP_NAME)
        self.setMinimumWidth(430)
        # v7.3：改为无边框毛玻璃面板
        self.setWindowFlags(Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self._build_ui()

    # ------------------------------------------------------------------
    def _build_ui(self):
        shell = QVBoxLayout(self)
        shell.setContentsMargins(0, 0, 0, 0)
        # 真·毛玻璃底板（背后桌面经抓屏模糊透出）
        glass = FrostGlass(self, radius=RADIUS_L)
        glass.setObjectName("FrostHost")
        glass.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        shell.addWidget(glass)

        root = glass.layout()
        root.setContentsMargins(22, 20, 22, 20)
        root.setSpacing(12)

        # ---- 品牌头 ----
        head = QHBoxLayout()
        head.setSpacing(12)
        logo = QLabel("✦")
        logo.setStyleSheet("font-size:34px;color:%s;" % self._theme["accent"])
        head.addWidget(logo)
        title_col = QVBoxLayout()
        title_col.setSpacing(2)
        name = QLabel(APP_NAME)
        name.setStyleSheet("font-size:%dpx;font-weight:bold;"
                           % (self._fs + 6))
        slogan = QLabel("%s · v%s" % (APP_SLOGAN, APP_VERSION))
        slogan.setObjectName("MutedLabel")
        title_col.addWidget(name)
        title_col.addWidget(slogan)
        head.addLayout(title_col, 1)
        root.addLayout(head)

        # ---- 更新 ----
        row = QHBoxLayout()
        self.update_btn = QPushButton("检查更新")
        self.update_btn.setCursor(Qt.PointingHandCursor)
        self.update_btn.clicked.connect(self._check_update)
        row.addWidget(self.update_btn)
        self.update_label = QLabel("当前版本 v%s" % APP_VERSION)
        self.update_label.setObjectName("MutedLabel")
        row.addWidget(self.update_label, 1)
        root.addLayout(row)

        # ---- 使用统计 ----
        if self.stats is not None:
            root.addWidget(self._stats_card())

        # ---- 快捷键 ----
        root.addWidget(self._shortcuts_card())

        # ---- 商业授权（v7.3：企业商用合规） ----
        root.addWidget(self._license_card())

        # ---- 数据与反馈 ----
        row2 = QHBoxLayout()
        row2.setSpacing(8)
        self.data_btn = QPushButton("打开数据目录")
        self.data_btn.setCursor(Qt.PointingHandCursor)
        self.data_btn.clicked.connect(self._open_data_dir)
        row2.addWidget(self.data_btn)
        self.feedback_btn = QPushButton("反馈 / 建议")
        self.feedback_btn.setCursor(Qt.PointingHandCursor)
        self.feedback_btn.clicked.connect(
            lambda: webbrowser.open(ISSUES_URL))
        row2.addWidget(self.feedback_btn)
        row2.addStretch(1)
        root.addLayout(row2)

        note = QLabel("API Key 与对话记录仅保存在本机，不会上传。"
                      "用量统计为本地聚合数字。")
        note.setObjectName("MutedLabel")
        note.setWordWrap(True)
        root.addWidget(note)

        close_btn = QPushButton("关闭")
        close_btn.setObjectName("AccentButton")
        close_btn.clicked.connect(self.accept)
        root.addWidget(close_btn, 0, Qt.AlignRight)

    # ------------------------------------------------------------------
    def _stats_card(self):
        card = QFrame()
        card.setObjectName("PluginCard")
        lay = QVBoxLayout(card)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(6)
        title = QLabel("📊 使用统计（本机）")
        title.setStyleSheet("font-weight:bold;")
        lay.addWidget(title)

        s = self.stats.summary()
        grid = QGridLayout()
        grid.setSpacing(4)
        items = [
            ("发送消息", "%d 条" % s["messages"]),
            ("工具调用", "%d 次" % s["tool_calls"]),
            ("创建会话", "%d 个" % s["sessions"]),
            ("估算 Tokens", "≈ %s" % format(s["est_tokens"], ",")),
            ("活跃天数", "%d 天" % s["active_days"]),
            ("首次使用", _fmt_ts(s["first_run"])),
        ]
        for i, (k, v) in enumerate(items):
            r, c = divmod(i, 3)
            kl = QLabel(k)
            kl.setObjectName("MutedLabel")
            vl = QLabel(v)
            vl.setStyleSheet("font-weight:bold;")
            grid.addWidget(kl, r * 2, c)
            grid.addWidget(vl, r * 2 + 1, c)
        lay.addLayout(grid)
        est = QLabel("Token 为按字符数的粗略估算，仅供参考。")
        est.setObjectName("MutedLabel")
        lay.addWidget(est)
        return card

    def _shortcuts_card(self):
        card = QFrame()
        card.setObjectName("PluginCard")
        lay = QVBoxLayout(card)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(6)
        title = QLabel("⌨ 快捷键与操作")
        title.setStyleSheet("font-weight:bold;")
        lay.addWidget(title)
        grid = QGridLayout()
        grid.setSpacing(4)
        rows = [
            ("Enter", "发送消息"),
            ("Shift+Enter", "输入框换行"),
            ("Ctrl+Shift+S", "区域截图提问"),
            ("Ctrl+V", "粘贴图片"),
        ]
        hotkey = (self.hotkey.hotkey.upper() if self.hotkey else "CTRL+SHIFT+A")
        if self.hotkey is not None and self.hotkey.active:
            rows.append((hotkey, "全局唤起 / 隐藏窗口"))
        else:
            reason = (self.hotkey.error if self.hotkey else "") or "未启用"
            rows.append((hotkey + "（未生效）", reason))
        for i, (k, v) in enumerate(rows):
            kl = QLabel(k)
            kl.setStyleSheet("font-weight:bold;")
            vl = QLabel(v)
            vl.setObjectName("MutedLabel")
            grid.addWidget(kl, i, 0)
            grid.addWidget(vl, i, 1)
        lay.addLayout(grid)
        return card

    def _license_card(self):
        """v7.3 商业授权状态块（企业商用合规）；v7.5 起可填写并即时校验密钥"""
        card = LiquidGlass(self, radius=14)
        lay = card.layout()              # 复用 LiquidGlass 自带布局
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(8)
        title = QLabel("⚖ 商业授权")
        title.setStyleSheet("font-weight:bold;")
        lay.addWidget(title)

        lic_key = (self.cfg.data.get("license_key") or "").strip()
        grid = QGridLayout()
        grid.setSpacing(4)
        type_lbl = QLabel("商业授权 · Commercial")
        type_lbl.setStyleSheet("font-weight:bold;")
        grid.addWidget(QLabel("授权类型"), 0, 0)
        grid.addWidget(type_lbl, 0, 1)

        # 可编辑密钥输入（v7.5：填写即校验，杜绝伪造串冒充正版）
        self._lic_edit = QLineEdit(lic_key)
        self._lic_edit.setPlaceholderText("填入许可密钥（格式 XXXX-XXXX-XXXX-XXXX）")
        self._lic_edit.setClearButtonEnabled(True)
        self._lic_edit.editingFinished.connect(self._on_license_edit)
        grid.addWidget(QLabel("许可密钥"), 1, 0)
        grid.addWidget(self._lic_edit, 1, 1)

        self._lic_status = QLabel()
        self._lic_status.setObjectName("MutedLabel")
        grid.addWidget(QLabel("校验状态"), 2, 0)
        grid.addWidget(self._lic_status, 2, 1)
        lay.addLayout(grid)
        self._refresh_license_status()

        foot = QLabel("© 2026 星语 Starry · 保留所有权利 ｜ 条款详见随附 LICENSE")
        foot.setObjectName("MutedLabel")
        foot.setWordWrap(True)
        lay.addWidget(foot)
        return card

    def _refresh_license_status(self):
        key = (self._lic_edit.text() or "").strip()
        if not key:
            self._lic_status.setText("未填写 · 试用版")
            self._lic_status.setStyleSheet("color:#888;")
        elif is_license_valid(self.cfg) and \
                self.cfg.data.get("license_key", "").strip() == key:
            self._lic_status.setText("✓ 已验证正版")
            self._lic_status.setStyleSheet("color:#1a9e6f;")
        else:
            self._lic_status.setText("格式无效（应为 16 位校验密钥）")
            self._lic_status.setStyleSheet("color:#c0392b;")

    def _on_license_edit(self):
        key = (self._lic_edit.text() or "").strip()
        self.cfg.data["license_key"] = key
        self.cfg.data["license_verified"] = bool(key) and is_license_valid(self.cfg)
        try:
            self.cfg.save()
        except Exception:                      # noqa: BLE001
            pass
        self._refresh_license_status()

    # ------------------------------------------------------------------
    def _check_update(self):
        self.update_label.setText("正在打开 Releases 页面 …")
        try:
            webbrowser.open(RELEASES_URL)
            self.update_label.setText(
                "已打开 Releases 页面，请查看最新版本（当前 v%s）" % APP_VERSION)
        except Exception as e:  # noqa: BLE001
            self.update_label.setText("打开失败：%s" % e)

    def _open_data_dir(self):
        path = get_config_dir()
        try:
            if os.name == "nt":
                os.startfile(path)  # noqa: S606
            elif os.name == "posix":
                os.system('xdg-open "%s" >/dev/null 2>&1 || open "%s" '
                          '>/dev/null 2>&1' % (path, path))
            self.update_label.setText("数据目录：%s" % path)
        except Exception as e:  # noqa: BLE001
            self.update_label.setText("数据目录：%s（打开失败：%s）" % (path, e))

    # ------------------------------------------------------------------
    def showEvent(self, e):
        """无边框窗口：显示时居中到父窗口 / 屏幕（避免落在角落）"""
        super().showEvent(e)
        parent = self.parent()
        if parent is not None:
            pr = parent.geometry()
            x = pr.x() + (pr.width() - self.width()) // 2
            y = pr.y() + (pr.height() - self.height()) // 2
        else:
            screen = QApplication.primaryScreen()
            sg = screen.availableGeometry() if screen else QRect(0, 0, 800, 600)
            x = sg.x() + (sg.width() - self.width()) // 2
            y = sg.y() + (sg.height() - self.height()) // 2
        self.move(max(0, x), max(0, y))

    # ------------------------------------------------------------------
    def apply_theme(self, theme_name=None, font_size=None):
        if theme_name:
            self._theme = get_theme(theme_name)
        if font_size:
            self._fs = int(font_size)
        self.setStyleSheet(build_qss(self._theme, self._fs))
