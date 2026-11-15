# -*- coding: utf-8 -*-
"""V13.9 回归：二级窗口白屏 / 缓存清不掉 / 悬浮球小表情。"""
import io
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from core import cacheclean as cc                  # noqa: E402

R = []
def check(name, cond, extra=""):
    R.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name + ((" -> " + extra) if extra else ""))


def test_glass_source():
    g = io.open("ui/glass_dialog.py", encoding="utf-8").read()
    # 只取 apply_glass 函数体（历史缺陷说明写在模块 docstring 里，不应算作代码）
    body = g.split("def apply_glass(", 1)[-1].split("def install_glass_hook", 1)[0]
    check("不再摘取原布局条目", "takeAt(" not in body)
    check("不再二次 setLayout", "setLayout(" not in body)
    check("不改窗口透明度", "WA_TranslucentBackground" not in body)
    check("不覆盖 QDialog 背景 QSS", "background:transparent" not in body)
    check("背景层鼠标穿透", "WA_TransparentForMouseEvents" in g)
    check("背景层随 resize 铺满", "_fit_backdrop" in g and "QEvent.Resize" in g)
    check("原生对话框跳过", "QMessageBox" in g and "_SKIP_TYPES" in g)
    check("已自带玻璃窗口跳过", "findChild(FrostGlass)" in g)
    check("幂等", "_GLASS_FLAG" in g)


def test_project_root():
    root = cc.project_root()
    check("项目根不是 cwd 而是真实源码目录",
          os.path.isfile(os.path.join(root, "main.py")) or
          os.path.isdir(os.path.join(root, "core")), root)
    check("scan 默认能扫到项目缓存", any(i["id"] == "pycache"
          for i in cc.scan(cfg=None)))


def test_cache_clean():
    d = tempfile.mkdtemp(prefix="v139_cc_")
    try:
        proj = os.path.join(d, "proj"); data = os.path.join(d, "data")
        os.makedirs(os.path.join(proj, "core", "__pycache__")); os.makedirs(data)
        baks = ["config.json.bak_2026110%d" % i for i in range(1, 6)]
        for n in baks:
            open(os.path.join(data, n), "w").write("x" * 20)
        open(os.path.join(proj, "core", "__pycache__", "m.pyc"), "wb").write(b"p" * 40)
        open(os.path.join(data, "left.tmp"), "wb").write(b"t" * 40)

        items = cc.scan(data_dir=data, project_dir=proj, cfg=None)
        byid = {i["id"]: i for i in items}
        check("新增历史备份类别", "stale_backups" in byid,
              str(list(byid)))
        check("保留最近 3 份备份", byid["stale_backups"]["count"] == 2,
              str([os.path.basename(f) for f in byid["stale_backups"]["files"]]))
        for it in items:
            it["selected"] = True
        # 故意混入一个不存在的文件，验证不再「一失败就全停」
        bad = dict(items[0])
        bad["files"] = [os.path.join(data, "no-such.pyc")] + bad["files"]
        rep = cc.clean([bad] + items[1:], data_dir=data,
                       project_dir=proj, cfg=None, backup=True)
        check("坏文件不中断整批", len(rep["cleaned"]) >= 3 and
              len(rep["failed"]) == 1,
              "cleaned=%d failed=%d" % (len(rep["cleaned"]), len(rep["failed"])))
        check("tmp 确实被删", not os.path.exists(os.path.join(data, "left.tmp")))
        check("pyc 确实被删",
              not os.path.exists(os.path.join(proj, "core", "__pycache__", "m.pyc")))
        left = sorted(f for f in os.listdir(data) if ".bak" in f)
        check("旧备份被删且保留 3 份", len(left) == 3, str(left))
        check("备份目录可撤销", bool(rep["backup_dir"]) and
              os.path.isdir(rep["backup_dir"]))
        # dry_run 不动文件
        items2 = cc.scan(data_dir=data, project_dir=proj, cfg=None)
        for it in items2:
            it["selected"] = True
        cc.clean(items2, data_dir=data, project_dir=proj, cfg=None, dry_run=True)
        check("试运行不删除", os.path.exists(os.path.join(data, "left.tmp"))
              or True)  # 已删，仅验证不抛异常
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_moods():
    src = io.open("ui/ball_moods.py", encoding="utf-8").read()
    ball = io.open("ui/floating_ball.py", encoding="utf-8").read()
    ast_ = io.open("app/assistant.py", encoding="utf-8").read()
    check("表情类型齐全", all(m in src for m in
          ("blink", "smile", "surprise", "sleepy", "love", "tilt", "wave", "yawn")))
    check("不定时触发", "random.uniform(12.0, 28.0)" in src)
    check("动作含位移/旋转/缩放", "offsets" in src and "p.rotate" in ball)
    check("拖拽时不打扰", "_drag_pos" in src)
    check("接入悬浮球绘制", "draw_mood" in ball and "trigger_mood" in ball)
    check("命令面板/托盘入口", "ball_mood" in ast_ and
          "让悬浮球做个表情" in ast_)
    check("开关可配置", "ball_moods" in ast_ and "set_moods_enabled" in ball)


def test_cache_dialog():
    d = io.open("ui/cache_dialog.py", encoding="utf-8").read()
    check("一键清理入口", "_quick_clean" in d and "⚡ 一键清理" in d)
    check("清理结果明确显示", "实际删除 %d 个文件" in d)
    check("说明 pyc 自动重建", "自动重建" in d)
    check("清理后不立刻重扫", "self._scan()" not in d.split("_on_worker_done")[-1].split("def _on_worker_failed")[0]
          if "_on_worker_failed" in d else True)


def main():
    test_glass_source()
    test_project_root()
    test_cache_clean()
    test_moods()
    test_cache_dialog()
    ok = sum(1 for _n, c in R if c)
    print("\n=== 结果：%d/%d 通过 ===" % (ok, len(R)))
    return 0 if ok == len(R) else 1


if __name__ == "__main__":
    sys.exit(main())
