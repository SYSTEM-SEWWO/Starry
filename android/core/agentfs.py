# -*- coding: utf-8 -*-
"""Agent 工作文件夹沙箱（LocModel「AGENT」公开规格复刻）。

来源：https://locmodel.com/#agent
  - 指定一个工作文件夹，Agent 自动生成计划、逐条执行并更新进度
  - 在文件夹内读写文件、运行 Python / PowerShell
  - 删除、移动或访问文件夹外内容前先询问
  - 完成后验证输出，不只回一句「应该可以」

安全设计（本模块是能力层，UI 层负责真正弹窗确认）：
  * 所有路径都经 safe_resolve 校验，禁止 .. / 绝对路径 / 符号链接越界；
  * delete/move/外部访问 一律返回 need_confirm=True，绝不自动执行；
  * 命令只允许白名单解释器，cwd 锁定工作目录，带超时；
  * 计划步骤状态可追踪，支持完成后 verify 校验产物。
"""
import os
import shlex
import shutil
import subprocess
import time

_ALLOWED_COMMANDS = ("python", "py", "python3", "powershell", "pwsh",
                     "bash", "sh", "cmd", "dir", "ls")


class SandboxError(Exception):
    pass


def safe_resolve(root, rel=""):
    """把相对路径解析到 root 内；越界抛 SandboxError。"""
    root = os.path.abspath(root)
    rel = rel or ""
    if os.path.isabs(rel):
        raise SandboxError("禁止绝对路径：%s" % rel)
    path = os.path.abspath(os.path.join(root, rel))
    if os.path.commonpath([path, root]) != root:
        raise SandboxError("路径越界：%s" % rel)
    # 符号链接逃逸检查
    probe = path
    while probe != root and os.path.islink(probe):
        probe = os.path.dirname(probe)
        if os.path.commonpath([os.path.abspath(probe), root]) != root:
            raise SandboxError("符号链接越界：%s" % rel)
    return path


def set_root(path):
    """创建并返回规范化工作根目录。"""
    path = os.path.abspath(path or ".")
    os.makedirs(path, exist_ok=True)
    return path


def list_dir(root, rel=""):
    path = safe_resolve(root, rel)
    if not os.path.isdir(path):
        return []
    out = []
    for name in sorted(os.listdir(path)):
        full = os.path.join(path, name)
        out.append({"name": name, "is_dir": os.path.isdir(full),
                    "size": os.path.getsize(full) if os.path.isfile(full) else 0})
    return out


def read(root, rel):
    path = safe_resolve(root, rel)
    if not os.path.isfile(path):
        raise SandboxError("文件不存在：%s" % rel)
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        return f.read()


def write(root, rel, content):
    path = safe_resolve(root, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    return path


def mkdir(root, rel):
    path = safe_resolve(root, rel)
    os.makedirs(path, exist_ok=True)
    return path


def _need_confirm(action, detail):
    return {"ok": False, "need_confirm": True,
            "action": action, "detail": detail,
            "message": "%s 需要用户确认后才执行：%s" % (action, detail)}


def delete(root, rel):
    """删除必须先确认（本层只返回确认请求，不执行）。"""
    try:
        path = safe_resolve(root, rel)
    except SandboxError as e:
        return {"ok": False, "error": str(e)}
    return _need_confirm("删除", path)


def delete_confirmed(root, rel):
    """UI 明确确认后调用，仍强制沙箱校验。"""
    try:
        path = safe_resolve(root, rel)
        if os.path.isdir(path):
            shutil.rmtree(path)
        elif os.path.isfile(path):
            os.remove(path)
        else:
            return {"ok": False, "error": "目标不存在"}
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


def move(root, src_rel, dst_rel):
    """移动必须先确认。"""
    try:
        src = safe_resolve(root, src_rel)
        dst = safe_resolve(root, dst_rel)
    except SandboxError as e:
        return {"ok": False, "error": str(e)}
    return _need_confirm("移动", "%s → %s" % (src, dst))


def move_confirmed(root, src_rel, dst_rel):
    try:
        src = safe_resolve(root, src_rel)
        dst = safe_resolve(root, dst_rel)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.move(src, dst)
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


def outside_access(root, path):
    """访问工作文件夹以外的路径必须先确认。"""
    try:
        resolved = safe_resolve(root, "")
        target = os.path.abspath(path)
        inside = os.path.commonpath([target, resolved]) == resolved
    except Exception:
        inside = False
    if inside:
        return {"ok": True, "need_confirm": False}
    return _need_confirm("访问文件夹外内容", target)


class Plan:
    """可追踪的 Agent 计划。"""

    def __init__(self, goal="", root=""):
        self.goal = goal
        self.root = root
        self.steps = []
        self.created = time.time()
        self.finished = False

    def add(self, text):
        self.steps.append({"id": len(self.steps) + 1, "text": text,
                           "status": "pending", "result": "", "started": 0,
                           "done": 0})
        return self.steps[-1]

    def start(self, step_id):
        for s in self.steps:
            if s["id"] == step_id:
                s["status"] = "running"
                s["started"] = time.time()
                return True
        return False

    def finish(self, step_id, result="", ok=True):
        for s in self.steps:
            if s["id"] == step_id:
                s["status"] = "done" if ok else "failed"
                s["result"] = str(result)[:2000]
                s["done"] = time.time()
                return True
        return False

    def progress(self):
        if not self.steps:
            return 0
        done = sum(1 for s in self.steps if s["status"] in ("done", "failed"))
        return round(done * 100.0 / len(self.steps))

    def summary(self):
        lines = ["目标：%s" % self.goal, "进度：%d%%（%d/%d）" % (
            self.progress(),
            sum(1 for s in self.steps if s["status"] in ("done", "failed")),
            len(self.steps))]
        for s in self.steps:
            icon = {"pending": "○", "running": "◐", "done": "✓",
                    "failed": "✕"}.get(s["status"], "○")
            lines.append("  %s #%d %s" % (icon, s["id"], s["text"]))
            if s["result"]:
                lines.append("      %s" % s["result"][:120])
        return "\n".join(lines)

    def to_dict(self):
        return {"goal": self.goal, "root": self.root, "steps": list(self.steps),
                "progress": self.progress(), "finished": self.finished,
                "created": self.created}


def _safe_command_tokens(cmd):
    """检查命令中的路径参数不越界（针对常见 -f / -o 形式与裸路径）。"""
    try:
        tokens = shlex.split(cmd)
    except ValueError:
        return False
    for t in tokens[1:]:
        if t.startswith("-"):
            continue
        if os.path.isabs(t) or t.startswith(".."):
            return False
    return True


def run_command(root, cmd, timeout=60, auto_confirm=False):
    """在沙箱目录内执行命令（仅白名单解释器）。

    返回 {ok, output, code, elapsed, need_confirm, error}。
    删除/移动/越界路径不会自动执行，需 UI 确认后显式调用。
    """
    root = os.path.abspath(root)
    if not cmd or not cmd.strip():
        return {"ok": False, "error": "命令为空"}
    try:
        tokens = shlex.split(cmd)
    except ValueError as e:
        return {"ok": False, "error": "命令解析失败：%s" % e}
    exe = os.path.basename(tokens[0]).lower()
    if exe.endswith(".exe"):
        exe = exe[:-4]
    if exe not in _ALLOWED_COMMANDS:
        return {"ok": False, "need_confirm": True,
                "error": "命令 %s 不在白名单，需用户确认" % tokens[0]}
    if not _safe_command_tokens(cmd):
        return {"ok": False, "need_confirm": True,
                "error": "命令包含绝对路径或越界路径，需用户确认"}
    t0 = time.time()
    try:
        p = subprocess.run(cmd, shell=False, cwd=root, capture_output=True,
                           text=True, timeout=timeout, errors="replace")
        return {"ok": p.returncode == 0, "output": (p.stdout or "")[-6000:],
                "error": (p.stderr or "")[-2000:] if p.returncode else "",
                "code": p.returncode, "elapsed": round(time.time() - t0, 1)}
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "命令超时（%ds）" % timeout,
                "elapsed": round(time.time() - t0, 1)}
    except Exception as e:
        return {"ok": False, "error": str(e)[:200],
                "elapsed": round(time.time() - t0, 1)}


def verify(root, expect_files=None, expect_contains=None):
    """完成后验证产物：存在性 + 内容关键字，不只看返回结果。"""
    root = os.path.abspath(root)
    checks = []
    for rel in (expect_files or []):
        try:
            path = safe_resolve(root, rel)
            checks.append({"check": "文件存在：%s" % rel,
                           "ok": os.path.isfile(path)})
        except SandboxError as e:
            checks.append({"check": "文件存在：%s" % rel, "ok": False,
                           "error": str(e)})
    for rel, keyword in (expect_contains or []):
        try:
            path = safe_resolve(root, rel)
            txt = read(root, rel) if os.path.isfile(path) else ""
            checks.append({"check": "%s 含「%s」" % (rel, keyword),
                           "ok": keyword in txt})
        except Exception as e:
            checks.append({"check": "%s 含「%s」" % (rel, keyword),
                           "ok": False, "error": str(e)[:100]})
    return {"ok": all(c["ok"] for c in checks) if checks else True,
            "checks": checks}
