# -*- coding: utf-8 -*-
"""REA（Reverse Engineer Anything）集成层 · 星语 Starry V9.0

REA 是 GitHub 当前爆火的开源项目（morluto/rea，MIT 协议），本质是一个
**MCP 服务器**，把 Hopper / Ghidra / IDA / Apktool 等逆向工具封装为 AI Agent
可调用接口，做「证据驱动、本地优先」的全链路逆向分析。

星语 Starry 作为 Agent 宿主，通过既有 MCP 生态接入 REA：本模块提供
- REA 的 MCP 预设（一键并入设置页的 mcp_servers）
- 逆向分析目标清单（供 UI / 文档展示）
- 构造「证据驱动」逆向分析提示的工作流（与 REA 官方流程同构）
- 能力声明（供 API 文档 / 评测引用）

> 复刻说明：REA 自身即「给 Agent 用的 MCP 服务器」，因此「在星语中复刻 REA
> 功能」最忠实的落地就是——让星语以宿主身份接入 REA，并以 Agent 编排 +
> 证据呈现的方式提供逆向分析能力。底层二进制引擎（Ghidra / IDA 等）需用户
> 按 REA 官方要求自备，与 REA 自身设计一致：星语负责编排与呈现，REA 负责
> 底层拆解。
"""
from __future__ import annotations

# ---------------------------------------------------------------------------
# REA 的 MCP 预设（与 npx rea-agents setup 注册的服务器同构，纯 JSON 可入库）
# ---------------------------------------------------------------------------
REA_MCP_PRESET = {
    "name": "REA 逆向工程",
    "command": "npx",
    "args": ["-y", "rea-agents@latest"],
    "enabled": False,      # 默认关闭：需用户本地具备 Node.js 与（按需）逆向引擎
    "trusted": False,      # 逆向工具属破坏性能力，默认不信任，需用户显式勾选
}

# 支持的逆向分析目标（与 REA 官方 "What you can analyze" 对齐）
REA_ANALYSIS_TARGETS = [
    ("原生二进制 (ELF / PE / Mach-O)",
     "伪代码 / 汇编 / 字符串 / 符号 / 调用图", "需 Ghidra · IDA · Hopper"),
    ("Electron / JavaScript 应用",
     "模块 / 导入 / 源映射 / 路由 / IPC", "静态分析无需原生引擎"),
    ("Android APK",
     "Manifest / 类 / 反编译方法 / 引用", "需 Headless JADX + 完整 JDK"),
    (".NET 程序集",
     "元数据 / CIL 指令 / 原生依赖", "仅静态，无需引擎"),
    ("网站 / 网络捕获 (HAR / mitmproxy)",
     "页面结构 / 脚本 / 网络观察", "需 Chrome 系 / mitmdump"),
    ("固件 / 模型工件 (GGUF / safetensors)",
     "Binwalk / Unblob 解包与解析", "需对应解包工具链"),
]

# 与 REA 官方工作流同构的分析步骤（用于提示构造与 UI 引导）
REA_WORKFLOW = [
    "先用 binary_overview / analyze 取得目标总览",
    "再追踪字符串、交叉引用、调用图，定位关键功能",
    "最后获取伪代码与汇编，并在自己项目中重建行为",
    "每条结论必须附证据（文件偏移 / 置信度）与明确标注的未知项",
]


def rea_capabilities():
    """返回 REA 能力声明（供 API 文档 / 评审引用）。"""
    return {
        "name": "REA · Reverse Engineer Anything",
        "license": "MIT",
        "kind": "MCP server (TypeScript)",
        "principle": "evidence-backed, local-first, agent-driven",
        "targets": [t[0] for t in REA_ANALYSIS_TARGETS],
        "workflow": list(REA_WORKFLOW),
    }


def build_rea_prompt(target_path, goal):
    """构造「证据驱动」的逆向分析提示（与 REA 工作流同构）。

    target_path: 待分析文件 / 目录路径（可空，空则要求对上文内容分析）
    goal:        用户意图（可空，空则给默认目标）
    """
    goal = (goal or "理解它的实现原理，并为我在自己项目里复刻类似功能").strip()
    tp = (target_path or "").strip()
    head = ("请使用已连接的 REA 逆向工程工具，对目标进行分析。\n"
            if tp else
            "请使用已连接的 REA 逆向工程工具，对用户提供的内容进行分析。\n")
    body = ("分析目标：%s\n目标路径：%s\n\n"
            "分析要求（证据驱动）：\n"
            "1. 先取得总览，再追踪关键代码与调用关系；\n"
            "2. 每条结论附上证据（文件偏移 / 符号 / 置信度）与明确标注的未知项；\n"
            "3. 最终给出可在我方项目复刻的实现思路与参考代码。\n"
            % (goal, tp or "（见上文内容）"))
    return head + body


def ensure_rea_preset(servers):
    """把 REA 预设并入 mcp_servers 列表（按 name 去重）。

    返回 (新列表, 是否已存在)。新列表为副本，不修改入参。
    """
    servers = [dict(s) for s in (servers or [])]
    if any(s.get("name") == REA_MCP_PRESET["name"] for s in servers):
        return servers, True
    servers.append(dict(REA_MCP_PRESET))
    return servers, False
