name: Pull Request
description: 提交代码前请阅读 docs/开源提交指南_v6.md 的 commit 规范
labels: []
body:
  - type: markdown
    attributes:
      value: |
        提交前自查（CI 会逐项验证）：
        - `python -m pyflakes .` 干净（有意项带 `# noqa`）
        - `QT_QPA_PLATFORM=offscreen python selftest.py` 全绿
        - 涉及网页版：`python verify_v6_browser.py` 12/12
  - type: input
    id: summary
    attributes:
      label: 概述
      description: 这个 PR 做什么（对应 commit message 的主题）
    validations:
      required: true
  - type: dropdown
    id: type
    attributes:
      label: 变更类型
      options:
        - feat（新功能）
        - fix（缺陷修复）
        - docs（文档）
        - refactor（重构）
        - test（测试）
        - build（打包）
        - chore（其他）
    validations:
      required: true
  - type: textarea
    id: motivation
    attributes:
      label: 动机与背景
      description: 为什么需要这个变更；关联 issue 请注明
    validations:
      required: true
  - type: textarea
    id: verify
    attributes:
      label: 验证证据
      description: 自测项数变化、截图（UI 变更必填）、已知边界
    validations:
      required: true
