# -*- coding: utf-8 -*-
"""PyInstaller 打包配置 · 星语 Starry

用法（在项目根目录执行）：
    pip install pyinstaller
    pyinstaller starrystar.spec --noconfirm --clean

产物：
    Windows / Linux → dist/星语Starry（单文件可执行）
    macOS           → dist/星语Starry（单文件）；如需 .app 见 scripts/build_macos.sh

说明：
- 界面模块多为「函数内懒加载」，PyInstaller 静态分析看不见，
  已在 hiddenimports 中全部显式声明；
- pyttsx3 / pynput / playwright 为可选依赖：构建机未安装时只会告警，
  不影响打包；playwright 已装时自动收集其 node driver；
- 浏览器内核（chromium，约 150MB）不内嵌，由产品内
  设置 → 网页接入页「⬇ 一键安装浏览器内核」按需安装；
- llama.cpp 二进制（本地模型推理用）不内置于安装包，
  由产品内「模型库 → 运行时状态条」引导用户放置/下载。
"""
import os

block_cipher = None


def _pw_datas():
    """收集 Playwright 的 node driver（368 个文件，onefile 默认看不见）。

    注意：浏览器内核（chromium，约 150MB）仍不内嵌——由产品内
    设置 → 网页接入页「一键安装浏览器内核」按需安装。
    """
    try:
        import playwright
        d = os.path.join(os.path.dirname(playwright.__file__), "driver")
        if os.path.isdir(d):
            return [(d, "playwright/driver")]
    except Exception:                              # noqa: BLE001
        pass
    return []


# 懒加载模块（函数内 import）——必须显式声明
_HIDDEN = [
    # app 控制器
    "app.model_controller", "app.screenshot_controller", "app.panel",
    # ui 对话框
    "ui.about_dialog", "ui.automation_dialog", "ui.command_palette",
    "ui.library_dialog", "ui.market_dialog", "ui.models_dialog",
    "ui.onboarding", "ui.panel_dialog", "ui.prompt_dialog", "ui.mail_dialog",
    "ui.session_dialog", "ui.text_input_dialog", "ui.attachment_bar",
    # core 全部子模块
    "core.agent", "core.agent.builtin", "core.agent.market",
    "core.agent.runtime", "core.agent.skills", "core.agent.tools",
    "core.agent.builtin.utility", "core.agent.builtin.system",
    "core.agent.builtin.web", "core.agent.builtin.files",
    "core.agent.builtin.library",
    "core.attachment", "core.automation", "core.config", "core.context",
    "core.exporter", "core.hotkey", "core.library", "core.local_llm",
    "core.markdown_render", "core.models", "core.modelscope",
    "core.prompts", "core.sessions", "core.stats", "core.tts",
    "core.workers",
    # v6：网页版接入（浏览器 harness）与网关
    "core.browser_llm", "core.web_deepseek", "core.gateway",
    "ui.gateway_dialog", "ui.liquid",
    # v7：多站点网页接入注册表（含 v7.1 动效增强组件）
    "core.web_sites",
    # v7.3：真·毛玻璃容器 + 企业商用 EULA 首启门
    "ui.frost", "ui.eula_dialog",
    # v7.4：MCP 工具生态 + 看屏幕问答（core.mcp 在设置页为函数内 import）
    "core.mcp", "core.screen",
    # v8.0：长期记忆系统 + 深度思考（推理）引擎
    "core.memory", "core.reasoning",
    "ui.memory_dialog",
    # v9.0：REA 逆向工程集成（core.rea 在设置页/控制器为函数内 import）
    "core.rea",
    # v10.0：平台检测与适配（无界面命令行版复用；桌面版保持自洽）
    "core.platforms",
    # v12.0 ~ v13.1：纯逻辑层在 GUI 里多为函数内懒加载，必须显式声明
    "core.stardust", "core.sessions", "core.storage", "core.insights",
    "core.project", "core.parallel", "core.updatecheck", "core.hub",
    "core.apierrors", "core.apidiag",
    "ui.workbench_dialog", "ui.hub_dialog", "ui.insight_dialog",
    "ui.api_diag_dialog",
    # v13.3：全局搜索 / 来源引用 / 工具按需选择 / 代码块增强
    "core.globalsearch", "core.toolselect", "ui.globalsearch_dialog",
    # v13.4：API Key 申请指引 / 缓存清理 / 模型能力矩阵与自动路由
    "core.apikey_guide", "core.cacheclean", "core.modelcap",
    "ui.apikey_guide_dialog", "ui.cache_dialog",
    # v13.5：分级日志 / 自动缩放 / 设置页样式 / 调试面板
    "core.devlog", "core.uiscale", "ui.settings_style", "ui.devtools_dialog",
    # v13.6：模型端点判定（CLI/设置页函数内 import，需显式声明）
    "core.endpoints",
    # 可选依赖（构建机未装时仅告警）
    "pyttsx3", "pynput", "pypdf", "playwright",
]

a = Analysis(
    ["main.py"],
    pathex=[os.path.abspath(os.getcwd())],
    binaries=[],
    # v13.1：示例 Skills 随 GUI EXE 分发，开箱即可打开 Skills Hub
    datas=([("README.md", "."), ("requirements.txt", ".")]
           + ([("skills", "skills")] if os.path.isdir("skills") else [])
           + ([("config.hub.example.json", ".")]
              if os.path.isfile("config.hub.example.json") else [])
           + _pw_datas()),
    hiddenimports=_HIDDEN,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # v7.2 瘦身：排除明确未使用的重量级模块（Qt 全家桶里的非 GUI 模块）
    excludes=[
        "tkinter", "matplotlib", "numpy", "PIL.ImageQt",
        "PyQt5.QtWebEngine", "PyQt5.QtWebEngineCore",
        "PyQt5.QtWebEngineWidgets", "PyQt5.QtQml", "PyQt5.QtQuick",
        "PyQt5.QtQuick3D", "PyQt5.Qt3DCore", "PyQt5.QtMultimedia",
        "PyQt5.QtMultimediaWidgets", "PyQt5.QtChart", "PyQt5.QtSql",
        "PyQt5.QtBluetooth", "PyQt5.QtNfc", "PyQt5.QtPositioning",
        "PyQt5.QtSerialPort", "PyQt5.QtDesigner", "PyQt5.QtTest",
        "PyQt5.QtHelp", "PyQt5.QtOpenGL", "PyQt5.QtSvg",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="星语Starry",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,               # GUI 程序：不弹控制台
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon="assets/icon.ico" if os.path.exists("assets/icon.ico") else None,
)

# macOS：scripts/build_macos.sh 会在本文件基础上追加 BUNDLE 生成 .app
# （onefile 模式下直接把 exe 交给用户双击也能运行）
