# -*- coding: utf-8 -*-
"""星语 · Starry — 核心层（纯逻辑，无 Qt 依赖）。

公共导出（懒加载，避免 import core 时拉起全部子模块）：

    from core import AppConfig, ChatClient, SessionStore, ...
"""

_LAZY_EXPORTS = {
    # 配置
    "AppConfig": "core.config",
    "PROVIDERS": "core.config",
    "APP_NAME": "core.config",
    "APP_ID": "core.config",
    "APP_VERSION": "core.config",
    "get_config_dir": "core.config",
    # API / 模型
    "ChatClient": "core.api",
    "models": "core.models",
    # 附件 / 渲染
    "Attachment": "core.attachment",
    "load_file_attachment": "core.attachment",
    "image_attachment": "core.attachment",
    "markdown_to_qt_html": "core.markdown_render",
    # 会话 / 提示词 / 统计
    "SessionStore": "core.sessions",
    "message_text": "core.sessions",
    "trim_history": "core.sessions",
    "PromptLibrary": "core.prompts",
    "UsageStats": "core.stats",
    # 导出 / 热键 / 工作线程
    "conversation_to_markdown": "core.exporter",
    "HotkeyManager": "core.hotkey",
    "DEFAULT_HOTKEY": "core.hotkey",
    "ChatWorker": "core.workers",
    "AgentWorker": "core.workers",
    # v12.0 星尘模块（星尘卡 / 上下文预算 / 可移植存档），三端同源
    "stardust": "core.stardust",
    # v13.0 整体项目 / 多线并行 / 自动更新（WorkBuddy 式工作台），三端同源
    "project": "core.project",
    "parallel": "core.parallel",
    "updatecheck": "core.updatecheck",
    # v13.1 Skills Hub（Claude Code / GitHub / WorkBuddy / 星语自有），三端同源
    "hub": "core.hub",
    # v13.2 企业级错误治理（分类 / 脱敏 / 诊断 / 退避），三端同源
    "apierrors": "core.apierrors",
    "apidiag": "core.apidiag",
}

__all__ = list(_LAZY_EXPORTS)


def __getattr__(name):
    """PEP 562 懒导出：from core import X 时按需加载子模块"""
    module_name = _LAZY_EXPORTS.get(name)
    if module_name is None:
        raise AttributeError("module 'core' has no attribute %r" % name)
    import importlib
    try:
        module = importlib.import_module(module_name)
        if name == module_name.rsplit(".", 1)[-1]:
            value = module        # 导出子模块本身（如 core.models / core.stardust）
        else:
            value = getattr(module, name)
    except (ImportError, ModuleNotFoundError) as exc:
        # v12.0：Android 端按白名单排除了 4 个桌面专属模块
        # (attachment / hotkey / models / workers)。若代码误访问，给出
        # 清晰的平台提示，而不是让 ModuleNotFoundError 冒到启动流程里。
        raise AttributeError(
            "core.%s 在当前平台不可用（%s 未随本端分发）" % (name, exc.name)
        ) from exc
    globals()[name] = value          # 缓存，后续访问零开销
    return value


def __dir__():
    return sorted(list(globals()) + __all__)
