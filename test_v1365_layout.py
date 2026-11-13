# -*- coding: utf-8 -*-
"""V13.6.5 回归：栏目密度四档 + 旧窗口尺寸一次性迁移。

零 Qt 依赖，可在任意环境直接运行（避开本机中文路径下 Qt 插件加载限制）。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from core import uilayout                     # noqa: E402
from core.config import DEFAULT_CONFIG        # noqa: E402


class _Cfg:
    """最小配置桩，记录 save() 调用次数。"""
    def __init__(self, size=None, version=None, density=None):
        self.data = {}
        if version is not None:
            self.data["layout_version"] = version
        if density is not None:
            self.data["ui_density"] = density
        self.appearance = {"window_size": list(size) if size else None}
        self.saves = 0

    def save(self):
        self.saves += 1


def run():
    results = []

    def check(name, cond, extra=""):
        results.append((name, bool(cond)))
        print(("PASS " if cond else "FAIL ") + name + (("  -> " + extra) if extra else ""))

    # 1) 四档尺寸严格递增
    labels = list(uilayout.DENSITY_LABELS)
    ms = [uilayout.metrics(d) for d in labels]
    check("四档齐全", labels == ["紧凑", "标准", "宽松", "超宽松"], str(labels))
    for key in ("title_h", "icon", "input_min", "send_h", "status_h",
                "input_gap", "msg_gap", "agent_h"):
        vals = [m[key] for m in ms]
        check("%s 逐档递增" % key, all(a < b for a, b in zip(vals, vals[1:])), str(vals))
    for i in range(len(ms) - 1):
        check("窗口逐档变大 %d" % i,
              ms[i]["window"][0] < ms[i + 1]["window"][0]
              and ms[i]["window"][1] < ms[i + 1]["window"][1])

    # 2) 未知密度回落到默认
    check("未知密度回落默认", uilayout.normalize("no-such") == uilayout.DEFAULT_DENSITY)
    check("别名解析", uilayout.normalize("XL") == "超宽松")
    check("metrics 返回副本", uilayout.metrics("宽松") is not uilayout.metrics("宽松"))

    # 3) 旧配置一次性迁移（复现用户 [430,640]）
    c = _Cfg(size=[430, 640])
    changed, why = uilayout.migrate(c)
    check("首次迁移执行", changed is True, why)
    check("旧窗口 430×640 → 620×860",
          c.appearance["window_size"] == [620, 860], str(c.appearance["window_size"]))
    check("写入密度与迁移标记",
          c.data["ui_density"] == "宽松" and c.data["layout_version"] == uilayout.LAYOUT_VERSION)
    check("迁移调用 save", c.saves == 1)
    check("窗口位置被重置", c.appearance.get("window_position") is None)

    # 4) 二次迁移不覆盖用户手动调整的尺寸
    c.appearance["window_size"] = [900, 1000]
    c.saves = 0
    changed2, _ = uilayout.migrate(c)
    check("二次迁移跳过", changed2 is False)
    check("用户手动尺寸保留", c.appearance["window_size"] == [900, 1000])
    check("二次不写盘", c.saves == 0)

    # 5) 已是新版本且有标记的旧配置不迁移
    c2 = _Cfg(size=[430, 640], version=uilayout.LAYOUT_VERSION)
    changed3, _ = uilayout.migrate(c2)
    check("已标记配置不重复迁移", changed3 is False)
    check("已标记尺寸保持不变", c2.appearance["window_size"] == [430, 640])

    # 6) reset 恢复推荐布局
    c3 = _Cfg(size=[400, 400])
    m = uilayout.reset(c3, "超宽松")
    check("reset 应用指定档位", c3.appearance["window_size"] == m["window"] == [720, 960])
    check("reset 写入密度", c3.data["ui_density"] == "超宽松")

    # 7) 全局默认配置
    check("默认密度为宽松", DEFAULT_CONFIG.get("ui_density") == "宽松")
    check("默认窗口 620×860",
          DEFAULT_CONFIG["appearance"]["window_size"] == [620, 860])
    check("默认迁移标记", DEFAULT_CONFIG.get("layout_version") == uilayout.LAYOUT_VERSION)

    # 8) CLI 摘要
    c4 = _Cfg(size=[620, 860], version=uilayout.LAYOUT_VERSION, density="宽松")
    text = uilayout.format_layout(c4)
    check("布局摘要含档位与窗口", "宽松" in text and "620 × 860" in text, text[:60])

    passed = sum(1 for _, ok in results if ok)
    print("\n=== 结果：%d/%d 通过 ===" % (passed, len(results)))
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(run())
