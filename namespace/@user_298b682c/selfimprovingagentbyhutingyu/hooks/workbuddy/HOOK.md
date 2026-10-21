---
name: self-improving-agent-cn
description: "在 bootstrap 时注入自我改进提醒，并在会话结束时扫描错误"
metadata: {"workbuddy":{"emoji":"🧠","events":["agent:bootstrap","command:new","command:reset"]}}
---

# 自我改进 Hook

在 Agent bootstrap 期间注入学习记录评估提醒，并在已结束的会话中检测错误。

WorkBuddy 没有每次工具调用的 Hook 事件，因此无法在每条命令之后实时检测错误。此 Hook 改用在会话结束时进行错误扫描来代替。

## 功能

**在 `agent:bootstrap` 时**（工作区文件注入之前）：

- 添加一个提醒块，提示检查 `.learnings/` 目录中的相关条目
- 提示 Agent 记录修正、错误和新发现
- 如果有待审核的自动检测错误，包含待处理分类提示

**在 `command:new` / `command:reset` 时**（会话结束时）：

- 定位刚结束会话的对话记录
  （`context.previousSessionEntry.sessionFile`，回退到
  `<workspace>/sessions/<sessionId>.jsonl`）
- 使用固定的错误模式列表进行扫描
  （`Error:`、`command not found`、`Traceback`、`npm ERR!` 等）
- 将截断、脱敏后的 `pending` 条目（每次扫描最多 5 条）追加到
  `<workspace>/.learnings/ERRORS.md`，供下一个会话审核
- 为每条条目标记从匹配模式派生的确定性 `Pattern-Key` 值
  （例如 `deps.module-not-found`、`shell.command-not-found`），
  使自动检测的错误可以按 key 去重和统计复现次数
  （参见 `SKILL.md` 中的 Pattern-Key 分类体系）

## 可选加入与安全

- 扫描仅在 `<workspace>/.learnings/` 存在时运行——创建该目录以启用，删除以禁用
- `ERRORS.md` 仅在不存在时创建，否则追加，绝不覆盖
- 摘录截断至 200 个字符，常见密钥形态（bearer tokens、API keys、GitHub/Slack/AWS tokens、JWTs、长不透明字符串）在写入前脱敏；`ERRORS.md` 中已存在的摘录会被跳过
- Hook 失败会被静默吞掉，确保网关不受影响；设置
  `SELF_IMPROVEMENT_DEBUG=1` 以记录失败日志

## 配置

无需配置。使用以下命令启用：

```bash
workbuddy hooks enable self-improving-agent-cn
```

通过创建学习记录目录来启用错误扫描：

```bash
mkdir -p ~/.workbuddy/workspace/.learnings
```

## 测试

```bash
node --test hooks/workbuddy/handler.test.js
```
