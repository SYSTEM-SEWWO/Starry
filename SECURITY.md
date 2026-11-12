# 安全政策 / Security Policy

## 数据边界

星语 Starry 是**本地优先**的桌面应用：

- API Key、会话记录、统计数据、网页版登录态（浏览器 profile）**全部只存本机**；
  应用不运营任何服务端，不上传任何用户数据；
- 浏览器 profile 内含登录态 Cookie，请勿分享 `~/.starry/browser/` 目录；
- 提交 issue / PR 时请不要附带 `config.json` 内容或真实 Key。

## 支持版本

| 版本 | 状态 |
| --- | --- |
| 7.x |  actively supported |
| 6.x | 安全修复 |
| ≤ 5.x | 不再支持 |

## 报告漏洞

发现安全问题请**不要**开公开 issue，请发送邮件到维护者（见仓库 About / commit 作者邮箱），
附：影响范围、复现步骤、修复建议（如有）。我们会在 72 小时内回应。
