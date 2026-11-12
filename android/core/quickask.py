# -*- coding: utf-8 -*-
"""划词提问（Selection Assistant）：把「选中的文字 + 一个动作」合成提示词。

灵感来源：Cherry Studio 划词助手 / Bob / RaymonDev clippy。
本模块只做纯逻辑（动作定义与提示词合成），不碰 UI，可被自测直接覆盖。
"""


class QuickAction(object):
    """一个划词动作"""

    def __init__(self, key, label, hint, template, target_lang=False):
        self.key = key
        self.label = label          # 按钮文案（含 emoji）
        self.hint = hint            # 一句话说明
        self.template = template    # 提示词模板，含 {text} / {extra}
        self.target_lang = target_lang


ACTIONS = [
    QuickAction("explain", "解释", "讲清楚它是什么、为什么这样写",
                "请解释下面这段内容（先一句话概括，再讲关键点，最后给一句"
                "「什么时候会用到」）：\n\n{text}"),
    QuickAction("translate", "翻译", "中英互译，保留格式",
                "请把下面内容翻译成{target}（保留原有格式与术语，"
                "只输出译文，不要加解释）：\n\n{text}"),
    QuickAction("summary", "总结", "提炼要点，结构化输出",
                "请把下面内容总结为 3-5 条要点"
                "（每条一行，保留关键名词与数字）：\n\n{text}"),
    QuickAction("polish", "润色", "更通顺专业，不改原意",
                "请润色下面这段文字（更通顺、得体、专业，但不改变原意，"
                "直接给出修改后的版本）：\n\n{text}"),
    QuickAction("review", "挑错", "找问题并给出改法",
                "请审阅下面内容，指出存在的问题、权衡优劣，"
                "并给出具体的改进建议：\n\n{text}"),
    QuickAction("action", "行动项", "从材料里提炼待办",
                "请从下面内容中提炼可执行的行动项"
                "（谁/做什么/何时，做成清单）：\n\n{text}"),
]

MAX_TEXT = 6000


def action_keys():
    return [a.key for a in ACTIONS]


def get_action(key):
    for a in ACTIONS:
        if a.key == key:
            return a
    return None


def clean_snippet(text, limit=MAX_TEXT):
    """清洗选中文本：去首尾空白、压缩连续空行、限长（超长截断并留标记）"""
    t = (text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not t:
        return ""
    lines = []
    blank = 0
    for ln in t.split("\n"):
        s = ln.rstrip()
        if not s.strip():
            blank += 1
            if blank > 1:
                continue
        else:
            blank = 0
        lines.append(s)
    t = "\n".join(lines).strip()
    if len(t) > limit:
        t = t[:limit] + "\n…（原文较长，已截断）"
    return t


def build_prompt(action_key, text, target_lang="", extra=""):
    """合成最终提示词（纯函数）。动作不存在则返回 None"""
    act = get_action(action_key)
    text = clean_snippet(text)
    if not act or not text:
        return None
    lang = (target_lang or "中文").strip() or "中文"
    prompt = act.template.format(text=text, target=lang)
    if extra:
        prompt += "\n\n补充要求：%s" % extra.strip()
    return prompt


def snippet_preview(text, n=140):
    """输入区上方的预览文本（单行摘要）"""
    t = (text or "").strip().replace("\n", " ")
    return (t[:n] + "…") if len(t) > n else t


def is_code_like(text):
    """粗判是否为代码片段（用于把「审阅」类动作排在前面）"""
    t = (text or "").strip()
    if not t:
        return False
    marks = ("def ", "class ", "import ", "#include", "function",
             "=>", "{}", "();", "SELECT ", "<html", "{", "}")
    hit = sum(1 for m in marks if m in t)
    return hit >= 2
