# -*- coding: utf-8 -*-
"""PyInstaller 打包配置 · 星语 Starry 命令行版（V10.0）

与 starrystar.spec（桌面 GUI 版）的区别：
  - 入口为 starry_cli.py（无界面）
  - console=True：保留终端窗口，可在 Windows 命令提示符 / PowerShell、
    Linux 终端、统信 UOS 终端、Android Termux 中交互与管道调用
  - hiddenimports 仅声明命令行路径真正用到的核心模块（不收集 ui.*），
    因此产物体积显著小于桌面版，且**不依赖图形环境**即可运行

用法（在项目根目录执行）：
    pip install pyinstaller
    pyinstaller starry_cli.spec --noconfirm --clean

产物：
    Windows → dist/星语Starry-CLI.exe
    Linux   → dist/星语Starry-CLI
"""
import os

block_cipher = None


def _datas():
    """v13.1：示例 Skills 随包；v13.2：追加 hub 配置示例，开箱可核对配置项。"""
    out = [("README.md", ".")] if os.path.exists("README.md") else []
    if os.path.isdir("skills"):
        out.append(("skills", "skills"))
    if os.path.isfile("config.hub.example.json"):
        out.append(("config.hub.example.json", "."))
    return out


# 命令行版实际依赖的隐藏导入（均为 core 层纯逻辑模块，无 PyQt 窗口类）
_HIDDEN = [
    # 基础
    "core.config", "core.api", "core.platforms", "core.memory",
    "core.reasoning", "core.rea", "core.web_sites",
    # v12.0 新增（星尘卡 / 存档 / 上下文预算 / 会话读写）
    "core.stardust", "core.sessions", "core.storage", "core.insights",
    # v13.0 新增（整体项目 / 多线并行 / 自动更新，CLI 与桌面工作台共用）
    "core.project", "core.parallel", "core.updatecheck",
    # v13.1 Skills Hub / v13.2 DeepSeek 与企业级错误治理
    "core.hub", "core.apierrors", "core.apidiag",
    # 智能体运行时与内置工具
    "core.agent", "core.agent.builtin", "core.agent.runtime",
    "core.agent.skills", "core.agent.tools", "core.agent.market",
    "core.agent.builtin.utility", "core.agent.builtin.system",
    "core.agent.builtin.web", "core.agent.builtin.files",
    "core.agent.builtin.library",
    # v13.2 MCP 注册 / v13.3~v13.6 新增的纯逻辑模块（CLI 命令在函数内 import）
    "core.mcp", "core.library", "core.globalsearch", "core.toolselect",
    "core.apikey_guide", "core.cacheclean", "core.modelcap",
    "core.devlog", "core.uiscale", "core.endpoints",
    # 可选依赖（构建机未装时仅告警）
    "pyttsx3", "pynput",
]

a = Analysis(
    ["starry_cli.py"],
    pathex=[os.path.abspath(os.getcwd())],
    binaries=[],
    datas=_datas(),
    hiddenimports=_HIDDEN,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "tkinter", "matplotlib", "numpy",
        "PyQt5", "PyQt5.QtCore", "PyQt5.QtWidgets", "PyQt5.QtGui",
        "PyQt5.QtWebEngine", "PyQt5.QtWebEngineCore",
        "PyQt5.QtWebEngineWidgets", "PyQt5.QtQml", "PyQt5.QtQuick",
        "PyQt5.QtQuick3D", "PyQt5.Qt3DCore", "PyQt5.QtMultimedia",
        "PyQt5.QtMultimediaWidgets", "PyQt5.QtChart", "PyQt5.QtSql",
        "PyQt5.QtBluetooth", "PyQt5.QtNfc", "PyQt5.QtPositioning",
        "PyQt5.QtSerialPort", "PyQt5.QtDesigner", "PyQt5.QtTest",
        "PyQt5.QtHelp", "PyQt5.QtOpenGL", "PyQt5.QtSvg",
        "playwright", "pypdf",
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
    name="星语Starry-CLI",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,                # 命令行版：保留终端
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
