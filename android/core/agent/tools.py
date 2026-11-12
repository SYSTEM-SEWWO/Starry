# -*- coding: utf-8 -*-
"""工具注册中心。

- @tool 装饰器注册工具（名称 / 描述 / JSON Schema 参数）
- get_tool_specs()  生成 OpenAI tools 数组
- execute_tool()    在调用方线程执行工具，异常一律转为字符串结果
- register_dynamic() 供插件市场安装的代码插件注册工具
"""

TOOLS = {}          # name -> ToolSpec
_DYNAMIC = {}       # 插件安装的工具（可整体卸载）


class ToolSpec:
    def __init__(self, name, description, parameters, func):
        self.name = name
        self.description = description
        self.parameters = parameters or {
            "type": "object", "properties": {}}
        self.func = func

    def to_openai(self):
        return {"type": "function",
                "function": {"name": self.name,
                             "description": self.description,
                             "parameters": self.parameters}}

    def __repr__(self):  # pragma: no cover
        return "<Tool %s>" % self.name


def tool(name, description, parameters=None):
    """注册工具的装饰器"""
    def deco(fn):
        TOOLS[name] = ToolSpec(name, description, parameters, fn)
        return fn
    return deco


def register_tool(name, description, parameters, func):
    TOOLS[name] = ToolSpec(name, description, parameters, func)


def unregister_tool(name):
    TOOLS.pop(name, None)


def register_dynamic(name, description, parameters, func, plugin_id=""):
    """插件市场安装的工具（带插件归属，便于卸载）"""
    TOOLS[name] = ToolSpec(name, description, parameters, func)
    _DYNAMIC[name] = plugin_id


def unregister_plugin_tools(plugin_id):
    for name in [n for n, pid in _DYNAMIC.items() if pid == plugin_id]:
        TOOLS.pop(name, None)
        _DYNAMIC.pop(name, None)


def get_tool_specs(enabled=None):
    """生成 OpenAI tools 数组；enabled 为启用的工具名集合（None 表示全部）"""
    return [t.to_openai() for n, t in sorted(TOOLS.items())
            if enabled is None or n in enabled]


def get_tool_specs_for_query(query, top_k=8, enabled=None,
                             always_include=None):
    """v13.3 · 按本轮问题挑工具（借鉴 AnythingLLM Intelligent Skill Selection）。

    与 get_tool_specs 完全兼容：query 为空时行为一致（返回全部）。
    返回 (tools 数组, report)，report 含节省 token 统计，供 UI / CLI 展示。
    """
    from core.toolselect import select_tools
    all_specs = get_tool_specs(enabled=enabled)
    selected, report = select_tools(
        all_specs, query=query, top_k=top_k,
        always_include=always_include, enabled=None)
    return selected, report


def execute_tool(name, arguments):
    """执行工具，任何异常都转换为可读字符串（返回给模型）"""
    spec = TOOLS.get(name)
    if spec is None:
        return "错误：工具 %s 不存在" % name
    args = dict(arguments or {})
    args.pop("_raw", None)
    try:
        result = spec.func(**args)
    except TypeError as e:
        return "错误：工具参数不匹配（%s）：%s" % (name, e)
    except Exception as e:  # noqa: BLE001
        return "错误：工具 %s 执行失败：%s" % (name, e)
    text = result if isinstance(result, str) else repr(result)
    return text[:6000]


# ---------------------------------------------------------------------------
# 内置工具（随包分发，market 中的「工具包」只是它们的开关）
# 导入即注册：@tool 装饰器在 import 时把工具写入 _REGISTRY。
# pyflakes 不识别 # noqa，这里显式收集模块引用以消除「imported but unused」。
# ---------------------------------------------------------------------------
from core.agent.builtin import utility, system, web, files, library  # noqa: E402

_BUILTIN_TOOL_MODULES = (utility, system, web, files, library)
