# -*- coding: utf-8 -*-
"""设计语言：翠绿 / 天蓝 × 白 —— 「星语 · Starry」v5 视觉基调。

色系（浅色为默认主体基调，白色为底、主色为魂）：
    浅色 light      —— 白底翠绿，清新通透（默认）
    浅色 sky        —— 白底天蓝，晴空朗澈（v5 新增）
    深色 dark       —— 墨绿底 + 亮翠绿，夜间不刺眼
    深色 sky_dark   —— 深蓝底 + 亮天蓝，夜空静谧（v5 新增）

动效令牌（全软件统一，见 motion 约定）：
    RADIUS_S/M/L   圆角：8 / 12 / 16
    DUR_FAST/BASE/SLOW  时长：160 / 240 / 360 ms
    缓动一律 OutCubic（先快后慢，自然减速感）
"""

# ---------------------------------------------------------------------------
# 动效令牌（全软件唯一的动效语言来源）
# ---------------------------------------------------------------------------
RADIUS_S = 10         # 小控件（按钮、输入框、chip）
RADIUS_M = 14         # 卡片、附件、工具 chip
RADIUS_L = 20         # 主容器、对话框（v7.3：更柔的现代玻璃圆角）

DUR_FAST = 160        # 微交互（hover、开关、chip 展开）
DUR_BASE = 240        # 常规过渡（主题切换、高度动画）
DUR_SLOW = 360        # 场景级（开屏、气泡入场）

EASE = "OutCubic"     # 统一缓动曲线名（QEasingCurve.OutCubic）


def duration_ms(name):
    """按令牌名取毫秒数（'fast' / 'base' / 'slow'）"""
    return {"fast": DUR_FAST, "base": DUR_BASE,
            "slow": DUR_SLOW}.get(name, DUR_BASE)


# ---------------------------------------------------------------------------
# 色板
# ---------------------------------------------------------------------------
THEMES = {
    # 白底翠绿：主体基调（默认）
    "light": {
        "container_bg": "#f6faf8",     # 微绿白容器
        "title_bg": "#ffffff",         # 纯白标题栏
        "text": "#17322a",             # 墨绿黑正文
        "muted": "#6b8177",            # 灰绿辅助
        "accent": "#0eaf7e",           # 翠绿主色
        "accent_2": "#14b8a6",         # 青绿辅色
        "accent_soft": "#d9f2e8",      # 翠绿浅底（选中/hover）
        "border": "#dce8e2",           # 浅绿灰描边
        "input_bg": "#ffffff",
        "bubble_ai_bg": "#ffffff",
        "bubble_user_bg": "#0eaf7e",   # 翠绿用户气泡
        "bubble_user_text": "#ffffff",
        "code_bg": "#edf6f1",
        "code_text": "#0a7d59",
        "link": "#0a8f68",
        "thinking_text": "#5f7a6e",
        "hover": "#e8f4ee",
        "danger": "#e5484d",
        "on_dark": "#ffffff",          # 主色上的文字
    },
    # 墨绿底 + 亮翠绿：夜间模式
    "dark": {
        "container_bg": "#0f1714",     # 深墨绿
        "title_bg": "#16211d",
        "text": "#e6f2ec",
        "muted": "#8aa79a",
        "accent": "#2dd4a7",           # 亮翠绿
        "accent_2": "#5eead4",         # 亮青
        "accent_soft": "#17362c",
        "border": "#253a33",
        "input_bg": "#16211d",
        "bubble_ai_bg": "#182621",
        "bubble_user_bg": "#0e9f6e",
        "bubble_user_text": "#ffffff",
        "code_bg": "#0b120f",
        "code_text": "#7fe3c4",
        "link": "#5eead4",
        "thinking_text": "#7fa393",
        "hover": "#1d2f28",
        "danger": "#ff6b6b",
        "on_dark": "#ffffff",
    },
    # 白底天蓝：晴空主体基调（v5 新增）
    "sky": {
        "container_bg": "#f3f8fd",     # 微蓝白容器
        "title_bg": "#ffffff",         # 纯白标题栏
        "text": "#16293c",             # 墨蓝黑正文
        "muted": "#5d7690",            # 灰蓝辅助
        "accent": "#0b8bd8",           # 天蓝主色
        "accent_2": "#38bdf8",         # 亮天蓝辅色
        "accent_soft": "#d9ecfb",      # 天蓝浅底（选中/hover）
        "border": "#d6e5f3",           # 浅蓝灰描边
        "input_bg": "#ffffff",
        "bubble_ai_bg": "#ffffff",
        "bubble_user_bg": "#0b8bd8",   # 天蓝用户气泡
        "bubble_user_text": "#ffffff",
        "code_bg": "#eaf3fc",
        "code_text": "#0a6cae",
        "link": "#0b7cc4",
        "thinking_text": "#5b7590",
        "hover": "#e4f0fb",
        "danger": "#e5484d",
        "on_dark": "#ffffff",
    },
    # 深蓝底 + 亮天蓝：夜空模式（v5 新增）
    "sky_dark": {
        "container_bg": "#0b1520",     # 深蓝夜
        "title_bg": "#10202f",
        "text": "#e2eefb",
        "muted": "#7d97b3",
        "accent": "#4db8f5",           # 亮天蓝
        "accent_2": "#7dd3fc",         # 亮青蓝
        "accent_soft": "#14314a",
        "border": "#1d3a52",
        "input_bg": "#10202f",
        "bubble_ai_bg": "#122535",
        "bubble_user_bg": "#0e86c8",
        "bubble_user_text": "#ffffff",
        "code_bg": "#0a1926",
        "code_text": "#8fd0f7",
        "link": "#7dd3fc",
        "thinking_text": "#6f8bab",
        "hover": "#16324a",
        "danger": "#ff6b6b",
        "on_dark": "#ffffff",
    },
}

DEFAULT_THEME = "light"        # 白底翠绿为默认主体基调

# 设置面板展示名
THEME_LABELS = {
    "light": "翠绿 · 白（默认）",
    "sky": "天蓝 · 白",
    "dark": "墨绿 · 夜",
    "sky_dark": "深蓝 · 夜",
}


def get_theme(name):
    return THEMES.get(name, THEMES[DEFAULT_THEME])


# ---------------------------------------------------------------------------
# 品牌渐变色（开屏 / 悬浮球 / 新手引导 / 托盘图标 共用）
# ---------------------------------------------------------------------------
BRAND = {
    # 翠绿系
    "light": {
        "deep": "#0a7d59", "main": "#0eaf7e", "aux": "#14b8a6", "light": "#7fe3c4",
        "glow": (45, 212, 167), "particle": (94, 234, 212),
        "particle_bright": (167, 243, 208), "particle_mid": (110, 231, 183),
        "shadow": (8, 24, 19), "bg": (7, 18, 15),
        "title_base": (230, 248, 241), "title_sub": (154, 199, 184),
    },
    "dark": {
        "deep": "#0a7d59", "main": "#2dd4a7", "aux": "#5eead4", "light": "#7fe3c4",
        "glow": (45, 212, 167), "particle": (94, 234, 212),
        "particle_bright": (167, 243, 208), "particle_mid": (110, 231, 183),
        "shadow": (8, 24, 19), "bg": (7, 18, 15),
        "title_base": (230, 248, 241), "title_sub": (154, 199, 184),
    },
    # 天蓝系
    "sky": {
        "deep": "#0a6cae", "main": "#0b8bd8", "aux": "#38bdf8", "light": "#a5ddf8",
        "glow": (11, 139, 216), "particle": (125, 211, 252),
        "particle_bright": (191, 231, 254), "particle_mid": (96, 196, 247),
        "shadow": (10, 28, 46), "bg": (9, 20, 32),
        "title_base": (226, 240, 252), "title_sub": (140, 190, 226),
    },
    "sky_dark": {
        "deep": "#0a6cae", "main": "#4db8f5", "aux": "#7dd3fc", "light": "#a5ddf8",
        "glow": (77, 184, 245), "particle": (125, 211, 252),
        "particle_bright": (191, 231, 254), "particle_mid": (96, 196, 247),
        "shadow": (10, 28, 46), "bg": (9, 20, 32),
        "title_base": (226, 240, 252), "title_sub": (140, 190, 226),
    },
}


def brand(theme_name=None):
    """按主题取品牌渐变色（开屏/悬浮球/引导共用）"""
    return BRAND.get(theme_name or DEFAULT_THEME, BRAND[DEFAULT_THEME])


# ---------------------------------------------------------------------------
# 新手引导沉浸卡片（深色玻璃质感，与品牌色系对应）
# ---------------------------------------------------------------------------
ONBOARD = {
    "light": {
        "card": "rgba(11, 28, 23, 244)", "card_border": "rgba(125, 227, 195, 60)",
        "title": "#eafaf3", "body": "#a5c9ba", "dots": "#2dd4a7",
        "btn_bg": "rgba(125, 227, 195, 14)", "btn_border": "rgba(125, 227, 195, 34)",
        "btn_text": "#c9ecdf", "btn_hover": "rgba(125, 227, 195, 26)",
        "primary": "#0eaf7e", "primary_hover": "#14b8a6",
        "skip": "#7fa393", "skip_hover": "#c9ecdf",
    },
    "sky": {
        "card": "rgba(11, 26, 42, 244)", "card_border": "rgba(125, 211, 252, 60)",
        "title": "#e8f3fd", "body": "#a8c6e2", "dots": "#4db8f5",
        "btn_bg": "rgba(125, 211, 252, 14)", "btn_border": "rgba(125, 211, 252, 34)",
        "btn_text": "#c5e3fa", "btn_hover": "rgba(125, 211, 252, 26)",
        "primary": "#0b8bd8", "primary_hover": "#38bdf8",
        "skip": "#6f8bab", "skip_hover": "#c5e3fa",
    },
}


def onboard(theme_name=None):
    """按主题取新手引导卡片配色（dark 跟随 light，sky_dark 跟随 sky）"""
    name = theme_name or DEFAULT_THEME
    if name.startswith("sky"):
        return ONBOARD["sky"]
    return ONBOARD["light"]


GLOBAL_FONT = '"Microsoft YaHei","PingFang SC","Noto Sans CJK SC","Segoe UI",sans-serif'

# 全局界面缩放档（与安卓端保持一致）：标准 / 大 / 超大。
# 桌面端此前从未读取该字段，导致配置里的 font_scale 是死字段、
# 「整个窗口的缩放」失灵；v13.2 起在桌面端落地。
FONT_SCALES = {"标准": 1.0, "大": 1.15, "超大": 1.3}
FONT_SCALE_LABELS = ["标准", "大", "超大"]


def effective_font_size(base, scale_label="标准"):
    """按界面缩放档计算最终字号（标准=1.0 / 大=1.15 / 超大=1.3）。

    base 为「正文字号」设置值（11–20），两者相乘得到整体界面字号，
    从而让整个窗口的文字与间距随缩放档一同放大/缩小。
    """
    base = int(base)
    factor = FONT_SCALES.get(scale_label, 1.0)
    return max(8, int(round(base * factor)))


def build_qss(theme, font_size=14):
    """全局 Qt Style Sheet（翠绿+白设计语言）"""
    fs = int(font_size)
    return f"""
    * {{
        font-family: {GLOBAL_FONT};
        font-size: {fs}px;
        color: {theme['text']};
    }}
    QToolTip {{
        color: {theme['text']};
        background-color: {theme['title_bg']};
        border: 1px solid {theme['border']};
        padding: 4px 6px;
    }}
    QMenu {{
        background-color: {theme['title_bg']};
        border: 1px solid {theme['border']};
        padding: 6px;
    }}
    QMenu::item {{ padding: 6px 24px; border-radius: {RADIUS_S}px; }}
    QMenu::item:selected {{ background-color: {theme['accent']}; color: {theme['on_dark']}; }}
    QWidget#Container {{
        background-color: {theme['container_bg']};
        border: 1px solid {theme['border']};
        border-radius: {RADIUS_L}px;
    }}
    QFrame#TitleBar {{
        background-color: {theme['title_bg']};
        border-top-left-radius: {RADIUS_L}px;
        border-top-right-radius: {RADIUS_L}px;
        border-bottom: 1px solid {theme['border']};
    }}
    QLabel#TitleLabel {{ font-size: {fs + 1}px; font-weight: bold; }}
    QPushButton#LogoLabel {{ font-size: {fs + 4}px; color: {theme['accent']};
        background: transparent; border: none; }}
    QPushButton#LogoLabel:hover {{ color: {theme['accent_2']}; }}
    QLabel#MutedLabel {{ color: {theme['muted']}; }}
    QComboBox {{
        background-color: {theme['input_bg']};
        border: 1px solid {theme['border']};
        border-radius: {RADIUS_S}px;
        padding: 3px 8px;
        min-width: 80px;
    }}
    QComboBox:hover {{ border: 1px solid {theme['accent']}; }}
    QComboBox::drop-down {{ border: none; width: 16px; }}
    QComboBox QAbstractItemView {{
        background-color: {theme['title_bg']};
        border: 1px solid {theme['border']};
        selection-background-color: {theme['accent']};
        selection-color: {theme['on_dark']};
        outline: none;
    }}
    QPushButton {{
        background-color: {theme['input_bg']};
        border: 1px solid {theme['border']};
        border-radius: {RADIUS_S}px;
        padding: 5px 12px;
    }}
    QPushButton:hover {{ background-color: {theme['hover']}; }}
    QPushButton:pressed {{ background-color: {theme['border']}; }}
    QPushButton:disabled {{ color: {theme['muted']}; }}
    QPushButton#AccentButton {{
        background-color: {theme['accent']};
        color: {theme['on_dark']};
        border: none;
        padding: 6px 18px;
        border-radius: {RADIUS_S}px;
    }}
    QPushButton#AccentButton:hover {{ background-color: {theme['accent_2']}; }}
    QPushButton#AccentButton:disabled {{ background-color: {theme['border']}; color: {theme['muted']}; }}
    QPushButton#FlatButton {{
        background: transparent;
        border: none;
        color: {theme['muted']};
        padding: 4px 8px;
        border-radius: {RADIUS_S}px;
    }}
    QPushButton#FlatButton:hover {{ color: {theme['accent']}; background-color: {theme['hover']}; }}
    QFrame#AttachChip {{
        background-color: {theme['bubble_ai_bg']};
        border: 1px solid {theme['border']};
        border-radius: {RADIUS_M}px;
    }}
    QLabel#AttachName {{ color: {theme['text']}; }}
    QLabel#AttachSize {{ color: {theme['muted']}; font-size: {fs - 2}px; }}
    QPushButton#ThinkingHeader {{
        background: transparent;
        border: none;
        color: {theme['muted']};
        text-align: left;
        padding: 3px 8px;
        border-radius: {RADIUS_S}px;
    }}
    QPushButton#ThinkingHeader:hover {{ color: {theme['accent']}; }}
    QLineEdit, QSpinBox, QDoubleSpinBox, QPlainTextEdit, QTextEdit, QComboBox:editable {{
        background-color: {theme['input_bg']};
        border: 1px solid {theme['border']};
        border-radius: {RADIUS_S}px;
        padding: 4px 8px;
        selection-background-color: {theme['accent']};
    }}
    QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus,
    QPlainTextEdit:focus, QTextEdit:focus {{ border: 1px solid {theme['accent']}; }}
    QCheckBox::indicator {{
        width: 16px; height: 16px;
        border: 1px solid {theme['border']};
        border-radius: 4px;
        background: {theme['input_bg']};
    }}
    QCheckBox::indicator:checked {{ background: {theme['accent']}; border: 1px solid {theme['accent']}; }}
    QScrollArea {{ border: none; background: transparent; }}
    QScrollArea > QWidget > QWidget {{ background: transparent; }}
    QScrollBar:vertical {{ background: transparent; width: 8px; margin: 0px; }}
    QScrollBar::handle:vertical {{
        background: {theme['border']};
        border-radius: 4px;
        min-height: 32px;
    }}
    QScrollBar::handle:vertical:hover {{ background: {theme['accent']}; }}
    QScrollBar::add-line, QScrollBar::sub-line {{ height: 0px; }}
    QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
    QTextBrowser {{ background: transparent; border: none; selection-background-color: {theme['accent']}; }}
    """
