# -*- coding: utf-8 -*-
"""技能（Skill）管理：一类「可切换的系统提示词专家」。

- 内置技能：通用助手 / 翻译 / 代码审查 / 总结 / 写作 / 数据分析
- 自定义技能：保存在配置 cfg.data["skills"]，可增删
- 应用时：技能提示词追加在基础系统提示之后
"""
import time

BUILTIN_SKILLS = [
    {"id": "general", "name": "通用助手", "icon": "💬",
     "description": "友善干练的默认助手",
     "prompt": ""},
    {"id": "translator", "name": "翻译专家", "icon": "🌐",
     "description": "中英互译，保留格式与专业术语",
     "prompt": ("你是一名专业翻译。用户给出待翻译内容时：\n"
                "1. 自动识别源语言，翻译为目标语言（中↔英，或按用户指定）\n"
                "2. 保留原文的格式、 Markdown 结构与代码块\n"
                "3. 专业术语给出准确译法，首次出现时可附原文\n"
                "4. 如内容有歧义，先给出最合理的翻译，再简要说明")},
    {"id": "code_reviewer", "name": "代码审查", "icon": "🔍",
     "description": "审查缺陷 / 安全 / 性能并给出修改建议",
     "prompt": ("你是一名资深代码审查专家。针对用户提供的代码：\n"
                "1. 指出潜在 Bug、边界条件与异常处理问题\n"
                "2. 检查安全风险（注入、越权、敏感信息泄露等）\n"
                "3. 评估性能与可读性，给出重构建议\n"
                "4. 用「问题 / 建议 / 修改后代码」的结构输出，按严重程度排序")},
    {"id": "summarizer", "name": "文档总结", "icon": "📚",
     "description": "长文结构化摘要与要点提取",
     "prompt": ("你是一名文档总结专家。针对用户提供的内容：\n"
                "1. 先用一句话概括核心结论\n"
                "2. 再按要点分条列出关键信息（保留数据与专有名词）\n"
                "3. 最后给出「行动建议」或「值得关注的风险」\n"
                "4. 总结长度不超过原文的 20%，除非用户另作要求")},
    {"id": "writer", "name": "写作润色", "icon": "✍️",
     "description": "润色 / 改写 / 扩写，适配不同场景",
     "prompt": ("你是一名文字润色专家。针对用户提供的文本：\n"
                "1. 修正语法、标点与用词，保持原意\n"
                "2. 按用户要求的场景（正式 / 亲切 / 营销）调整语气\n"
                "3. 直接输出润色后的版本，再用列表简要说明主要改动")},
    {"id": "analyst", "name": "数据分析", "icon": "📊",
     "description": "解读数据、发现规律、给出结论",
     "prompt": ("你是一名数据分析师。针对用户提供的数据：\n"
                "1. 先描述数据规模与字段含义\n"
                "2. 指出关键趋势、异常值与相关关系\n"
                "3. 给出可执行的结论与建议\n"
                "4. 如需图表，说明推荐的图表类型与坐标轴设计")},
    {"id": "meeting", "name": "会议纪要", "icon": "🗒️",
     "description": "把杂乱的记录整理为结构化纪要",
     "prompt": ("你是一名会议纪要整理专家。针对用户提供的记录：\n"
                "1. 提取「会议主题 / 时间 / 参会人」（如可得）\n"
                "2. 按「结论 / 待办（负责人 + 期限）/ 风险与争议」结构化输出\n"
                "3. 语言简洁，删除口语与冗余")},
]

CUSTOM_KEY = "skills"


class SkillManager:
    def __init__(self, cfg):
        self.cfg = cfg

    # ---------------- 查询 ----------------
    def all_skills(self):
        custom = []
        for s in (self.cfg.data.get(CUSTOM_KEY) or []):
            if isinstance(s, dict) and s.get("id"):
                custom.append({**s, "custom": True})
        return BUILTIN_SKILLS + custom

    def get(self, skill_id):
        for s in self.all_skills():
            if s["id"] == skill_id:
                return s
        return BUILTIN_SKILLS[0]

    def current_id(self):
        return self.cfg.data.get("current_skill") or "general"

    def set_current(self, skill_id):
        if self.get(skill_id):
            self.cfg.data["current_skill"] = skill_id
            self.cfg.save()

    # ---------------- 自定义技能 ----------------
    def add_custom(self, name, prompt, description="", icon="🧩",
                   skill_id=None):
        name = (name or "").strip()
        prompt = (prompt or "").strip()
        if not name or not prompt:
            return None
        skill_id = (skill_id or "").strip() or "custom_%d" % int(time.time() * 1000)
        skills = self.cfg.data.setdefault(CUSTOM_KEY, [])
        # 同 id 覆盖更新（技能包重装 / 远程索引更新）
        skills[:] = [s for s in skills if s.get("id") != skill_id]
        skill = {"id": skill_id,
                 "name": name, "prompt": prompt,
                 "description": description or "自定义技能",
                 "icon": icon or "🧩"}
        skills.append(skill)
        self.cfg.save()
        return skill

    def remove_custom(self, skill_id):
        skills = self.cfg.data.get(CUSTOM_KEY) or []
        self.cfg.data[CUSTOM_KEY] = [s for s in skills
                                     if s.get("id") != skill_id]
        if self.cfg.data.get("current_skill") == skill_id:
            self.cfg.data["current_skill"] = "general"
        self.cfg.save()

    # ---------------- 应用 ----------------
    def system_prompt_for(self, skill_id=None):
        """基础系统提示 + 技能提示"""
        base = (self.cfg.data.get("system_prompt") or "").strip()
        skill = self.get(skill_id or self.current_id())
        extra = (skill.get("prompt") or "").strip()
        if not extra:
            return base
        if base:
            return base + "\n\n" + extra
        return extra
