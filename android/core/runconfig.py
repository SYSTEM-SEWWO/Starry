# -*- coding: utf-8 -*-
"""本地模型运行参数与局域网访问（LocModel「RUN」公开规格复刻）。

来源：https://locmodel.com/#run
  - 8K / 16K / 32K / 64K 上下文一键切换
  - 思考模式（让模型先想再答）
  - 局域网访问：手机和其他电脑也能调用
  - 预计速度 / tok/s 可见

说明：llama-server 的 OpenAI 兼容服务默认只监听 127.0.0.1；
开启局域网访问时改为 0.0.0.0 并给出本机可访问地址。
思考模式通过请求侧 system 提示实现（不依赖特定 llama.cpp 版本参数），
避免传入未公开验证的命令行开关。
"""
import socket

from core import hwprobe, local_llm

CONTEXT_OPTIONS = [8192, 16384, 32768, 65536]
CONTEXT_LABELS = {8192: "8K", 16384: "16K", 32768: "32K", 65536: "64K"}

THINK_PROMPT = (
    "请先进行逐步思考（思考过程写在 <thinking>...</thinking> 中），"
    "再给出最终答案。"
)


def normalize_ctx(value):
    """把任意输入归一到支持的上下文档位。"""
    try:
        n = int(value)
    except (TypeError, ValueError):
        return 8192
    if n in CONTEXT_OPTIONS:
        return n
    return min(CONTEXT_OPTIONS, key=lambda x: abs(x - n))


def local_ips():
    """列出本机内网 IPv4（用于局域网访问提示）。"""
    ips = []
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None,
                                       socket.AF_INET):
            ip = info[4][0]
            if ip not in ips and not ip.startswith("127."):
                ips.append(ip)
    except Exception:
        pass
    # UDP Connect 法（不真正发包），补充虚拟网卡之外的主网卡
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("223.5.5.5", 80))
        ip = s.getsockname()[0]
        if ip not in ips and not ip.startswith("127."):
            ips.insert(0, ip)
        s.close()
    except Exception:
        pass
    return ips


def lan_urls(port=local_llm.DEFAULT_PORT):
    return ["http://%s:%d/v1" % (ip, port) for ip in local_ips()]


def build_command(model_path, ctx=8192, port=local_llm.DEFAULT_PORT,
                  lan=False, extra=None):
    """构造 llama-server 命令（host 由 lan 决定）。"""
    exe = local_llm.find_llama_server()
    if not exe:
        return None
    ctx = normalize_ctx(ctx)
    cmd = [exe, "-m", model_path, "--port", str(port),
           "-c", str(ctx), "--host", "0.0.0.0" if lan else "127.0.0.1"]
    if extra:
        cmd.extend([str(x) for x in extra])
    return cmd


def start(model_path, ctx=8192, port=local_llm.DEFAULT_PORT, lan=False):
    """启动本地服务（复用 local_llm 的进程管理与健康检查）。"""
    return local_llm.start_server(model_path, port=port, ctx=normalize_ctx(ctx),
                                  host="0.0.0.0" if lan else "127.0.0.1")


def running(port=local_llm.DEFAULT_PORT):
    return local_llm.is_running(port=port)


def server_status(port=local_llm.DEFAULT_PORT):
    """运行状态：是否在线、上下文、地址、估算速度。"""
    models = []
    try:
        import requests
        r = requests.get("http://127.0.0.1:%d/v1/models" % port, timeout=2)
        if r.status_code == 200:
            models = [m.get("id") for m in
                      (r.json().get("data") or []) if isinstance(m, dict)]
    except Exception:
        pass
    return {"online": bool(models), "port": port, "models": models,
            "local_url": local_llm.base_url(port),
            "lan_urls": lan_urls(port)}


def speed_hint(hw=None, params_b=7.0, size_gb=4.7):
    """预计速度（估算值，UI 必须标注）。"""
    hw = hw or hwprobe.probe()
    tps = hwprobe.estimate_speed(params_b, hw.get("vram_gb") or 0,
                                 (hw.get("backends") or ["CPU"])[0], size_gb)
    return "约 %s tok/s（估算，非实测）" % tps


def format_status(port=local_llm.DEFAULT_PORT):
    s = server_status(port)
    if not s["online"]:
        return "本地服务未启动"
    lines = ["本地服务运行中 · 端口 %d" % port,
             "已加载：%s" % ", ".join(s["models"]),
             "本机：%s" % s["local_url"]]
    if s["lan_urls"]:
        lines.append("局域网：" + " / ".join(s["lan_urls"]))
    return "\n".join(lines)
