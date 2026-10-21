# WorkBuddy 集成指南

完整的设置和使用指南，用于将自我改进 Skill 与 WorkBuddy 集成。

## 概述

WorkBuddy 使用基于工作区的提示注入结合事件驱动的 Hook。上下文在会话开始时从工作区文件注入，Hook 可以在生命周期事件上触发。

## 工作区结构

```
~/.workbuddy/                      
├── workspace/                   # 工作目录
│   ├── AGENTS.md               # 多 Agent 协调模式
│   ├── SOUL.md                 # 行为准则和个性
│   ├── TOOLS.md                # 工具能力和注意事项
│   ├── MEMORY.md               # 长期记忆（仅主会话）
│   └── memory/                 # 每日记忆文件
│       └── YYYY-MM-DD.md
├── skills/                      # 已安装的 Skill
│   └── <skill-name>/
│       └── SKILL.md
└── hooks/                       # 自定义 Hook
    └── <hook-name>/
        ├── HOOK.md
        └── handler.ts
```

## 快速设置

### 1. 安装 Skill

```bash
skillhub install self-improving-agent
```

或手动复制——Skill 包位于仓库的 `self-improving-agent/` 子目录，非仓库根目录：

```bash
git clone https://github.com/peterskoett/self-improving-agent.git /tmp/self-improving-agent-repo
cp -r /tmp/self-improving-agent-repo/self-improving-agent ~/.workbuddy/skills/self-improving-agent
```

### 2. 安装 Hook（可选）

将 Hook 复制到 WorkBuddy 的 hooks 目录：

```bash
cp -r ~/.workbuddy/skills/self-improving-agent-cn/hooks/workbuddy ~/.workbuddy/hooks/self-improving-agent-cn
```

启用 Hook：

```bash
workbuddy hooks enable self-improving-agent-cn
```

Hook 完成两件事：

- **`agent:bootstrap`** — 将会话上下文注入自我改进提醒
  （并标记等待审核的自动检测错误）
- **`command:new` / `command:reset`** — 扫描刚结束会话的对话记录中的错误模式，
  将待处理条目追加到 `<workspace>/.learnings/ERRORS.md`
  （仅在 `.learnings/` 存在时——参见[错误检测](#错误检测)）

### 3. 创建学习记录文件

在工作区创建 `.learnings/` 目录：

```bash
mkdir -p ~/.workbuddy/workspace/.learnings
```

或在 Skill 目录中：

```bash
mkdir -p ~/.workbuddy/skills/self-improving-agent-cn/.learnings
```

## 注入的提示文件示例

### AGENTS.md

用途：多 Agent 工作流和委派模式。

```markdown
# Agent Coordination

## Delegation Rules
- Use explore agent for open-ended codebase questions
- Spawn sub-agents for long-running tasks

## Session Handoff
When delegating to another session:
1. Provide full context in the handoff message
2. Include relevant file paths
3. Specify expected output format
```

### SOUL.md

用途：行为准则和沟通风格。

```markdown
# Behavioral Guidelines

## Communication Style
- Be direct and concise
- Avoid unnecessary caveats and disclaimers
- Use technical language appropriate to context

## Error Handling
- Admit mistakes promptly
- Provide corrected information immediately
- Log significant errors to learnings
```

### TOOLS.md

用途：工具能力、集成注意事项、本地配置。

```markdown
# Tool Knowledge

## Self-Improvement Skill
Log learnings to `.learnings/` for continuous improvement.

## Local Tools
- Document tool-specific gotchas here
- Note authentication requirements
- Track integration quirks
```

## 学习工作流

### 捕获学习记录

1. **会话内**：按常规记录到 `.learnings/`
2. **跨会话**：提升到工作区文件

### 提升决策树

```
学习记录是否项目特定？
├── 是 → 保留在 .learnings/
└── 否 → 是否与行为/风格相关？
    ├── 是 → 提升到 SOUL.md
    └── 否 → 是否与工具相关？
        ├── 是 → 提升到 TOOLS.md
        └── 否 → 提升到 AGENTS.md（工作流）
```

### 提升格式示例

**来自学习记录：**
> Git push 到 GitHub 在没有配置认证时失败——触发桌面提示

**在 TOOLS.md 中：**
```markdown
## Git
- 不要在没有确认认证已配置的情况下执行 push
- 使用 `gh auth status` 检查 GitHub CLI 认证
```

## Agent 间通信

WorkBuddy 提供以下跨会话通信工具：

仅在明确需要跨会话共享且环境受信任时使用。优先使用简短的脱敏摘要，而非原始对话记录、命令输出或含密钥的内容。

### 【WorkBuddy不支持：使用conversation_search】

查看活跃和最近的会话：
```
【WorkBuddy不支持：使用conversation_search】(activeMinutes=30, messageLimit=3)
```

### 【WorkBuddy不支持：使用conversation_search】

读取另一个会话的对话记录：
```
【WorkBuddy不支持：使用conversation_search】(sessionKey="session-id", limit=50)
```

仅在用户明确需要跨会话共享上下文或继续之前的工作时才读取其他会话的记录。

### 【WorkBuddy不支持：使用memory系统】

向另一个会话发送消息：
```
【WorkBuddy不支持：使用memory系统】(sessionKey="session-id", message="Learning: API requires X-Custom-Header")
```

优先发送简洁的学习摘要和相关路径，而非转发原始对话内容。

### 【WorkBuddy不支持：使用Agent工具】

生成后台子 Agent：
```
【WorkBuddy不支持：使用Agent工具】(task="Research X and report back", label="research")
```

## 可用的 Hook 事件

| 事件 | 触发时机 |
|------|----------|
| `agent:bootstrap` | 工作区文件注入之前 |
| `command:new` | 发出 `/new` 命令时 |
| `command:reset` | 发出 `/reset` 命令时 |
| `command:stop` | 发出 `/stop` 命令时 |
| `gateway:startup` | 网关启动时 |
| `gateway:shutdown` | 网关关闭时 |
| `message:received` / `message:sent` | 消息收发前后 |
| `session:compact:before` / `:after` | 会话压缩前后 |

**重要提示：** WorkBuddy **没有每次工具调用的 Hook 事件**——没有在每次单独工具调用之后触发的事件，因此无法实现每条命令的实时错误检测。错误检测改为在会话结束时进行（见下文）。

## 错误检测

Skill 的 Hook（`hooks/workbuddy/`）实现了**会话结束时的错误扫描**：

1. 当 `/new` 或 `/reset` 结束一个会话时，Hook 从
   `context.previousSessionEntry` 解析已结束会话的对话记录
   （回退到 `<workspace>/sessions/<sessionId>.jsonl`）——
   这与 WorkBuddy 内置的 `session-memory` Hook 使用相同的来源。
2. 对话记录按固定的错误模式列表进行扫描（`Error:`、
   `command not found`、`Traceback`、`npm ERR!`、`Permission denied` 等）。
3. 匹配项作为 `pending` 条目追加到 `<workspace>/.learnings/ERRORS.md`，
   标记 `Source: workbuddy-error-sweep`，最多包含 5 条简短摘录
   （截断至 200 字符、常见密钥形态已脱敏、重复条目已跳过）。
   每条条目标记从匹配模式派生的确定性 `Pattern-Key` 值
   （例如 `ModuleNotFoundError` → `deps.module-not-found`），
   使复现次数可以在审核时按 key 统计——参见 `SKILL.md` 中的 Pattern-Key 分类。
4. 在下一次 `agent:bootstrap` 时，注入的提醒会包含**待处理分类**提示，
   以便 Agent 审核自动检测的条目——确认真实错误、补充修复方案或删除噪声。

### 启用/禁用扫描

扫描是可选的，由 `.learnings/` 目录控制：

```bash
# 启用
mkdir -p ~/.workbuddy/workspace/.learnings

# 禁用（提醒注入仍继续工作）
rm -r ~/.workbuddy/workspace/.learnings
```

### 扫描限制

- 从未用 `/new` 或 `/reset` 结束的会话不会被扫描。
- 检测发生在会话结束时，而非失败命令执行后立即触发
  ——没有每次工具调用的事件可以 Hook。
- 模式匹配是启发式的；可能标记误报，例如行文中出现 "failed" 一词
  ——这就是需要审核步骤的原因。
- 摘录使用尽力而为的规则进行脱敏；将 `.learnings/` 视为潜在敏感数据，
  默认不要纳入版本控制。

## 检测触发器

### 标准触发器
- 用户修正（"不对，应该是..."）
- 命令失败（非零退出码）
- API 错误
- 知识缺口

### WorkBuddy 特有触发器

| 触发器 | 操作 |
|--------|------|
| 工具调用错误 | 记录到 TOOLS.md，附带工具名 |
| 会话交接混乱 | 记录到 AGENTS.md，附带委派模式 |
| 模型行为异常 | 记录到 SOUL.md，附带预期与实际对比 |
| Skill 问题 | 记录到 .learnings/ 或向上游反馈 |

## 验证

检查 Hook 是否已注册：

```bash
workbuddy hooks list
```

检查 Skill 是否已加载：

```bash
workbuddy status
```

## 故障排除

### Hook 未触发

1. 确保配置中已启用 Hook
2. 配置更改后重启网关
3. 检查网关日志中的错误

### 学习记录未持久化

1. 验证 `.learnings/` 目录是否存在
2. 检查文件权限
3. 确保工作区路径配置正确

### 错误扫描未写入条目

1. 验证 `<workspace>/.learnings/` 是否存在（扫描是可选的，没有它静默跳过）
2. 用 `/new` 或 `/reset` 结束会话——扫描仅在这些命令上运行
3. 确认 `<workspace>/sessions/` 中存在对话记录
4. 以 `SELF_IMPROVEMENT_DEBUG=1` 运行网关以显示 Hook 错误
5. 记住 `ERRORS.md` 中已存在的摘录会被跳过（去重）

### Skill 未加载

1. 检查 Skill 是否在 skills 目录中
2. 验证 SKILL.md 具有正确的前置元数据
3. 运行 `workbuddy status` 查看已加载的 Skill
