# -*- coding: utf-8 -*-
"""应用层：主控制器与独立流程控制器。

- AssistantApp           装配编排 + 对话流程 + 对话框管理
- ModelController        模型列表 / 本地探测 / 视觉·推理模型切换
- ScreenshotController   截图提问流程
"""

from app.assistant import AssistantApp, make_tray_icon
from app.model_controller import ModelController
from app.screenshot_controller import ScreenshotController

__all__ = ["AssistantApp", "make_tray_icon",
           "ModelController", "ScreenshotController"]
