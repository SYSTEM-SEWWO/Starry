# -*- coding: utf-8 -*-
"""星语 · Starry — 程序入口（桌面 GUI 版）。

职责仅限启动编排（业务逻辑见 app/ 与 core/，界面见 ui/）：
1. 创建 QApplication（常驻托盘，关窗不退出）
2. 液态玻璃开屏动画先行，装配期间并行完成
3. 开屏结束 → AssistantApp.reveal() 首次亮相
4. 进入事件循环

运行：
    python main.py                       # 正常 GUI
    python main.py --version             # 打印版本后退出（不建窗口）
    python main.py --selftest --out r.json   # 无显示器自检，结果落盘

v13.1：GUI EXE 是 console=False 的窗口程序，sys.stdout 可能为 None，
因此自检结果同时**写入 --out 指定的文件**，供 CI / 子进程冒烟核对。
"""
import json
import os
import shutil
import sys
import tempfile
import time


def _fix_qt_plugin_path():
    """v13.6.5：安装路径含中文时，Qt 5 无法加载平台插件。

    现象：启动报错 "no Qt platform plugin could be initialized"。
    处理：仅当插件目录含非 ASCII 字符时，把 platforms 复制到纯 ASCII 的
    临时目录，并显式设置 QT_QPA_PLATFORM_PLUGIN_PATH（首次复制后复用）。
    PyInstaller 打包的 EXE 解压到英文临时目录，本来就不受影响。
    """
    try:
        import PyQt5
        src = os.path.join(os.path.dirname(PyQt5.__file__), "Qt5",
                           "plugins", "platforms")
        if not os.path.isdir(src) or src.isascii():
            return
        dst = os.path.join(tempfile.gettempdir(), "starry_qt_plugins",
                           "platforms")
        os.makedirs(dst, exist_ok=True)
        for name in os.listdir(src):
            if name.lower().endswith(".dll") or name.lower().endswith(".so"):
                to = os.path.join(dst, name)
                if not os.path.exists(to):
                    shutil.copy2(os.path.join(src, name), to)
        os.environ["QT_QPA_PLATFORM_PLUGIN_PATH"] = dst
    except Exception:                       # noqa: BLE001 - 失败不阻断启动
        pass


_fix_qt_plugin_path()

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QApplication, QDialog

from app.assistant import AssistantApp
from ui.splash import SplashWindow
from core.config import APP_VERSION

# ---------------------------------------------------------------------------
# 高分屏 / 系统显示缩放支持（v13.2 修复：此前未启用，导致在高 DPI 显示器上
# 整个窗口尺寸不跟随系统缩放，表现为「窗口缩放失灵」）。
# 必须在首个 QApplication 实例创建之前设置，否则不生效。
# ---------------------------------------------------------------------------
QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)


def _option_value(argv, flag):
    """读取 `--out path` 或 `--out=path`；没有则为空串。"""
    if flag in argv:
        i = argv.index(flag)
        if i + 1 < len(argv):
            return argv[i + 1]
    for item in argv:
        if item.startswith(flag + "="):
            return item.split("=", 1)[1]
    return ""


def _emit(text, path=""):
    """窗口子系统下 stdout 可能不可用；尽力打印，并落盘供自动化核对。"""
    try:
        if sys.stdout is not None:
            sys.stdout.write(text)
            sys.stdout.flush()
    except (AttributeError, OSError, ValueError):
        pass
    if path:
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(text)
        except OSError:
            pass


def _selftest(out_path=""):
    """无显示器自检：版本真源 / core.hub / 随包技能 / 两个桌面对话框。"""
    results = []

    def ck(name, cond):
        results.append((name, bool(cond)))

    ck("版本真源非空", bool(APP_VERSION))
    try:
        from core import hub as hb
        ck("core.hub 可用", hb.HUB_MAGIC == "STARRY-HUB")
        bundled = hb.bundled_skills_dir()
        ck("随包 skills/ 已打进产物", os.path.isdir(bundled))
        ck("随包技能不少于 3 个",
           len(hb.scan_dir(bundled, "github")) >= 3)
    except Exception as exc:                          # noqa: BLE001
        ck("core.hub 可用：%r" % (exc,), False)

    # offscreen 由环境变量 QT_QPA_PLATFORM=offscreen 控制；有显示器时也能跑。
    qt = QApplication.instance() or QApplication(sys.argv[:1])
    try:
        from ui.hub_dialog import offscreen_check
        for name, ok in offscreen_check():
            ck("HubDialog · " + name, ok)
    except Exception as exc:                          # noqa: BLE001
        ck("HubDialog 自检：%r" % (exc,), False)

    try:
        from ui.workbench_dialog import WorkbenchDialog
        wb = WorkbenchDialog()
        ck("WorkbenchDialog 装配成功", wb.tree is not None)
        wb.close()
    except Exception as exc:                          # noqa: BLE001
        ck("WorkbenchDialog 装配成功：%r" % (exc,), False)

    # v13.2 企业级：错误分类 / 脱敏 / 诊断 / 配置隔离 / DeepSeek 来源
    try:
        import tempfile
        from core import apidiag, apierrors, config as cfg_mod, hub as hb
        ck("Hub 来源含 deepseek", "deepseek" in hb.SOURCES)
        ck("Hub 配置归一化可用",
           "deepseek" in hb.hub_config({"sources": ["deepseek"]})["sources"])
        ck("401 归为鉴权类",
           apierrors.status_kind(401) == apierrors.KIND_AUTH)
        ck("脱敏不泄露 API Key",
           "sk-live-ABC123456" not in apierrors.redact(
               "Bearer sk-live-ABC123456"))
        ck("429 可退避重试", apierrors.backoff_seconds(
            apierrors.from_http(429), 2) == 60)
        apidiag.record("selftest", apierrors.from_http(401),
                       scope="selftest")
        ck("API 诊断记录可用", apidiag.summary()["total"] >= 1)
        old = os.environ.get("STARRY_DATA_DIR")
        tmp = tempfile.mkdtemp(prefix="starry_gui_selftest_")
        os.environ["STARRY_DATA_DIR"] = tmp
        ck("STARRY_DATA_DIR 显式隔离生效",
           os.path.normcase(cfg_mod.get_config_dir()) == os.path.normcase(tmp))
        if old is None:
            os.environ.pop("STARRY_DATA_DIR", None)
        else:
            os.environ["STARRY_DATA_DIR"] = old
    except Exception as exc:                          # noqa: BLE001
        ck("企业级错误治理自检：%r" % (exc,), False)

    try:
        from ui.api_diag_dialog import offscreen_check as diag_check
        for name, ok in diag_check():
            ck("ApiDiag · " + name, ok)
    except Exception as exc:                          # noqa: BLE001
        ck("ApiDiagDialog 自检：%r" % (exc,), False)

    payload = {
        "app": "星语Starry-GUI",
        "version": APP_VERSION,
        "passed": sum(1 for _, ok in results if ok),
        "total": len(results),
        "checks": [{"name": n, "ok": ok} for n, ok in results],
    }
    _emit(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", out_path)
    return 0 if payload["passed"] == payload["total"] else 1


def _headless_cli(argv):
    """处理不建窗口的参数；返回 None 表示交给正常 GUI 流程。"""
    if "--version" in argv:
        _emit("星语 Starry %s（桌面版 GUI）\n" % APP_VERSION,
              _option_value(argv, "--out"))
        return 0
    if "--selftest" in argv:
        return _selftest(_option_value(argv, "--out"))
    return None


def main():
    rc = _headless_cli(sys.argv[1:])
    if rc is not None:
        sys.exit(rc)

    _t_start = time.perf_counter()
    qt = QApplication(sys.argv)
    qt.setQuitOnLastWindowClosed(False)
    _t_qt = time.perf_counter()

    # 0) 企业商用合规：首次运行须同意 EULA（不同意则退出）
    #    v7.5：除布尔位外，还要求「防篡改令牌」匹配，直编 config 无法绕过
    from core.config import AppConfig, APP_VERSION
    from ui.eula_dialog import EulaDialog, eula_accept_token
    cfg = AppConfig.load()
    # v13.5：初始化分级日志（默认关闭；STARRY_DEBUG / 配置开启后才输出）
    from core import devlog
    devlog.configure(cfg=cfg)
    devlog.info("startup", "应用启动", version=APP_VERSION,
                platform=sys.platform)
    eula_ok = (bool(cfg.data.get("accepted_eula"))
               and cfg.data.get("eula_accept_token") == eula_accept_token())
    if not eula_ok:
        eula = EulaDialog(cfg)
        eula.show()
        if eula.exec_() != QDialog.Accepted:
            # 拒绝许可：绝不进入，并退出进程
            qt.quit()
            sys.exit(0)

    # 1) 液态玻璃开屏动画先行（品牌色跟随已配置的主题）
    theme = cfg.appearance.get("theme", "light")
    splash = SplashWindow(theme=theme)
    splash.show()
    splash.start()

    holder = {"app": None}

    def reveal():
        app = holder["app"]
        if app is not None:
            if os.environ.get("STARRY_PERF"):
                try:
                    from core.config import APP_VERSION
                except Exception:             # noqa: BLE001
                    APP_VERSION = "?"
                print("[starry-perf] 首屏亮相（自启动累计）%.1f ms (v%s)"
                      % ((time.perf_counter() - _t_start) * 1000, APP_VERSION),
                      file=sys.stderr)
            devlog.info("startup", "首屏亮相",
                        ms=round((time.perf_counter() - _t_start) * 1000, 1))
            splash.close()
            app.reveal()

    splash.finished.connect(reveal)

    def boot():
        # 2) 动画播放期间完成应用装配（通常远快于动画时长）
        #    v13.2 启动性能埋点：仅 STARRY_PERF=1 时打印，不打扰正式用户。
        _t0 = time.perf_counter()
        holder["app"] = AssistantApp()
        _dt = time.perf_counter() - _t0
        devlog.info("startup", "AssistantApp 同步装配完成",
                    ms=round(_dt * 1000, 1))
        if os.environ.get("STARRY_PERF"):
            try:
                from core.config import APP_VERSION
            except Exception:                 # noqa: BLE001
                APP_VERSION = "?"
            print("[starry-perf] QApplication+配置加载 %.1f ms"
                  % ((_t_qt - _t_start) * 1000), file=sys.stderr)
            print("[starry-perf] AssistantApp 同步装配 %.1f ms (v%s)"
                  % (_dt * 1000, APP_VERSION), file=sys.stderr)
        if splash._finished_emitted or not splash.isVisible():
            reveal()          # 被点击跳过时开屏已结束

    from PyQt5.QtCore import QTimer
    QTimer.singleShot(80, boot)
    sys.exit(qt.exec_())


if __name__ == "__main__":
    main()
