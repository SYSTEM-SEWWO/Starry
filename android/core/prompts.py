# -*- coding: utf-8 -*-
"""提示词库：内置常用提示词 + 用户自定义。

- 内置按分类组织（写作 / 编程 / 学习 / 办公 / 生活）
- 自定义提示词保存在 cfg.data["prompt_library"]
- 支持搜索与「插入输入框」
"""
import time

BUILTIN_PROMPTS = [
    # ---- 写作 ----
    {"id": "p_polish", "category": "写作", "title": "润色文案",
     "content": "请帮我润色下面的文字，保持原意，使表达更流畅、专业：\n\n"},
    {"id": "p_expand", "category": "写作", "title": "扩写段落",
     "content": "请围绕下面内容进行扩写，补充细节、案例与过渡，篇幅约为原来的两倍：\n\n"},
    {"id": "p_title", "category": "写作", "title": "起标题",
     "content": "请为下面的内容起 5 个吸引人的标题，分别侧重悬念、痛点、数字与利益点：\n\n"},
    {"id": "p_xhs", "category": "写作", "title": "小红书风格",
     "content": "请把下面的内容改写成小红书笔记风格：带 emoji、口语化、有场景感，"
                "结尾引导互动并附 5 个话题标签：\n\n"},
    # ---- 编程 ----
    {"id": "p_explain", "category": "编程", "title": "解释代码",
     "content": "请逐段解释下面代码的功能与逻辑，指出关键实现与潜在问题：\n\n"},
    {"id": "p_review", "category": "编程", "title": "代码审查",
     "content": "请审查下面的代码，按「Bug / 安全 / 性能 / 可读性」分类给出问题与修改建议：\n\n"},
    {"id": "p_unittest", "category": "编程", "title": "写单元测试",
     "content": "请为下面的函数编写单元测试，覆盖正常路径、边界与异常情况：\n\n"},
    {"id": "p_regex", "category": "编程", "title": "写正则",
     "content": "请写一个正则表达式匹配下面的需求，并解释每个部分的作用，给出测试用例：\n\n"},
    # ---- 学习 ----
    {"id": "p_eli5", "category": "学习", "title": "小白讲解",
     "content": "请用通俗易懂的方式（类比 + 例子）向完全不懂的人解释下面的概念：\n\n"},
    {"id": "p_quiz", "category": "学习", "title": "出题考我",
     "content": "请围绕下面的知识点出 5 道题（选择 + 简答），由易到难，先不要给答案：\n\n"},
    {"id": "p_outline", "category": "学习", "title": "学习大纲",
     "content": "请为下面的主题制定一份 4 周学习大纲，分周列出目标、重点与练习：\n\n"},
    # ---- 办公 ----
    {"id": "p_weekly", "category": "办公", "title": "周报生成",
     "content": "请把下面的工作记录整理成一份结构清晰的周报（本周进展 / 数据 / 下周计划）：\n\n"},
    {"id": "p_meeting", "category": "办公", "title": "会议纪要",
     "content": "请把下面的会议记录整理为结构化纪要：主题、结论、待办（负责人 + 期限）、风险：\n\n"},
    {"id": "p_email", "category": "办公", "title": "写邮件",
     "content": "请根据下面要点写一封得体的工作邮件，语气专业、条理清晰：\n\n"},
    {"id": "p_ppt", "category": "办公", "title": "PPT 大纲",
     "content": "请把下面的内容组织成一份 10 页 PPT 大纲，每页给出标题与 3 个要点：\n\n"},
    # ---- 生活 ----
    {"id": "p_recipe", "category": "生活", "title": "食谱推荐",
     "content": "请根据下面现有食材推荐 3 道菜，给出步骤与用时：\n\n"},
    {"id": "p_travel", "category": "生活", "title": "旅行规划",
     "content": "请为下面的旅行需求制定一份行程规划，含每日安排、交通与预算建议：\n\n"},
    {"id": "p_gift", "category": "生活", "title": "送礼建议",
     "content": "请根据下面场景推荐 5 个礼物选项，说明理由与预算区间：\n\n"},
]

CUSTOM_KEY = "prompt_library"


class PromptLibrary:
    def __init__(self, cfg):
        self.cfg = cfg

    # ------------------------------------------------------------------
    def all(self):
        """全部提示词（内置 + 自定义）"""
        out = [dict(p) for p in BUILTIN_PROMPTS]
        for p in (self.cfg.data.get(CUSTOM_KEY) or []):
            if isinstance(p, dict) and p.get("content"):
                out.append({**p, "custom": True})
        return out

    def categories(self):
        cats = []
        for p in self.all():
            c = p.get("category", "自定义")
            if c not in cats:
                cats.append(c)
        return cats

    def by_category(self, category):
        return [p for p in self.all()
                if p.get("category", "自定义") == category]

    def search(self, query):
        q = (query or "").strip().lower()
        if not q:
            return self.all()
        return [p for p in self.all()
                if q in (p.get("title", "") + p.get("content", "")
                         + p.get("category", "")).lower()]

    def get(self, prompt_id):
        for p in self.all():
            if p.get("id") == prompt_id:
                return p
        return None

    # ------------------------------------------------------------------
    def add(self, title, content, category="自定义"):
        title = (title or "").strip()
        content = (content or "").strip()
        if not title or not content:
            return None
        prompts = self.cfg.data.setdefault(CUSTOM_KEY, [])
        prompt = {"id": "up_%d" % int(time.time() * 1000),
                  "category": (category or "自定义").strip() or "自定义",
                  "title": title, "content": content}
        prompts.append(prompt)
        self.cfg.save()
        return prompt

    def remove(self, prompt_id):
        prompts = self.cfg.data.get(CUSTOM_KEY) or []
        self.cfg.data[CUSTOM_KEY] = [p for p in prompts
                                     if p.get("id") != prompt_id]
        self.cfg.save()
