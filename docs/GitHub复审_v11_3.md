# GitHub 复审 · v11.3.0

> 维度：工程化、CI、发版、提交规范、可复现构建。

## 1. CI / 发版链路

- `.github/workflows/build-android.yml` 沿用：推送 `v11.3.0` tag 即在运行器**真实编译并签名 APK、自动发布 Releases**。
- 本地已验证完整可复现链路：`干净重建（rm -rf build）→ briefcase create/build → gradle assembleRelease → zipalign → apksigner（v2+v3）→ 安装可用`。

## 2. 可复现构建（本次重点）

- 既往闪退根因之一是**构建复用陈旧缓存 wheel / `app.imy`**，导致分发 APK 版本与源码漂移（曾出现 APK 内 `config.pyc` 仍为旧版本）。
- 本轮约定：`rm -rf build bin logs` 后再 `briefcase create android`，强制从当前 11.3.0 源码全量重建，杜绝缓存歧义。
- JDK 固定为系统 **JDK17**（`/usr/lib/jvm/java-17-openjdk-amd64`），避免 Briefcase 0.4.7 对 Java 版本的硬性要求导致构建失败。

## 3. 提交与文档

- 每版本独立文件夹 + 后缀版本（`星语Starry-v11.3*`）+ zip 分发，README / CHANGELOG / RELEASE_NOTES / 评审纪要 / API 文档齐备。
- 版本号四处同步，已单测 `selftest.py` 断言守护。

## 4. 密钥管理建议

- 演示 keystore 留仓库便于本地/CI；正式发版建议移出仓库、走 CI Secret，并在 `.gitignore` 增加 `android/*.keystore`。

**结论**：工程链路稳定、发版可复现，GitHub 复审通过。
