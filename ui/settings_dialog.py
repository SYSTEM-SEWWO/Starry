# -*- coding: utf-8 -*-
"""设置对话框：服务商 / API Key / 模型 / 生成参数 / 外观 / 网页接入。"""
import json
import os

from PyQt5.QtCore import Qt, QThread, pyqtSignal
from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QFormLayout,
                             QTabWidget, QWidget, QLabel, QComboBox, QLineEdit,
                             QCheckBox, QSpinBox, QDoubleSpinBox, QTextEdit,
                             QPushButton, QDialogButtonBox, QFileDialog,
                             QMessageBox, QFrame, QListWidget, QApplication,
                             QColorDialog, QSlider)

from core import models as model_reg
from core.config import PROVIDERS
from core.web_sites import (SELECTOR_LABELS, get_site, is_web_site,
                            site_keys, site_status_text)
from ui.theme import get_theme, build_qss, THEME_LABELS, FONT_SCALE_LABELS, effective_font_size
from ui.settings_style import settings_qss, section_label

# 兼容旧引用
ModelFetcher = model_reg.ModelFetcher

# 文件大小格式化（与模型库共用）
_human_size = None


def _fmt_size(n):
    global _human_size
    if _human_size is None:
        from core.modelscope import format_size
        _human_size = format_size
    return _human_size(n)


class _KernelInstallWorker(QThread):
    """后台安装浏览器内核（v7：缺 playwright 包时自动先装，再装 chromium）"""
    line = pyqtSignal(str)          # 实时安装输出
    done = pyqtSignal(bool, str)    # (成功, 说明)

    def __init__(self, install_playwright=None):
        super().__init__()
        self._install_pw = install_playwright

    def run(self):
        try:
            from core import browser_llm as bl
        except Exception as e:                     # noqa: BLE001
            self.done.emit(False, str(e)[:150])
            return
        # install_chromium 内部按需先装 playwright 包（venv/conda 跟随
        # sys.executable），这里只透传参数与输出
        ok, detail = bl.install_chromium(self.line.emit,
                                         install_playwright=self._install_pw)
        self.done.emit(ok, detail)


class SettingsDialog(QDialog):
    onboarding_requested = pyqtSignal()
    about_requested = pyqtSignal()
    models_library_requested = pyqtSignal()
    web_login_requested = pyqtSignal(str)    # v7：引导登录指定网页站点
    apikey_guide_requested = pyqtSignal()    # v13.4：打开应用内 API Key 申请过程说明
    cache_clean_requested = pyqtSignal()     # v13.5：打开缓存清理窗口
    devtools_requested = pyqtSignal()        # v13.5：打开开发者调试面板
    auto_scale_requested = pyqtSignal()      # v13.5：立即按屏幕自动适配缩放
    density_requested = pyqtSignal(str)      # v13.6.5：即时切换栏目密度
    layout_reset_requested = pyqtSignal()    # v13.6.5：一键恢复推荐布局
    background_changed = pyqtSignal()        # v13.7：主窗口背景立即应用
    web_switch_requested = pyqtSignal(str)   # v7：切换到指定网页站点
    gateway_requested = pyqtSignal()         # v6：打开网关仪表盘

    def __init__(self, config, parent=None, hotkey=None):
        super().__init__(parent)
        self.cfg = config
        self._fetcher = None
        self._hotkey = hotkey
        self._theme = get_theme(config.appearance.get("theme", "light"))
        self._fs = effective_font_size(
            config.appearance.get("font_size", 14),
            config.data.get("font_scale", "标准"))
        self.setStyleSheet(build_qss(self._theme, self._fs)
                           + settings_qss(self._theme, self._fs))
        self.setWindowTitle("设置 · 星语 · Starry")
        self.setMinimumWidth(470)
        self._build_ui()
        self._load_values()

    def apply_theme(self, theme_name=None, font_size=None):
        """主题/字号变化后刷新（由主程序在保存设置后调用）"""
        if theme_name:
            self._theme = get_theme(theme_name)
        base = int(self.cfg.appearance.get("font_size", 14))
        scale = self.cfg.data.get("font_scale", "标准")
        self._fs = effective_font_size(base, scale)
        self.setStyleSheet(build_qss(self._theme, self._fs)
                           + settings_qss(self._theme, self._fs))

    # ------------------------------------------------------------------
    # ---- v13.7 背景自定义辅助 ----
    def _current_bg_settings(self):
        return {
            "background_mode": self.bg_mode_combo.currentData(),
            "background_color": self._bg_color_name,
            "background_image": self.bg_image_edit.text().strip(),
            "background_opacity": int(self.bg_opacity_slider.value()),
        }

    def _apply_background_now(self):
        ap = self.cfg.appearance
        ap.update(self._current_bg_settings())
        try:
            self.cfg.save()
        except Exception:                       # noqa: BLE001
            pass
        self.background_changed.emit()
        self._refresh_banner()

    def _reset_background(self):
        self.bg_mode_combo.setCurrentIndex(0)
        self._bg_color_name = "#ffffff"
        self.bg_image_edit.clear()
        self.bg_opacity_slider.setValue(35)
        self._sync_bg_preview()
        self._apply_background_now()

    def _pick_bg_color(self):
        from PyQt5.QtGui import QColor
        c = QColorDialog.getColor(QColor(self._bg_color_name or "#ffffff"),
                                  self, "选择主窗口背景色")
        if c.isValid():
            self._bg_color_name = c.name()
            self.bg_mode_combo.setCurrentIndex(1)
            self._sync_bg_preview()

    def _pick_bg_image(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "选择主窗口背景图片", "",
            "图片文件 (*.png *.jpg *.jpeg *.webp *.bmp);;所有文件 (*)")
        if path:
            self.bg_image_edit.setText(path)
            self.bg_mode_combo.setCurrentIndex(2)

    def _sync_bg_preview(self):
        self.bg_color_preview.setStyleSheet(
            "background:%s;border:1px solid #c9d4e0;border-radius:4px;"
            % (self._bg_color_name or "#ffffff"))

    def _load_bg_values(self):
        ap = self.cfg.appearance
        mode = ap.get("background_mode", "theme")
        idx = self.bg_mode_combo.findData(mode)
        self.bg_mode_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self._bg_color_name = ap.get("background_color", "") or "#ffffff"
        self.bg_image_edit.setText(ap.get("background_image", "") or "")
        self.bg_opacity_slider.setValue(int(ap.get("background_opacity", 35)))
        self.bg_opacity_label.setText("%d%%" % self.bg_opacity_slider.value())
        self._sync_bg_preview()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setSpacing(10)

        # v13.5：顶部状态横幅 —— 一眼看清当前生效配置
        banner = QFrame()
        banner.setObjectName("SettingsBanner")
        bl = QVBoxLayout(banner)
        bl.setContentsMargins(11, 7, 11, 7)
        bl.setSpacing(2)
        self.banner_title = QLabel("⚙ 设置 · 星语 Starry")
        self.banner_title.setObjectName("BannerTitle")
        bl.addWidget(self.banner_title)
        self.banner_meta = QLabel("")
        self.banner_meta.setObjectName("BannerMeta")
        self.banner_meta.setWordWrap(True)
        bl.addWidget(self.banner_meta)
        root.addWidget(banner)

        tabs = QTabWidget()
        root.addWidget(tabs)

        # ================= 模型页 =================
        page = QWidget()
        form = QFormLayout(page)
        form.setLabelAlignment(Qt.AlignRight)
        form.setSpacing(10)

        self.provider_combo = QComboBox()
        for key, info in PROVIDERS.items():
            self.provider_combo.addItem(info["name"], key)
        self.provider_combo.currentIndexChanged.connect(self._on_provider_changed)
        form.addRow("服务商", self.provider_combo)

        self.desc_label = QLabel("")
        self.desc_label.setObjectName("MutedLabel")
        self.desc_label.setWordWrap(True)
        form.addRow("", self.desc_label)

        key_row = QHBoxLayout()
        self.key_edit = QLineEdit()
        self.key_edit.setEchoMode(QLineEdit.Password)
        self.key_edit.setPlaceholderText("sk-...")
        self.key_show = QCheckBox("显示")
        self.key_show.stateChanged.connect(self._toggle_key_echo)
        key_row.addWidget(self.key_edit, 1)
        key_row.addWidget(self.key_show)
        self.guide_btn = QPushButton("📖 申请步骤")
        self.guide_btn.setToolTip("查看该服务商 API Key 的完整申请过程（应用内说明，不联网）")
        self.guide_btn.clicked.connect(self.apikey_guide_requested.emit)
        key_row.addWidget(self.guide_btn)
        form.addRow("API Key", key_row)

        self.key_link = QLabel("")
        self.key_link.setObjectName("MutedLabel")
        self.key_link.setOpenExternalLinks(True)
        form.addRow("", self.key_link)

        self.url_edit = QLineEdit()
        self.url_edit.setPlaceholderText("https://api.example.com/v1")
        form.addRow("Base URL", self.url_edit)

        model_row = QHBoxLayout()
        self.model_combo = QComboBox()
        self.model_combo.setEditable(True)
        self.model_combo.currentIndexChanged.connect(self._load_param_values)
        model_row.addWidget(self.model_combo, 1)
        self.fetch_btn = QPushButton("获取模型列表")
        self.fetch_btn.clicked.connect(self._fetch_models)
        model_row.addWidget(self.fetch_btn)
        form.addRow("模型", model_row)

        # v13.6：空模型引导 + 服务商/端口错配一键修正
        self.model_hint = QLabel("")
        self.model_hint.setObjectName("HintLabel")
        self.model_hint.setWordWrap(True)
        form.addRow("", self.model_hint)
        self.fix_provider_btn = QPushButton("")
        self.fix_provider_btn.setObjectName("PrimaryAction")
        self.fix_provider_btn.setVisible(False)
        self.fix_provider_btn.clicked.connect(self._fix_provider_mismatch)
        form.addRow("", self.fix_provider_btn)
        self._suggest_provider = None

        self.test_btn = QPushButton("测试连接")
        self.test_btn.clicked.connect(self._fetch_models)
        form.addRow("", self.test_btn)

        self.auto_refresh_check = QCheckBox("启动时自动拉取最新模型列表")
        self.auto_refresh_check.setToolTip("自动更新免费/新增模型，下拉框带「免费」徽标")
        form.addRow("", self.auto_refresh_check)

        tabs.addTab(page, "⚙ 模型")

        # ================= 生成参数页 =================
        page_p = QWidget()
        form_p = QFormLayout(page_p)
        form_p.setLabelAlignment(Qt.AlignRight)
        form_p.setSpacing(10)

        self.param_scope_lb = QLabel("")
        self.param_scope_lb.setWordWrap(True)
        form_p.addRow("当前模型", self.param_scope_lb)

        self.temp_spin = QDoubleSpinBox()
        self.temp_spin.setRange(0.0, 2.0)
        self.temp_spin.setSingleStep(0.1)
        self.temp_spin.setDecimals(1)
        self.temp_spin.setToolTip("越低越保守稳定，越高越发散有创意")
        form_p.addRow("温度 Temperature", self.temp_spin)

        self.top_p_spin = QDoubleSpinBox()
        self.top_p_spin.setRange(0.10, 1.0)
        self.top_p_spin.setSingleStep(0.05)
        self.top_p_spin.setDecimals(2)
        self.top_p_spin.setToolTip("核采样：1.00 表示关闭（由模型默认决定）")
        form_p.addRow("Top-P", self.top_p_spin)

        self.tokens_spin = QSpinBox()
        self.tokens_spin.setRange(256, 32768)
        self.tokens_spin.setSingleStep(256)
        form_p.addRow("最大 Tokens", self.tokens_spin)

        self.effort_combo = QComboBox()
        for key, label in (("off", "关闭（默认）"), ("low", "低 · 快速"),
                           ("medium", "中 · 均衡"), ("high", "高 · 深度思考")):
            self.effort_combo.addItem(label, key)
        self.effort_combo.setToolTip(
            "思考强度：控制推理模型的思考预算。需模型/服务商支持"
            "（OpenRouter / DeepSeek / 智谱 / 阿里百炼 / Groq 等），"
            "不支持的服务商将自动忽略该参数")
        form_p.addRow("思考强度", self.effort_combo)

        ctx_row = QHBoxLayout()
        self.ctx_combo = QComboBox()
        for v in (4096, 8192, 16384, 32768, 65536, 131072):
            self.ctx_combo.addItem("%dK" % (v // 1024), v)
        self.ctx_combo.setToolTip("常用预设（也可在右侧自定义）")
        self.ctx_combo.currentIndexChanged.connect(self._on_ctx_preset)
        ctx_row.addWidget(self.ctx_combo)
        self.ctx_spin = QSpinBox()
        self.ctx_spin.setRange(2048, 200000)
        self.ctx_spin.setSingleStep(1024)
        self.ctx_spin.setToolTip("上下文窗口大小：超出后自动裁剪最早的聊天记录"
                                 "（系统提示与最近消息始终保留）")
        ctx_row.addWidget(self.ctx_spin)
        ctx_row.addStretch(1)
        form_p.addRow("上下文大小", ctx_row)

        self.prompt_edit = QTextEdit()
        self.prompt_edit.setFixedHeight(72)
        self.prompt_edit.setPlaceholderText("系统提示词（人设）")
        form_p.addRow("系统提示", self.prompt_edit)

        # ---- 参数作用域：全局 / 当前模型 ----
        scope_box = QFrame()
        scope_box.setObjectName("AttachChip")
        sb = QVBoxLayout(scope_box)
        sb.setSpacing(8)
        self.scope_global = QCheckBox("应用到所有模型（全局默认）")
        self.scope_model = QCheckBox("仅对当前模型生效")
        self.scope_global.setChecked(True)
        self.scope_global.toggled.connect(
            lambda on: self.scope_model.setChecked(not on) if on else None)
        self.scope_model.toggled.connect(
            lambda on: self.scope_global.setChecked(not on) if on else None)
        sb.addWidget(self.scope_global)
        sb.addWidget(self.scope_model)
        scope_btn_row = QHBoxLayout()
        self.override_badge = QLabel("")
        self.override_badge.setObjectName("MutedLabel")
        self.override_badge.setWordWrap(True)
        scope_btn_row.addWidget(self.override_badge, 1)
        self.save_override_btn = QPushButton("保存为当前模型专属参数")
        self.save_override_btn.setCursor(Qt.PointingHandCursor)
        self.save_override_btn.setToolTip(
            "把当前参数保存为「当前模型」的专属配置，切换模型后自动恢复")
        self.save_override_btn.clicked.connect(self._save_override)
        scope_btn_row.addWidget(self.save_override_btn)
        self.clear_override_btn = QPushButton("清除")
        self.clear_override_btn.setCursor(Qt.PointingHandCursor)
        self.clear_override_btn.clicked.connect(self._clear_override)
        scope_btn_row.addWidget(self.clear_override_btn)
        sb.addLayout(scope_btn_row)
        form_p.addRow("", scope_box)
        tabs.addTab(page_p, "🎛 生成参数")

        # ================= 外观页 =================
        page2 = QWidget()
        form2 = QFormLayout(page2)
        form2.setLabelAlignment(Qt.AlignRight)
        form2.setSpacing(10)

        self.theme_combo = QComboBox()
        for key, label in THEME_LABELS.items():
            self.theme_combo.addItem(label, key)
        form2.addRow("主题", self.theme_combo)

        self.font_spin = QSpinBox()
        self.font_spin.setRange(11, 20)
        form2.addRow("正文字号", self.font_spin)

        self.scale_combo = QComboBox()
        for label in FONT_SCALE_LABELS:
            self.scale_combo.addItem(label)
        form2.addRow("界面缩放", self.scale_combo)

        from core import uilayout
        self.density_combo = QComboBox()
        for label in uilayout.DENSITY_LABELS:
            self.density_combo.addItem(label)
        self.density_combo.setToolTip(
            "上下栏目的间距与尺寸：宽松（默认）/ 超宽松更舒展，紧凑回归旧版；保存后即时生效")
        form2.addRow("栏目密度", self.density_combo)
        self.layout_reset_btn = QPushButton("↺ 恢复推荐布局（放大窗口）")
        self.layout_reset_btn.setToolTip("重置窗口尺寸与位置为当前密度的推荐值")
        self.layout_reset_btn.clicked.connect(self.layout_reset_requested.emit)
        form2.addRow("", self.layout_reset_btn)

        # ---- v13.7 主窗口背景自定义 ----
        for w in section_label(
                "🖼 主窗口背景",
                "可设为纯色或本地图片；点「立即应用」无需重启即可看到效果，"
                "保存设置后长期生效。"):
            form2.addRow("", w)
        self.bg_mode_combo = QComboBox()
        self.bg_mode_combo.addItem("跟随主题（毛玻璃）", "theme")
        self.bg_mode_combo.addItem("纯色背景", "color")
        self.bg_mode_combo.addItem("图片背景", "image")
        form2.addRow("背景模式", self.bg_mode_combo)

        bg_color_row = QHBoxLayout()
        self.bg_color_btn = QPushButton("选择颜色")
        self.bg_color_btn.clicked.connect(self._pick_bg_color)
        bg_color_row.addWidget(self.bg_color_btn)
        self.bg_color_preview = QLabel("     ")
        self.bg_color_preview.setFixedWidth(46)
        bg_color_row.addWidget(self.bg_color_preview)
        bg_color_row.addStretch(1)
        form2.addRow("背景颜色", bg_color_row)

        bg_img_row = QHBoxLayout()
        self.bg_image_edit = QLineEdit()
        self.bg_image_edit.setPlaceholderText("选择一张本地图片（png / jpg / webp）")
        self.bg_image_edit.setReadOnly(True)
        bg_img_row.addWidget(self.bg_image_edit, 1)
        self.bg_image_btn = QPushButton("浏览…")
        self.bg_image_btn.clicked.connect(self._pick_bg_image)
        bg_img_row.addWidget(self.bg_image_btn)
        form2.addRow("背景图片", bg_img_row)

        bg_op_row = QHBoxLayout()
        self.bg_opacity_slider = QSlider(Qt.Horizontal)
        self.bg_opacity_slider.setRange(5, 90)
        self.bg_opacity_slider.setValue(35)
        self.bg_opacity_slider.valueChanged.connect(
            lambda v: self.bg_opacity_label.setText("%d%%" % v))
        bg_op_row.addWidget(self.bg_opacity_slider, 1)
        self.bg_opacity_label = QLabel("35%")
        bg_op_row.addWidget(self.bg_opacity_label)
        form2.addRow("叠加强度", bg_op_row)

        bg_btn_row = QHBoxLayout()
        self.bg_apply_btn = QPushButton("立即应用")
        self.bg_apply_btn.setObjectName("PrimaryAction")
        self.bg_apply_btn.clicked.connect(self._apply_background_now)
        bg_btn_row.addWidget(self.bg_apply_btn)
        self.bg_reset_btn = QPushButton("恢复默认")
        self.bg_reset_btn.clicked.connect(self._reset_background)
        bg_btn_row.addWidget(self.bg_reset_btn)
        bg_btn_row.addStretch(1)
        form2.addRow("", bg_btn_row)

        self.ball_spin = QSpinBox()
        self.ball_spin.setRange(40, 96)
        self.ball_spin.setSingleStep(4)
        form2.addRow("悬浮球大小", self.ball_spin)

        self.top_check = QCheckBox("窗口始终置顶")
        form2.addRow("", self.top_check)

        hotkey_row = QHBoxLayout()
        self.hotkey_edit = QLineEdit()
        self.hotkey_edit.setPlaceholderText("ctrl+shift+a")
        self.hotkey_edit.setToolTip(
            "全局唤起热键，格式：ctrl+shift+a / alt+space / ctrl+f5；"
            "留空使用默认值；需安装 pynput 后生效")
        self.hotkey_edit.textChanged.connect(self._update_hotkey_status)
        hotkey_row.addWidget(self.hotkey_edit, 1)
        self.hotkey_status = QLabel("")
        self.hotkey_status.setObjectName("MutedLabel")
        self._update_hotkey_status()
        hotkey_row.addWidget(self.hotkey_status)
        form2.addRow("全局唤起热键", hotkey_row)

        # ---- 语音朗读引擎状态（HR v5 P1-1） ----
        tts_row = QHBoxLayout()
        self.tts_status = QLabel("")
        self.tts_status.setObjectName("MutedLabel")
        self.tts_status.setWordWrap(True)
        tts_row.addWidget(self.tts_status, 1)
        form2.addRow("语音朗读", tts_row)
        self._update_tts_status()

        note = QLabel("提示：悬浮球大小修改后立即生效；主题与字号切换会即时刷新界面。")
        note.setObjectName("MutedLabel")
        note.setWordWrap(True)
        form2.addRow("", note)

        # ---- 引导与备份 ----
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        self.guide_btn = QPushButton("重新观看新手引导")
        self.guide_btn.setCursor(Qt.PointingHandCursor)
        self.guide_btn.setToolTip("保存设置后重新播放首次启动的聚光灯引导")
        self.guide_btn.clicked.connect(self._replay_onboarding)
        btn_row.addWidget(self.guide_btn)
        self.about_btn = QPushButton("关于 星语")
        self.about_btn.setCursor(Qt.PointingHandCursor)
        self.about_btn.setToolTip("查看版本、使用统计、快捷键与数据目录")
        self.about_btn.clicked.connect(self._open_about)
        btn_row.addWidget(self.about_btn)
        btn_row.addStretch(1)
        self.export_btn = QPushButton("导出配置")
        self.export_btn.setCursor(Qt.PointingHandCursor)
        self.export_btn.clicked.connect(self._export_config)
        btn_row.addWidget(self.export_btn)
        self.import_btn = QPushButton("导入配置")
        self.import_btn.setCursor(Qt.PointingHandCursor)
        self.import_btn.clicked.connect(self._import_config)
        btn_row.addWidget(self.import_btn)
        self.export_all_btn = QPushButton("导出全部数据")
        self.export_all_btn.setCursor(Qt.PointingHandCursor)
        self.export_all_btn.setToolTip(
            "打包配置 + 会话 + 用量统计为一个 zip（含 API Key，请妥善保管）")
        self.export_all_btn.clicked.connect(self._export_all_data)
        btn_row.addWidget(self.export_all_btn)
        form2.addRow("", btn_row)

        # ---- v13.5 自动缩放大小比例 ----
        for w in section_label(
                "🔎 自动缩放",
                "按屏幕 DPI 与分辨率自动推荐界面缩放档与窗口尺寸；"
                "关闭后沿用上方手动「界面缩放」档位。"):
            form2.addRow("", w)
        self.auto_scale_check = QCheckBox("启动时自动按屏幕适配")
        self.auto_scale_check.setToolTip(
            "开启后每次启动会读取主屏 DPI / 可用区域，自动设置缩放档与窗口尺寸")
        form2.addRow("", self.auto_scale_check)
        self.auto_scale_hint = QLabel("")
        self.auto_scale_hint.setObjectName("HintLabel")
        self.auto_scale_hint.setWordWrap(True)
        form2.addRow("", self.auto_scale_hint)
        self.auto_scale_btn = QPushButton("立即按屏幕适配")
        self.auto_scale_btn.setObjectName("PrimaryAction")
        self.auto_scale_btn.clicked.connect(self.auto_scale_requested.emit)
        form2.addRow("", self.auto_scale_btn)
        tabs.addTab(page2, "🎨 外观")

        # ================= 智能体页 =================
        page3 = QWidget()
        form3 = QFormLayout(page3)
        form3.setLabelAlignment(Qt.AlignRight)
        form3.setSpacing(10)

        self.agent_check = QCheckBox("启用智能体（允许 AI 调用工具）")
        self.agent_check.setToolTip(
            "开启后 AI 可按需调用计算器 / 搜索 / 文件读取等工具；"
            "关闭则退回普通对话模式")
        form3.addRow("", self.agent_check)

        self.library_auto_check = QCheckBox("资料库自动注入（提问时检索相关片段）")
        self.library_auto_check.setToolTip(
            "开启后，每次提问会自动在资料库中检索相关文档片段，"
            "作为参考上下文发送给 AI（可在聊天窗 📚 中管理文档）")
        form3.addRow("", self.library_auto_check)

        self.iter_spin = QSpinBox()
        self.iter_spin.setRange(1, 12)
        self.iter_spin.setToolTip("单次回答中允许的最大「模型↔工具」循环轮数")
        form3.addRow("最大工具轮数", self.iter_spin)

        self.market_url_edit = QLineEdit()
        self.market_url_edit.setPlaceholderText("https://.../index.json")
        form3.addRow("插件市场地址", self.market_url_edit)

        note3 = QLabel("工具包与技能包可在聊天窗输入区上方的「🧩 插件市场」中"
                       "浏览、安装与开关；代码插件安装前会显示安全警示。")
        note3.setObjectName("MutedLabel")
        note3.setWordWrap(True)
        form3.addRow("", note3)
        tabs.addTab(page3, "🤖 智能体")

        # ================= 本地模型页 =================
        page4 = QWidget()
        form4 = QFormLayout(page4)
        form4.setLabelAlignment(Qt.AlignRight)
        form4.setSpacing(10)

        self.local_models_btn = QPushButton("📦 打开模型库（阿里魔塔）")
        self.local_models_btn.setCursor(Qt.PointingHandCursor)
        self.local_models_btn.setToolTip(
            "搜索 / 下载 GGUF 模型到本地，由 llama-server 加载为 OpenAI 兼容服务")
        self.local_models_btn.clicked.connect(self._open_models_library)
        form4.addRow("", self.local_models_btn)

        self.llama_status_lb = QLabel("")
        self.llama_status_lb.setWordWrap(True)
        self.llama_status_lb.setObjectName("MutedLabel")
        form4.addRow("llama.cpp", self.llama_status_lb)

        self.local_gguf_lb = QLabel("")
        self.local_gguf_lb.setWordWrap(True)
        form4.addRow("已下载模型", self.local_gguf_lb)

        note4 = QLabel(
            "使用流程：模型库下载 GGUF →「启动服务」→ 在服务商中选择"
            "「魔塔本地模型 · GGUF（llama.cpp）」。\n"
            "也可以使用 Ollama / LM Studio：安装后在模型下拉框会自动出现本地模型。")
        note4.setObjectName("MutedLabel")
        note4.setWordWrap(True)
        form4.addRow("", note4)
        tabs.addTab(page4, "📦 本地模型")

        # ================= 网页接入页（v6 → v7 多站点） =================
        page5 = QWidget()
        form5 = QFormLayout(page5)
        form5.setLabelAlignment(Qt.AlignRight)
        form5.setSpacing(10)

        web_note = QLabel(
            "把网页版 AI「套上马具」：用真实浏览器打开网页，像人一样提问，"
            "回答逐字流式返回。\n"
            "✓ 无需 API Key，用网页版的免费额度\n"
            "✓ 深度思考与联网搜索都能使用\n"
            "✓ 首次使用需在弹出的浏览器中登录一次，之后登录态自动持久化")
        web_note.setObjectName("MutedLabel")
        web_note.setWordWrap(True)
        form5.addRow("", web_note)

        # v7：站点选择（DeepSeek / 智谱清言 / 豆包）
        site_row = QHBoxLayout()
        site_row.setSpacing(8)
        self.web_site_combo = QComboBox()
        for skey in site_keys():
            site = get_site(skey)
            # 社区维护站点未经真机验证，标注必须醒目（HR v7 P0-1）
            tag = "" if "官方" in site["maintained"] else "（社区维护 · 未经真机验证）"
            self.web_site_combo.addItem("%s%s" % (site["name"], tag), skey)
        self.web_site_combo.currentIndexChanged.connect(
            self._on_web_site_changed)
        site_row.addWidget(self.web_site_combo)
        site_row.addStretch(1)
        form5.addRow("配置站点", site_row)

        self.web_status_lb = QLabel("检测中…")
        self.web_status_lb.setWordWrap(True)
        form5.addRow("环境状态", self.web_status_lb)

        web_btn_row = QHBoxLayout()
        self.web_login_btn = QPushButton("🌐 打开浏览器登录")
        self.web_login_btn.clicked.connect(self._on_web_login)
        self.web_switch_btn = QPushButton("切换到该网页版")
        self.web_switch_btn.clicked.connect(self._on_web_switch)
        self.gateway_btn = QPushButton("🛰 网关仪表盘")
        self.gateway_btn.clicked.connect(self._on_gateway)
        self.web_install_btn = QPushButton("⬇ 一键安装浏览器内核")
        self.web_install_btn.setToolTip(
            "在产品内执行 playwright install chromium，无需打开终端")
        self.web_install_btn.clicked.connect(self._on_web_install)
        web_btn_row.addWidget(self.web_login_btn)
        web_btn_row.addWidget(self.web_switch_btn)
        web_btn_row.addWidget(self.gateway_btn)
        web_btn_row.addWidget(self.web_install_btn)
        web_btn_row.addStretch(1)
        form5.addRow("", web_btn_row)

        self.web_install_out = QLabel("")
        self.web_install_out.setObjectName("MutedLabel")
        self.web_install_out.setWordWrap(True)
        self.web_install_out.setTextInteractionFlags(Qt.TextSelectableByMouse)
        form5.addRow("", self.web_install_out)

        self.web_headless_check = QCheckBox("无头模式（登录后不弹出浏览器窗口）")
        self.web_headless_check.setToolTip(
            "登录态持久化后，可开启无头模式在后台运行浏览器")
        form5.addRow("", self.web_headless_check)

        self.web_timeout_spin = QSpinBox()
        self.web_timeout_spin.setRange(30, 600)
        self.web_timeout_spin.setSuffix(" 秒")
        self.web_timeout_spin.setToolTip("单次回答最长等待时间")
        form5.addRow("回答超时", self.web_timeout_spin)

        install_note = QLabel(
            "依赖（可选）：pip install playwright && playwright install chromium\n"
            "未安装时其余功能不受影响，仅网页版模式不可用。")
        install_note.setObjectName("MutedLabel")
        install_note.setWordWrap(True)
        form5.addRow("", install_note)

        # ---- v7：选择器覆盖（高级，O-2） ----
        sel_note = QLabel(
            "网页结构改版后回答抓取失败时，在这里把选择器改成新结构即可，"
            "无需升级软件。每行可填多个候选用英文逗号分隔；"
            "<b>留空 = 用内置默认</b>。")
        sel_note.setObjectName("MutedLabel")
        sel_note.setWordWrap(True)
        form5.addRow("", sel_note)
        self.selector_edits = {}
        for key in ("input", "send", "answer_block", "answer",
                    "reasoning", "stop", "new_chat",
                    "logged_in", "logged_out"):
            edit = QLineEdit()
            edit.setPlaceholderText("默认：%s" % "，".join(
                (get_site("web_deepseek")["selectors"].get(key) or [])[:2])
                or "（无默认，可留空）")
            edit.setToolTip(SELECTOR_LABELS.get(key, key))
            self.selector_edits[key] = edit
            form5.addRow(SELECTOR_LABELS.get(key, key), edit)
        self.web_sel_reset_btn = QPushButton("↩ 恢复全部默认选择器")
        self.web_sel_reset_btn.setToolTip("清除本站点的全部选择器覆盖")
        self.web_sel_reset_btn.clicked.connect(self._on_reset_selectors)
        form5.addRow("", self.web_sel_reset_btn)
        tabs.addTab(page5, "🌐 网页接入")

        # ================= MCP 工具页（v7.3 补齐） =================
        page6 = QWidget()
        form6 = QFormLayout(page6)
        form6.setLabelAlignment(Qt.AlignRight)
        form6.setSpacing(10)

        mcp_note = QLabel(
            "MCP（Model Context Protocol）是 2026 年工具生态的事实标准："
            "填入他人写好的 MCP 服务器启动命令，其工具即可被本智能体直接调用，"
            "无需我们内置。工具会自动进入智能体工具箱（前缀 mcp_）。")
        mcp_note.setObjectName("MutedLabel")
        mcp_note.setWordWrap(True)
        form6.addRow("", mcp_note)

        self.mcp_list = QListWidget()
        self.mcp_list.setMinimumHeight(90)
        self.mcp_list.currentRowChanged.connect(self._on_mcp_row_changed)
        form6.addRow("服务器", self.mcp_list)

        self.mcp_name_ed = QLineEdit()
        self.mcp_name_ed.setPlaceholderText("例如：filesystem")
        form6.addRow("名称", self.mcp_name_ed)

        self.mcp_cmd_ed = QLineEdit()
        self.mcp_cmd_ed.setPlaceholderText("例如：npx")
        form6.addRow("启动命令", self.mcp_cmd_ed)

        self.mcp_args_ed = QLineEdit()
        self.mcp_args_ed.setPlaceholderText("例如：-y @modelcontextprotocol/server-filesystem /tmp")
        form6.addRow("参数", self.mcp_args_ed)

        self.mcp_enabled_cb = QCheckBox("启用")
        self.mcp_enabled_cb.setChecked(True)
        form6.addRow("", self.mcp_enabled_cb)
        self.mcp_trusted_cb = QCheckBox(
            "信任此服务器（允许其写/执行类工具自动运行；仅在你确认来源安全时勾选）")
        self.mcp_trusted_cb.setObjectName("MutedLabel")
        form6.addRow("", self.mcp_trusted_cb)

        mcp_btns = QHBoxLayout()
        self.mcp_add_btn = QPushButton("➕ 添加 / 更新")
        self.mcp_del_btn = QPushButton("🗑 删除")
        self.mcp_test_btn = QPushButton("🔌 测试连接")
        self.mcp_add_btn.clicked.connect(self._on_mcp_add)
        self.mcp_del_btn.clicked.connect(self._on_mcp_del)
        self.mcp_test_btn.clicked.connect(self._on_mcp_test)
        self.mcp_rea_btn = QPushButton("🔍 添加 REA 预设")
        self.mcp_rea_btn.setToolTip("一键添加 GitHub 爆火项目 REA（逆向工程 MCP）")
        self.mcp_rea_btn.clicked.connect(self._on_mcp_add_rea)
        mcp_btns.addWidget(self.mcp_add_btn)
        mcp_btns.addWidget(self.mcp_del_btn)
        mcp_btns.addWidget(self.mcp_test_btn)
        mcp_btns.addWidget(self.mcp_rea_btn)
        mcp_btns_w = QWidget()
        mcp_btns_w.setLayout(mcp_btns)
        form6.addRow("", mcp_btns_w)

        self.mcp_status_lb = QLabel("")
        self.mcp_status_lb.setWordWrap(True)
        self.mcp_status_lb.setObjectName("MutedLabel")
        form6.addRow("状态", self.mcp_status_lb)
        tabs.addTab(page6, "🔌 MCP 工具")

        # ================= v13.5 存储与缓存 / 开发者调试页 =================
        page7 = QWidget()
        form7 = QFormLayout(page7)
        form7.setLabelAlignment(Qt.AlignRight)
        form7.setSpacing(9)
        for w in section_label(
                "💾 存储与缓存",
                "只清理应用自身可再生的临时数据；会话 / 资料库 / 长期记忆 / "
                "API Key / 模型文件永不清理，清理前会自动备份、可撤销。"):
            form7.addRow("", w)
        self.cache_overview = QLabel("正在扫描…")
        self.cache_overview.setObjectName("HintLabel")
        self.cache_overview.setWordWrap(True)
        form7.addRow("占用概览", self.cache_overview)
        self.cache_open_btn = QPushButton("🧹 打开缓存清理窗口")
        self.cache_open_btn.setObjectName("PrimaryAction")
        self.cache_open_btn.clicked.connect(self.cache_clean_requested.emit)
        form7.addRow("", self.cache_open_btn)
        self.auto_clean_check = QCheckBox("退出时自动清理临时残留（.tmp / .log）")
        form7.addRow("", self.auto_clean_check)

        for w in section_label(
                "🛠 开发者调试",
                "开启后记录分级日志，可在调试面板实时查看、清空与导出；"
                "默认关闭且日志会脱敏，不影响正式使用。"):
            form7.addRow("", w)
        self.dev_mode_check = QCheckBox("启用开发者调试模式")
        form7.addRow("", self.dev_mode_check)
        self.log_level_combo = QComboBox()
        for lv in ("DEBUG", "INFO", "WARN", "ERROR"):
            self.log_level_combo.addItem(lv)
        form7.addRow("日志级别", self.log_level_combo)
        self.devtools_btn = QPushButton("🛠 打开开发者调试面板")
        self.devtools_btn.clicked.connect(self.devtools_requested.emit)
        form7.addRow("", self.devtools_btn)
        tabs.addTab(page7, "💾 存储与缓存")

        # ================= 按钮 =================
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._on_save)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    # ------------------------------------------------------------------
    def _load_values(self):
        idx = self.provider_combo.findData(self.cfg.provider)
        if idx >= 0:
            self.provider_combo.setCurrentIndex(idx)
        ap = self.cfg.appearance
        t_idx = self.theme_combo.findData(ap.get("theme", "light"))
        if t_idx >= 0:
            self.theme_combo.setCurrentIndex(t_idx)
        self.font_spin.setValue(int(ap.get("font_size", 14)))
        s_idx = self.scale_combo.findText(self.cfg.data.get("font_scale", "标准"))
        if s_idx >= 0:
            self.scale_combo.setCurrentIndex(s_idx)
        from core import uilayout
        self._load_bg_values()
        d_idx = self.density_combo.findText(
            uilayout.normalize(self.cfg.data.get("ui_density")))
        if d_idx >= 0:
            self.density_combo.setCurrentIndex(d_idx)
        self.ball_spin.setValue(int(ap.get("ball_size", 56)))
        self.top_check.setChecked(bool(ap.get("always_on_top", True)))
        from core.hotkey import DEFAULT_HOTKEY
        self.hotkey_edit.setText(
            self.cfg.data.get("hotkey") or DEFAULT_HOTKEY)
        self.auto_refresh_check.setChecked(
            bool(self.cfg.data.get("auto_refresh_models", True)))
        self.agent_check.setChecked(
            bool(self.cfg.data.get("agent_enabled", True)))
        self.library_auto_check.setChecked(
            bool(self.cfg.data.get("library_auto", True)))
        self.iter_spin.setValue(
            int(self.cfg.data.get("agent_max_iterations", 6)))
        from core.agent.market import PluginMarket
        self.market_url_edit.setText(PluginMarket(self.cfg).market_url())
        self._load_model_list()
        self._load_param_values()
        self._refresh_local_status()
        # 网页接入（v7）：站点下拉定位到当前网页站点（或默认 DeepSeek）
        cur_site = self.cfg.provider if is_web_site(self.cfg.provider) \
            else "web_deepseek"
        idx = self.web_site_combo.findData(cur_site)
        if idx >= 0:
            self.web_site_combo.setCurrentIndex(idx)
        self._load_web_site_values()
        self._refresh_web_status()
        # MCP 工具服务器（v7.3 补齐）
        self._load_mcp()
        # v13.5：自动缩放 / 缓存 / 调试模式
        self.auto_scale_check.setChecked(
            bool(self.cfg.data.get("auto_ui_scale", False)))
        self.auto_clean_check.setChecked(
            bool(self.cfg.data.get("auto_clean_tmp", False)))
        self.dev_mode_check.setChecked(
            bool(self.cfg.data.get("debug_mode", False)))
        lv_idx = self.log_level_combo.findText(
            str(self.cfg.data.get("log_level", "INFO")).upper())
        if lv_idx >= 0:
            self.log_level_combo.setCurrentIndex(lv_idx)
        self._refresh_banner()
        self._refresh_cache_overview()
        self._refresh_auto_scale_hint()

    # ------------------------------------------------------------------
    # v13.5：状态横幅 / 缓存概览 / 自动缩放建议
    # ------------------------------------------------------------------
    def _refresh_banner(self):
        from core.config import PROVIDERS
        info = PROVIDERS.get(self.cfg.provider) or {}
        theme_label = THEME_LABELS.get(
            self.cfg.appearance.get("theme", "light"), "浅色")
        try:
            model = self.cfg.model()
        except Exception:                               # noqa: BLE001
            model = "?"
        self.banner_title.setText("⚙ 当前生效配置")
        self.banner_meta.setText(
            "服务商：%s  ·  模型：%s\n主题：%s  ·  缩放：%s  ·  调试模式：%s"
            % (info.get("name", self.cfg.provider), model, theme_label,
               self.cfg.data.get("font_scale", "标准"),
               "开" if self.cfg.data.get("debug_mode") else "关"))

    def _refresh_cache_overview(self):
        """只读扫描缓存占用，绝不在此删除任何文件。"""
        from core import cacheclean as cc
        try:
            items = cc.scan(cfg=self.cfg)
            total = sum(i["size"] for i in items)
            count = sum(i["count"] for i in items)
            if not items:
                self.cache_overview.setText("✅ 当前没有可清理的应用缓存。")
            else:
                self.cache_overview.setText(
                    "可清理 %d 类 / %d 项，约 %s（只读扫描，未删除任何文件）"
                    % (len(items), count, cc._fmt_size(total)))
        except Exception as e:                          # noqa: BLE001
            self.cache_overview.setText("扫描失败：%s" % str(e)[:80])

    def _refresh_auto_scale_hint(self):
        from PyQt5.QtWidgets import QApplication
        from core import uiscale
        desk = QApplication.desktop()
        try:
            area = desk.availableGeometry()
            dpi = desk.logicalDpiX() or 96
            rec = uiscale.recommend(
                area.width(), area.height(), dpi,
                int(self.cfg.appearance.get("font_size", 14)))
            self._auto_scale_rec = rec
            self.auto_scale_hint.setText(uiscale.format_recommendation(rec))
            return rec
        except Exception as e:                          # noqa: BLE001
            self._auto_scale_rec = None
            self.auto_scale_hint.setText("无法读取屏幕信息：%s" % str(e)[:80])
            return None

    def _current_web_site(self):
        """网页接入页当前选中的站点 key（默认 deepseek）"""
        return self.web_site_combo.currentData() or "web_deepseek"

    def _on_web_site_changed(self, _idx=None):
        self._load_web_site_values()
        self._refresh_web_status()

    def _load_web_site_values(self):
        """把选中站点的配置（无头/超时/选择器覆盖）载入界面控件"""
        skey = self._current_web_site()
        web = self.cfg.data.get(skey, {}) or {}
        self.web_headless_check.setChecked(bool(web.get("headless", False)))
        self.web_timeout_spin.setValue(int(web.get("timeout", 180) or 180))
        # 选择器覆盖：有覆盖显示覆盖值，无覆盖留空（placeholder 显示默认）
        site = get_site(skey) or {}
        defaults = site.get("selectors", {}) or {}
        overrides = web.get("selectors", {}) or {}
        for key, edit in self.selector_edits.items():
            vals = overrides.get(key)
            edit.setText("，".join(vals) if vals else "")
            dv = defaults.get(key) or []
            edit.setPlaceholderText("默认：%s" % ("，".join(dv[:2]) if dv
                                                else "（无默认，可留空）"))

    def _on_reset_selectors(self):
        """清除当前站点的全部选择器覆盖（回退内置默认）"""
        skey = self._current_web_site()
        self.cfg.data.setdefault(skey, {})["selectors"] = {}
        for edit in self.selector_edits.values():
            edit.setText("")
        self.web_install_out.setText("已恢复 %s 的默认选择器"
                                     % (get_site(skey) or {}).get("name", skey))

    def _save_web_site_values(self):
        """保存当前站点配置（无头/超时/选择器覆盖）到 cfg.data"""
        skey = self._current_web_site()
        web = self.cfg.data.setdefault(skey, {})
        web["headless"] = bool(self.web_headless_check.isChecked())
        web["timeout"] = int(self.web_timeout_spin.value())
        overrides = {}
        for key, edit in self.selector_edits.items():
            text = (edit.text() or "").strip()
            if not text:
                continue                      # 留空 = 用默认
            vals = [v.strip() for v in text.replace("，", ",").split(",")
                    if v.strip()]
            if vals:
                overrides[key] = vals
        web["selectors"] = overrides

    def _refresh_web_status(self):
        """网页接入页：环境就绪度 + 登录态探测（当前站点）"""
        skey = self._current_web_site()
        try:
            state, detail = site_status_text(skey, self.cfg)
        except Exception as e:                 # noqa: BLE001
            state, detail = "✗ 未就绪", str(e)[:120]
        site = get_site(skey) or {}
        extra = "" if "官方" in site.get("maintained", "") else \
            "\n（社区维护站点 · 未经真机验证：抓取失败时请检查下方「选择器覆盖」，" \
            "或到 GitHub Issues 反馈新选择器）"
        self.web_status_lb.setText("%s\n%s%s" % (state, detail, extra))
        web = self.cfg.data.get(skey, {}) or {}
        self.web_headless_check.setChecked(bool(web.get("headless", False)))
        self.web_timeout_spin.setValue(int(web.get("timeout", 180) or 180))
        # 安装按钮语义：内核已就绪 → 禁用；否则 → 启用（未装 playwright 时按钮会连本体一起装）
        try:
            from core import browser_llm as bl
            ready = bl.playwright_available() and (
                bl.find_chromium() is not None or "已就绪" in state)
            self.web_install_btn.setEnabled(not ready)
            if ready:
                self.web_install_btn.setToolTip("浏览器内核已就绪")
        except Exception:                          # noqa: BLE001
            self.web_install_btn.setEnabled(True)

    def _on_web_login(self):
        self.web_login_requested.emit(self.web_site_combo.currentData())

    def _on_web_switch(self):
        self.web_switch_requested.emit(self.web_site_combo.currentData())
        self.close()

    def _on_gateway(self):
        self.gateway_requested.emit()

    def _on_web_install(self):
        """一键安装浏览器内核（P0-1：产品内闭环，不甩给终端）"""
        from core import browser_llm as bl
        if not bl.playwright_available():
            # 连 playwright 都没装：先装本体，再装内核
            self._start_kernel_install(install_playwright=True)
            return
        if bl.find_chromium():
            self.web_install_out.setText(
                "已检测到系统浏览器（%s），无需安装内核。"
                % bl.find_chromium())
            self._kernel_worker = None
            return
        # v12.0：Playwright 自带内核已装好时也不要重复下载 100+ MB。
        # 旧实现只判断系统 Chrome，导致已就绪环境下点按钮仍会启动安装线程。
        if bl.chromium_kernel_available():
            self.web_install_out.setText(
                "已检测到 Playwright 内置 Chromium 内核，无需重复安装。"
                "若网页版仍不可用，请检查登录态或点「刷新状态」。")
            self._kernel_worker = None
            return
        self._start_kernel_install(install_playwright=False)

    def _start_kernel_install(self, install_playwright=False):
        self.web_install_btn.setEnabled(False)
        self.web_install_btn.setText("⬇ 安装中…")
        self.web_install_out.setText("正在安装，请稍候（约 1–3 分钟）…")
        self._kernel_worker = _KernelInstallWorker(install_playwright)
        self._kernel_worker.line.connect(self._on_kernel_line)
        self._kernel_worker.done.connect(self._on_kernel_done)
        self._kernel_worker.start()

    def _on_kernel_line(self, text):
        tail = (self.web_install_out.text() or "").split("\n")
        tail = (tail + [text])[-4:]
        self.web_install_out.setText("\n".join(tail))

    def _on_kernel_done(self, ok, detail):
        self.web_install_btn.setEnabled(True)
        self.web_install_btn.setText("⬇ 一键安装浏览器内核")
        self.web_install_out.setText(
            ("✓ %s" if ok else "✗ %s") % detail)
        self._refresh_web_status()

    def _current_model(self):
        """对话框中当前选中的模型（未保存的更改也可见）"""
        return self.model_combo.currentData() \
            or self.model_combo.currentText().strip()

    def _load_param_values(self):
        """加载生成参数（按当前模型：覆盖值优先，否则全局值）"""
        model = self._current_model()
        provider = self.provider_combo.currentData() or self.cfg.provider
        info = PROVIDERS.get(provider, PROVIDERS["custom"])
        self.param_scope_lb.setText("%s · %s" % (info.get("name", provider),
                                                 model or "（未选择）"))
        temp = float(self.cfg.effective("temperature", provider, model) or 0.7)
        top_p = float(self.cfg.effective("top_p", provider, model) or 1.0)
        tokens = int(self.cfg.effective("max_tokens", provider, model) or 4096)
        effort = self.cfg.effective("reasoning_effort", provider, model) or "medium"
        ctx = int(self.cfg.effective("context_window", provider, model) or 32768)
        self.temp_spin.setValue(max(0.0, min(2.0, temp)))
        self.top_p_spin.setValue(max(0.10, min(1.0, top_p)))
        self.tokens_spin.setValue(max(256, min(32768, tokens)))
        e_idx = self.effort_combo.findData(effort)
        self.effort_combo.setCurrentIndex(e_idx if e_idx >= 0 else 0)
        self.ctx_spin.setValue(max(2048, min(200000, ctx)))
        c_idx = self.ctx_combo.findData(self.ctx_spin.value())
        self.ctx_combo.setCurrentIndex(c_idx if c_idx >= 0 else 0)
        self.prompt_edit.setPlainText(self.cfg.data.get("system_prompt", ""))
        # 覆盖徽标
        ov = self.cfg.get_override(provider, model)
        if ov:
            self.override_badge.setText("★ 该模型有专属参数（%d 项）" % len(ov))
            self.scope_model.setChecked(True)
            self.save_override_btn.setText("更新专属参数")
        else:
            self.override_badge.setText("当前模型未设置专属参数，保存时写入全局默认。")
            self.scope_global.setChecked(True)
            self.save_override_btn.setText("保存为当前模型专属参数")

    def _on_provider_changed(self, _index=None):
        key = self.provider_combo.currentData()
        info = PROVIDERS.get(key, PROVIDERS["custom"])
        self.key_edit.setText(self.cfg.api_key(key))
        if info.get("web"):
            # 网页版接入：无需 API Key，由浏览器登录态承载
            self.key_edit.setEnabled(False)
            self.key_edit.setPlaceholderText("网页版无需 API Key（浏览器登录）")
        else:
            self.key_edit.setEnabled(not info.get("local"))
            self.key_edit.setPlaceholderText("sk-...")
        url = self.cfg.base_url(key) or info.get("base_url", "")
        self.url_edit.setText(url)
        self._load_model_list(key)
        self._load_param_values()
        self.desc_label.setText(info.get("desc", ""))
        if info.get("web"):
            self.key_link.setText(
                '<a href="https://chat.deepseek.com" style="color:%s;">'
                '👉 点此打开 DeepSeek 网页版（无需 Key，登录即可用）</a>'
                % self._theme["accent"])
        elif info.get("key_url"):
            self.key_link.setText('<a href="%s" style="color:%s;">👉 点此申请 API Key</a>'
                                  % (info["key_url"], self._theme["accent"]))
        else:
            self.key_link.setText("")
        if info.get("local"):
            # v13.6：本地服务商切换后自动从本机拉取模型，开箱即用
            self.desc_label.setText(
                "已切换到「%s」（本地模型）。正在自动从本机拉取可用模型…"
                % PROVIDERS[key]["name"])
            self._auto_fetch_if_local()

    def _update_model_hints(self):
        """v13.6：无模型 / 服务商与端口错配时给出明确可操作引导。"""
        key = self.provider_combo.currentData()
        base = self.url_edit.text().strip()
        ep = model_reg.resolve_endpoint(key, base, PROVIDERS.get(key, {}))
        if self.model_combo.count() == 0:
            self.model_hint.setText(
                "⚠️ 该服务商没有预设模型。请点「获取模型列表」从当前 Base URL 拉取，"
                "或直接在上方模型框输入模型 ID（如 LM Studio 中已加载的模型名）。")
            self.model_combo.setPlaceholderText("输入模型名，或点「获取模型列表」")
        else:
            self.model_hint.setText("")
            self.model_combo.setPlaceholderText("")
        if ep["mismatch"]:
            target = ep["suggest_provider"]
            name = (PROVIDERS.get(target) or {}).get("name", target or "")
            self.fix_provider_btn.setText(
                "⚠️ 地址与服务商不匹配 → 一键改用「%s」" % name)
            self.fix_provider_btn.setVisible(True)
            self._suggest_provider = target
        else:
            self.fix_provider_btn.setVisible(False)
            self._suggest_provider = None

    def _fix_provider_mismatch(self):
        """一键切换到与 Base URL 匹配的服务商，并保留用户已填的地址/Key。"""
        key = getattr(self, "_suggest_provider", None)
        if not key:
            return
        base = model_reg.normalize_base_url(self.url_edit.text())
        api_key = self.key_edit.text().strip()
        idx = self.provider_combo.findData(key)
        if idx < 0:
            return
        self.provider_combo.setCurrentIndex(idx)
        self.url_edit.setText(base)
        self.key_edit.setText(api_key)
        # 下面的 setCurrentIndex 会触发 _on_provider_changed，本地服务商会自动拉模型
        self._update_model_hints()

    def _load_model_list(self, key=None):
        """用 预设 + 缓存 填充模型下拉框（带免费徽标）"""
        key = key or self.provider_combo.currentData()
        merged = model_reg.merge_models(PROVIDERS.get(key, {}).get("models"),
                                        model_reg.cache_get(self.cfg, key))
        cur = self.cfg.model(key)
        self.model_combo.clear()
        for m in merged:
            if "embed" in str(m).lower():
                continue
            self.model_combo.addItem(model_reg.display_name(m, key), m)
        if cur:
            idx = self.model_combo.findData(cur)
            if idx >= 0:
                self.model_combo.setCurrentIndex(idx)
            else:
                self.model_combo.setCurrentText(cur)
        self._update_model_hints()

    def refresh_model_list(self):
        """外部（主程序）在模型缓存更新后调用"""
        self._load_model_list()

    def _on_ctx_preset(self, _index=None):
        """上下文预设 → 同步自定义 spin"""
        v = self.ctx_combo.currentData()
        if v:
            self.ctx_spin.setValue(int(v))

    def _save_override(self):
        """把当前参数保存为当前模型专属配置"""
        provider = self.provider_combo.currentData() or self.cfg.provider
        model = self._current_model()
        if not model:
            QMessageBox.warning(self, "无法保存", "请先选择模型。")
            return
        params = {
            "temperature": round(float(self.temp_spin.value()), 2),
            "top_p": round(float(self.top_p_spin.value()), 2),
            "max_tokens": int(self.tokens_spin.value()),
            "reasoning_effort": self.effort_combo.currentData(),
            "context_window": int(self.ctx_spin.value()),
        }
        self.cfg.set_override(params, provider, model)
        self._load_param_values()
        QMessageBox.information(
            self, "已保存专属参数",
            "「%s」的参数已单独保存。\n切换到其他模型时全局默认不受影响，\n"
            "切回本模型时自动恢复。" % model)

    def _clear_override(self):
        provider = self.provider_combo.currentData() or self.cfg.provider
        model = self._current_model()
        if not self.cfg.get_override(provider, model):
            return
        if QMessageBox.question(self, "清除专属参数",
                                "确定清除「%s」的专属参数？" % model) \
                != QMessageBox.Yes:
            return
        self.cfg.clear_override(provider, model)
        self._load_param_values()

    def _toggle_key_echo(self, state):
        self.key_edit.setEchoMode(QLineEdit.Normal if state else QLineEdit.Password)

    # ------------------------------------------------------------------
    # 本地模型页
    # ------------------------------------------------------------------
    def _open_models_library(self):
        """请求主程序打开模型库对话框（避免模态叠加）"""
        self.models_library_requested.emit()

    def _refresh_local_status(self):
        """刷新 llama.cpp 状态与已下载 GGUF 列表"""
        from core import local_llm
        exe = local_llm.find_llama_server()
        if exe:
            self.llama_status_lb.setText("✓ 已就绪：%s" % exe)
        else:
            self.llama_status_lb.setText(
                "✗ 未检测到 llama-server。请到 github.com/ggml-org/llama.cpp/releases "
                "下载预编译包，将 llama-server 放入 PATH 或 %s。" % local_llm.bin_dir())
        ggufs = local_llm.list_local_gguf()
        if ggufs:
            total = sum(g["size"] for g in ggufs)
            self.local_gguf_lb.setText(
                "%d 个模型（合计 %s）\n%s"
                % (len(ggufs), _fmt_size(total),
                   "\n".join("· " + g["name"] for g in ggufs[:8])
                   + ("\n…" if len(ggufs) > 8 else "")))
        else:
            self.local_gguf_lb.setText(
                "暂无。点上方「打开模型库」从阿里魔塔下载 GGUF 模型。")

    # ------------------------------------------------------------------
    # 新手引导 / 配置备份
    # ------------------------------------------------------------------
    def _update_hotkey_status(self):
        """根据 HotkeyManager 实际状态刷新标签（P1-5）"""
        from core.hotkey import normalize_hotkey, DEFAULT_HOTKEY, \
            pynput_available
        text = self.hotkey_edit.text().strip()
        norm = normalize_hotkey(text) or DEFAULT_HOTKEY
        if not pynput_available():
            self.hotkey_status.setText("✗ 未安装 pynput（pip install pynput）")
        elif self._hotkey is not None and self._hotkey.active:
            self.hotkey_status.setText("✓ %s 已生效" % norm.upper())
        else:
            reason = (self._hotkey.error if self._hotkey else "") or "未生效"
            self.hotkey_status.setText("✗ %s" % reason)

    def _replay_onboarding(self):
        self.cfg.data["onboarded"] = False
        self.onboarding_requested.emit()
        self.guide_btn.setText("✓ 保存后将重新播放")
        self.guide_btn.setEnabled(False)

    def _update_tts_status(self):
        """语音朗读引擎状态与分平台安装指引（HR v5 P1-1）"""
        from core.tts import Speaker, tts_guidance
        sp = Speaker()
        if sp.available():
            self.tts_status.setText(
                "✓ 已就绪：点击回复气泡中的「🔊 朗读」即可播放"
                "（离线合成，不联网、不上传文本）")
        else:
            self.tts_status.setText("✗ 未就绪。" + tts_guidance())

    def _open_about(self):
        """打开关于对话框（由主程序响应，避免设置模态叠加）"""
        self.about_requested.emit()

    def _export_config(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "导出配置", "ai-assistant-config.json", "JSON 文件 (*.json)")
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(self.cfg.data, f, ensure_ascii=False, indent=2)
            QMessageBox.information(self, "导出成功",
                                    "配置已导出到：\n%s\n\n该文件包含 API Key，请妥善保管。"
                                    % path)
        except Exception as e:  # noqa: BLE001
            QMessageBox.warning(self, "导出失败", str(e))

    def _import_config(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "导入配置", "", "JSON 文件 (*.json)")
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                raise ValueError("配置文件格式不正确")
        except Exception as e:  # noqa: BLE001
            QMessageBox.warning(self, "导入失败", "无法读取配置文件：%s" % e)
            return
        # 合并导入（保留默认结构中不存在的键也一并带入）
        for k, v in data.items():
            if isinstance(v, dict) and isinstance(self.cfg.data.get(k), dict):
                self.cfg.data[k].update(v)
            else:
                self.cfg.data[k] = v
        self.cfg.save()
        self._load_values()
        self.apply_theme(self.cfg.appearance.get("theme"),
                         self.cfg.appearance.get("font_size"))
        QMessageBox.information(self, "导入成功",
                                "配置已导入。点击「Save」保存后生效。")

    # ------------------------------------------------------------------
    def _export_all_data(self):
        """打包配置 + 会话 + 统计为一个 zip（P1-4 数据主权）"""
        import zipfile
        from core.config import get_config_dir
        path, _ = QFileDialog.getSaveFileName(
            self, "导出全部数据", "ai-assistant-data.zip", "ZIP 文件 (*.zip)")
        if not path:
            return
        try:
            base = get_config_dir()
            files = {"config.json": "应用配置（含 API Key）",
                     "sessions.json": "全部会话记录",
                     "stats.json": "本机用量统计"}
            readme = ("星语 · Starry · 全部数据导出\n"
                      "============================\n\n"
                      + "\n".join("  %-16s %s" % (k, v)
                                  for k, v in files.items())
                      + "\n\n警告：config.json 包含 API Key，请妥善保管，勿随意传播。\n")
            with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
                zf.writestr("README.txt", readme)
                for name in files:
                    full = os.path.join(base, name)
                    if os.path.exists(full):
                        zf.write(full, name)
            QMessageBox.information(
                self, "导出成功",
                "全部数据已导出到：\n%s\n\n包含配置（含 API Key）、会话与统计，"
                "请妥善保管。" % path)
        except Exception as e:  # noqa: BLE001
            QMessageBox.warning(self, "导出失败", str(e))

    # ------------------------------------------------------------------
    def _auto_fetch_if_local(self):
        """v13.6：本地服务商（lmstudio / ollama）且有 Base URL 时，自动拉取模型。

        让 lmstudio 这类「无预设模型」的本地服务商开箱即用：切到它下拉立即
        有内容，不必手动点「获取模型列表」。用 isRunning 防重入。
        """
        key = self.provider_combo.currentData()
        info = PROVIDERS.get(key, {})
        if not info.get("local"):
            return
        base = model_reg.normalize_base_url(self.url_edit.text())
        if not base:
            return
        fetcher = getattr(self, "_fetcher", None)
        if fetcher is not None and fetcher.isRunning():
            return
        self._fetch_models()

    # ------------------------------------------------------------------
    def _fetch_models(self):
        key = self.provider_combo.currentData()
        info = PROVIDERS.get(key, PROVIDERS["custom"])
        base = model_reg.normalize_base_url(self.url_edit.text())
        api_key = self.key_edit.text().strip()
        if not base:
            self.desc_label.setText("请先填写 Base URL")
            return
        # v13.6：以实际 Base URL 判定端点，而不是只看服务商名。
        # 用户在 Ollama 项填 LM Studio(1234) 时，也能正确拉到 /v1/models。
        ep = model_reg.resolve_endpoint(key, base, info)
        self._endpoint = ep
        self.fetch_btn.setEnabled(False)
        self.test_btn.setEnabled(False)
        self.desc_label.setText("正在连接 %s ...（%s）" % (
            ep["base_url"], "/api/tags" if ep["is_ollama"] else "/v1/models"))
        self._fetcher = ModelFetcher(ep["base_url"], api_key,
                                     is_ollama=ep["is_ollama"],
                                     tags_url=ep["tags_url"])
        self._fetcher.done.connect(self._on_models_done)
        # 向后兼容：旧的 ModelFetcher mock 可能没有 failed_detail 信号
        if hasattr(self._fetcher, "failed_detail"):
            self._fetcher.failed_detail.connect(self._on_models_failed_detail)
        self._fetcher.failed.connect(self._on_models_failed)
        self._fetcher.start()

    def _on_models_done(self, models):
        self.fetch_btn.setEnabled(True)
        self.test_btn.setEnabled(True)
        if models:
            key = self.provider_combo.currentData()
            cur = self.model_combo.currentData() or self.model_combo.currentText().strip()
            merged = model_reg.merge_models(PROVIDERS.get(key, {}).get("models"), models)
            model_reg.cache_put(self.cfg, key, merged)
            self.model_combo.clear()
            for m in merged:
                if "embed" in str(m).lower():
                    continue
                self.model_combo.addItem(model_reg.display_name(m, key), m)
            if not cur and merged:
                # v13.6：本地服务商首次拉到模型时自动选中第一个，开箱即用
                cur = merged[0]
            if cur:
                idx = self.model_combo.findData(cur)
                if idx >= 0:
                    self.model_combo.setCurrentIndex(idx)
                else:
                    self.model_combo.setCurrentText(cur)
            if self.model_combo.currentIndex() < 0 and self.model_combo.count():
                self.model_combo.setCurrentIndex(0)
            ep = getattr(self, "_endpoint", None) or {}
            msg = "连接成功，共获取到 %d 个模型。" % len(merged)
            if ep.get("mismatch"):
                msg += "\n⚠️ " + ep.get("hint", "")
            self.desc_label.setText(msg)
            self._update_model_hints()
        else:
            self.desc_label.setText("连接成功，但未返回模型列表。")
            self._update_model_hints()

    def _on_models_failed_detail(self, detail):
        """v13.2：保存结构化分类，供可操作错误卡片使用。"""
        self._last_fetch_error = dict(detail or {})

    def _on_models_failed(self, err):
        """v13.2：显示分类、原因与逐条建议，而不是一行不可操作的原始错误。"""
        from core import apierrors
        self.fetch_btn.setEnabled(True)
        self.test_btn.setEnabled(True)
        detail = (getattr(self, "_last_fetch_error", None)
                  or apierrors.from_exception(err, "model_fetch"))
        self.desc_label.setWordWrap(True)
        self.desc_label.setText(
            apierrors.full_text(detail)
            + "\n\n（完整脱敏记录：命令面板 → 「API 诊断」）")
        self._last_fetch_error = {}

    # ------------------------------------------------------------------
    # ------------------------------------------------------------------
    # MCP 工具服务器（v7.3 补齐）
    # ------------------------------------------------------------------
    def _load_mcp(self):
        from core.mcp import normalize_entry
        self._mcp_entries = [normalize_entry(e) for e in
                             (self.cfg.data.get("mcp_servers") or [])]
        self._refresh_mcp_list()

    def _refresh_mcp_list(self):
        self.mcp_list.clear()
        for e in self._mcp_entries:
            flag = "启用" if e["enabled"] else "禁用"
            trust = "·信任" if e.get("trusted") else ""
            args = " ".join(e["args"])
            self.mcp_list.addItem("%s（%s%s）— %s %s"
                                  % (e["name"], flag, trust,
                                     e["command"], args))

    def _on_mcp_row_changed(self, row):
        if row is None or row < 0 or row >= len(self._mcp_entries):
            return
        e = self._mcp_entries[row]
        self.mcp_name_ed.setText(e["name"])
        self.mcp_cmd_ed.setText(e["command"])
        self.mcp_args_ed.setText(" ".join(e["args"]))
        self.mcp_enabled_cb.setChecked(bool(e["enabled"]))
        self.mcp_trusted_cb.setChecked(bool(e.get("trusted", False)))

    def _on_mcp_add(self):
        from core.mcp import normalize_entry
        name = self.mcp_name_ed.text().strip()
        cmd = self.mcp_cmd_ed.text().strip()
        if not name or not cmd:
            self.mcp_status_lb.setText("名称与启动命令都不能为空")
            return
        entry = normalize_entry({
            "name": name, "command": cmd,
            "args": self.mcp_args_ed.text(),
            "enabled": self.mcp_enabled_cb.isChecked(),
            "trusted": self.mcp_trusted_cb.isChecked()})
        for i, e in enumerate(self._mcp_entries):
            if e["name"] == name:
                self._mcp_entries[i] = entry
                break
        else:
            self._mcp_entries.append(entry)
        self._refresh_mcp_list()
        self.mcp_status_lb.setText("已记录「%s」，点窗口「保存」生效" % name)

    def _on_mcp_del(self):
        row = self.mcp_list.currentRow()
        if row is None or row < 0 or row >= len(self._mcp_entries):
            self.mcp_status_lb.setText("请先在上方列表选中一条")
            return
        name = self._mcp_entries.pop(row)["name"]
        self._refresh_mcp_list()
        self.mcp_status_lb.setText("已删除「%s」，点窗口「保存」生效" % name)

    def _on_mcp_add_rea(self):
        """V9.0：一键添加 REA 逆向工程 MCP 预设（GitHub 爆火项目）。"""
        from core.rea import ensure_rea_preset
        self._mcp_entries, existed = ensure_rea_preset(self._mcp_entries)
        self._refresh_mcp_list()
        self.mcp_status_lb.setText(
            ("已定位到 REA 预设（已存在）" if existed
             else "已添加 REA 逆向工程预设（默认禁用，需在列表勾选启用并连接）")
            + "，点窗口「保存」生效")

    def _on_mcp_test(self):
        from core.mcp import McpClient
        name = self.mcp_name_ed.text().strip()
        cmd = self.mcp_cmd_ed.text().strip()
        if not name or not cmd:
            self.mcp_status_lb.setText("请先填写名称与启动命令，再测试")
            return
        self.mcp_status_lb.setText("正在连接…（最长 8 秒）")
        QApplication.processEvents()
        cli = McpClient(name, cmd, self.mcp_args_ed.text().split())
        cli.timeout = 8.0
        ok, msg = cli.start()
        if ok:
            tools = cli.list_tools()
            names = ", ".join(t.get("name", "") for t in tools) or "无"
            self.mcp_status_lb.setText("%s；工具：%s" % (msg, names))
        else:
            self.mcp_status_lb.setText("连接失败：%s" % msg)
        cli.stop()

    def _on_save(self):
        key = self.provider_combo.currentData()
        # v13.6：模型框可编辑，但 QComboBox.currentData() 在用户手动改写文本后
        # 仍返回旧下拉项的数据。若直接取 currentData，用户输入的模型名会被
        # 静默忽略 —— 这正是「设置里改不了模型」的直接原因之一。
        typed = str(self.model_combo.currentText() or "").strip().replace(
            "（免费）", "").strip()
        data = self.model_combo.currentData()
        raw = typed if typed and (not data or typed != str(data)) else (data or typed)
        model = str(raw).replace("（免费）", "").strip()
        if not model:
            # v13.6：本地服务商没有预设模型时，优先用缓存里的第一个，
            # 绝不再静默写入空模型名（旧行为会让请求带空 model 字段失败）。
            merged = model_reg.merge_models(
                PROVIDERS.get(key, {}).get("models"),
                model_reg.cache_get(self.cfg, key))
            model = (merged or [""])[0]
        if not model:
            QMessageBox.warning(
                self, "请先选择或填写模型",
                "该服务商当前没有可用模型。\n\n"
                "请点「获取模型列表」从 Base URL 拉取真实模型，"
                "或直接在上方模型框输入模型 ID 后再保存。")
            return
        self.cfg.set_provider(key)
        self.cfg.set_api_key(self.key_edit.text().strip(), key)
        self.cfg.set_base_url(
            model_reg.normalize_base_url(self.url_edit.text()), key)
        self.cfg.set_model(model, key)
        params = {
            "temperature": round(float(self.temp_spin.value()), 2),
            "top_p": round(float(self.top_p_spin.value()), 2),
            "max_tokens": int(self.tokens_spin.value()),
            "reasoning_effort": self.effort_combo.currentData(),
            "context_window": int(self.ctx_spin.value()),
        }
        if self.scope_model.isChecked():
            # 仅当前模型：写入覆盖表
            self.cfg.set_override(params, key, model)
        else:
            # 全局默认：写全局值（并清除本模型的旧覆盖，避免混淆）
            self.cfg.data.update(params)
            self.cfg.data.get("model_overrides", {}).pop(
                self.cfg.override_key(key, model), None)
        self.cfg.data["system_prompt"] = self.prompt_edit.toPlainText().strip()
        self.cfg.data["auto_refresh_models"] = bool(self.auto_refresh_check.isChecked())
        self.cfg.data["agent_enabled"] = bool(self.agent_check.isChecked())
        self.cfg.data["library_auto"] = bool(self.library_auto_check.isChecked())
        self.cfg.data["agent_max_iterations"] = int(self.iter_spin.value())
        # 网页接入（v7：多站点，保存当前选中的站点）
        self._save_web_site_values()
        # MCP 工具服务器（v7.3 补齐）
        self.cfg.data["mcp_servers"] = [dict(e) for e in self._mcp_entries]
        url = self.market_url_edit.text().strip()
        if url:
            from core.agent.market import PluginMarket
            PluginMarket(self.cfg).set_market_url(url)
        self.cfg.appearance["theme"] = self.theme_combo.currentData()
        self.cfg.appearance["font_size"] = int(self.font_spin.value())
        self.cfg.appearance["ball_size"] = int(self.ball_spin.value())
        self.cfg.appearance["always_on_top"] = bool(self.top_check.isChecked())
        self.cfg.data["font_scale"] = self.scale_combo.currentText()
        from core import uilayout
        _new_density = uilayout.normalize(self.density_combo.currentText())
        if _new_density != uilayout.normalize(self.cfg.data.get("ui_density")):
            self.density_requested.emit(_new_density)
        self.cfg.appearance.update(self._current_bg_settings())
        self.cfg.data["ui_density"] = _new_density
        self.cfg.data["layout_version"] = uilayout.LAYOUT_VERSION
        # v13.5：自动缩放 / 缓存自动清理 / 开发者调试
        self.cfg.data["auto_ui_scale"] = bool(self.auto_scale_check.isChecked())
        self.cfg.data["auto_clean_tmp"] = bool(self.auto_clean_check.isChecked())
        self.cfg.data["debug_mode"] = bool(self.dev_mode_check.isChecked())
        self.cfg.data["log_level"] = self.log_level_combo.currentText()
        from core.hotkey import normalize_hotkey, DEFAULT_HOTKEY
        hotkey = normalize_hotkey(self.hotkey_edit.text())
        if hotkey is None and self.hotkey_edit.text().strip():
            QMessageBox.warning(self, "热键格式不正确",
                                "示例：ctrl+shift+a、alt+space、ctrl+f5\n"
                                "将保留原热键设置。")
        else:
            self.cfg.data["hotkey"] = hotkey or DEFAULT_HOTKEY
        self.accept()
