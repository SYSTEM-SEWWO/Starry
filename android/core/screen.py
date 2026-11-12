# -*- coding: utf-8 -*-
"""「看屏幕」问答（Screen Q&A）—— 纯逻辑层（无 Qt 依赖，便于单测）。

补齐的由来：Moonwalker / Jini / Cluely / Highlight AI 这类 2026 年新秀的共同
高频交互是「点一下 → 抓当前屏幕 → 就屏幕内容直接问」，省掉「先框选、再想问题」
两步。星语原本只有框选截图（✂），缺一键全屏直问。

本模块只放纯函数（预设问题 / 文件名 / 校验），抓屏与界面编排放在
app/screenshot_controller.py，保证逻辑可单测、UI 可替换。
"""

# (展示名, 预设问题)
SCREEN_PRESETS = [
    ("👁 解释屏幕", "请阅读并解释当前屏幕上的内容，说明我正在做什么。"),
    ("🌐 翻译屏幕", "请识别屏幕上的文字并翻译成中文，尽量保留原有排版结构。"),
    ("🐞 诊断报错", "屏幕上出现了错误提示，请说明错误原因并给出具体修复步骤。"),
    ("📄 总结屏幕", "请总结当前屏幕的核心信息，用要点列出。"),
]


def preset_labels():
    """预设问题的展示名列表"""
    return [p[0] for p in SCREEN_PRESETS]


def preset_question(label):
    """按展示名取预设问题；未命中返回 None"""
    for name, q in SCREEN_PRESETS:
        if name == label:
            return q
    return None


def default_question():
    """默认问题（解释屏幕）"""
    return SCREEN_PRESETS[0][1]


def capture_name(stamp):
    """生成截图附件名（stamp 形如 '143025'）"""
    stamp = str(stamp or "").strip() or "000000"
    return "屏幕_%s.png" % stamp


def build_question(label=None, extra=""):
    """生成最终提问词：预设问题 + 可选的补充要求"""
    base = preset_question(label) if label else None
    base = base or default_question()
    extra = (extra or "").strip()
    if not extra:
        return base
    return "%s\n补充要求：%s" % (base, extra)
