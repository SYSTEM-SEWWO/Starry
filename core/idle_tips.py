# -*- coding: utf-8 -*-
"""待机提示语（Idle Tips）：让悬浮球在闲暇时「说句话」。

灵感来源：RaymonDev/clippy 的 Random Tips、YourFriendlyAI 的情感反馈。
纯数据 + 纯函数，零依赖、可单测。

设计要点：
    - 按**时段**分桶（清晨/白天/傍晚/深夜），问候不尴尬；
    - 混三类内容：**问候**（时段感知）、**功能提示**（教会用户用）、
      **趣句**（拟人化，像 Cherry Studio 强调的「人多触点」）；
    - pick() 避免短期重复（记住最近 N 条）。
"""


def time_slot(hour):
    """0-23 → 时段 key"""
    if 5 <= hour < 9:
        return "morning"
    if 9 <= hour < 12:
        return "forenoon"
    if 12 <= hour < 14:
        return "noon"
    if 14 <= hour < 18:
        return "afternoon"
    if 18 <= hour < 23:
        return "evening"
    return "night"


GREETINGS = {
    "morning": ["早呀，今天想先搞定哪件事？", "早上好，脑子最清醒的时候到了"],
    "forenoon": ["上午好，要不要先把难题啃了？", "这个点适合做需要专注的事"],
    "noon": ["午饭时间到啦，先歇会儿吧", "中午好，别忘了喝水"],
    "afternoon": ["下午好，来杯水再继续？", "困了吗？聊聊也有提神效果"],
    "evening": ["晚上好，今天收获怎么样", "收个尾吧，明天会更轻松"],
    "night": ["夜深了，早点休息哦", "熬夜伤神，有事明天再说？"],
}

FEATURE_TIPS = [
    "按住 Ctrl+K 能叫出命令面板，键盘党最爱",
    "选中文字后按 Ctrl+Shift+Q，我可以直接解释它",
    "Ctrl+Shift+S 可以框选屏幕截图提问",
    "回复气泡上的 ①②③ 可以回看不同版本答案",
    "拖文件到窗口就能让它帮我读这份文档",
    "网关仪表盘能看到每家服务商的速度与用量",
    "专家会诊能让多位专家同时帮你看一个问题",
    "资料库会自动把相关笔记塞进上下文",
    "长按悬浮球可以拖到屏幕任何角落",
    "网页接入可以免 Key 直接用各家网页版",
    "嫌我溜达太吵？命令面板里能关掉漫游",
]

QUIPS = [
    "我在，随时待命 ✦",
    "发呆也是一种充电",
    "想到什么就问我，不用客气",
    "这个问题可能刚好是我的强项",
    "要不要试试让我写首诗？",
    "慢慢来，我不着急",
    "你说一句，我回一屏",
    "有问题别憋着，我不收费",
]


def all_tips(include_greetings=True):
    out = list(FEATURE_TIPS) + list(QUIPS)
    if include_greetings:
        for lst in GREETINGS.values():
            out.extend(lst)
    return out


def pick_tip(hour, history=(), max_history=6):
    """挑一句提示：时段优先问候，其余为功能/趣句；尽量避免近期重复。

    纯函数：同一 (hour, history) 结果稳定（用 hash 做确定性选择）。
    """
    slot = time_slot(hour)
    import random as _random

    recent = [h for h in (history or ())][-max_history:]
    pool = list(FEATURE_TIPS) + list(QUIPS)
    # 问候：每个时段有 2 句，加入 pool 并提高权重
    greet = GREETINGS.get(slot, [])
    pool = pool + greet + greet
    fresh = [t for t in pool if t not in recent]
    if not fresh:                       # 全部重复过则放宽
        fresh = pool
    rng = _random.Random("%s|%d|%d" % (slot, len(recent), len(pool)))
    return rng.choice(sorted(set(fresh)))
