# -*- coding: utf-8 -*-
"""本地 JSON 存储的原子读写（会话 / 统计 / 资料库 / 自动化 共用）。

v7.2 轻量重构：原先 4 个存储类各写一遍同样的 save（临时文件 + os.replace），
这里统一为两个纯函数，行为不变但只有一份实现。
"""
import json
import os


def save_json(path, data):
    """原子写入 JSON：写临时文件 → os.replace。

    返回 bool；失败一律静默——存储失败绝不该打断主对话流程。
    """
    try:
        d = os.path.dirname(path)
        if d:
            os.makedirs(d, exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        os.replace(tmp, path)
        return True
    except Exception:                                 # noqa: BLE001
        return False


def load_json(path, default=None):
    """读取 JSON；文件不存在或损坏时返回 default（深拷贝一份，避免共享）"""
    try:
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                return json.load(f)
    except Exception:                                 # noqa: BLE001
        pass
    if isinstance(default, dict):
        return dict(default)
    if isinstance(default, list):
        return list(default)
    return default
