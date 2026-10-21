# self-improving-agent（中文版）

WorkBuddy 的自我改进 Skill。捕获学习经验、错误和功能请求，支持跨会话持续改进。

**此版本仅适用于 WorkBuddy。** 如需在其他 Agent 中使用（Claude Code、Codex、GitHub Copilot 等），
请使用原始多平台版本：
https://github.com/pskoett/pskoett-ai-skills/tree/main/skills/self-improving-agent-cn

## 仓库结构

可发布的 Skill 包位于仓库的 [`self-improving-agent/`](self-improving-agent/) 子目录——
这是 SkillHub 安装的内容，也是你复制到 `~/.workbuddy/skills/` 的内容。仓库级文件（本 README、`.github/` CI）
有意放在包外。

- Skill 入口文件：[`self-improving-agent/SKILL.md`](self-improving-agent/SKILL.md)
- WorkBuddy Hook：[`self-improving-agent/hooks/workbuddy/`](self-improving-agent/hooks/workbuddy/)

## 安装

```bash
skillhub install self-improving-agent
```

或手动——复制 Skill 子目录（非仓库根目录）：

```bash
git clone https://github.com/peterskoett/self-improving-agent.git /tmp/self-improving-agent-repo
cp -r /tmp/self-improving-agent-repo/self-improving-agent ~/.workbuddy/skills/self-improving-agent
```

## 归属

从原始仓库为 WorkBuddy 重制：

- https://github.com/pskoett/pskoett-ai-skills
- https://github.com/pskoett/pskoett-ai-skills/tree/main/skills/self-improving-agent-cn

## 升级

版本历史和升级说明参见 `self-improving-agent/CHANGELOG.md`。升级后，重新复制 WorkBuddy Hook 并重启网关：

```bash
cp -r ~/.workbuddy/skills/self-improving-agent-cn/hooks/workbuddy ~/.workbuddy/hooks/self-improving-agent-cn
```

## 卸载

禁用与完全删除的步骤参见 `self-improving-agent/references/uninstall.md`。
删除前请审核 `.learnings/`——它包含的是你捕获的学习记录，而非 Skill 代码。
