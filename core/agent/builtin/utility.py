# -*- coding: utf-8 -*-
"""实用工具包：计算器 / 当前时间 / 随机选择 / 文本统计"""
import ast
import datetime
import operator
import random

from core.agent.tools import tool

_BIN_OPS = {
    ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
    ast.Div: operator.truediv, ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod, ast.Pow: operator.pow,
}
_UNARY_OPS = {ast.USub: operator.neg, ast.UAdd: operator.pos}


def _safe_eval(node):
    if isinstance(node, ast.Expression):
        return _safe_eval(node.body)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _BIN_OPS:
        return _BIN_OPS[type(node.op)](_safe_eval(node.left),
                                       _safe_eval(node.right))
    if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY_OPS:
        return _UNARY_OPS[type(node.op)](_safe_eval(node.operand))
    raise ValueError("仅支持四则运算与幂运算")


@tool("calculator", "数学计算器：计算一个算术表达式（支持 + - * / // % ** 与括号）",
      {"type": "object",
       "properties": {"expression": {"type": "string",
                                     "description": "算术表达式，如 (3+5)*2"}},
       "required": ["expression"]})
def calculator(expression):
    try:
        tree = ast.parse(str(expression), mode="eval")
        value = _safe_eval(tree)
    except Exception as e:  # noqa: BLE001
        return "计算失败：%s" % e
    if isinstance(value, float) and value == int(value):
        value = int(value)
    return str(value)


@tool("get_current_time", "获取当前日期时间（含星期）", {"type": "object", "properties": {}})
def get_current_time():
    now = datetime.datetime.now()
    week = "一二三四五六日"[now.weekday()]
    return now.strftime("%Y-%m-%d %H:%M:%S") + " 星期" + week


@tool("random_pick", "从给定选项中随机选择一个",
      {"type": "object",
       "properties": {"options": {"type": "array",
                                  "items": {"type": "string"},
                                  "description": "可选项列表"}},
       "required": ["options"]})
def random_pick(options):
    opts = [str(o) for o in (options or [])]
    if not opts:
        return "错误：选项列表为空"
    return random.choice(opts)


@tool("text_stats", "统计文本的字数、行数与字符数",
      {"type": "object",
       "properties": {"text": {"type": "string", "description": "待统计文本"}},
       "required": ["text"]})
def text_stats(text):
    t = str(text or "")
    lines = t.count("\n") + 1
    chars = len(t)
    no_space = len(re.sub(r"\s", "", t))
    return "字符数：%d（不含空白 %d）｜行数：%d" % (chars, no_space, lines)


import re  # noqa: E402  （text_stats 使用）
