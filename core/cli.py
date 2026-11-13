# -*- coding: utf-8 -*-
"""星语 Starry · 无界面命令行版引擎（V10.0 新增）。

设计原则：
  1. **完全无 PyQt 依赖** —— 仅依赖 core 层纯逻辑模块，可在无桌面/无显卡的
     服务器、CI、Termux、Windows 命令提示符中运行，且 PyInstaller 打包后
     体积显著小于桌面版（不收集 ui.* 模块）。
  2. **复用真实能力** —— 直接构造与桌面版一致的 ChatClient，并复用
     core.agent.runtime.AgentRuntime 驱动「模型 ↔ 工具」多轮循环；
     不是另写一套伪实现。
  3. **纯函数可单测** —— collect_chat / collect_agent 不触碰 IO，便于自测
     用假 client 断言；run_cli 仅负责参数解析与打印，可注入 out 流。

用法（根目录）：
    python3 starry_cli.py "你好，介绍一下你自己"
    python3 starry_cli.py -f prompt.txt --json
    python3 starry_cli.py --platform
    python3 starry_cli.py --agent "帮我查一下当前目录有哪些文件"
"""
import argparse
import io
import json
import sys

from core import api as api_mod
from core import config as cfg_mod
from core.agent.runtime import AgentRuntime
from core.agent.tools import get_tool_specs, execute_tool
from core.web_sites import is_web_site  # 网页接入型服务商（需浏览器，CLI 不支持）
from core.memory import MemoryStore
from core.platforms import (detect_platform, platform_label, platform_suffix,
                            platform_package_hint)
from core.rea import ensure_rea_preset  # V9.0：REA 逆向工程 MCP 预设并入

# 思考强度仅对这些服务商下发（与桌面版一致；其余自动忽略，避免报错）
EFFORT_SUPPORTED_PROVIDERS = {"openrouter", "deepseek", "zhipu",
                              "dashscope", "groq", "siliconflow",
                              "minimax", "together"}

SYSTEM_PROMPT = (
    "你是「星语 Starry」，一个中文友好、可靠、注重安全与隐私的 AI 助手。"
    "回答简洁准确；涉及敏感或危险操作要明确提醒。若用户要求使用工具，"
    "在工具不可用或需要确认时如实说明。"
)


# ---------------------------------------------------------------------------
# 纯函数：直接驱动真实流式能力，便于单测
# ---------------------------------------------------------------------------
def collect_chat(client, messages, should_stop=None):
    """驱动一次普通流式对话，返回 (reasoning, answer) 两个字符串。

    client 需实现 chat_stream(messages, should_stop) -> 迭代 ("reasoning"/"content", 文本)。
    """
    reasoning_parts, answer_parts = [], []
    for kind, text in client.chat_stream(messages, should_stop):
        if kind == "reasoning":
            reasoning_parts.append(text)
        else:
            answer_parts.append(text)
    return "".join(reasoning_parts), "".join(answer_parts)


def collect_agent(client, messages, enabled_tools=None,
                  max_iterations=6, should_stop=None):
    """驱动「模型 ↔ 工具」多轮循环，返回 (reasoning, answer, tools)。

    tools: list[{"name","args","result"}], 记录每一轮工具调用的输入与产出。
    """
    runtime = AgentRuntime(client, enabled_tools, max_iterations, should_stop)
    reasoning_parts, answer_parts = [], []
    tool_events = []
    for kind, payload in runtime.run(messages):
        if kind == "reasoning":
            reasoning_parts.append(payload)
        elif kind == "content":
            answer_parts.append(payload)
        elif kind == "tool":
            if not payload.get("running"):
                tool_events.append({"name": payload["name"],
                                    "args": payload.get("args"),
                                    "result": payload.get("result")})
        elif kind == "notice":
            answer_parts.append("\n[提示] %s\n" % payload)
        elif kind == "error":
            answer_parts.append("\n[错误] %s\n" % payload)
    return "".join(reasoning_parts), "".join(answer_parts), tool_events


# ---------------------------------------------------------------------------
# 客户端构造（与桌面版 _effective_client 逻辑一致）
# ---------------------------------------------------------------------------
def build_client(cfg, overrides=None):
    """从 AppConfig + 命令行覆盖项构造 ChatClient。

    overrides: dict{provider, base_url, api_key, model}
    """
    overrides = overrides or {}
    provider = overrides.get("provider") or cfg.provider
    if is_web_site(provider):
        # 网页接入型（DeepSeek/智谱清言/豆包）需要浏览器 harness，CLI 不可用
        raise api_mod.ChatError(
            "当前服务商「%s」为网页接入型，需桌面版浏览器环境，"
            "请在桌面端使用。" % provider)
    base_url = overrides.get("base_url") or cfg.base_url(provider)
    api_key = overrides.get("api_key") or cfg.api_key(provider)
    model = overrides.get("model") or cfg.model(provider)
    effort = cfg.effective("reasoning_effort")
    if provider not in EFFORT_SUPPORTED_PROVIDERS:
        effort = None
    top_p = float(cfg.effective("top_p") or 1.0)
    if abs(top_p - 1.0) < 1e-6:
        top_p = None
    return api_mod.ChatClient(
        base_url=base_url,
        api_key=api_key,
        model=model,
        temperature=float(cfg.effective("temperature") or 0.7),
        max_tokens=int(cfg.effective("max_tokens") or 4096),
        top_p=top_p,
        reasoning_effort=effort,
    )


def _build_messages(cfg, prompt, use_memory=True):
    """构造发送给模型的 messages（含系统提示 + 可选长期记忆注入）。"""
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    if use_memory:
        try:
            store = MemoryStore()
            block = store.build_memory_block()
            if block:
                messages.append({"role": "system", "content": block})
        except Exception:  # noqa: BLE001 - 记忆不可用不影响对话
            pass
    messages.append({"role": "user", "content": prompt})
    return messages


# ---------------------------------------------------------------------------
# 打印层（可注入 out 流，便于自测）
# ---------------------------------------------------------------------------
def _emit(out, text):
    """安全打印：Windows 控制台 cp1252/GBK 无法编码中文时不让 CLI 崩溃。

    V11.5 在 Wine（模拟真实 Windows 控制台）里打包 exe 后实测发现：
    ``out.write("星语 Starry ...")`` 会抛 UnicodeEncodeError 导致秒退。
    这里退化为「按目标流编码 + replace」重写，保证核心功能可用。
    """
    try:
        out.write(text)
        return
    except UnicodeEncodeError:
        pass
    encoding = getattr(out, "encoding", None) or "ascii"
    try:
        safe = text.encode(encoding, errors="replace").decode(encoding)
        out.write(safe)
    except Exception:                                  # noqa: BLE001
        # 最后兜底：连编码都不可用时，写 ASCII 近似值，绝不因打印而退出
        try:
            out.write(text.encode("ascii", errors="replace").decode("ascii"))
        except Exception:                              # noqa: BLE001
            pass


def run_chat(client, prompt, *, cfg=None, show_reasoning=True,
             as_json=False, use_memory=True, out=None, should_stop=None,
             echo=False):
    """执行一次普通对话并打印结果。返回退出码（0 成功）。

    echo=True（v12.0）：额外输出/附带一张本地生成的星尘卡，零 token、零联网。
    """
    from core import stardust
    out = out or sys.stdout
    messages = _build_messages(cfg, prompt, use_memory)
    reasoning, answer = collect_chat(client, messages, should_stop)
    card = (stardust.build_echo_card(
        title="本轮问答", reasoning=reasoning, answer=answer, prompt=prompt)
        if echo else None)
    if as_json:
        payload = {"platform": detect_platform(),
                   "reasoning": reasoning, "answer": answer}
        if card:
            payload["echo_card"] = card
        json.dump(payload, out, ensure_ascii=False)
        out.write("\n")
    else:
        if show_reasoning and reasoning.strip():
            _emit(out, "【思考过程】\n" + reasoning.strip() + "\n\n")
        _emit(out, answer + "\n")
        if card:
            _emit(out, "\n" + card + "\n")
    return 0


def run_agent(client, prompt, *, cfg=None, enabled_tools=None,
              max_iterations=6, show_reasoning=True, as_json=False,
              use_memory=True, out=None, should_stop=None, echo=False):
    """执行一次智能体（含工具）对话并打印结果。"""
    from core import stardust
    out = out or sys.stdout
    messages = _build_messages(cfg, prompt, use_memory)
    reasoning, answer, tools = collect_agent(
        client, messages, enabled_tools, max_iterations, should_stop)
    card = (stardust.build_echo_card(
        title="本轮智能体问答", reasoning=reasoning, answer=answer, prompt=prompt)
        if echo else None)
    if as_json:
        payload = {"platform": detect_platform(),
                   "reasoning": reasoning, "answer": answer, "tools": tools}
        if card:
            payload["echo_card"] = card
        json.dump(payload, out, ensure_ascii=False)
        out.write("\n")
    else:
        if show_reasoning and reasoning.strip():
            _emit(out, "【思考过程】\n" + reasoning.strip() + "\n\n")
        for t in tools:
            _emit(out, "[工具] %s(%s) → %s\n"
                   % (t["name"], json.dumps(t["args"], ensure_ascii=False)[:200],
                      (t["result"] or "")[:200]))
        _emit(out, answer + "\n")
        if card:
            _emit(out, "\n" + card + "\n")
    return 0


# ---------------------------------------------------------------------------
# 命令行入口（argparse）
# ---------------------------------------------------------------------------
def _resolve_prompt(args):
    """按优先级解析用户输入：--file > --prompt > 标准输入（直到 EOF）。"""
    if args.file:
        with open(args.file, "r", encoding="utf-8") as f:
            return f.read().strip()
    if args.prompt:
        return args.prompt
    if not sys.stdin.isatty():
        data = sys.stdin.read().strip()
        if data:
            return data
    return ""


def build_arg_parser():
    p = argparse.ArgumentParser(
        prog="星语Starry-CLI", add_help=True,
        description="星语 Starry 无界面命令行版（跨平台：Windows / Linux / 统信 UOS / Android Termux）")
    p.add_argument("-p", "--prompt", help="直接传入提问文本")
    p.add_argument("-f", "--file", help="从文件读取提问文本")
    p.add_argument("--provider", help="覆盖服务商（如 zhipu / deepseek / openrouter）")
    p.add_argument("--model", help="覆盖模型名")
    p.add_argument("--base-url", help="覆盖 API Base URL")
    p.add_argument("--api-key", help="覆盖 API Key（也可写在 config.json）")
    p.add_argument("-a", "--agent", action="store_true",
                   help="启用智能体模式（调用内置工具，如读文件/执行命令）")
    p.add_argument("--tools", help="智能体模式限定工具名（逗号分隔），默认全部")
    p.add_argument("--max-iterations", type=int, default=6,
                   help="智能体最大工具循环轮数（默认 6）")
    p.add_argument("--no-reasoning", action="store_true",
                   help="不打印思考过程")
    p.add_argument("--json", action="store_true",
                   help="以 JSON 输出 {platform, reasoning, answer[, tools]}")
    p.add_argument("--platform", action="store_true",
                   help="打印检测到的平台与版本后缀后退出")
    p.add_argument("--no-memory", action="store_true",
                   help="不注入长期记忆")
    p.add_argument("-V", "--version", action="store_true",
                   help="打印版本号后退出")
    p.add_argument("--config", help="指定 config.json 路径（默认按平台读取）")
    p.add_argument("--add-rea", action="store_true",
                   help="将 REA 逆向工程 MCP 预设并入配置（V9.0 能力）")
    # ---- v12.0 电脑端新功能（纯本地、零联网，跨三端同源）----
    p.add_argument("--doctor", action="store_true",
                   help="运行环境 / 版本一致性自检后退出（v12.0）")
    p.add_argument("--archive", metavar="PATH",
                   help="把全部会话与长期记忆导出为 .starry 存档后退出（v12.0）")
    p.add_argument("--restore", metavar="PATH",
                   help="从 .starry 存档导入；校验失败一律拒绝（v12.0）")
    p.add_argument("--budget", type=int, metavar="N",
                   help="对当前会话给出 token 上限 N 的上下文裁剪计划（v12.0）")
    p.add_argument("--echo", action="store_true",
                   help="对话结束后附加打印一张本地生成的星尘卡（零 token，v12.0）")
    # ---- v13.0 大版本：整体项目 → 多线并行 → 自动更新 → 工作台 ----
    g = p.add_argument_group("v13.0 整体项目与多线并行")
    g.add_argument("--project", metavar="GOAL",
                   help="把一个目标拆成「整体项目」并打印项目报告（v13.0）")
    g.add_argument("--project-load", metavar="PATH",
                   help="从 .starryproj 载入项目；校验失败一律拒绝（v13.0）")
    g.add_argument("--project-save", metavar="PATH",
                   help="把项目另存为 .starryproj（可保存并行执行后的结果）")
    g.add_argument("--parallel", action="store_true",
                   help="多线并行执行整体项目（按依赖分波，异常隔离，v13.0）")
    g.add_argument("--workers", type=int, default=4, metavar="N",
                   help="并行度 / 线数（默认 4）")
    g.add_argument("--timeout", type=float, metavar="SEC",
                   help="每波整体超时秒数（默认不限）")
    g.add_argument("--retries", type=int, default=0, metavar="N",
                   help="单线失败后的额外重试次数（默认 0）")
    g.add_argument("--execute", action="store_true",
                   help="chat 类任务改用真实模型（需 API Key）；默认离线确定性执行")
    u = p.add_argument_group("v13.0 自动更新与工作台")
    u.add_argument("--update-check", action="store_true",
                   help="检查新版本（本地清单 / STARRY_UPDATE_URL / --update-url）")
    u.add_argument("--update-manifest", metavar="PATH",
                   help="本地 update.json 路径（完全离线，v13.0）")
    u.add_argument("--update-url", metavar="URL",
                   help="远程更新清单 URL（只读联网，覆盖 STARRY_UPDATE_URL）")
    u.add_argument("--workbench", action="store_true",
                   help="打印工作台总览：环境 + 整体项目 + 多线并行 + 更新（v13.0）")
    # ---- v13.2 Skills Hub：GitHub / DeepSeek / Claude Code / WorkBuddy ----
    b = p.add_argument_group("v13.2 Skills Hub 与技能更新")
    b.add_argument("--hub", action="store_true",
                   help="列出已发现的技能（GitHub / DeepSeek / Claude Code / WorkBuddy / 星语自有）")
    b.add_argument("--hub-search", metavar="QUERY",
                   help="按名称 / 描述 / 标签 / 正文搜索技能")
    b.add_argument("--hub-info", metavar="ID",
                   help="查看某个技能的完整说明与指令正文")
    b.add_argument("--hub-update", action="store_true",
                   help="用 --hub-manifest 指定的 hub.json 判定技能是否有更新")
    b.add_argument("--hub-manifest", metavar="PATH",
                   help="Hub 清单路径（本地 hub.json，离线严格校验）")
    b.add_argument("--hub-source", action="append", metavar="PATH", default=[],
                   help="追加一个本地技能源目录（可重复使用）")
    b.add_argument("--hub-import", metavar="ID",
                   help="把指定技能导入星语自有技能库（写入 config.json）")
    # v13.2：统一配置项与可观测性
    b.add_argument("--hub-config", metavar="PATH",
                   help="从 JSON 读 hub 配置段（config.json 的 hub 键，或裸 hub 配置）")
    b.add_argument("--hub-sources", metavar="LIST",
                   help="逗号分隔的来源开关，如 github,deepseek,claude-code")
    b.add_argument("--hub-config-show", action="store_true",
                   help="打印当前生效的 hub 配置与配置告警后退出")
    b.add_argument("--hub-diagnostics", action="store_true",
                   help="打印扫描诊断：生效来源 / 告警 / 异常 / 技能数")
    # ---- v13.2 MCP 工具服务器（stdio）注册管理：控制台注册 / 列出 / 测试 / 移除 ----
    m = p.add_argument_group("v13.2 MCP 工具服务器（stdio）注册管理")
    m.add_argument("--mcp-add", metavar="NAME",
                   help="注册一个 stdio MCP 服务器（配合 --mcp-cmd / --mcp-args；写入 config.json 的 mcp_servers）")
    m.add_argument("--mcp-cmd", metavar="COMMAND",
                   help="被注册服务器的启动命令（如 npx / uvx / python / 绝对路径可执行文件）")
    m.add_argument("--mcp-arg", metavar="ARG", action="append", default=[],
                   help="服务器启动参数（可重复；值以 - 开头时用 --mcp-arg=VALUE 形式）")
    m.add_argument("--mcp-args", metavar="ARGS",
                   help="服务器启动参数（空格分隔的整体字符串，推荐；如 "
                        "--mcp-args \"-y @modelcontextprotocol/server-filesystem\"）")
    m.add_argument("--mcp-env", metavar="K=V", action="append", default=[],
                   help="传给服务器的环境变量（可重复，如 --mcp-env API_KEY=xxx）")
    m.add_argument("--mcp-trust", action="store_true",
                   help="标记该服务器为「信任」（跳过写/执行类工具的安全确认）")
    m.add_argument("--mcp-off", action="store_true",
                   help="注册后默认禁用（需手动 --mcp-enable 启用）")
    m.add_argument("--mcp-remove", metavar="NAME",
                   help="移除一个已注册的 MCP 服务器")
    m.add_argument("--mcp-enable", metavar="NAME",
                   help="启用一个 MCP 服务器（enabled=true）")
    m.add_argument("--mcp-disable", metavar="NAME",
                   help="禁用一个 MCP 服务器（enabled=false）")
    m.add_argument("--mcp-list", action="store_true",
                   help="列出当前已注册的 MCP 服务器（名称 / 命令 / 启用 / 信任）")
    m.add_argument("--mcp-show", action="store_true",
                   help="以 JSON 打印当前 mcp_servers 配置")
    m.add_argument("--mcp-test", metavar="NAME",
                   help="测试连接某个 MCP 服务器（启动并拉取工具清单，不常驻）")

    # ---- v13.3：借鉴 GitHub 同类爆火项目后融入的三项能力 ----
    n = p.add_argument_group("v13.3 全局搜索 / 来源引用 / 工具按需选择")
    n.add_argument("--global-search", metavar="QUERY",
                   help="一次搜完会话 / 资料库 / 提示词 / 长期记忆 / 收藏（Cherry Studio 式）")
    n.add_argument("--citations", metavar="QUERY",
                   help="列出该问题会引用到的资料库来源清单（AnythingLLM 式可溯源）")
    n.add_argument("--tool-select", metavar="QUERY",
                   help="按问题挑选最相关的工具，减少提示词 token（AnythingLLM 式）")
    n.add_argument("--tool-top-k", metavar="N", type=int, default=8,
                   help="--tool-select 保留的工具数（默认 8）")
    n.add_argument("--tool-input", metavar="PATH",
                   help="--tool-select 用的 JSON 工具清单（缺省用已注册工具）")

    # ---- v13.4：API Key 申请引导 / 缓存清理 / 大模型能力 ----
    q = p.add_argument_group("v13.4 API Key 指引 / 缓存清理 / 模型能力")
    q.add_argument("--apikey-guide", metavar="PROVIDER", nargs="?",
                   const="", help="打印某服务商 API Key 的完整申请步骤（缺省用当前服务商）")
    q.add_argument("--cache-scan", action="store_true",
                   help="只读扫描应用缓存，列出可清理项（绝不删除）")
    q.add_argument("--cache-clean", action="store_true",
                   help="清理应用缓存；不加 --yes 时只试运行，不删除任何文件")
    q.add_argument("--yes", action="store_true",
                   help="配合 --cache-clean 确认执行（会先自动备份，可撤销）")
    q.add_argument("--model-capabilities", action="store_true",
                   help="打印当前服务商的模型能力矩阵（工具/视觉/推理/上下文）")
    q.add_argument("--model-route", metavar="QUERY",
                   help="按本轮问题特征推荐最合适的模型（自动路由）")
    q.add_argument("--need-tools", action="store_true",
                   help="--model-route：本轮需要工具调用")
    q.add_argument("--with-images", action="store_true",
                   help="--model-route：本轮包含图片")
    q.add_argument("--deep", action="store_true",
                   help="--model-route：本轮开启深度思考")

    # ---- v13.5：开发者调试 / 分级日志 / 自动缩放 ----
    r = p.add_argument_group("v13.5 开发者调试与自动缩放")
    r.add_argument("--devlog", action="store_true",
                   help="打印调试日志状态、环境摘要与最近记录（含脱敏）")
    r.add_argument("--debug", action="store_true",
                   help="本次运行开启 DEBUG 级日志（等价 STARRY_DEBUG=1）")
    r.add_argument("--log-level", metavar="LEVEL",
                   help="临时设置日志级别 DEBUG / INFO / WARN / ERROR")
    r.add_argument("--ui-scale", action="store_true",
                   help="打印自动缩放建议（纯计算，不修改配置）")
    r.add_argument("--screen", metavar="WxH", default="1920x1080",
                   help="--ui-scale 用的屏幕可用区域，如 2560x1440")
    r.add_argument("--dpi", metavar="N", type=int, default=96,
                   help="--ui-scale 用的逻辑 DPI（默认 96）")
    r.add_argument("--ui-layout", action="store_true",
                   help="打印当前栏目密度与上下栏尺寸（只读诊断）")
    r.add_argument("--ui-density", metavar="NAME",
                   help="设置栏目密度：紧凑 / 标准 / 宽松 / 超宽松")

    # ---- v13.6：模型配置诊断（排查「改不了模型 / 默认 lmstudio」）----
    s = p.add_argument_group("v13.6 模型配置诊断")
    s.add_argument("--model-diagnose", action="store_true",
                   help="只读诊断当前服务商 / Base URL / 端点 / 模型是否匹配")
    return p


# ---------------------------------------------------------------------------
# v12.0 电脑端新功能（全部本地执行，零联网、零模型调用）
# ---------------------------------------------------------------------------
def _load_json_file(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:                                  # noqa: BLE001
        return default


def _config_paths():
    import os as _os
    from core.config import get_config_dir
    from core.sessions import SESSIONS_FILE
    d = get_config_dir()
    return _os.path.join(d, SESSIONS_FILE), _os.path.join(d, "memory.json")


def _run_doctor(out):
    """运行环境 + 版本一致性自检（「鉴定完成」的命令行入口）。"""
    from core import stardust
    lines = ["星语 Starry %s · 环境自检" % cfg_mod.APP_VERSION,
             "平台：%s / %s" % (detect_platform(), platform_label()),
             "配置目录：%s" % cfg_mod.get_config_dir()]
    try:
        cfg = cfg_mod.AppConfig.load()
        lines.append("配置就绪：%s（服务商 %s）"
                     % ("是" if cfg.is_ready() else "否", cfg.provider))
    except Exception as exc:                            # noqa: BLE001
        lines.append("配置读取异常：%s" % exc)
    # markdown 只被桌面端的 markdown_to_qt_html 使用，CLI 单文件包有意不收集
    for name, required in (("requests", True), ("bs4", True), ("markdown", False)):
        try:
            __import__(name)
            lines.append("依赖 %-10s OK%s" % (
                name, "" if required else "（桌面渲染用，CLI 可选）"))
        except Exception as exc:                         # noqa: BLE001
            lines.append("依赖 %-10s %s (%s)" % (
                name, "缺失" if required else "未随 CLI 包分发（符合预期）", exc))
    lines.append("星尘模块：v%s 存档格式" % stardust.ARCHIVE_VERSION)
    # 三端同源（若源码目录存在）
    try:
        import os
        import filecmp
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        a, b = os.path.join(root, "core"), os.path.join(root, "android", "core")
        if os.path.isdir(a) and os.path.isdir(b):
            skip = {"attachment.py", "hotkey.py", "models.py", "workers.py"}
            names = []
            for base, dirs, files in os.walk(a):
                dirs[:] = [d for d in dirs if d != "__pycache__"]
                for f in files:
                    if f.endswith(".py") and f not in skip:
                        names.append(os.path.relpath(os.path.join(base, f), a))
            drift = [rel for rel in names
                     if not os.path.exists(os.path.join(b, rel))
                     or not filecmp.cmp(os.path.join(a, rel),
                                        os.path.join(b, rel), shallow=False)]
            lines.append("三端同源：%s（%d 文件，漂移 %d）"
                         % ("OK" if not drift else "漂移", len(names), len(drift)))
        else:
            lines.append("三端同源：单文件包跳过（源码目录不在 exe 内，"
                         "由 CI 发布门禁保证）")
    except Exception as exc:                            # noqa: BLE001
        lines.append("三端同源：跳过（%s）" % exc)
    _emit(out, "\n".join(lines) + "\n")
    return 0


def _run_archive(path, out):
    """导出 .starry 存档（会话 + 长期记忆 + 元信息 + SHA-256）。"""
    import os
    from core import stardust
    from core.sessions import SessionStore
    sessions_path, memory_path = _config_paths()
    store = SessionStore()
    memory = _load_json_file(memory_path, {"enabled": True, "seq": 0, "entries": []})
    text = stardust.pack_archive(
        sessions=store.data, memory=memory,
        meta={"app": "星语 Starry", "version": cfg_mod.APP_VERSION,
              "platform": detect_platform()})
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
    except Exception as exc:                            # noqa: BLE001
        _emit(out, "导出失败：%s\n" % exc)
        return 2
    n_sessions = len((store.data or {}).get("sessions") or [])
    n_mem = len((memory or {}).get("entries") or [])
    _emit(out, "已导出 .starry 存档：%s\n会话 %d 个 · 记忆 %d 条 · 版本 %s\n"
          % (os.path.abspath(path), n_sessions, n_mem, cfg_mod.APP_VERSION))
    return 0


def _run_restore(path, out):
    """导入 .starry 存档：先验签再落盘，且自动备份原文件。"""
    import os
    import shutil
    import time
    from core import stardust
    from core import storage
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = stardust.unpack_archive(f.read())
    except ValueError as exc:
        _emit(out, "拒绝导入：%s\n" % exc)
        return 2
    except Exception as exc:                            # noqa: BLE001
        _emit(out, "读取存档失败：%s\n" % exc)
        return 2
    sessions = data["sessions"]
    if not isinstance(sessions, dict) or not isinstance(sessions.get("sessions"), list):
        _emit(out, "拒绝导入：存档中的 sessions 结构不合法\n")
        return 2
    sessions_path, memory_path = _config_paths()
    stamp = time.strftime("%Y%m%d-%H%M%S")
    for p in (sessions_path, memory_path):
        if os.path.exists(p):
            try:
                shutil.copy2(p, p + ".bak-" + stamp)
            except Exception:                           # noqa: BLE001
                pass
    ok1 = storage.save_json(sessions_path, sessions)
    ok2 = storage.save_json(memory_path, data["memory"])
    if not (ok1 and ok2):
        _emit(out, "导入未完全成功（写入失败），原文件已备份为 *.bak-%s\n" % stamp)
        return 2
    _emit(out, "导入完成：会话 %d 个 · 记忆 %d 条；原文件已备份 *.bak-%s\n"
          % (len(sessions.get("sessions") or []),
             len((data["memory"] or {}).get("entries") or []), stamp))
    return 0


def _run_budget(limit, out):
    """对当前会话消息给出确定性的上下文裁剪计划。"""
    from core import stardust
    from core.sessions import SessionStore
    cur = SessionStore().current() or {}
    msgs = [m for m in (cur.get("messages") or [])
            if isinstance(m, dict) and m.get("role") in ("system", "user", "assistant")]
    if not msgs:
        _emit(out, "上下文预算裁剪计划（上限 %d tokens）\n"
                   "当前会话没有可分析的消息。\n" % max(0, int(limit or 0)))
        return 0
    plan = stardust.plan_trim(msgs, limit, policy="keep_recent")
    lines = ["上下文预算裁剪计划（上限 %d tokens）" % plan["max_tokens"],
             "会话：%s" % (cur.get("title") or "未命名"),
             "消息总数：%d · 估算总量：%d tokens" % (len(msgs), plan["total_tokens"]),
             "保留 %d 条 / 裁剪 %d 条 · 保留后约 %d tokens"
             % (len(plan["keep_indices"]), len(plan["drop_indices"]),
                plan["kept_tokens"]),
             "保留下标：%s" % plan["keep_indices"]]
    if plan["drop_indices"]:
        lines.append("建议裁剪下标：%s" % plan["drop_indices"])
    lines.append("（离线相对估算，不代表任何模型的精确计费；不修改任何数据）")
    _emit(out, "\n".join(lines) + "\n")
    return 0


def _emit_echo(out, prompt, reasoning, answer):
    from core import stardust
    card = stardust.build_echo_card(
        title="本轮问答", reasoning=reasoning, answer=answer,
        prompt=prompt, branched_from=None)
    _emit(out, "\n" + card + "\n")


# ---------------------------------------------------------------------------
# v13.0 电脑端大版本：整体项目 / 多线并行 / 自动更新 / 工作台
#
# 设计要点（与 v12.0 一脉相承）：
#   - 默认**完全离线**：项目规划、分波并行、版本判定都是纯逻辑，
#     Windows EXE / Linux deb 开箱即跑完整流程，不需要 API Key 或网络。
#   - 只有显式 --execute（模型）与 --update-url（联网）才触碰外部资源，
#     且失败一律优雅降级，绝不让 CLI 崩溃。
#   - 所有判定逻辑都在 core.project / core.parallel / core.updatecheck，
#     本层只负责参数编排与打印，因此可进 CI 门禁做离线单测。
# ---------------------------------------------------------------------------
_DEMO_GOAL = "梳理当前目标：盘点资料、提炼要点、草拟方案并复核汇总"


def _resolve_project(args, out):
    """--project-load > --project > 演示目标；返回项目字典或 None。"""
    from core import project as pj
    if args.project_load:
        try:
            with open(args.project_load, "r", encoding="utf-8") as f:
                return pj.unpack_project(f.read())
        except ValueError as exc:
            _emit(out, "拒绝载入项目：%s\n" % exc)
            return None
        except Exception as exc:                            # noqa: BLE001
            _emit(out, "读取项目失败：%s\n" % exc)
            return None
    goal = args.project or (_DEMO_GOAL if (args.parallel or args.workbench) else "")
    if not goal:
        return None
    return pj.plan_from_goal(goal)


def _project_worker(use_model, cfg=None):
    """chat 任务可选走真实模型；其余一律本地确定性 worker。"""
    from core import parallel as pl
    if not use_model:
        return pl.local_worker
    holder = {}

    def _worker(job):
        if (job or {}).get("kind") != "chat":
            return pl.local_worker(job)
        if "client" not in holder:
            holder["client"] = build_client(cfg)
        text = str((job.get("payload") or {}).get("text", "") or "")
        reasoning, answer = collect_chat(
            holder["client"], _build_messages(cfg, text, True), None)
        return {"type": "chat", "reasoning": reasoning, "answer": answer}

    return _worker


def _save_project(project, path, out):
    import os
    from core import project as pj
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(pj.pack_project(project))
        _emit(out, "已保存项目：%s\n" % os.path.abspath(path))
        return 0
    except Exception as exc:                                # noqa: BLE001
        _emit(out, "保存项目失败：%s\n" % exc)
        return 2


def _merge_waves(waves, workers):
    """把多波并行报告合成一份总报告（供 Markdown 渲染复用）。"""
    return {
        "workers": workers,
        "ok": sum(w["ok"] for w in waves),
        "failed": sum(w["failed"] for w in waves),
        "total": sum(w["total"] for w in waves),
        "elapsed_ms": sum(w["elapsed_ms"] for w in waves),
        "timed_out": any(w["timed_out"] for w in waves),
        "results": [r for w in waves for r in w["results"]],
    }


def _run_project(args, cfg, out):
    """整体项目 →（可选）多线并行 → 项目报告 / 存档。"""
    from core import project as pj
    from core import parallel as pl
    project = _resolve_project(args, out)
    if project is None:
        return 2                      # 载入/读取失败，原因已由 _resolve_project 打印
    if not project.get("tasks"):
        _emit(out, "项目没有任务，请检查 .starryproj 内容。\n")
        return 2
    waves = []
    if args.parallel:
        project, waves = pl.run_project(
            project, worker=_project_worker(args.execute, cfg),
            max_workers=args.workers, timeout=args.timeout,
            retries=args.retries)
    report = _merge_waves(waves, args.workers) if waves else None
    _emit(out, pj.render_project_markdown(project, report))
    if waves:
        _emit(out, "\n" + pl.merge_results(
            report, "多线并行汇总（%d 波）" % len(waves)))
    if args.project_save:
        return _save_project(project, args.project_save, out)
    return 0


def _fetch_manifest(url, out, timeout=6):
    """标准库联网只读抓取更新清单；失败优雅降级，不视为程序故障。"""
    import urllib.request
    try:
        req = urllib.request.Request(
            url, headers={"User-Agent": "Starry/%s" % cfg_mod.APP_VERSION})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read(1024 * 1024).decode("utf-8", errors="replace")
        return json.loads(raw)
    except Exception as exc:                                # noqa: BLE001
        _emit(out, "无法获取远程更新清单：%s\n（离线环境属正常情况）\n" % exc)
        return None


def _run_update_check(args, out):
    """检查更新：本地清单 / 远程 URL / 未配置（离线）三种确定性结果。"""
    from core import updatecheck as uc
    from core.platforms import detect_platform
    head = ["星语 Starry %s · 更新检查" % cfg_mod.APP_VERSION,
            "平台：%s" % detect_platform()]
    manifest, source = None, ""
    if args.update_manifest:
        try:
            manifest = uc.load_manifest(args.update_manifest)
            source = "本地清单 %s" % args.update_manifest
        except ValueError as exc:
            _emit(out, "读取清单失败：%s\n" % exc)
            return 2
    else:
        url = args.update_url or uc.configured_manifest_url()
        if url:
            source = "远程清单 %s" % url
            manifest = _fetch_manifest(url, out)
            if manifest is None:
                return 0
        else:
            _emit(out, "\n".join(head + [
                "更新源：未配置（离线模式，未发起任何网络请求）",
                "当前版本：%s" % cfg_mod.APP_VERSION,
                "",
                "配置方式（任选其一）：",
                "  · --update-manifest update.json   本地清单，可完全离线校验",
                "  · --update-url https://.../update.json",
                "  · 设置环境变量 STARRY_UPDATE_URL",
            ]) + "\n")
            return 0
    res = uc.check_update(cfg_mod.APP_VERSION, manifest, detect_platform())
    lines = head + [
        "清单来源：%s" % source,
        "清单校验：%s" % ("通过" if res["manifest_valid"] else "失败"),
        "当前版本：%s · 最新版本：%s" % (res["current"], res["latest"] or "未知"),
        "结论：%s" % (res["reason"] or "无可用结论"),
    ]
    # v13.1：同平台可能有多个正式资产（Windows 同时有 CLI EXE 与 GUI EXE），
    # select_asset() 只返回第一个，这里把该平台的全部资产都列出来，
    # 避免用户以为只有其中一个需要更新。
    if res["update_available"] and res["manifest_valid"]:
        assets = [a for a in (manifest or {}).get("assets", [])
                  if isinstance(a, dict)
                  and a.get("platform") == res.get("platform")]
        if not assets and res["asset"]:
            assets = [res["asset"]]
        if assets:
            lines += ["", "可更新资产（%d 个）：" % len(assets)]
            for a in assets:
                lines += [
                    "  · 名称：%s" % a.get("name"),
                    "    平台：%s · 大小：%s 字节"
                    % (a.get("platform"), a.get("size")),
                    "    地址：%s" % a.get("url"),
                    "    SHA-256：%s" % a.get("sha256"),
                ]
            lines += [
                "",
                "提示：本工具只做完整性判定，不自动下载/替换程序；"
                "请从可信来源下载后用 sha256sum 核对。",
            ]
    if not res["manifest_valid"]:
        lines.append("安全提示：清单校验未通过，已忽略其中的版本与资产信息。")
    _emit(out, "\n".join(lines) + "\n")
    return 0


def _run_workbench(args, cfg, out):
    """WorkBuddy 式工作台总览：环境 + 整体项目 + 多线并行 + 更新，一站式。"""
    import io
    from core import project as pj
    from core import parallel as pl
    from core import updatecheck as uc
    from core.platforms import detect_platform
    lines = [
        "# ✦ 星语 Starry · 工作台", "",
        "> 整体项目 → 多线并行 → 自动更新，一条命令纵览全部状态（离线可跑）。", "",
        "## 1 · 运行环境", "",
        "- 版本：**%s** · 平台：**%s**" % (cfg_mod.APP_VERSION, detect_platform()),
        "- 配置：%s（服务商 %s）" % (
            "已就绪" if cfg.is_ready() else "待配置 API Key", cfg.provider),
        "- 数据目录：`%s`" % cfg_mod.get_config_dir(),
    ]
    # 依赖自检摘要（复用 v12.0 doctor 的确定性输出）
    buf = io.StringIO()
    _run_doctor(buf)
    dep = [ln.strip() for ln in buf.getvalue().splitlines() if ln.startswith("依赖 ")]
    lines += ["- 依赖：" + ("；".join(dep) if dep else "跳过")]

    # 2 · 整体项目 + 3 · 多线并行
    project = _resolve_project(args, out)
    if project is None:
        project = pj.plan_from_goal(_DEMO_GOAL)
    lines += ["", "## 2 · 整体项目", "",
              "- 项目：**%s**" % project.get("title"),
              "- 目标：%s" % (project.get("goal") or "（未填写）"),
              "- 任务数：%d（无依赖任务可并行，汇总任务自动排到第二波）"
              % len(project.get("tasks") or []), ""]
    project, waves = pl.run_project(
        project, worker=pl.local_worker, max_workers=args.workers,
        timeout=args.timeout, retries=args.retries)
    prog = pj.project_progress(project)
    report = _merge_waves(waves, args.workers) if waves else {}
    lines += ["## 3 · 多线并行执行", "",
              "- 波次：**%d** · 并行度：**%s** · 成功 **%s** / 失败 **%s** · 耗时 %s ms"
              % (len(waves), report.get("workers", 0), report.get("ok", 0),
                 report.get("failed", 0), report.get("elapsed_ms", 0)),
              "- 项目进度：**%d%%**（完成 %d / %d）"
              % (prog["percent"], prog["done"], prog["total"]), ""]
    for t in project.get("tasks", []):
        lines.append("  - %s **%s** `%s` · 依赖 %s" % (
            "✓" if t["status"] == pj.TASK_DONE else "✗",
            t["title"], t["status"], ", ".join(t["depends"]) or "—"))

    # 4 · 自动更新
    url = args.update_url or uc.configured_manifest_url()
    lines += ["", "## 4 · 自动更新", "",
              "- 更新源：%s" % (url or "未配置（离线模式）"),
              "- 清单格式：`update.json` v%s · SHA-256 完整性校验"
              % uc.MANIFEST_VERSION,
              "- 说明：版本比较与资产校验为纯逻辑，不自动下载或替换程序。", "",
              "## 5 · 常用命令", "",
              "```",
              "  starry --project \"调研并撰写发版方案\"        # 只规划整体项目",
              "  starry --project \"...\" --parallel --workers 4  # 分波并行执行",
              "  starry --project \"...\" --parallel --project-save p.starryproj",
              "  starry --project-load p.starryproj --parallel   # 继续已有项目",
              "  starry --update-check --update-manifest update.json",
              "  starry --doctor                                # 环境自检",
              "```", ""]
    _emit(out, "\n".join(lines))
    if args.project_save:
        return _save_project(project, args.project_save, out)
    return 0


# ---------------------------------------------------------------------------
# v13.2 Skills Hub（GitHub / DeepSeek / Claude Code / WorkBuddy / 星语自有）
# 只读发现与判定；唯一写操作是用户显式触发的 --hub-import。
# ---------------------------------------------------------------------------
def _build_hub(args, cfg):
    """按 config.json 的 hub 段 / --hub-config / --hub-sources 装配 Hub。

    优先级：--hub-config 文件 > config.json 的 hub 段 > 内置默认值；
    --hub-sources 与 --hub-source 作为覆盖项最后叠加。
    返回 `(module, hub, config, warnings, fatal)`；fatal 非空表示配置不可用。
    """
    import os as _os
    from core import hub as hb
    raw = {}
    if args.hub_config:
        if not _os.path.isfile(args.hub_config):
            return (hb, None, None, [],
                    "Hub 配置文件不存在：%s" % args.hub_config)
        obj = _load_json_file(args.hub_config, None)
        if obj is None:
            return (hb, None, None, [],
                    "Hub 配置不是合法 JSON：%s" % args.hub_config)
        raw = obj.get(hb.HUB_CONFIG_KEY, obj) if isinstance(obj, dict) else {}
    else:
        raw = cfg.data.get(hb.HUB_CONFIG_KEY, {}) or {}
    overrides = {}
    if args.hub_sources:
        overrides["sources"] = args.hub_sources
    config, warnings = hb.normalize_hub_config(raw, overrides)
    if args.hub_source:
        config["extra_dirs"] = list(config["extra_dirs"]) + [
            {"path": p, "source": "local"} for p in args.hub_source]
    hub_obj = hb.Hub(config=config,
                     starry_skills=(cfg.data.get("skills") or []))
    return hb, hub_obj, config, warnings, ""


def _hub_update_check(hb, hub_obj, path, out):
    """用本地 hub.json 判定技能更新；清单校验失败一律拒绝，不联网。"""
    if not path:
        _emit(out, "检查技能更新需要 --hub-manifest 指定本地 hub.json。\n"
                   "（Hub 只做判定，不自动下载或安装技能。）\n")
        return 2
    manifest = _load_json_file(path, None)
    if manifest is None:
        _emit(out, "读取 Hub 清单失败：%s（文件不存在或不是合法 JSON）\n" % path)
        return 2
    res = hb.check_hub_update(hub_obj.discover(), manifest)
    lines = [
        "星语 Starry %s · Skills Hub 更新检查" % cfg_mod.APP_VERSION,
        "清单来源：%s" % path,
        "清单校验：%s" % ("通过" if res["manifest_valid"] else "失败"),
        "Hub 版本：%s" % (res["hub_version"] or "未知"),
        "结论：%s" % res["reason"],
    ]
    if res["update_available"]:
        for label, key in (("新增", "added"), ("变更", "changed"),
                           ("移除", "removed")):
            items = res[key]
            if items:
                lines.append("  %s %d：%s" % (
                    label, len(items),
                    ", ".join(str(x.get("name", "")) for x in items)))
    lines.append("")
    lines.append("说明：Hub 清单的 digest 是完整性校验，不是签名认证；"
                 "安装技能请显式执行 --hub-import。")
    if not res["manifest_valid"]:
        lines.append("安全提示：清单校验未通过，已忽略其中的技能信息。")
    _emit(out, "\n".join(lines) + "\n")
    return 0 if res["manifest_valid"] else 2


def _run_hub(args, cfg, out):
    hb, hub_obj, config, warnings, fatal = _build_hub(args, cfg)
    if fatal:
        _emit(out, fatal + "\n")
        return 2

    # v13.2：配置项可观测 —— 直接打印生效配置，便于集成方核对
    if args.hub_config_show:
        payload = {
            "version": cfg_mod.APP_VERSION,
            "source_file": args.hub_config or "config.json 的 hub 段 / 内置默认值",
            "config": config,
            "config_warnings": warnings,
            "template": hb.config_template(),
        }
        _emit(out, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
        return 0

    skills = hub_obj.discover()

    # v13.2：异常边界可观测 —— 生效来源、配置告警、扫描异常逐条列出
    if args.hub_diagnostics:
        diag = hub_obj.diagnostics()
        diag["version"] = cfg_mod.APP_VERSION
        diag["config_warnings"] = warnings
        _emit(out, json.dumps(diag, ensure_ascii=False, indent=2) + "\n")
        return 0

    if args.hub_import:
        if not hub_obj.can_import():
            _emit(out, "当前 hub 配置 allow_import=false，已拒绝导入。\n")
            return 2
        target = hub_obj.get(args.hub_import)
        if target is None:
            _emit(out, "未找到技能：%s（可用 --hub 查看列表）\n" % args.hub_import)
            return 2
        conv = hb.to_starry_skill(target)
        if not str(conv.get("prompt") or "").strip():
            _emit(out, "该技能在清单里只有元数据、没有指令正文，无法导入。\n")
            return 2
        from core.agent.skills import SkillManager
        saved = SkillManager(cfg).add_custom(
            conv["name"], conv["prompt"], conv["description"],
            conv["icon"], conv["id"])
        if not saved:
            _emit(out, "导入失败：技能名称或指令正文为空。\n")
            return 2
        _emit(out, "已导入技能：**%s**（id `%s`）\n来源：%s · 摘要 `%s`\n"
              % (saved["name"], saved["id"], target["source"],
                 str(target["sha256"])[:16]))
        return 0

    if args.hub_update or args.hub_manifest:
        return _hub_update_check(hb, hub_obj, args.hub_manifest, out)

    if args.hub_info:
        target = hub_obj.get(args.hub_info)
        if target is None:
            _emit(out, "未找到技能：%s（可用 --hub 查看列表）\n" % args.hub_info)
            return 2
        _emit(out, hb.render_skill(target))
        return 0

    query = args.hub_search or ""
    found = hb.search(skills, query)
    title = ("Skills Hub · 搜索「%s」" % query if query
             else "Skills Hub · 星语技能中心")
    enabled = "、".join(config["sources"]) or "（全部关闭）"
    head = [
        "星语 Starry %s · Skills Hub" % cfg_mod.APP_VERSION,
        "共发现 %d 个技能，%s" % (len(skills),
                                  "命中 %d 个" % len(found) if query else "全部列出"),
        "启用来源：%s" % enabled,
    ]
    if warnings or hub_obj.errors:
        head.append("配置告警 %d · 扫描异常 %d（--hub-diagnostics 查看明细）"
                    % (len(warnings), len(hub_obj.errors)))
    head.append("")
    tail = ["", "提示：--hub-info <ID> 看正文 · --hub-import <ID> 导入技能库 · "
                "--hub-config-show 看生效配置 · --hub-diagnostics 看异常边界 · "
                "--hub-update --hub-manifest hub.json 检查技能更新。"]
    _emit(out, "\n".join(head) + hb.render_catalog(found, title)
          + "\n".join(tail) + "\n")
    return 0


# ---------------------------------------------------------------------------
# v13.2 MCP 工具服务器（stdio）注册管理（全部本地执行，零联网、零模型调用）
# ---------------------------------------------------------------------------
def _run_v136(args, cfg, out):
    """v13.6 · 模型配置诊断（只读，不修改任何配置）。"""
    from core import endpoints
    from core.config import PROVIDERS
    key = cfg.provider
    info = PROVIDERS.get(key, {})
    base = cfg.base_url(key)
    ep = endpoints.resolve_endpoint(key, base, info)
    raw = (cfg.data.get("model_cache") or {}).get(key) or {}
    cached = raw.get("models") if isinstance(raw, dict) else raw
    preset = list(info.get("models") or [])
    cached = list(cached or [])
    merged = list(dict.fromkeys(preset + cached))

    lines = ["🔍 模型配置诊断（只读）",
             "  服务商   ：%s（%s）" % (key, info.get("name", "")),
             "  Base URL ：%s" % (base or "(未填写)"),
             "  端点判定 ：%s → %s" % (
                 ep["mode"],
                 ep["tags_url"] if ep["is_ollama"] else (ep["base_url"] or "(未填写)")),
             "  当前模型 ：%s" % (cfg.model() or "(空)"),
             "  可选模型 ：%d 个（预设 %d / 缓存 %d）" % (
                 len(merged), len(preset), len(cached))]
    if merged:
        lines.append("  模型清单 ：%s" % "、".join(merged[:8])
                     + ("…" if len(merged) > 8 else ""))
    if ep["mismatch"]:
        lines.append("  ⚠️ 服务商与地址不匹配：" + ep["hint"])
        lines.append("     建议服务商：%s" % ep["suggest_provider"])
    if not merged:
        lines.append("  ⚠️ 该服务商没有可用模型：请在「设置 → 模型」点"
                     "「获取模型列表」，或手动输入模型 ID 后保存。")
    if not cfg.model():
        lines.append("  ⚠️ 当前模型为空，请求会失败；请先选择或填写模型。")
    _emit(out, "\n".join(lines) + "\n")
    return 0


def _run_v135(args, cfg, out):
    """v13.5 · 开发者调试日志 / 自动缩放建议（全部本地执行）。"""
    import platform
    from core import devlog
    from core import uiscale
    from core.config import APP_VERSION, get_config_dir

    if args.debug or args.log_level:
        devlog.configure(
            enabled=True if args.debug else None,
            level=args.log_level or ("DEBUG" if args.debug else None),
            cfg=cfg)
        devlog.info("cli", "命令行调试日志已开启", version=APP_VERSION)
    else:
        devlog.configure(cfg=cfg)

    did = False
    if args.debug:
        did = True
        _emit(out, "🛠 调试模式已开启：%s\n" % devlog.state()["level"])
    if args.log_level:
        did = True
        _emit(out, "日志级别：%s\n" % devlog.state()["level"])

    if args.devlog:
        did = True
        s = devlog.summary()
        _emit(out, "🛠 开发者调试面板（命令行）\n")
        _emit(out, "  版本 %s  ·  %s  ·  Python %s\n"
              % (APP_VERSION, platform.platform(),
                 __import__("sys").version.split()[0]))
        _emit(out, "  数据目录：%s\n" % get_config_dir())
        _emit(out, "  状态：%s  ·  级别 %s  ·  缓冲 %d/%d  ·  落盘 %s\n"
              % ("启用" if s["enabled"] else "关闭", s["level"],
                 s["buffered"], s["max_records"], s["path"] or "未开启"))
        _emit(out, "  分级计数：%s\n" % "  ".join(
            "%s %d" % (k, v) for k, v in s["counts"].items()))
        _emit(out, "---- 最近日志 ----\n")
        _emit(out, devlog.text_report(50) + "\n")

    if args.ui_scale:
        did = True
        try:
            w, h = (int(x) for x in str(args.screen).lower().split("x")[:2])
        except Exception:                               # noqa: BLE001
            w, h = 1920, 1080
        rec = uiscale.recommend(
            w, h, args.dpi, int(cfg.appearance.get("font_size", 14)))
        _emit(out, uiscale.format_recommendation(rec) + "\n")
        _emit(out, "（纯计算展示，未修改任何配置；应用内可在设置 → 外观"
                   "点「立即按屏幕适配」）\n")

    if args.ui_density:
        did = True
        from core import uilayout
        name = uilayout.normalize(args.ui_density)
        cfg.data["ui_density"] = name
        cfg.data["layout_version"] = uilayout.LAYOUT_VERSION
        cfg.appearance["window_size"] = list(uilayout.metrics(name)["window"])
        cfg.appearance["window_position"] = None
        try:
            cfg.save()
        except Exception:                       # noqa: BLE001
            pass
        _emit(out, "已设置栏目密度：%s，推荐窗口 %s\n"
              % (name, uilayout.metrics(name)["window"]))

    if args.ui_layout:
        did = True
        from core import uilayout
        _emit(out, uilayout.format_layout(cfg) + "\n")

    if not did:
        _emit(out, "请指定 --devlog / --debug / --log-level / --ui-scale / "
                   "--ui-layout / --ui-density。\n")
        return 2
    return 0


def _run_v134(args, cfg, out):
    """v13.4 · API Key 申请指引 / 缓存清理 / 模型能力（全部本地执行）。"""
    from core.apikey_guide import format_guide, provider_keys
    from core import cacheclean as cc
    from core import modelcap
    from core.config import PROVIDERS

    did = False

    if args.apikey_guide is not None:
        did = True
        provider = args.apikey_guide or cfg.provider
        if args.apikey_guide and provider not in PROVIDERS:
            _emit(out, "未知服务商：%s\n可用：%s\n"
                  % (provider, "、".join(provider_keys())))
            return 2
        _emit(out, format_guide(provider, cfg.api_key(provider)) + "\n")

    if args.cache_scan or args.cache_clean:
        did = True
        items = cc.scan(cfg=cfg)
        _emit(out, cc.format_scan(items) + "\n")
        if args.cache_clean:
            if not args.yes:
                _emit(out, "⚠️ 未加 --yes：仅试运行，不删除任何文件。\n")
            else:
                _emit(out, "⚠️ 即将清理应用缓存；会先自动备份，用户数据不会触碰。\n")
            for it in items:
                it["selected"] = it["default_selected"]
            report = cc.clean(items, cfg=cfg, backup=True,
                              dry_run=not args.yes)
            _emit(out, cc.format_report(report) + "\n")
            if report.get("failed"):
                return 1

    if args.model_capabilities:
        did = True
        names = list((PROVIDERS.get(cfg.provider) or {}).get("models") or [])
        _emit(out, modelcap.format_capabilities(
            modelcap.capability_table(names, cfg.provider)) + "\n")

    if args.model_route:
        did = True
        names = list((PROVIDERS.get(cfg.provider) or {}).get("models") or [])
        req = modelcap.describe_request(
            query=args.model_route, has_images=args.with_images,
            need_tools=args.need_tools, deep_thinking=args.deep)
        route = modelcap.route_model(names, req, provider=cfg.provider,
                                     current=cfg.model())
        _emit(out, modelcap.format_route(route) + "\n")
        if not names:
            _emit(out, "提示：当前服务商没有预设模型，请先在设置里切换服务商，"
                       "或用 --model-capabilities 查看能力矩阵。\n")
        elif route.get("ok") and route.get("alternatives"):
            _emit(out, "失败回退链：%s\n" % " → ".join(
                modelcap.fallback_chain(names, route["model"], req,
                                        provider=cfg.provider)))

    if not did:
        _emit(out, "请指定 v13.4 相关参数（--apikey-guide / --cache-scan / "
                   "--cache-clean / --model-capabilities / --model-route）。\n")
        return 2
    return 0


def _run_v133(args, cfg, out):
    """v13.3 · 全局搜索 / 来源引用 / 工具按需选择（全部本地执行，零联网）。"""
    from core import globalsearch as gs
    from core import toolselect as ts
    from core.library import KnowledgeBase, format_citations

    did = False

    if args.global_search:
        did = True
        from core.sessions import SessionStore
        from core.prompts import PromptLibrary
        from core.memory import MemoryStore
        stores = {}
        for key, factory in (("sessions", SessionStore),
                             ("library", KnowledgeBase),
                             ("prompts", lambda: PromptLibrary(cfg)),
                             ("memory", MemoryStore)):
            try:
                stores[key] = factory()
            except Exception:                          # noqa: BLE001
                pass                                    # 单个数据源不可用就跳过
        rows = gs.search_all(args.global_search, **stores)
        _emit(out, "🔎 全局搜索：%s\n" % args.global_search)
        _emit(out, gs.format_results(rows) + "\n")
        c = gs.source_counts(rows)
        _emit(out, "命中分布：%s\n" % "  ".join(
            "%s %d" % (gs.SOURCE_LABELS[s], c[s])
            for s in gs.ALL_SOURCES))

    if args.citations:
        did = True
        try:
            cites = KnowledgeBase().citations_for(args.citations)
        except Exception as e:                         # noqa: BLE001
            cites = []
            _emit(out, "读取资料库失败：%s\n" % e)
        _emit(out, "📎 %s：%s\n" % (
            args.citations, format_citations(cites, with_excerpt=True)))

    if args.tool_select:
        did = True
        if args.tool_input:
            raw = _load_json_file(args.tool_input, [])
            tools = raw.get("tools", []) if isinstance(raw, dict) else raw
        else:
            from core.agent.tools import get_tool_specs   # 触发内置工具注册
            tools = get_tool_specs()
        if not tools:
            _emit(out, "当前没有可用工具；可用 --tool-input 传入 JSON 工具清单。\n")
        else:
            selected, report = ts.select_tools(
                tools, args.tool_select, top_k=args.tool_top_k)
            _emit(out, "🧩 %s → %s\n" % (
                args.tool_select,
                ", ".join(ts._parts(t)[0] for t in selected) or "(无)"))
            _emit(out, "%s\n" % ts.format_report(report))

    if not did:
        _emit(out, "请指定 --global-search / --citations / --tool-select 之一。\n")
        return 2
    return 0


def _run_mcp(args, cfg, custom_config_path, out):
    """控制台注册 / 管理 stdio MCP 服务器。

    所有写操作写入 ``cfg.data["mcp_servers"]``（与桌面端设置页共用同一份配置），
    并持久化到 config.json（或 ``--config`` 指定的自定义路径）。这与已有
    ``McpManager`` / 设置页 UI 完全同源：命令行注册后，GUI 与 CLI 启动都会
    自动加载并接入该服务器的工具。
    """
    from core.mcp import (McpManager, normalize_entry, is_valid_entry)

    servers = list(cfg.data.get("mcp_servers") or [])

    def _save():
        cfg.data["mcp_servers"] = servers
        # v13.2：若用户显式指定了 --config，则写回该路径（与读取一致）；
        # 否则回落到默认配置目录。避免「读 A 写默认」的静默不一致。
        if custom_config_path:
            try:
                with open(custom_config_path, "w", encoding="utf-8") as f:
                    json.dump(cfg.data, f, ensure_ascii=False, indent=2)
                return
            except Exception:                              # noqa: BLE001
                pass
        cfg.save()

    # ---- 列出（只读） ----
    if args.mcp_list:
        if not servers:
            _emit(out, "当前没有已注册的 MCP 服务器。\n"
                      "用 --mcp-add <名称> --mcp-cmd <命令> 注册一个。\n")
            return 0
        lines = ["已注册的 MCP 服务器（%d 个）：" % len(servers), ""]
        for s in servers:
            ne = normalize_entry(s)
            flag = []
            if not ne["enabled"]:
                flag.append("禁用")
            if ne["trusted"]:
                flag.append("信任")
            lines.append("· %s" % ne["name"])
            lines.append("    命令：%s %s" % (ne["command"],
                                             " ".join(ne["args"])))
            if ne["env"]:
                lines.append("    环境：%s"
                             % " ".join("%s=%s" % (k, v)
                                        for k, v in ne["env"].items()))
            if flag:
                lines.append("    标记：%s" % " · ".join(flag))
        _emit(out, "\n".join(lines) + "\n")
        return 0

    # ---- JSON 展示（只读） ----
    if args.mcp_show:
        _emit(out, json.dumps(servers, ensure_ascii=False, indent=2) + "\n")
        return 0

    # ---- 测试连接（启动并拉取工具清单，不常驻） ----
    if args.mcp_test:
        entry = next((s for s in servers
                      if normalize_entry(s)["name"] == args.mcp_test), None)
        if entry is None:
            _emit(out, "未找到服务器：%s\n" % args.mcp_test)
            return 1
        mgr = McpManager([entry])
        ok, msg, tools = mgr.connect_one(args.mcp_test)
        if not ok:
            _emit(out, "连接失败：%s\n" % msg)
            return 1
        names = [t.get("name") for t in tools]
        _emit(out, "连接成功：%s\n" % msg)
        _emit(out, "工具清单（%d）：%s\n" % (len(names),
                                            ", ".join(names) if names else "（无）"))
        return 0

    # ---- 移除 ----
    if args.mcp_remove:
        name = args.mcp_remove
        before = len(servers)
        servers = [s for s in servers
                   if normalize_entry(s)["name"] != name]
        if len(servers) == before:
            _emit(out, "未找到服务器：%s（无需移除）\n" % name)
            return 1
        _save()
        _emit(out, "已移除 MCP 服务器：%s\n" % name)
        return 0

    # ---- 启用 / 禁用 ----
    if args.mcp_enable or args.mcp_disable:
        name = args.mcp_enable or args.mcp_disable
        target = next((s for s in servers
                       if normalize_entry(s)["name"] == name), None)
        if target is None:
            _emit(out, "未找到服务器：%s\n" % name)
            return 1
        target["enabled"] = bool(args.mcp_enable)
        _save()
        _emit(out, "已将 %s 设为%s。\n" % (name,
                                           "启用" if target["enabled"] else "禁用"))
        return 0

    # ---- 注册（新增 / 覆盖同名） ----
    if args.mcp_add:
        if not args.mcp_cmd:
            _emit(out, "错误：注册服务器需要 --mcp-cmd 指定启动命令。\n"
                      "示例：--mcp-add 我的工具 --mcp-cmd npx "
                      "--mcp-args \"-y @modelcontextprotocol/server-filesystem\"\n")
            return 2
        env = {}
        for kv in args.mcp_env:
            if "=" not in kv:
                _emit(out, "警告：--mcp-env 缺少 '='，已忽略：%s\n" % kv)
                continue
            k, v = kv.split("=", 1)
            env[k.strip()] = v
        entry = {
            "name": args.mcp_add,
            "command": args.mcp_cmd,
            "args": list(args.mcp_arg),
            "env": env,
            "enabled": not args.mcp_off,
            "trusted": bool(args.mcp_trust),
        }
        if args.mcp_args:
            entry["args"].extend(str(a) for a in args.mcp_args.split())
        if not is_valid_entry(entry):
            _emit(out, "错误：服务器名称或命令为空，注册失败。\n")
            return 2
        # 覆盖同名（本次参数决定启用 / 信任状态）
        servers = [s for s in servers
                   if normalize_entry(s)["name"] != entry["name"]]
        servers.append(entry)
        _save()
        status = ("（默认禁用，需 --mcp-enable 启用）"
                  if args.mcp_off else "（已启用）")
        trust = " · 已标记为信任" if args.mcp_trust else ""
        _emit(out, "已注册 MCP 服务器：%s → %s %s%s%s\n"
                  % (entry["name"], entry["command"],
                     " ".join(entry["args"]), status, trust))
        _emit(out, "下次启动星语时该服务器的工具将自动接入；"
                  "可用 --mcp-test %s 立即验证连接。\n" % entry["name"])
        return 0

    _emit(out, "未指定任何 MCP 操作。可用：--mcp-add / --mcp-list / "
              "--mcp-show / --mcp-test / --mcp-enable / --mcp-disable / "
              "--mcp-remove。\n")
    return 1


def run_cli(argv=None, out=None):
    """命令行主入口。返回进程退出码（int）。"""
    out = out or sys.stdout
    parser = build_arg_parser()
    args = parser.parse_args(argv if argv is not None else sys.argv[1:])

    if args.version:
        _emit(out, "星语 Starry %s（命令行版）\n" % cfg_mod.APP_VERSION)
        return 0
    if args.platform:
        plat = detect_platform()
        _emit(out, "平台：%s\n版本后缀：%s\n打包形态：%s\n"
               % (platform_label(plat), platform_suffix(plat),
                  platform_package_hint(plat)))
        return 0
    if args.doctor:
        return _run_doctor(out)

    # 加载配置（支持自定义路径）
    if args.config:
        import os as _os
        with open(args.config, "r", encoding="utf-8") as f:
            cfg = cfg_mod.AppConfig(json.load(f))
    else:
        cfg = cfg_mod.AppConfig.load()

    if args.add_rea:
        ensure_rea_preset(cfg)
        cfg.save()
        _emit(out, "已将 REA 逆向工程 MCP 预设并入配置（默认关闭，需在设置中启用）。\n")
        return 0

    # ---- v13.2 MCP 工具服务器（stdio）注册管理：控制台增删改查 + 连通性测试 ----
    if (args.mcp_add or args.mcp_remove or args.mcp_enable or args.mcp_disable
            or args.mcp_list or args.mcp_show or args.mcp_test):
        return _run_mcp(args, cfg, args.config, out)

    # ---- v13.6 模型配置诊断 ----
    if args.model_diagnose:
        return _run_v136(args, cfg, out)

    # ---- v13.5 开发者调试 / 日志 / 自动缩放 ----
    if (args.devlog or args.debug or args.log_level or args.ui_scale
            or args.ui_layout or args.ui_density):
        return _run_v135(args, cfg, out)

    # ---- v13.4 API Key 指引 / 缓存清理 / 模型能力 ----
    if (args.apikey_guide is not None or args.cache_scan or args.cache_clean
            or args.model_capabilities or args.model_route):
        return _run_v134(args, cfg, out)

    # ---- v13.3 全局搜索 / 来源引用 / 工具按需选择 ----
    if args.global_search or args.citations or args.tool_select:
        return _run_v133(args, cfg, out)

    # ---- v12.0 本地工具模式：都不需要 prompt，也不发网络请求 ----
    if args.archive:
        return _run_archive(args.archive, out)
    if args.restore:
        return _run_restore(args.restore, out)
    if args.budget is not None:
        return _run_budget(args.budget, out)

    # ---- v13.1 Skills Hub：只读发现 / 搜索 / 查看 / 更新判定 ----
    if (args.hub or args.hub_search or args.hub_info or args.hub_update
            or args.hub_manifest or args.hub_import or args.hub_source
            or args.hub_config or args.hub_sources or args.hub_config_show
            or args.hub_diagnostics):
        return _run_hub(args, cfg, out)

    # ---- v13.0 本地工作台模式：默认离线，不需要 prompt，不发网络请求 ----
    if args.update_check:
        return _run_update_check(args, out)
    if args.workbench:
        return _run_workbench(args, cfg, out)
    if (args.project or args.project_load or args.parallel
            or args.project_save):
        return _run_project(args, cfg, out)

    prompt = _resolve_prompt(args)
    if not prompt:
        parser.error("未提供提问：请用 -p/--prompt、--file，或从标准输入传入。")

    overrides = {}
    if args.provider:
        overrides["provider"] = args.provider
    if args.base_url:
        overrides["base_url"] = args.base_url
    if args.api_key:
        overrides["api_key"] = args.api_key
    if args.model:
        overrides["model"] = args.model

    try:
        client = build_client(cfg, overrides)
    except api_mod.ChatError as e:
        _emit(out, "配置错误：%s\n" % e)
        return 2

    use_memory = not args.no_memory
    if args.agent:
        enabled = None
        if args.tools:
            enabled = [t.strip() for t in args.tools.split(",") if t.strip()]
        return run_agent(client, prompt, cfg=cfg, enabled_tools=enabled,
                         max_iterations=args.max_iterations,
                         show_reasoning=not args.no_reasoning,
                         as_json=args.json, use_memory=use_memory, out=out,
                         echo=args.echo)
    return run_chat(client, prompt, cfg=cfg,
                    show_reasoning=not args.no_reasoning,
                    as_json=args.json, use_memory=use_memory, out=out,
                    echo=args.echo)


if __name__ == "__main__":
    sys.exit(run_cli())
