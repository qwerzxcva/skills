# 卸载指南

如何禁用或彻底删除自我改进 Skill。**禁用**会关闭自动行为但保留数据；**删除**会移除 Skill 文件。这是不同的操作——按需选择。

> **你的学习记录是数据，不是 Skill 的组成部分。** `.learnings/` 包含 Skill 为你捕获的错误、修正和洞察。在删除任何内容之前，请先审核或归档。Skill *提升*到 `SOUL.md`、`TOOLS.md` 或 `AGENTS.md` 中的内容现在是这些文件的一部分——删除 Skill 不会（也不应该）自动删除它们。

## 仅禁用

```bash
# 停止 Hook（提醒注入 + 会话结束错误扫描）
workbuddy hooks disable self-improving-agent-cn
```

要保留 bootstrap 提醒但仅禁用错误扫描，改为删除学习记录目录（如果其中有条目，请先归档）：

```bash
rm -r ~/.workbuddy/workspace/.learnings
```

Hook 更改后重启网关。

## 彻底删除

```bash
# 1. 禁用并删除 Hook
workbuddy hooks disable self-improving-agent-cn
rm -r ~/.workbuddy/hooks/self-improving-agent-cn

# 2. 删除 Skill
rm -r ~/.workbuddy/skills/self-improving-agent

# 3. 可选——删除捕获的学习记录（请先审核，这是你的数据）
rm -r ~/.workbuddy/workspace/.learnings
```

然后重启网关，用 `workbuddy hooks list` 和 `workbuddy status` 验证。

手动审核 `~/.workbuddy/workspace/` 中的 `SOUL.md`、`TOOLS.md` 和 `AGENTS.md`，
删除由此 Skill 提升的、你不再需要的部分。如果 Skill 在你处理过的项目仓库中写入了 `.learnings/` 目录，请分别审核和删除。

## 验证

- `workbuddy hooks list` 不再显示 `self-improving-agent-cn`
- 新会话不再包含 `SELF_IMPROVEMENT_REMINDER.md`
- 没有遗留的 `.learnings/` 目录（除非你选择保留）
