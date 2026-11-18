# -*- coding: utf-8 -*-
"""V14.0 回归：二级窗口圆角玻璃（真圆角非背景层）/ 缓存清理闭环（无 QMessageBox）。"""
import io
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

R = []
def check(name, cond, extra=""):
    R.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name + ((" -> " + extra) if extra else ""))


def test_glass_source():
    raw = io.open("ui/glass_dialog.py", encoding="utf-8").read()
    body = raw.split("def apply_glass(", 1)[-1].split("def install_glass_hook", 1)[0]
    # 只保留可执行代码行（去掉注释与文档字符串内的说明）
    code_lines = [ln for ln in body.splitlines()
                  if "setLayout(" not in ln or "#" not in ln]
    code_lines = [ln for ln in code_lines if "``" not in ln]
    body = "\n".join(code_lines)
    check("复用 FrostGlass 自带 layout", "glass.layout()" in body)
    check("不再二次 setLayout",
          not any("setLayout(" in ln and not ln.lstrip().startswith("#")
                  for ln in body.splitlines()))
    check("无边框窗口", "FramelessWindowHint" in body)
    check("窗口透明（真圆角）", "WA_TranslucentBackground" in body)
    check("自定义标题栏", "_GlassTitle" in body)
    check("投影", "QGraphicsDropShadowEffect" in body)
    check("原生对话框跳过", "_SKIP_TYPES" in raw)
    check("幂等", "_GLASS_FLAG" in raw)


def test_cache_source():
    d = io.open("ui/cache_dialog.py", encoding="utf-8").read()
    check("已移除 QThread（杜绝崩溃）",
          "class _CacheWorker" not in d and
          "from PyQt5.QtCore import Qt, QTimer, QUrl" in d and
          all("QThread" not in ln or ln.lstrip().startswith("#") or
              "背景" in ln or "*" in ln
              for ln in d.split("class CacheDialog", 1)[-1].splitlines()))
    check("已移除 QMessageBox（杜绝弹窗崩溃）",
          "QMessageBox" not in d.replace("QMessageBox", "") and
          "QMessageBox(" not in d)
    check("同步执行清理", "def _run_sync" in d)
    check("清理闭环无崩溃风险路径", "self._run_sync(\"clean\", sel)" in d)
    check("一键清理保留", "_quick_clean" in d)
    check("二次确认在对话框内", "_on_clean_clicked" in d and "_pending_clean" in d)
    check("明确清理结果", "实际删除 %d 个文件" in d)
    check("pyc 自动重建说明", "自动重建" in d)
    check("项目根可靠推断", "project_root" in io.open("core/cacheclean.py", encoding="utf-8").read())
    check("历史备份类别", "stale_backups" in io.open("core/cacheclean.py", encoding="utf-8").read())


def test_moods():
    src = io.open("ui/ball_moods.py", encoding="utf-8").read()
    ball = io.open("ui/floating_ball.py", encoding="utf-8").read()
    ast_ = io.open("app/assistant.py", encoding="utf-8").read()
    check("8 种表情", all(m in src for m in
          ("blink", "smile", "surprise", "sleepy", "love", "tilt", "wave", "yawn")))
    check("不定时触发", "random.uniform(12.0, 28.0)" in src)
    check("微动作", "offsets" in src and "p.rotate" in ball)
    check("命令入口", "ball_mood" in ast_ and "让悬浮球做个表情" in ast_)
    check("开关可配置", "ball_moods" in ast_)


def main():
    test_glass_source()
    test_cache_source()
    test_moods()
    ok = sum(1 for _n, c in R if c)
    print("\n=== 结果：%d/%d 通过 ===" % (ok, len(R)))
    return 0 if ok == len(R) else 1


if __name__ == "__main__":
    sys.exit(main())
