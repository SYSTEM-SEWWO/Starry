# -*- coding: utf-8 -*-
"""界面栏目布局（v13.6.5）：密度档位 + 旧配置一次性迁移。

纯逻辑、零 Qt 依赖（三端同源）。UI 层读取 metrics() 应用到控件。

解决的历史问题：用户反馈「布局没有任何改动」——旧版把窗口尺寸写进
config.json，启动时 ``_restore_geometry()`` 会用旧值（430×640）覆盖代码里
的新默认值，导致改了源码用户也看不到变化。这里用 ``migrate()`` 在首次
启动时一次性升级旧窗口尺寸并打版本标记，之后用户手动调整的尺寸不再被覆盖。
"""
LAYOUT_VERSION = 2
DEFAULT_DENSITY = "宽松"
DENSITY_LABELS = ("紧凑", "标准", "宽松", "超宽松")

# 每个档位给出全部栏目尺寸（px）。窗口宽度是重点：标题栏 + 智能体行都是
# 横向排列，宽度不足时图标会挤成一团甚至压到文字上。
_PRESETS = {
    "紧凑": dict(
        window=[480, 680], min_window=[400, 460], outer=[12, 12, 12, 14],
        title_h=48, title_m=[12, 0, 8, 0], title_gap=6, icon=28, logo=26,
        model_w=120, msg_m=[12, 10, 12, 10], msg_gap=10,
        input_m=[12, 6, 12, 10], input_gap=6, agent_gap=4, agent_h=28,
        skill_w=100, input_min=74, input_max=150, input_pad=18,
        btn_gap=4, small_icon=28, prompt_icon=30, deep_h=30, send_h=32,
        status_h=24, status_m=[14, 0, 14, 0], grip=16),
    "标准": dict(
        window=[540, 760], min_window=[430, 500], outer=[14, 14, 14, 16],
        title_h=54, title_m=[14, 0, 9, 0], title_gap=8, icon=32, logo=28,
        model_w=140, msg_m=[14, 12, 14, 12], msg_gap=12,
        input_m=[14, 8, 14, 12], input_gap=8, agent_gap=6, agent_h=32,
        skill_w=112, input_min=88, input_max=170, input_pad=22,
        btn_gap=6, small_icon=30, prompt_icon=32, deep_h=34, send_h=36,
        status_h=28, status_m=[16, 0, 16, 0], grip=16),
    "宽松": dict(
        window=[620, 860], min_window=[470, 560], outer=[18, 18, 18, 20],
        title_h=64, title_m=[18, 0, 12, 0], title_gap=12, icon=38, logo=34,
        model_w=170, msg_m=[18, 16, 18, 16], msg_gap=18,
        input_m=[18, 14, 18, 16], input_gap=14, agent_gap=10, agent_h=40,
        skill_w=132, input_min=112, input_max=210, input_pad=26,
        btn_gap=10, small_icon=36, prompt_icon=38, deep_h=42, send_h=46,
        status_h=36, status_m=[20, 0, 20, 0], grip=18),
    "超宽松": dict(
        window=[720, 960], min_window=[520, 620], outer=[22, 22, 22, 24],
        title_h=72, title_m=[22, 0, 14, 0], title_gap=14, icon=44, logo=38,
        model_w=190, msg_m=[22, 20, 22, 20], msg_gap=22,
        input_m=[22, 18, 22, 20], input_gap=18, agent_gap=12, agent_h=46,
        skill_w=150, input_min=132, input_max=240, input_pad=30,
        btn_gap=12, small_icon=42, prompt_icon=44, deep_h=48, send_h=52,
        status_h=40, status_m=[24, 0, 24, 0], grip=20),
}

_ALIASES = {
    "compact": "紧凑", "small": "紧凑", "standard": "标准", "normal": "标准",
    "medium": "标准", "comfortable": "宽松", "loose": "宽松", "roomy": "宽松",
    "large": "宽松", "xl": "超宽松", "extra": "超宽松", "huge": "超宽松",
}


def normalize(name):
    """容错解析密度名，未知值回落到默认档。"""
    key = str(name or "").strip()
    if key in _PRESETS:
        return key
    return _ALIASES.get(key.lower(), DEFAULT_DENSITY)


def metrics(density=None):
    """返回该档位的全部尺寸（副本，调用方可安全修改）。"""
    return dict(_PRESETS.get(normalize(density), _PRESETS[DEFAULT_DENSITY]))


def migrate(cfg):
    """一次性升级旧配置。返回 (是否变更, 说明)。

    只在 ``layout_version`` 缺失或过旧时执行；升级后打标记，之后用户手动
    拖动的窗口尺寸不会再被覆盖。未到位的旧窗口尺寸会被抬到当前档位推荐值。
    """
    try:
        cur = int(cfg.data.get("layout_version") or 0)
    except (TypeError, ValueError):
        cur = 0
    if cur >= LAYOUT_VERSION:
        return False, "布局配置已是最新（无需迁移）"
    density = normalize(cfg.data.get("ui_density"))
    m = metrics(density)
    cfg.data["ui_density"] = density
    cfg.data["layout_version"] = LAYOUT_VERSION
    old = cfg.appearance.get("window_size")
    target = m["window"]
    need = (not old or int(old[0]) < int(target[0] * 0.9)
            or int(old[1]) < int(target[1] * 0.9))
    if need:
        cfg.appearance["window_size"] = list(target)
        cfg.appearance["window_position"] = None
    try:
        cfg.save()
    except Exception:                       # noqa: BLE001 - 只读环境不应阻断启动
        pass
    return True, ("窗口 %s → %s，密度「%s」" % (old, target, density)
                  if need else "已写入密度「%s」（保留你的窗口尺寸）" % density)


def reset(cfg, density=None):
    """一键恢复推荐布局：重置密度、窗口尺寸与位置。"""
    d = normalize(density or cfg.data.get("ui_density"))
    m = metrics(d)
    cfg.data["ui_density"] = d
    cfg.data["layout_version"] = LAYOUT_VERSION
    cfg.appearance["window_size"] = list(m["window"])
    cfg.appearance["window_position"] = None
    try:
        cfg.save()
    except Exception:                       # noqa: BLE001
        pass
    return m


def format_layout(cfg):
    """CLI / 调试面板用的纯文本布局摘要。"""
    d = normalize(cfg.data.get("ui_density"))
    m = metrics(d)
    stored = cfg.appearance.get("window_size")
    lines = [
        "界面栏目布局（v13.6.5 · 密度档位即时生效）",
        "  当前档位      ：%s（可选 %s）" % (d, " / ".join(DENSITY_LABELS)),
        "  推荐窗口      ：%d × %d" % tuple(m["window"]),
        "  配置中窗口    ：%s" % (stored if stored else "未保存（跟随推荐值）"),
        "  最小窗口      ：%d × %d" % tuple(m["min_window"]),
        "  顶部标题栏    ：高 %d，图标 %d，间距 %d，模型框 %d"
        % (m["title_h"], m["icon"], m["title_gap"], m["model_w"]),
        "  消息区        ：间距 %d，边距 %s" % (m["msg_gap"], m["msg_m"]),
        "  底部输入区    ：间距 %d，输入框 %d（上限 %d），智能体按钮 %d"
        % (m["input_gap"], m["input_min"], m["input_max"], m["agent_h"]),
        "  底部按钮行    ：间距 %d，发送 %d，深度思考 %d，状态栏 %d"
        % (m["btn_gap"], m["send_h"], m["deep_h"], m["status_h"]),
        "  迁移标记      ：%s" % cfg.data.get("layout_version", "未设置"),
        "  提示：设置 → 外观 → 栏目密度 可即时切换，无需重启；"
        "也可用 starry --ui-density 宽松 修改。",
    ]
    return "\n".join(lines)
