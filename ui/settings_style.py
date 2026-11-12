# -*- coding: utf-8 -*-
"""设置页专用视觉样式（v13.5）。

以「附加 QSS」方式叠加在 ``ui.theme.build_qss`` 之上，不改动既有控件结构，
因此向后兼容、可随时关闭。设计目标：分区更清晰、焦点更明确、层次更轻。
"""


def settings_qss(theme, font_size=14):
    t = theme or {}
    accent = t.get("accent", "#0b8bd8")
    text = t.get("text", "#16293c")
    muted = t.get("muted", "#8b93a1")
    border = t.get("border", "#e3e8ef")
    card = t.get("container_bg", "#ffffff")
    soft = t.get("code_bg", "#f5f7fa")
    on_dark = t.get("on_dark", "#ffffff")
    fs = int(font_size or 14)
    small = max(10, fs - 2)
    return """
    /* 页签：选中态用主题色下划线，去掉默认笨重边框 */
    QTabWidget::pane {{
        border: 1px solid {border};
        border-radius: 10px;
        background: {card};
        top: -1px;
    }}
    QTabBar::tab {{
        background: transparent;
        color: {muted};
        padding: 7px 12px;
        margin-right: 2px;
        border: none;
        border-bottom: 2px solid transparent;
        font-size: {fs}px;
    }}
    QTabBar::tab:selected {{
        color: {accent};
        border-bottom: 2px solid {accent};
        font-weight: 600;
    }}
    QTabBar::tab:hover:!selected {{ color: {text}; }}

    /* 顶部状态横幅 */
    QFrame#SettingsBanner {{
        background: {soft};
        border: 1px solid {border};
        border-radius: 10px;
        padding: 9px 12px;
    }}
    QLabel#BannerTitle {{
        color: {text};
        font-size: {fs}px;
        font-weight: 600;
    }}
    QLabel#BannerMeta {{ color: {muted}; font-size: {small}px; }}

    /* 分区标题与说明 */
    QLabel#SectionTitle {{
        color: {accent};
        font-size: {small}px;
        font-weight: 600;
        padding: 6px 0 2px 0;
        letter-spacing: 0.5px;
    }}
    QLabel#HintLabel {{
        color: {muted};
        font-size: {small}px;
        padding: 2px 0 6px 0;
    }}
    QFrame#SectionLine {{
        color: {border};
        background: {border};
        max-height: 1px;
        border: none;
    }}

    /* 输入控件：焦点态更明确 */
    QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {{
        border: 1px solid {border};
        border-radius: 7px;
        padding: 5px 8px;
        background: {card};
        selection-background-color: {accent};
        selection-color: {on_dark};
    }}
    QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus {{
        border: 1px solid {accent};
    }}
    QLineEdit:disabled, QComboBox:disabled {{ color: {muted}; }}
    QCheckBox {{ spacing: 7px; padding: 2px 0; }}
    QCheckBox::indicator {{ width: {fs}px; height: {fs}px; }}

    /* 按钮：主操作保持主题色，次操作轻量化 */
    QPushButton {{
        border: 1px solid {border};
        border-radius: 8px;
        padding: 6px 12px;
        background: {card};
        color: {text};
    }}
    QPushButton:hover {{ border-color: {accent}; color: {accent}; }}
    QPushButton:pressed {{ background: {soft}; }}
    QPushButton:disabled {{ color: {muted}; }}
    QPushButton#PrimaryAction {{
        background: {accent};
        color: {on_dark};
        border-color: {accent};
        font-weight: 600;
    }}
    QPushButton#PrimaryAction:hover {{ color: {on_dark}; opacity: 0.9; }}
    QGroupBox {{
        border: 1px solid {border};
        border-radius: 10px;
        margin-top: 10px;
        padding: 10px;
    }}
    QGroupBox::title {{
        subcontrol-origin: margin;
        left: 10px;
        padding: 0 5px;
        color: {accent};
        font-weight: 600;
    }}
    """.format(accent=accent, text=text, muted=muted, border=border,
               card=card, soft=soft, on_dark=on_dark, fs=fs, small=small)


def section_label(text, hint=None):
    """生成一对「分区标题 + 说明」控件，供设置页各页复用。"""
    from PyQt5.QtWidgets import QLabel, QFrame
    out = []
    title = QLabel(text)
    title.setObjectName("SectionTitle")
    out.append(title)
    line = QFrame()
    line.setObjectName("SectionLine")
    line.setFrameShape(QFrame.HLine)
    out.append(line)
    if hint:
        lab = QLabel(hint)
        lab.setObjectName("HintLabel")
        lab.setWordWrap(True)
        out.append(lab)
    return out
