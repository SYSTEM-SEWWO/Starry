# -*- coding: utf-8 -*-
"""真实鼠标 / 键盘操作助手（配合 e2e_session.py 做 GUI 测评）。

    python scripts/e2e_mouse.py --out DIR --action windows
    python scripts/e2e_mouse.py --out DIR --action shot --name 01_startup
    python scripts/e2e_mouse.py --out DIR --action click --x 900 --y 500 --name 02_click
    python scripts/e2e_mouse.py --out DIR --action dclick --x .. --y ..
    python scripts/e2e_mouse.py --out DIR --action key --keys ctrl+k --name 03_palette
    python scripts/e2e_mouse.py --out DIR --action type --text "hello" --name 04_typed

所有操作都是**真实系统级输入**（user32 SendInput / pyautogui），不调用应用内部 API，
因此能测到真实用户才会遇到的遮挡、焦点、坐标与焦点丢失问题。
"""
import argparse
import ctypes
import json
import os
import time
from ctypes import wintypes

import pyautogui

pyautogui.FAILSAFE = True
pyautogui.PAUSE = 0.25

user32 = ctypes.WinDLL("user32", use_last_error=True)
EnumWindowsProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND,
                                     wintypes.LPARAM)


def list_windows():
    out = []

    def cb(hwnd, _):
        if not user32.IsWindowVisible(hwnd):
            return True
        n = user32.GetWindowTextLengthW(hwnd)
        buf = ctypes.create_unicode_buffer(n + 1)
        user32.GetWindowTextW(hwnd, buf, n + 1)
        rect = wintypes.RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(rect))
        if rect.right <= rect.left or rect.bottom <= rect.top:
            return True                       # 跳过零尺寸窗口
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        # PyQt 的 frameless 悬浮球没有标题，必须连无标题窗口一起枚举，
        # 否则真实 GUI 测评会「找不到应用窗口」。
        out.append({"hwnd": int(hwnd), "title": buf.value, "pid": pid.value,
                    "rect": [rect.left, rect.top, rect.right, rect.bottom]})
        return True

    user32.EnumWindows(EnumWindowsProc(cb), 0)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--action", required=True,
                    choices=("windows", "shot", "click", "dclick",
                             "key", "type", "wait-window", "focus"))
    ap.add_argument("--hwnd", type=int, default=0)
    ap.add_argument("--name", default="")
    ap.add_argument("--x", type=int, default=0)
    ap.add_argument("--y", type=int, default=0)
    ap.add_argument("--keys", default="")
    ap.add_argument("--text", default="")
    ap.add_argument("--title-contains", default="")
    ap.add_argument("--timeout", type=float, default=20.0)
    args = ap.parse_args()
    out = os.path.abspath(args.out)
    os.makedirs(out, exist_ok=True)
    result = {"action": args.action, "ts": time.time()}
    # 指针停在屏幕四角时 pyautogui 的 fail-safe 会在 moveTo 前抛异常；
    # 先用底层 API 把指针移到中心，保留 fail-safe 本身不关闭。
    sw, sh = pyautogui.size()
    user32.SetCursorPos(sw // 2, sh // 2)

    if args.action == "wait-window":
        deadline = time.time() + args.timeout
        found = []
        while time.time() < deadline:
            found = [w for w in list_windows()
                     if args.title_contains.lower() in w["title"].lower()]
            if found:
                break
            time.sleep(0.5)
        result["found"] = found
        result["ok"] = bool(found)
    elif args.action == "windows":
        result["windows"] = list_windows()
    elif args.action == "focus":
        hwnd = args.hwnd
        if not hwnd and args.title_contains:
            hwnd = next((w["hwnd"] for w in list_windows()
                         if args.title_contains.lower() in w["title"].lower()), 0)
        if hwnd:
            user32.ShowWindow(hwnd, 9)               # SW_RESTORE
            user32.SetForegroundWindow(hwnd)
        result["focused"] = hwnd
    elif args.action == "click":
        pyautogui.click(args.x, args.y)
        result["clicked"] = [args.x, args.y]
    elif args.action == "dclick":
        pyautogui.doubleClick(args.x, args.y)
        result["clicked"] = [args.x, args.y]
    elif args.action == "key":
        pyautogui.hotkey(*[k.strip() for k in args.keys.split("+") if k.strip()])
        result["keys"] = args.keys
    elif args.action == "type":
        pyautogui.write(args.text, interval=0.01)
        result["typed_len"] = len(args.text)

    if args.action in ("click", "dclick", "key", "type"):
        time.sleep(1.2)                     # 等界面响应后再截图
    if args.name:
        path = os.path.join(out, args.name + ".png")
        pyautogui.screenshot().save(path)
        result["screenshot"] = path
    result["windows_after"] = list_windows()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("ok", True) else 1


if __name__ == "__main__":
    raise SystemExit(main())
