# -*- coding: utf-8 -*-
"""插件市场。

插件类型：
  - tool  工具包：开关应用内置工具（calculator / web_search / ...）
          内置工具包默认全部开启，用户可在市场中逐一关闭
  - skill 技能包：安装一组「技能」（专家人设提示词），零风险；
          安装后出现在聊天窗的技能下拉框中，可随时卸载
  - code  代码插件：远程索引下发、用户确认后在本机执行注册工具
          （受限命名空间：仅允许白名单模块，禁止文件/网络外的危险导入）

安全姿态：
  - 安装任何「代码插件」前必须由 UI 明确警示并二次确认
  - 远程索引仅从用户配置的 URL 获取，失败时静默回退到内置索引
  - 插件工具统一加 plugin_ 前缀命名空间隔离，可整体卸载
"""
import time

import requests

# ---------------------------------------------------------------------------
# 内置市场索引（随应用分发）
# ---------------------------------------------------------------------------
BUILTIN_INDEX = [
    {"id": "utility", "name": "实用工具箱", "type": "tool", "version": "1.0.0",
     "author": "内置", "description": "计算器 / 当前时间 / 随机选择 / 文本统计",
     "tags": ["效率"], "tools": ["calculator", "get_current_time",
                                 "random_pick", "text_stats"]},
    {"id": "web", "name": "联网搜索与网页读取", "type": "tool", "version": "1.0.0",
     "author": "内置", "description": "DuckDuckGo 搜索 / 网页正文提取，让模型获取实时信息",
     "tags": ["联网"], "tools": ["web_search", "fetch_webpage"]},
    {"id": "system", "name": "系统与快捷操作", "type": "tool", "version": "1.0.0",
     "author": "内置", "description": "系统信息 / 打开网页 / 打开本地文件",
     "tags": ["系统"], "tools": ["get_system_info", "open_url", "open_path"]},
    {"id": "files", "name": "本地文件读取", "type": "tool", "version": "1.0.0",
     "author": "内置", "description": "读取文本文件 / 浏览目录（上限 5MB）",
     "tags": ["文件"], "tools": ["read_text_file", "list_directory"]},
    {"id": "library", "name": "资料库检索", "type": "tool", "version": "1.0.0",
     "author": "内置",
     "description": "检索用户导入资料库的文档（本地 TF-IDF，无需联网），"
                    "让回答基于你自己的资料",
     "tags": ["知识"], "tools": ["search_library"]},
    {"id": "pack_translator", "name": "翻译进阶包", "type": "skill",
     "version": "1.0.0", "author": "内置",
     "description": "学术翻译 / 技术本地化两位专家，安装后出现在技能下拉框",
     "tags": ["语言"],
     "skills": [
         {"id": "academic_translator", "name": "学术翻译", "icon": "🎓",
          "description": "论文级中英互译，保留术语与引用格式",
          "prompt": ("你是一名学术翻译专家，擅长论文与专业文献的中英互译：\n"
                     "1. 保持学术语体，术语统一且准确，首次出现可附英文原文\n"
                     "2. 保留引用格式、图表标题与公式编号\n"
                     "3. 长句按中文习惯拆分，不改变原意与逻辑关系\n"
                     "4. 如有歧义，给出最贴合的译法并在译注中说明")},
         {"id": "tech_localizer", "name": "技术本地化", "icon": "⚙️",
          "description": "软件界面 / 文档 / 错误信息本地化",
          "prompt": ("你是一名软件技术本地化专家：\n"
                     "1. 将界面文案、文档、错误信息翻译为地道的中文\n"
                     "2. 遵循常见 UI 用语规范（如「设置」而非「配置」）\n"
                     "3. 保留占位符（%s、{name}、<b> 等）与变量名不动\n"
                     "4. 输出时保持原有格式，可附简短译注说明取舍")},
     ]},
    {"id": "pack_office", "name": "办公技能三件套", "type": "skill",
     "version": "1.0.0", "author": "内置",
     "description": "面试官 / 客服专家 / 小红书文案，安装后出现在技能下拉框",
     "tags": ["办公"],
     "skills": [
         {"id": "interviewer", "name": "模拟面试官", "icon": "💼",
          "description": "按岗位出题、追问并给出评估反馈",
          "prompt": ("你是一名经验丰富的技术面试官：\n"
                     "1. 先询问用户目标岗位与工作年限，再据此出题\n"
                     "2. 每次只问一个问题，根据回答追问细节\n"
                     "3. 用户回答后给出「亮点 / 不足 / 参考答案」三节点评\n"
                     "4. 全部结束后给出综合评分与改进建议")},
         {"id": "customer_service", "name": "客服专家", "icon": "🎧",
          "description": "得体专业的客户投诉 / 咨询回复",
          "prompt": ("你是一名优秀的客服专家：\n"
                     "1. 先共情安抚，再给出清晰的问题处理方案\n"
                     "2. 语气专业得体，不推诿、不承诺做不到的事\n"
                     "3. 涉及补偿时给出明确的时间节点与方式\n"
                     "4. 结尾附上后续跟进方式")},
         {"id": "xhs_copywriter", "name": "小红书文案", "icon": "📕",
          "description": "爆款笔记标题 / 正文 / 话题标签",
          "prompt": ("你是一名小红书爆款文案写手：\n"
                     "1. 标题带 emoji、制造悬念或痛点，20 字以内\n"
                     "2. 正文口语化、有场景感，适当分段并搭配 emoji\n"
                     "3. 结尾引导互动（提问 / 求收藏），并给出 5-8 个话题标签\n"
                     "4. 根据用户给出的主题或产品卖点创作")},
     ]},
]

DEFAULT_MARKET_URL = ("https://raw.githubusercontent.com/ai-desktop-assistant/"
                      "plugin-index/main/index.json")

INSTALLED_KEY = "plugins"          # {plugin_id: {"enabled": bool, ...}}
MARKET_URL_KEY = "market_url"
CACHE_KEY = "market_cache"


# ---------------------------------------------------------------------------
# 代码插件沙箱
# ---------------------------------------------------------------------------
_SAFE_MODULES = {
    "math": __import__("math"), "json": __import__("json"),
    "re": __import__("re"), "time": __import__("time"),
    "random": __import__("random"), "datetime": __import__("datetime"),
    "hashlib": __import__("hashlib"), "base64": __import__("base64"),
    "collections": __import__("collections"), "itertools": __import__("itertools"),
    "string": __import__("string"), "textwrap": __import__("textwrap"),
    "statistics": __import__("statistics"), "urllib.parse": __import__("urllib.parse"),
}


def _safe_import(name, *args, **kwargs):
    root = name.split(".")[0]
    if name in _SAFE_MODULES or root in {m.split(".")[0] for m in _SAFE_MODULES}:
        return __import__(name, *args, **kwargs)
    raise ImportError("插件不允许导入模块：%s" % name)


def install_code_plugin(plugin):
    """执行代码插件的注册逻辑。返回 (ok, 消息)"""
    code = plugin.get("code") or ""
    if not code.strip():
        return False, "插件没有可执行的代码"
    registered = []

    def register(name, description, parameters=None, func=None):
        from core.agent.tools import register_dynamic
        full = "plugin_%s" % name
        register_dynamic(full, "[%s] %s" % (plugin.get("name", "插件"),
                                            description),
                         parameters, func, plugin_id=plugin["id"])
        registered.append(full)

    namespace = {"register": register, "__builtins__": {
        "len": len, "range": range, "str": str, "int": int, "float": float,
        "bool": bool, "list": list, "dict": dict, "set": set, "tuple": tuple,
        "abs": abs, "round": round, "min": min, "max": max, "sum": sum,
        "sorted": sorted, "enumerate": enumerate, "zip": zip, "print": print,
        "isinstance": isinstance, "Exception": Exception, "ValueError": ValueError,
        "TypeError": TypeError, "True": True, "False": False, "None": None,
        "__import__": _safe_import,
    }}
    try:
        exec(compile(code, "<plugin:%s>" % plugin.get("id"), "exec"),  # noqa: S102
             namespace)
    except Exception as e:  # noqa: BLE001
        return False, "插件代码执行失败：%s" % e
    if not registered:
        return False, "插件没有注册任何工具"
    return True, "已注册 %d 个工具" % len(registered)


def uninstall_code_plugin(plugin_id):
    from core.agent.tools import unregister_plugin_tools
    unregister_plugin_tools(plugin_id)


# ---------------------------------------------------------------------------
# 市场
# ---------------------------------------------------------------------------
class PluginMarket:
    def __init__(self, cfg):
        self.cfg = cfg

    # ---------------- 索引 ----------------
    def builtin_index(self):
        return [dict(p) for p in BUILTIN_INDEX]

    @staticmethod
    def is_builtin(plugin_id):
        return any(p.get("id") == plugin_id for p in BUILTIN_INDEX)

    def remote_index(self):
        return list((self.cfg.data.get(CACHE_KEY) or {}).get("plugins") or [])

    def all_plugins(self):
        seen, out = set(), []
        for p in self.builtin_index() + self.remote_index():
            if p.get("id") and p["id"] not in seen:
                seen.add(p["id"])
                out.append(p)
        return out

    def get(self, plugin_id):
        for p in self.all_plugins():
            if p.get("id") == plugin_id:
                return p
        return None

    def market_url(self):
        return (self.cfg.data.get(MARKET_URL_KEY) or DEFAULT_MARKET_URL).strip()

    def set_market_url(self, url):
        self.cfg.data[MARKET_URL_KEY] = (url or "").strip()
        self.cfg.save()

    def refresh_remote(self, timeout=12):
        """拉取远程索引；成功写入缓存。返回 (ok, 消息)"""
        url = self.market_url()
        if not url:
            return False, "未配置市场地址"
        try:
            r = requests.get(url, timeout=timeout,
                             headers={"Accept": "application/json"})
            if r.status_code != 200:
                return False, "HTTP %d" % r.status_code
            data = r.json()
            plugins = data.get("plugins") if isinstance(data, dict) else data
            if not isinstance(plugins, list):
                return False, "索引格式不正确"
            plugins = [p for p in plugins if isinstance(p, dict) and p.get("id")]
        except Exception as e:  # noqa: BLE001
            return False, "拉取失败：%s" % e
        self.cfg.data[CACHE_KEY] = {"plugins": plugins,
                                    "ts": int(time.time())}
        self.cfg.save()
        return True, "已更新 %d 个插件" % len(plugins)

    def cache_age_str(self):
        ts = (self.cfg.data.get(CACHE_KEY) or {}).get("ts")
        if not ts:
            return ""
        minutes = max(0, int((time.time() - ts) / 60))
        if minutes < 1:
            return "刚刚更新"
        if minutes < 60:
            return "%d 分钟前更新" % minutes
        return "%d 小时前更新" % (minutes // 60)

    # ---------------- 安装 / 卸载 ----------------
    def installed(self):
        return self.cfg.data.setdefault(INSTALLED_KEY, {})

    def is_installed(self, plugin_id):
        return plugin_id in self.installed()

    def is_enabled(self, plugin_id):
        return self.pack_enabled(plugin_id)

    def pack_enabled(self, plugin_id):
        """插件是否生效：
        - 已安装插件：以安装时记录的开关为准
        - 未安装的内置工具包：默认开启（可在市场中关闭）
        - 其他未安装插件（含远程索引内容）：关闭，需显式安装
        """
        info = self.installed().get(plugin_id)
        if info is not None:
            return bool(info.get("enabled"))
        if self.is_builtin(plugin_id):
            plugin = self.get(plugin_id)
            if plugin is not None and plugin.get("type") == "tool":
                return True
        return False

    def set_pack_enabled(self, plugin_id, on):
        """开关插件：内置/远程工具包可直接开关（等同于安装），
        技能包与代码插件需先安装"""
        plugin = self.get(plugin_id)
        if plugin is None:
            return False, "插件不存在"
        ptype = plugin.get("type", "tool")
        if ptype == "tool":
            info = self.installed().setdefault(
                plugin_id, {"enabled": True, "type": "tool",
                            "version": plugin.get("version", ""),
                            "ts": int(time.time()),
                            "builtin": self.is_builtin(plugin_id)})
            info["enabled"] = bool(on)
            self.cfg.save()
            return True, ""
        if plugin_id not in self.installed():
            return False, "请先安装该插件"
        self.installed()[plugin_id]["enabled"] = bool(on)
        self.cfg.save()
        return True, ""

    def install(self, plugin_id):
        plugin = self.get(plugin_id)
        if plugin is None:
            return False, "插件不存在"
        ptype = plugin.get("type", "tool")
        if ptype == "code":
            ok, msg = install_code_plugin(plugin)
            if not ok:
                return False, msg
        elif ptype == "skill":
            # 技能包：把技能写入 SkillManager（出现在技能下拉框）
            from core.agent.skills import SkillManager
            sm = SkillManager(self.cfg)
            added = 0
            for sk in (plugin.get("skills") or []):
                if not isinstance(sk, dict) or not sk.get("prompt"):
                    continue
                if sm.add_custom(sk.get("name", plugin_id), sk["prompt"],
                                 sk.get("description", ""),
                                 sk.get("icon", "🧩"),
                                 skill_id=sk.get("id")):
                    added += 1
            if added == 0:
                return False, "该技能包没有可安装的技能"
        self.installed()[plugin_id] = {
            "enabled": True, "type": ptype,
            "version": plugin.get("version", ""), "ts": int(time.time())}
        self.cfg.save()
        return True, "已安装：%s" % plugin.get("name", plugin_id)

    def uninstall(self, plugin_id):
        info = self.installed().pop(plugin_id, None)
        ptype = (info or {}).get("type")
        if ptype is None:
            plugin = self.get(plugin_id)
            ptype = (plugin or {}).get("type")
        if ptype == "code":
            uninstall_code_plugin(plugin_id)
        elif ptype == "skill":
            # 技能包：移除它带来的自定义技能
            from core.agent.skills import SkillManager
            plugin = self.get(plugin_id) or {}
            sm = SkillManager(self.cfg)
            for sk in (plugin.get("skills") or []):
                if isinstance(sk, dict) and sk.get("id"):
                    sm.remove_custom(sk["id"])
        self.cfg.save()
        return True, "已卸载"

    def set_enabled(self, plugin_id, on):
        return self.set_pack_enabled(plugin_id, on)

    # ---------------- 生效范围 ----------------
    def enabled_tools(self):
        """所有生效的工具包提供的工具名集合（空集合 = 不启用任何工具）"""
        names = set()
        for plugin in self.all_plugins():
            if plugin.get("type") != "tool":
                continue
            if not self.pack_enabled(plugin["id"]):
                continue
            names.update(plugin.get("tools") or [])
        return names

    def enabled_tool_count(self):
        return len(self.enabled_tools())

    def enabled_skills(self):
        """生效技能包提供的技能 id（用于市场展示，实际技能由 SkillManager 管理）"""
        ids = []
        for plugin in self.all_plugins():
            if plugin.get("type") != "skill":
                continue
            if not self.pack_enabled(plugin["id"]):
                continue
            for sk in (plugin.get("skills") or []):
                if isinstance(sk, dict) and sk.get("id"):
                    ids.append(sk["id"])
        return ids
