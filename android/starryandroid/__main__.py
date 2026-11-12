# -*- coding: utf-8 -*-
"""Android 启动入口（``python -m starryandroid`` / Briefcase 打包入口）。

v12.0 改动：
  - 安装全局 ``sys.excepthook``：任何未捕获异常都写 logcat **并落盘**到应用
    私有目录的 crash.log，用户可在 App 内「诊断」页或文件管理器里取到；
    v11.5 只在构造/主循环两处 try，且失败后 ``sys.exit(1)`` —— 在 Android
    上这就是用户看到的「闪退，且什么线索都没有」。
  - 启动前做一次 Toga 版本自检：v11.5 的 APK 实测混装了 toga 0.2.15 元包与
    toga_core 0.5.7 内核；这里主动把版本信息打到日志，构建链问题一眼可见。
  - 仍使用 Toga 0.5.7 的正确写法 ``app.main_loop()``（阻塞运行，不返回 .run()）。
"""
import os
import sys
import time
import traceback


def _log(tag, text):
    try:
        from android.util import Log
        Log.e(tag, text)
    except Exception:                                    # noqa: BLE001
        try:
            sys.stderr.write("[%s] %s\n" % (tag, text))
        except Exception:                                # noqa: BLE001
            pass


def _crash_path():
    """崩溃日志落在应用私有目录；取不到就放临时目录，绝不因此再抛异常。"""
    for base in (os.environ.get("STARRY_CONFIG_DIR"),
                 os.environ.get("HOME"),
                 "/data/user/0/com.starry/files",
                 os.environ.get("TMPDIR"), "/data/local/tmp"):
        if base and os.path.isdir(base) and os.access(base, os.W_OK):
            return os.path.join(base, "starry-crash.log")
    return None


def _excepthook(exc_type, exc_value, exc_tb):
    detail = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
    _log("StarryApp", "UNCAUGHT: " + detail)
    try:
        path = _crash_path()
        if path:
            with open(path, "a", encoding="utf-8") as f:
                f.write("\n===== %s =====\n%s" % (
                    time.strftime("%Y-%m-%d %H:%M:%S"), detail))
    except Exception:                                    # noqa: BLE001
        pass


def _log_environment():
    try:
        import toga
        from importlib.metadata import version, PackageNotFoundError
        parts = ["toga=%s" % getattr(toga, "__version__", "?")]
        for pkg in ("toga", "toga-core", "toga-android", "toga-gtk"):
            try:
                parts.append("%s=%s" % (pkg, version(pkg)))
            except PackageNotFoundError:
                pass
            except Exception:                            # noqa: BLE001
                pass
        _log("StarryEnv", "Python %s | %s | platform=%s | HOME=%s" % (
            sys.version.split()[0], ", ".join(parts), sys.platform,
            os.environ.get("HOME", "<unset>")))
    except Exception as exc:                             # noqa: BLE001
        _log("StarryEnv", "环境探测失败: %r" % exc)


def _run():
    sys.excepthook = _excepthook
    _log_environment()
    app = None
    try:
        from starryandroid.app import main
        app = main()
    except Exception:                                    # noqa: BLE001
        _excepthook(*sys.exc_info())
        # 构造期失败：不再 sys.exit(1) 直接杀进程，尝试显示最小错误窗口
        try:
            import toga
            from toga.style import Pack

            class _ErrorApp(toga.App):
                def startup(self):
                    box = toga.Box(style=Pack(direction="column", padding=20))
                    box.add(toga.Label("⚠ 星语启动异常", style=Pack(
                        padding=10, font_size=18)))
                    box.add(toga.Label(
                        "依赖或初始化失败。日志已写入 starry-crash.log，"
                        "可用「诊断」思路反馈；也可用 adb logcat | grep Starry",
                        style=Pack(padding=10, font_size=13)))
                    self.main_window = toga.MainWindow(title="星语 Starry")
                    self.main_window.content = box
                    self.main_window.show()

            _ErrorApp().main_loop()
        except Exception:                                # noqa: BLE001
            _excepthook(*sys.exc_info())
        return 1

    try:
        app.main_loop()
        return 0
    except Exception:                                    # noqa: BLE001
        _excepthook(*sys.exc_info())
        return 1


if __name__ == "__main__":
    sys.exit(_run())
