# -*- coding: utf-8 -*-
"""本地 GGUF 推理运行时管理（llama.cpp server）。

模型从阿里魔塔下载到本地 models/ 目录后，通过 llama-server
（llama.cpp 的 OpenAI 兼容服务）加载，助手以「魔塔本地模型」服务商接入。

- models_dir       本地模型目录（配置目录下 models/）
- find_llama_server  在 PATH / 常见位置 / 配置目录 bin/ 中查找 llama-server
- list_local_gguf  扫描已下载的 .gguf（跳过 .part 半成品）
- start_server     后台启动 llama-server（OpenAI 兼容 :8080/v1）
- stop_server      结束进程
- is_running       健康检查（/v1/models 是否响应）
"""
import glob
import os
import shutil
import subprocess
import time

import requests

from core.config import get_config_dir

DEFAULT_PORT = 8080
DEFAULT_CTX = 8192

# llama.cpp 官方预编译包（GitHub Release，按平台选择）
LLAMA_CPP_RELEASES = {
    "win": ("llama-bXXXX-bin-win-cpu-x64.zip",
            "https://github.com/ggml-org/llama.cpp/releases/latest"),
    "mac": ("llama-bXXXX-bin-macos-arm64.zip",
            "https://github.com/ggml-org/llama.cpp/releases/latest"),
    "linux": ("llama-bXXXX-bin-ubuntu-x64.zip",
              "https://github.com/ggml-org/llama.cpp/releases/latest"),
}


def models_dir():
    """本地 GGUF 模型目录（自动创建）"""
    path = os.path.join(get_config_dir(), "models")
    os.makedirs(path, exist_ok=True)
    return path


def bin_dir():
    """本地第三方可执行文件目录（配置目录下 bin/）"""
    path = os.path.join(get_config_dir(), "bin")
    os.makedirs(path, exist_ok=True)
    return path


def _platform_key():
    import sys
    if sys.platform.startswith("win"):
        return "win"
    if sys.platform == "darwin":
        return "mac"
    return "linux"


def _exe_names():
    return ["llama-server", "llama-server.exe"]


def find_llama_server():
    """查找 llama-server 可执行文件，找不到返回 None"""
    names = _exe_names()
    # 1) PATH
    for n in names:
        found = shutil.which(n)
        if found:
            return found
    # 2) 配置目录 bin/
    for n in names:
        cand = os.path.join(bin_dir(), n)
        if os.path.exists(cand):
            return cand
    # 3) 常见安装位置
    home = os.path.expanduser("~")
    for base in (os.path.join(home, "llama.cpp"), "/opt/llama.cpp",
                 "/usr/local/llama.cpp", os.path.join(home, ".local/bin")):
        for n in names:
            for sub in ("", "build/bin", "bin"):
                cand = os.path.join(base, sub, n) if sub else os.path.join(base, n)
                if os.path.exists(cand):
                    return cand
    return None


def list_local_gguf():
    """扫描 models/ 目录的 .gguf 文件 [{name, path, size}]（按名称排序）"""
    out = []
    for path in sorted(glob.glob(os.path.join(models_dir(), "**", "*.gguf"),
                                 recursive=True)):
        try:
            size = os.path.getsize(path)
        except OSError:
            continue
        out.append({"name": os.path.basename(path), "path": path,
                    "size": size})
    return out


def delete_gguf(path):
    """删除模型文件（返回是否成功）"""
    try:
        if os.path.commonpath([os.path.abspath(path),
                               os.path.abspath(models_dir())]) \
                != os.path.abspath(models_dir()):
            return False           # 只允许删除模型目录内文件
        os.remove(path)
        return True
    except Exception:
        return False


def server_command(model_path, port=DEFAULT_PORT, ctx=DEFAULT_CTX):
    """构造 llama-server 启动命令"""
    exe = find_llama_server()
    if not exe:
        return None
    return [exe, "-m", model_path, "--port", str(port),
            "-c", str(ctx), "--host", "127.0.0.1"]


class ServerHandle:
    """本地服务进程句柄（start_server 返回）"""

    def __init__(self, proc, model_path, port):
        self.proc = proc
        self.model_path = model_path
        self.port = port

    def stop(self):
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=5)
            except Exception:
                self.proc.kill()

    def is_alive(self):
        return bool(self.proc and self.proc.poll() is None)


def is_running(port=DEFAULT_PORT, timeout=3):
    """本地 llama-server 是否在运行"""
    try:
        r = requests.get("http://127.0.0.1:%d/v1/models" % port, timeout=timeout)
        return r.status_code == 200
    except Exception:
        return False


def start_server(model_path, port=DEFAULT_PORT, ctx=DEFAULT_CTX):
    """后台启动 llama-server 并等待就绪（最多 30 秒）"""
    if is_running(port):
        raise RuntimeError("端口 %d 已被占用（可能服务已在运行）" % port)
    cmd = server_command(model_path, port, ctx)
    if not cmd:
        raise RuntimeError("未找到 llama-server，请先安装 llama.cpp")
    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL)
    handle = ServerHandle(proc, model_path, port)
    deadline = time.time() + 30
    while time.time() < deadline:
        if proc.poll() is not None:
            raise RuntimeError("llama-server 启动失败（退出码 %s）" % proc.returncode)
        if is_running(port, timeout=1):
            return handle
        time.sleep(0.5)
    handle.stop()
    raise RuntimeError("等待 llama-server 就绪超时（模型过大或内存不足）")


def base_url(port=DEFAULT_PORT):
    return "http://127.0.0.1:%d/v1" % port
