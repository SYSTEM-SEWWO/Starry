# -*- coding: utf-8 -*-
"""平台检测与适配：Windows / Linux / 统信 UOS / Android(Termux) / macOS。

本模块纯标准库实现、不依赖 PyQt，供「无界面命令行版」与「桌面版」
在启动时判断所处平台，从而选择：
  - 配置文件目录（get_config_dir 已按平台区分）
  - 默认打包形态（Windows CLI / Linux CLI / UOS deb / Android Termux / 桌面 GUI）
  - 平台专属提示（如 UOS 建议安装 libxcb-cursor0、Android 走 Termux pip）

V10.0 新增：将「统一能力」按平台分发出各自后缀的版本，做到一处代码、多端适配。
"""
import os
import sys


def _read_os_release():
    """读取 /etc/os-release 文本（不存在返回空串）。"""
    try:
        with open("/etc/os-release", encoding="utf-8") as f:
            return f.read()
    except Exception:  # noqa: BLE001 - 文件缺失即视为非目标平台
        return ""


def is_uos():
    """是否为统信 UOS（或基于其的 Deepin 衍生）。

    UOS 的 /etc/os-release 中常见 ID=uos / NAME="UnionTech OS"；
    银河麒麟等国产系的判定可在此扩展。
    """
    txt = _read_os_release().lower()
    if "id=uos" in txt:
        return True
    if "uniontech" in txt:
        return True
    return False


def is_android_termux():
    """是否运行在 Android 的 Termux 终端环境中。"""
    return bool(os.environ.get("TERMUX_VERSION"))


def is_windows():
    return sys.platform.startswith("win")


def is_macos():
    return sys.platform == "darwin"


def is_linux():
    return sys.platform.startswith("linux")


def detect_platform():
    """返回当前平台标识：windows / macos / uos / android / linux / unknown。"""
    if is_android_termux():
        return "android"
    if is_windows():
        return "windows"
    if is_macos():
        return "macos"
    if is_uos():
        return "uos"
    if is_linux():
        return "linux"
    return "unknown"


_PLATFORM_LABELS = {
    "windows": "Windows",
    "macos": "macOS",
    "linux": "Linux",
    "uos": "统信 UOS",
    "android": "Android (Termux)",
    "unknown": "未知平台",
}


def platform_label(platform=None):
    """平台中文/英文显示名。"""
    return _PLATFORM_LABELS.get(platform or detect_platform(), "未知平台")


# 各平台对应的「版本后缀」与默认产物形态（供打包脚本/文档统一引用）
PLATFORM_SUFFIX = {
    "windows": "windows-cli",
    "linux": "linux-cli",
    "uos": "uos",
    "android": "android",
    "macos": "macos",
    "unknown": "unknown",
}

PLATFORM_PACKAGE_HINT = {
    "windows": "Windows 命令行版（PyInstaller --console → 星语Starry-CLI.exe）",
    "linux": "Linux 命令行版（PyInstaller --console → 星语Starry-CLI）",
    "uos": "统信 UOS 版（Linux CLI 二进制封装为 .deb 安装包）",
    "android": "Android 版（Termux 直接运行；可选 python-for-android 产出 APK）",
    "macos": "macOS 版（PyInstaller 产出可执行文件）",
    "unknown": "通用版",
}


def platform_suffix(platform=None):
    """返回该平台对应的版本后缀名（如 windows-cli / uos / android）。"""
    return PLATFORM_SUFFIX.get(platform or detect_platform(), "unknown")


def platform_package_hint(platform=None):
    """返回该平台默认的打包形态说明。"""
    return PLATFORM_PACKAGE_HINT.get(platform or detect_platform(), "通用版")
