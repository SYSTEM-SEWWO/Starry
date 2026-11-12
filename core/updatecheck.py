# -*- coding: utf-8 -*-
"""星语 Starry · 自动更新检查（v13.0 大版本新增，纯逻辑）。

「增加更新功能」的落地：把「有没有新版本 / 该下哪个资产 / 资产是否完整」
做成**可离线单测的纯逻辑**，网络下载交给调用方（CLI / UI）。这样
    - Windows EXE / Linux deb 在无网络时也能给出确定结论；
    - 更新清单的结构、版本比较、SHA-256 校验都能进 CI 门禁；
    - 不会因为一个 URL 拼错就把「检查更新」变成不可测的黑盒。

清单格式（update.json）：
    {
      "magic": "STARRY-UPDATE", "schema": 1,
      "app_version": "13.0.0",
      "assets": [{"platform":"windows","name":"...exe",
                  "url":"https://...","sha256":"<64 hex>","size":123}],
      "notes": "...", "released_at": "...",
      "digest": "<sha256 of canonical manifest without digest>"
    }

安全边界：digest 与 asset.sha256 都是**完整性校验**，不是签名认证；
清单来源必须可信（HTTPS + GitHub Releases），生产环境建议再加签名验证。
"""
import hashlib
import json
import os
import re

UPDATE_MAGIC = "STARRY-UPDATE"
MANIFEST_VERSION = 1
PLATFORMS = ("windows", "linux", "android", "macos")

_ALIASES = {
    "win32": "windows", "win": "windows", "windows": "windows", "exe": "windows",
    "linux": "linux", "linux2": "linux", "uos": "linux", "deb": "linux",
    "android": "android", "apk": "android",
    "darwin": "macos", "mac": "macos", "macos": "macos",
}

__all__ = [
    "UPDATE_MAGIC", "MANIFEST_VERSION", "PLATFORMS",
    "normalize_platform", "parse_version", "compare_versions", "is_newer",
    "manifest_digest", "build_manifest", "validate_manifest",
    "select_asset", "verify_asset_sha256", "check_update",
    "configured_manifest_url", "load_manifest",
]


def normalize_platform(platform):
    p = str(platform or "").strip().lower()
    return _ALIASES.get(p, p if p in PLATFORMS else "")


def parse_version(text):
    """把版本字符串解析为可比较的数字元组；非数字后缀忽略。"""
    nums = re.findall(r"\d+", str(text or ""))
    return tuple(int(n) for n in nums[:4]) or (0,)


def _pad(a, b):
    n = max(len(a), len(b))
    return a + (0,) * (n - len(a)), b + (0,) * (n - len(b))


def compare_versions(a, b):
    """a > b 返回 1，相等返回 0，a < b 返回 -1。"""
    x, y = _pad(parse_version(a), parse_version(b))
    return (x > y) - (x < y)


def is_newer(remote, current):
    return compare_versions(remote, current) > 0


def manifest_digest(manifest):
    """对不含 digest 字段的规范化 JSON 计算 SHA-256。"""
    obj = {k: v for k, v in (manifest or {}).items() if k != "digest"}
    canonical = json.dumps(obj, ensure_ascii=False, sort_keys=True,
                           separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def build_manifest(app_version, assets=None, notes="", released_at=None,
                   repo_url=""):
    """构造并自签（完整性摘要）一份更新清单。"""
    obj = {
        "magic": UPDATE_MAGIC,
        "schema": MANIFEST_VERSION,
        "app_version": str(app_version or "0.0.0"),
        "assets": [dict(a) for a in (assets or [])],
        "notes": str(notes or ""),
        "released_at": str(released_at or ""),
        "repo_url": str(repo_url or ""),
    }
    obj["digest"] = manifest_digest(obj)
    return obj


def validate_manifest(obj):
    """返回 (ok, reason)。结构 / 版本 / digest / 资产字段全部严格校验。"""
    if not isinstance(obj, dict):
        return False, "清单根节点必须是对象"
    if obj.get("magic") != UPDATE_MAGIC:
        return False, "不是 Starry 更新清单（magic 不匹配）"
    if obj.get("schema") != MANIFEST_VERSION:
        return False, "不支持的清单格式版本：%r" % (obj.get("schema"),)
    if "app_version" not in obj or not parse_version(obj.get("app_version"))[0]:
        return False, "app_version 缺失或非法"
    if obj.get("digest") != manifest_digest(obj):
        return False, "清单校验失败（内容被修改或传输损坏）"
    assets = obj.get("assets")
    if not isinstance(assets, list) or not assets:
        return False, "assets 必须是非空列表"
    for i, a in enumerate(assets):
        if not isinstance(a, dict):
            return False, "assets[%d] 不是对象" % i
        if normalize_platform(a.get("platform")) not in PLATFORMS:
            return False, "assets[%d].platform 非法：%r" % (i, a.get("platform"))
        if not str(a.get("name") or "").strip():
            return False, "assets[%d].name 缺失" % i
        if not str(a.get("url") or "").startswith(("http://", "https://")):
            return False, "assets[%d].url 非法" % i
        sha = str(a.get("sha256") or "")
        if not re.fullmatch(r"[0-9a-fA-F]{64}", sha):
            return False, "assets[%d].sha256 必须是 64 位十六进制" % i
        size = a.get("size")
        if not isinstance(size, int) or size < 0:
            return False, "assets[%d].size 必须是非负整数" % i
    return True, "OK"


def select_asset(manifest, platform):
    """按平台挑选资产；同平台多个取第一个，无匹配返回 None。"""
    target = normalize_platform(platform)
    if not target:
        return None
    for a in (manifest or {}).get("assets", []):
        if isinstance(a, dict) and normalize_platform(a.get("platform")) == target:
            return a
    return None


def verify_asset_sha256(path, expected):
    """分块校验已下载文件；任何异常返回 False，不抛。"""
    try:
        want = str(expected or "").lower()
        if not re.fullmatch(r"[0-9a-f]{64}", want):
            return False
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return h.hexdigest() == want
    except Exception:                                    # noqa: BLE001
        return False


def check_update(current, manifest, platform="windows"):
    """纯逻辑更新判定（不联网）。

    返回 {current, latest, manifest_valid, update_available, asset,
          reason, platform}。任何异常都被收敛为「不可判定」，不抛。
    """
    res = {
        "current": str(current or ""), "latest": "", "manifest_valid": False,
        "update_available": False, "asset": None, "reason": "",
        "platform": normalize_platform(platform) or str(platform or ""),
    }
    ok, reason = validate_manifest(manifest)
    if not ok:
        res["reason"] = reason
        return res
    res["manifest_valid"] = True
    res["latest"] = str(manifest.get("app_version") or "")
    if not is_newer(res["latest"], res["current"]):
        res["reason"] = "已是最新版本（%s）" % res["current"]
        return res
    res["update_available"] = True
    asset = select_asset(manifest, platform)
    res["asset"] = asset
    res["reason"] = ("发现新版本 %s" % res["latest"] if asset
                     else "发现新版本 %s，但当前平台无对应资产" % res["latest"])
    return res


def configured_manifest_url():
    """读取 STARRY_UPDATE_URL；未配置返回空串（离线模式）。

    刻意不硬编码任何仓库地址——仓库由使用者在 fork 后自行配置，
    避免把不存在的 URL 写进产物。
    """
    return str(os.environ.get("STARRY_UPDATE_URL") or "").strip()


def load_manifest(path):
    """从本地文件读取清单（本模块唯一带 I/O 的函数），失败抛 ValueError。"""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as exc:                             # noqa: BLE001
        raise ValueError("无法读取更新清单：%s" % exc)
