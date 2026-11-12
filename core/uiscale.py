# -*- coding: utf-8 -*-
"""界面自动缩放（v13.5）。

根据屏幕 DPI 与可用分辨率，自动推荐「界面缩放档 + 窗口尺寸」，
解决高 DPI 屏上字太小、小屏上窗口过大需要手动拖的问题。

纯逻辑、零 Qt 依赖（三端同源）：屏幕信息由 UI 层采集后传给 ``recommend()``。
缩放档与 ``ui.theme.FONT_SCALES`` 保持一致：标准 1.0 / 大 1.15 / 超大 1.3。
"""
# 与 ui/theme.py::FONT_SCALES 保持一致（此处不 import ui，避免安卓端依赖 Qt）
FONT_SCALES = {"标准": 1.0, "大": 1.15, "超大": 1.3}
SCALE_LABELS = ("标准", "大", "超大")


def _clamp(v, lo, hi):
    return max(lo, min(hi, v))


def recommend(screen_w, screen_h, dpi=96, base_font=14):
    """返回自动缩放建议。

    判定规则（明确、可复现）：
      - DPI >= 144 或 屏幕高 >= 1600 → 超大（1.3）
      - DPI >= 120 或 屏幕高 >= 1200 → 大（1.15）
      - 其余 → 标准（1.0）
    窗口尺寸按可用区域的约 30% 宽 / 62% 高计算，并限制在 380–780 /
    520–980 之间；小屏时进一步收紧，保证标题栏可见。

    返回 {scale_label, factor, font_size, window_size, dpi, screen,
          reason}，``font_size`` 为最终正文字号（供 build_qss 使用）。
    """
    w = int(screen_w or 0)
    h = int(screen_h or 0)
    d = float(dpi or 96)
    if w <= 0 or h <= 0:
        w, h = 1920, 1080
    if d >= 144 or h >= 1600:
        label = "超大"
        reason = "高 DPI / 大屏（DPI %.0f，可用高度 %d）" % (d, h)
    elif d >= 120 or h >= 1200:
        label = "大"
        reason = "偏高 DPI / 中大屏（DPI %.0f，可用高度 %d）" % (d, h)
    else:
        label = "标准"
        reason = "常规显示环境（DPI %.0f，可用高度 %d）" % (d, h)
    factor = FONT_SCALES[label]
    base = int(base_font or 14)
    font_size = max(8, int(round(base * factor)))

    win_w = _clamp(int(w * 0.30), 380, 780)
    win_h = _clamp(int(h * 0.62), 520, 980)
    if h <= 800:                        # 小屏：窗口再收一点，避免遮满桌面
        win_w = min(win_w, 520)
        win_h = min(win_h, 620)
    return {
        "scale_label": label,
        "factor": factor,
        "font_size": font_size,
        "base_font": base,
        "window_size": [win_w, win_h],
        "dpi": d,
        "screen": [w, h],
        "reason": reason,
    }


def apply_to_config(cfg, rec, save=False):
    """把建议写回配置（返回改动前后对照，便于日志与 UI 提示）。

    只写 ``cfg.data["font_scale"]`` 与 ``cfg.appearance["window_size"]``，
    不覆盖用户手工设置的主题 / 正文字号。
    """
    old_scale = cfg.data.get("font_scale", "标准")
    old_size = list(cfg.appearance.get("window_size") or [])
    new_scale = rec["scale_label"]
    new_size = list(rec["window_size"])
    cfg.data["font_scale"] = new_scale
    cfg.appearance["window_size"] = new_size
    if save:
        cfg.save()
    return {"font_scale": [old_scale, new_scale],
            "window_size": [old_size, new_size],
            "changed": old_scale != new_scale or old_size != new_size}


def format_recommendation(rec):
    """纯文本摘要（设置页 / CLI）。"""
    if not rec:
        return "无法获取屏幕信息。"
    return ("自动缩放建议：%s（×%.2f）\n"
            "  · 依据：%s\n"
            "  · 正文字号：%s px（基准 %s px）\n"
            "  · 窗口尺寸：%s × %s\n"
            "  · 屏幕可用区域：%s × %s @ %.0f DPI" % (
                rec["scale_label"], rec["factor"], rec["reason"],
                rec["font_size"], rec["base_font"],
                rec["window_size"][0], rec["window_size"][1],
                rec["screen"][0], rec["screen"][1], rec["dpi"]))
