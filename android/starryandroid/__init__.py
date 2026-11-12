# -*- coding: utf-8 -*-
"""星语 Starry · Android 版（BeeWare / Toga 原生封装）。

本包是「桌面核心逻辑」在移动端的原生 GUI 封装层：
- 所有对话 / 思考流 / 长期记忆 / 智能体工具 / 平台检测能力，
  全部复用纯 Python 的 core 层（与桌面版、命令行版同一份代码）；
- 仅 UI 用 Toga 重写成 Android 原生控件（聊天、思考可视化、设置）；
- 不含任何 PyQt / Playwright 依赖，可在 Android 上直接打包运行。

运行（开发态）：
    briefcase dev
打包（产出 APK）：
    briefcase create android
    briefcase build android
    briefcase package android
"""
