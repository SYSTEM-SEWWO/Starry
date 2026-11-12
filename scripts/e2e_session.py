# -*- coding: utf-8 -*-
"""星语 Starry · 真实 GUI 测评会话（v13.2 新增，可复跑 / 不碰用户真实数据）。

启动一个**本地 mock 服务**返回 HTTP 401，再用隔离的 STARRY_DATA_DIR 启动真实
GUI 主程序，供外部用 pyautogui 做真实鼠标操作与截图测评。

设计约束（企业级测评要求）：
  * 不读取、不复制、不向外部发送用户真实 API Key；隔离配置里只用假 Key；
  * 所有网络请求都指向 127.0.0.1，绝不产生外部流量；
  * 请求日志只记录方法 / 路径 / 是否携带 Authorization / 响应码，**不记录 Key 值**；
  * 会话信息写入 session.json，供其它脚本按阶段点击与截图。

用法：
    python scripts/e2e_session.py --out C:/path/to/e2e_out
    # 另开终端用 pyautogui 点击 / 截图；结束时终止本进程即可
"""
import argparse
import json
import os
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

REQUESTS = []
REQUESTS_LOCK = threading.Lock()


class Mock401Handler(BaseHTTPRequestHandler):
    """模拟「Key 已填但失效」的上游：/models 与 /chat/completions 一律 401。"""

    def _handle(self):
        length = int(self.headers.get("Content-Length") or 0)
        if length:
            self.rfile.read(length)          # 丢弃请求体，不落盘、不打印
        with REQUESTS_LOCK:
            REQUESTS.append({
                "method": self.command,
                "path": self.path,
                "has_auth": bool(self.headers.get("Authorization")),
                "status": 401,
                "ts": round(time.time(), 3),
            })
        body = json.dumps({
            "error": {
                "message": "Invalid API key provided (E2E mock)",
                "type": "invalid_request_error",
                "code": "invalid_api_key",
            }
        }, ensure_ascii=False).encode("utf-8")
        self.send_response(401)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    do_GET = _handle
    do_POST = _handle

    def log_message(self, *args):            # 静默，避免把请求写进控制台
        pass


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True, help="测评输出目录（截图 / 日志 / 隔离配置）")
    ap.add_argument("--port", type=int, default=8765)
    args = ap.parse_args()
    out = os.path.abspath(args.out)
    os.makedirs(out, exist_ok=True)
    profile = os.path.join(out, "profile")
    os.makedirs(profile, exist_ok=True)

    # 隔离配置：模拟「真实用户已填过 Key，但 Key 已失效 / 与 Base URL 不匹配」
    cfg_path = os.path.join(profile, "config.json")
    cfg = {
        "provider": "zhipu",
        "base_urls": {"zhipu": "http://127.0.0.1:%d/v1" % args.port},
        "api_keys": {"zhipu": "E2E-INVALID-KEY-DO-NOT-USE"},
        "auto_refresh_models": True,
        "models": {"zhipu": "glm-4-flash"},
        "accepted_eula": True,
        # 关闭与本次测评无关的自动行为，保证截图稳定
        "deep_thinking": False,
        "stream": True,
    }
    # EULA 令牌必须与实现一致，否则首启会弹授权框（另设 --with-eula 场景再测）
    sys.path.insert(0, ROOT)
    from ui.eula_dialog import eula_accept_token
    cfg["eula_accept_token"] = eula_accept_token()
    with open(cfg_path, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)

    server = ThreadingHTTPServer(("127.0.0.1", args.port), Mock401Handler)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()

    env = dict(os.environ)
    # 双保险：STARRY_DATA_DIR 是产品级显式覆盖；APPDATA 兜底，
    # 即使覆盖逻辑失效也绝不会读写用户真实配置目录。
    env["STARRY_DATA_DIR"] = profile
    env["APPDATA"] = profile
    env.pop("QT_QPA_PLATFORM", None)       # 使用真实桌面
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"

    # 隔离硬门禁：启动 GUI 前用同一套环境变量验证「配置目录 + Base URL」确实
    # 指向隔离环境。不通过就拒绝启动，避免拿用户真实 Key 打外部 API。
    probe_code = (
        "import os,sys,json;sys.path.insert(0,r'%s');"
        "from core.config import get_config_dir,AppConfig;"
        "c=AppConfig.load();"
        "print(json.dumps({'dir':get_config_dir(),'base':c.base_url(),"
        "'has_key':bool(c.api_key())}))" % ROOT)
    probe = subprocess.run([sys.executable, "-c", probe_code], cwd=ROOT,
                           env=env, capture_output=True, text=True,
                           encoding="utf-8", errors="replace")
    try:
        state = json.loads((probe.stdout or "").strip().splitlines()[-1])
    except (ValueError, IndexError):
        state = {}
    expect_base = "http://127.0.0.1:%d/v1" % args.port
    if (os.path.normcase(state.get("dir", "")) != os.path.normcase(profile)
            or state.get("base") != expect_base):
        print("隔离门禁失败，拒绝启动 GUI（避免触碰用户真实配置）：",
              state, "expect_dir=", profile, "expect_base=", expect_base,
              flush=True)
        server.shutdown()
        return 2
    print("隔离门禁通过：", state, flush=True)

    log = open(os.path.join(out, "gui_stdout.log"), "w", encoding="utf-8")
    proc = subprocess.Popen([sys.executable, "main.py"], cwd=ROOT,
                            env=env, stdout=log, stderr=subprocess.STDOUT)

    session = {
        "pid": proc.pid,
        "port": args.port,
        "out": out,
        "profile": profile,
        "config": cfg_path,
        "mock_requests": os.path.join(out, "mock_requests.json"),
        "started_at": time.time(),
    }
    with open(os.path.join(out, "session.json"), "w", encoding="utf-8") as f:
        json.dump(session, f, ensure_ascii=False, indent=2)
    print(json.dumps(session, ensure_ascii=False, indent=2), flush=True)

    try:
        while proc.poll() is None:
            with REQUESTS_LOCK:
                snapshot = list(REQUESTS)
            with open(session["mock_requests"], "w", encoding="utf-8") as f:
                json.dump(snapshot, f, ensure_ascii=False, indent=2)
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        with REQUESTS_LOCK:
            snapshot = list(REQUESTS)
        with open(session["mock_requests"], "w", encoding="utf-8") as f:
            json.dump(snapshot, f, ensure_ascii=False, indent=2)
        if proc.poll() is None:
            proc.terminate()
        server.shutdown()
        log.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
