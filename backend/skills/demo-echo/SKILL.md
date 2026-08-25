---
name: demo_echo
description: 示例技能（工具型）：回显输入文本与当前 space_id，用于验证 SkillBridge 的 subprocess 管线（吃 JSON 参数、读 X_SPACE_KEY 环境变量、吐 JSON 结果）。
type: tool
command: ["python", "scripts/echo.py"]
timeout: 30
enabled: true
parameters: {"type":"object","properties":{"text":{"type":"string","description":"要回显的文本"}},"required":["text"]}
---
# demo_echo

这是一个**工具型**技能示例，用来端到端验证 SkillBridge 的 subprocess 执行链路。

当 Agent 调用 `demo_echo` 时，SkillBridge 会：

1. 把 `parameters` 以 JSON 形式写入子进程 `scripts/echo.py` 的 stdin；
2. 通过环境变量 `X_SPACE_KEY` 传入当前空间，使脚本可遵守空间隔离；
3. 解析子进程 stdout 的 JSON 结果回灌给模型。

该技能不涉及任何业务副作用，可安全用于冒烟测试。
