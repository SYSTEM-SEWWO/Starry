# -*- coding: utf-8 -*-
"""系统工具包：系统信息 / 打开网页 / 打开文件"""
import os
import platform
import subprocess
import sys
import webbrowser

from core.agent.tools import tool


@tool("get_system_info", "获取运行环境信息（操作系统 / Python / 应用版本）",
      {"type": "object", "properties": {}})
def get_system_info():
    try:
        from core.config import APP_NAME, APP_VERSION
        app = "%s v%s" % (APP_NAME, APP_VERSION)
    except Exception:  # noqa: BLE001
        app = "AI 桌面助手"
    return ("操作系统：%s %s｜Python：%s｜应用：%s"
            % (platform.system(), platform.release(),
               platform.python_version(), app))


@tool("open_url", "在默认浏览器中打开一个网页链接",
      {"type": "object",
       "properties": {"url": {"type": "string", "description": "http(s) 链接"}},
       "required": ["url"]})
def open_url(url):
    u = str(url or "")
    if not u.startswith(("http://", "https://")):
        return "错误：仅支持 http/https 链接"
    try:
        webbrowser.open(u)
        return "已在浏览器中打开：%s" % u
    except Exception as e:  # noqa: BLE001
        return "打开失败：%s" % e


@tool("open_path", "用系统默认程序打开本地文件或文件夹",
      {"type": "object",
       "properties": {"path": {"type": "string", "description": "文件或文件夹路径"}},
       "required": ["path"]})
def open_path(path):
    p = os.path.expanduser(str(path or ""))
    if not os.path.exists(p):
        return "错误：路径不存在：%s" % p
    try:
        if sys.platform.startswith("win"):
            os.startfile(p)  # noqa: B110
        elif sys.platform == "darwin":
            subprocess.Popen(["open", p])
        else:
            subprocess.Popen(["xdg-open", p])
        return "已打开：%s" % p
    except Exception as e:  # noqa: BLE001
        return "打开失败：%s" % e
