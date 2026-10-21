---
name: self-improving-agent-cn
description: "自我改进技能（中文版）：记录学习经验、错误和修正，实现持续改进。适用于以下场景：(1) 命令或操作意外失败，(2) 用户纠正你的错误（'不对，应该是...'、'实际上...'），(3) 用户请求不存在的功能，(4) 外部 API 或工具调用失败，(5) 你发现自己的知识已过时或错误，(6) 发现了处理重复任务的更优方法。在执行重要任务前也应回顾历史学习记录。"
version: "4.0.0-cn"
metadata:
  source: "https://github.com/pskoett/self-improving-agent"
  translator: "WorkBuddy AI"
  original_version: "4.0.0"
  license: "MIT"
---

# 自我改进技能

将学习经验和错误记录到 Markdown 文件中，实现持续改进。Agent 后续可以将这些记录处理成修复方案，重要的学习经验则提升到工作区记忆中。此版本专为 WorkBuddy 构建——如需其他 Agent 的多平台版本，请参阅原始版本：https://github.com/pskoett/pskoett-ai-skills。

> **说明**：此中文版本基于英文原版 [self-improving-agent v4.0.0](https://github.com/pskoett/self-improving-agent) 翻译而来。工具名、参数名、命令、路径和代码块保留英文原文，仅翻译说明性文字和注释部分。

## 首次使用初始化

在记录任何内容之前，确保项目或工作区根目录下存在 `.learnings/` 目录和文件。如果缺少，请创建它们：

```bash
mkdir -p .learnings
[ -f .learnings/LEARNINGS.md ] || printf "# Learnings\n\n开发过程中捕获的修正、洞察和知识缺口。\n\n**类别**: correction | insight | knowledge_gap | best_practice\n\n---\n" > .learnings/LEARNINGS.md
[ -f .learnings/ERRORS.md ] || printf "# Errors\n\n命令失败和集成错误。\n\n---\n" > .learnings/ERRORS.md
[ -f .learnings/FEATURE_REQUESTS.md ] || printf "# Feature Requests\n\n用户请求的功能。\n\n---\n" > .learnings/FEATURE_REQUESTS.md
```

**绝不覆盖已有文件**。如果 `.learnings/` 已经初始化，此操作为空操作。

不要记录密钥、令牌、私钥、环境变量或完整的源码/配置文件，除非用户明确要求记录到该细节程度。优先使用简短摘要或脱敏摘录，而非原始命令输出或完整对话记录。

如需自动提醒和会话结束时的错误检测，请启用下面描述的可选 Hook：[可选：启用 Hook](#可选启用-hook)。

## 快速参考

| 场景 | 操作 |
|------|------|
| 命令/操作失败 | 记录到 `.learnings/ERRORS.md` |
| 用户纠正你的错误 | 以 `correction` 类别记录到 `.learnings/LEARNINGS.md` |
| 用户需要缺失的功能 | 记录到 `.learnings/FEATURE_REQUESTS.md` |
| API/外部工具失败 | 记录到 `.learnings/ERRORS.md`，附带集成详情 |
| 知识已过时 | 以 `knowledge_gap` 类别记录到 `.learnings/LEARNINGS.md` |
| 发现了更优方法 | 以 `best_practice` 类别记录到 `.learnings/LEARNINGS.md` |
| 简化/加固重复模式 | 以 `Source: simplify-and-harden` 和稳定的 `Pattern-Key` 记录/更新 `.learnings/LEARNINGS.md` |
| 与已有条目相似 | 先用 `Pattern-Key` 搜索，用 `**See Also**` 关联，增加 `Recurrence-Count` |
| 工作流改进 | 提升到 `AGENTS.md`（工作区） |
| 工具踩坑经验 | 提升到 `TOOLS.md`（工作区） |
| 行为模式 | 提升到 `SOUL.md`（工作区） |

## WorkBuddy 设置

WorkBuddy 使用基于工作区的提示注入和自动 Skill 加载。

### 安装

**通过 SkillHub 安装（推荐）：**
```bash
skillhub install self-improving-agent
```

**手动安装**（Skill 位于仓库的 `self-improving-agent/` 子目录；
复制该文件夹，非仓库根目录）：
```bash
git clone https://github.com/peterskoett/self-improving-agent.git /tmp/self-improving-agent-repo
cp -r /tmp/self-improving-agent-repo/self-improving-agent ~/.workbuddy/skills/self-improving-agent
```

从原始仓库为 WorkBuddy 重制：https://github.com/pskoett/pskoett-ai-skills - https://github.com/pskoett/pskoett-ai-skills/tree/main/skills/self-improving-agent-cn

### 工作区结构

WorkBuddy 在每个会话中注入以下文件：

```
~/.workbuddy/workspace/
├── AGENTS.md          # 多 Agent 工作流、委派模式
├── SOUL.md            # 行为准则、个性、原则
├── TOOLS.md           # 工具能力、集成注意事项
├── MEMORY.md          # 长期记忆（仅主会话）
├── memory/            # 每日记忆文件
│   └── YYYY-MM-DD.md
└── .learnings/        # 本 Skill 的日志文件
    ├── LEARNINGS.md
    ├── ERRORS.md
    └── FEATURE_REQUESTS.md
```

### 创建学习文件

```bash
mkdir -p ~/.workbuddy/workspace/.learnings
```

然后创建日志文件（或从 `assets/` 复制）：
- `LEARNINGS.md` — 修正、知识缺口、最佳实践
- `ERRORS.md` — 命令失败、异常
- `FEATURE_REQUESTS.md` — 用户请求的功能

### 提升目标

当学习经验被证明具有广泛适用性时，将其提升到工作区文件：

| 学习类型 | 提升到 | 示例 |
|----------|--------|------|
| 行为模式 | `SOUL.md` | "保持简洁，避免免责声明" |
| 工作流改进 | `AGENTS.md` | "对长任务使用子 Agent" |
| 工具踩坑经验 | `TOOLS.md` | "Git push 需要先配置认证" |

### 跨会话通信

WorkBuddy 提供了以下跨会话共享学习经验的工具：

- **【WorkBuddy不支持：使用conversation_search】** — 查看活跃/最近的会话
- **【WorkBuddy不支持：使用conversation_search】** — 读取另一个会话的记录
- **【WorkBuddy不支持：使用memory系统】** — 向另一个会话发送学习经验
- **【WorkBuddy不支持：使用Agent工具】** — 生成子 Agent 执行后台工作

仅在受信任的环境中、且用户明确需要跨会话共享时才使用这些工具。优先发送简短的脱敏摘要和相关文件路径，而非原始对话记录、密钥或完整命令输出。

### 可选：启用 Hook

在会话开始时自动提醒，并在会话结束时进行错误检测：

```bash
cp -r ~/.workbuddy/skills/self-improving-agent-cn/hooks/workbuddy ~/.workbuddy/hooks/self-improving-agent-cn
workbuddy hooks enable self-improving-agent-cn
```

触发时机：`agent:bootstrap`（注入提醒，当有待审核的自动检测错误时附加待处理分类提示）和 `command:new`/`command:reset`（将已结束会话的记录中错误模式扫描到 `<workspace>/.learnings/ERRORS.md`；可选择加入——仅在 `.learnings/` 存在时运行）。WorkBuddy 没有每次工具调用的 Hook 事件，因此错误检测在会话结束时进行。详见 `references/workbuddy-integration.md` 了解详情和扫描限制。

## 记录格式

### 学习条目

追加到 `.learnings/LEARNINGS.md`：

```markdown
## [LRN-YYYYMMDD-XXX] category

**Logged**: ISO-8601 时间戳
**Priority**: low | medium | high | critical
**Status**: pending
**Area**: frontend | backend | infra | tests | docs | config

### Summary
一行描述学到的内容

### Details
完整上下文：发生了什么、错在哪里、正确做法是什么

### Suggested Action
具体要做的修复或改进

### Metadata
- Source: conversation | error | user_feedback
- Related Files: path/to/file.ext
- Tags: tag1, tag2
- See Also: LRN-20250110-001（如果与已有条目相关）
- Pattern-Key: area.symptom（推荐；例如 deps.module-not-found、simplify.dead_code——参见 Pattern-Key 分类）
- Recurrence-Count: 1（可选）
- First-Seen: 2025-01-15（可选）
- Last-Seen: 2025-01-15（可选）

---
```

### 错误条目

追加到 `.learnings/ERRORS.md`：

```markdown
## [ERR-YYYYMMDD-XXX] skill_or_command_name

**Logged**: ISO-8601 时间戳
**Priority**: high
**Status**: pending
**Area**: frontend | backend | infra | tests | docs | config

### Summary
简要描述失败的内容

### Error
```
实际的错误消息或输出
```

### Context
- 尝试执行的命令/操作
- 使用的输入或参数
- 相关环境详情
- 相关输出的摘要或脱敏摘录（避免默认包含完整对话记录和含密钥的数据）

### Suggested Fix
如果可确定，可能的解决方案

### Metadata
- Reproducible: yes | no | unknown
- Related Files: path/to/file.ext
- See Also: ERR-20250110-001（如果是复现问题）
- Pattern-Key: area.symptom（推荐；例如 net.connection-refused——参见 Pattern-Key 分类）
- Recurrence-Count: 1（可选）
- First-Seen: 2025-01-15（可选）
- Last-Seen: 2025-01-15（可选）

---
```

### 功能请求条目

追加到 `.learnings/FEATURE_REQUESTS.md`：

```markdown
## [FEAT-YYYYMMDD-XXX] capability_name

**Logged**: ISO-8601 时间戳
**Priority**: medium
**Status**: pending
**Area**: frontend | backend | infra | tests | docs | config

### Requested Capability
用户想要做什么

### User Context
为什么需要、他们想解决什么问题

### Complexity Estimate
simple | medium | complex

### Suggested Implementation
如何构建、可能扩展什么

### Metadata
- Frequency: first_time | recurring
- Related Features: existing_feature_name
- Pattern-Key: area.symptom（可选——功能通常按功能名去重；仅在重复出现的主题上使用 key，例如 api.missing-endpoint）

---
```

## ID 生成规则

格式：`TYPE-YYYYMMDD-XXX`
- TYPE：`LRN`（学习）、`ERR`（错误）、`FEAT`（功能）
- YYYYMMDD：当前日期
- XXX：序号或随机 3 个字符（例如 `001`、`A7B`）

示例：`LRN-20250115-001`、`ERR-20250115-A3F`、`FEAT-20250115-002`

## 条目解决

当问题被修复后，更新条目：

1. 将 `**Status**: pending` 改为 `**Status**: resolved`
2. 在 Metadata 之后添加解决记录块：

```markdown
### Resolution
- **Resolved**: 2025-01-16T09:00:00Z
- **Commit/PR**: abc123 或 #42
- **Notes**: 简要描述做了什么
```

其他状态值：
- `in_progress` - 正在处理中
- `wont_fix` - 决定不处理（在 Resolution notes 中添加原因）
- `promoted` - 已提升到工作区文件（`SOUL.md`、`TOOLS.md`、`AGENTS.md`）

## 提升到工作区记忆

当学习经验具有广泛适用性（非一次性修复）时，将其提升到工作区文件，使每个会话都能继承。

### 何时提升

- 学习经验适用于多个文件/功能
- 任何贡献者（人类或 AI）都应该知道的知识
- 防止重复犯错
- 文档化项目特定的约定

### 提升目标

| 目标文件 | 应包含的内容 |
|----------|-------------|
| `SOUL.md` | 行为准则、沟通风格、原则 |
| `TOOLS.md` | 工具能力、使用模式、集成注意事项 |
| `AGENTS.md` | 工作流、委派模式、自动化规则 |

当学习经验特定于你正在工作的项目仓库（而非工作区）时，改为提升到该项目的 Agent 文件（例如其 `AGENTS.md`）。

### 如何提升

1. **精炼**学习经验为简洁的规则或事实
2. **添加**到目标文件的适当位置（如文件不存在则创建）
3. **更新**原始条目：
   - 将 `**Status**: pending` 改为 `**Status**: promoted`
   - 添加 `**Promoted**: SOUL.md`、`TOOLS.md` 或 `AGENTS.md`

### 提升示例

**学习记录**（详细版）：
> 项目使用 pnpm workspaces。尝试了 `npm install` 但失败。
> lock file 是 `pnpm-lock.yaml`。必须使用 `pnpm install`。

**在 TOOLS.md 中**（简洁版）：
```markdown
## Build & Dependencies
- 包管理器：pnpm（非 npm）- 使用 `pnpm install`
```

**学习记录**（详细版）：
> 修改 API 端点时，必须重新生成 TypeScript 客户端。
> 忘记这步会导致运行时类型不匹配。

**在 AGENTS.md 中**（可执行版）：
```markdown
## API 修改之后
1. 重新生成客户端：`pnpm run generate:api`
2. 检查类型错误：`pnpm tsc --noEmit`
```

## Pattern-Key 分类体系

`Pattern-Key` 是所有三个日志文件中条目的稳定去重和复现 key：
关键词搜索会遗漏语义相同但措辞不同的条目，而共享 key 则不会——可靠的 key 是 `Recurrence-Count` 和提升规则生效的基础。

**格式**：`area.symptom` — 恰好两级，小写，连字符分隔
（例如 `deps.module-not-found`）。保持症状描述足够通用以便复现：key 中不要包含文件名、版本号或主机名。

| Area | 范围 | 示例 Key |
|------|------|----------|
| `api` | 外部 API/服务行为 | `api.rate-limit`、`api.schema-mismatch`、`api.missing-endpoint` |
| `auth` | 凭证、令牌、权限范围 | `auth.token-expired`、`auth.missing-scope` |
| `build` | 编译、打包、CI | `build.type-error`、`build.missing-artifact` |
| `config` | 配置文件、环境变量、设置 | `config.missing-env`、`config.invalid-json` |
| `deps` | 包管理器、依赖 | `deps.module-not-found`、`deps.npm-error`、`deps.version-conflict` |
| `fs` | 文件系统 | `fs.no-such-file`、`fs.permission-denied` |
| `net` | 网络连接 | `net.connection-refused`、`net.timeout` |
| `runtime` | 语言/运行时错误（以上未涵盖） | `runtime.type-error`、`runtime.python-exception` |
| `shell` | Shell/CLI 机制 | `shell.command-not-found`、`shell.nonzero-exit` |
| `vcs` | Git 及其他版本控制 | `vcs.fatal-error`、`vcs.merge-conflict` |
| `simplify` / `harden` | 来自 simplify-and-harden 流的代码质量模式 | `simplify.dead_code`、`harden.input_validation` |

**规则：**

1. **先复用再新建**：`grep -rh "Pattern-Key:" .learnings/ | sort -u` — 近似匹配优于新建 key。
2. **每条手动条目一个 key**；自动扫描的 WorkBuddy 条目可能携带多个——在分类审核时合并为一个。
3. **谨慎新建 area**——仅在多个条目会共享同一个 area 时才创建。
4. **通用扫描 key**（`runtime.error`、`runtime.failure`）表示"未分类"——在审核时替换为具体 key。

## 重复模式检测

如果记录的内容与已有条目相似：

1. **优先按 key 搜索**：`grep -n "Pattern-Key: area.symptom" .learnings/*.md`
   ——这是默认的去重检查，能捕获关键词搜索遗漏的不同措辞
2. **备选关键词搜索**：`grep -ri "keyword" .learnings/` 用于查找未设置 key 的条目
3. **合并而非重复**：命中时更新已有条目——增加 `Recurrence-Count`、设置 `Last-Seen`、添加 `**See Also**`——而非创建新条目
4. **提升优先级**如果问题持续复现
5. **考虑系统性修复**：重复出现的问题通常意味着：
   - 知识缺失（→ 提升到 `TOOLS.md` 或 `SOUL.md`）
   - 自动化缺失（→ 添加到 `AGENTS.md`）
   - 架构问题（→ 创建技术债务 Ticket）

## 简化与加固反馈流

使用此工作流从 `simplify-and-harden` Skill 中摄取重复模式，并将其转化为持久的提示指导。

### 摄取工作流

1. 从任务摘要中读取 `simplify_and_harden.learning_loop.candidates`。
2. 对每个候选项，使用 `pattern_key` 作为稳定的去重 key。
3. 在 `.learnings/LEARNINGS.md` 中搜索已有该 key 的条目：
   - `grep -n "Pattern-Key: <pattern_key>" .learnings/LEARNINGS.md`
4. 如果找到：
   - 增加 `Recurrence-Count`
   - 更新 `Last-Seen`
   - 添加 `See Also` 链接到相关条目/任务
5. 如果未找到：
   - 创建新的 `LRN-...` 条目
   - 设置 `Source: simplify-and-harden`
   - 设置 `Pattern-Key`、`Recurrence-Count: 1` 和 `First-Seen`/`Last-Seen`

### 提升规则（系统提示反馈）

将重复模式提升到 Agent 上下文/系统提示文件中，当满足以下所有条件时：

- `Recurrence-Count >= 3`
- 出现在至少 2 个不同的任务中
- 发生在 30 天的时间窗口内

提升目标：`SOUL.md`、`TOOLS.md` 或 `AGENTS.md`（工作区），或者当模式是项目特定时提升到项目自身的 Agent 文件。

将提升的规则写为简短的预防规则（编码前/编码中该做什么），而非冗长的事件记录。

## 定期回顾

在自然断点时回顾 `.learnings/`：

### 何时回顾
- 开始新的重要任务之前
- 完成一个功能之后
- 在处理有历史学习记录的区域工作时
- 活跃开发期间每周一次

### 快速状态检查
```bash
# 统计待处理的条目数
grep -h "Status\*\*: pending" .learnings/*.md | wc -l

# 列出待处理的高优先级条目
grep -B5 "Priority\*\*: high" .learnings/*.md | grep "^## \["

# 查找特定区域的学习记录
grep -l "Area\*\*: backend" .learnings/*.md
```

### 回顾操作
- 解决已修复的条目
- 提升适用的学习经验
- 关联相关条目
- 升级重复出现的问题

## 检测触发器

当你注意到以下情况时自动记录：

**修正**（→ 以 `correction` 类别记录学习）：
- "不对，不是这样的..."
- "实际上，应该是..."
- "你搞错了..."
- "那个已经过时了..."

**功能请求**（→ 记录功能请求）：
- "能不能也..."
- "我希望你能..."
- "有没有办法..."
- "为什么你不能..."

**知识缺口**（→ 以 `knowledge_gap` 类别记录学习）：
- 用户提供了你不知道的信息
- 你引用的文档已过时
- API 行为与你的理解不符

**错误**（→ 记录错误条目）：
- 命令返回非零退出码
- 异常或堆栈跟踪
- 意外的输出或行为
- 超时或连接失败

## 优先级指南

| Priority | 何时使用 |
|----------|----------|
| `critical` | 阻塞核心功能、有数据丢失风险、安全问题 |
| `high` | 影响重大、影响常用工作流、重复出现的问题 |
| `medium` | 影响适中、存在变通方案 |
| `low` | 轻微不便、边缘情况、锦上添花 |

## Area 标签

用于按代码区域筛选学习记录：

| Area | 范围 |
|------|------|
| `frontend` | UI、组件、客户端代码 |
| `backend` | API、服务、服务端代码 |
| `infra` | CI/CD、部署、Docker、云 |
| `tests` | 测试文件、测试工具、覆盖率 |
| `docs` | 文档、注释、README |
| `config` | 配置文件、环境、设置 |

## 最佳实践

1. **立即记录** - 问题发生后上下文最鲜活
2. **具体明确** - 未来的 Agent 需要快速理解
3. **包含复现步骤** - 尤其是错误
4. **关联相关文件** - 使修复更容易
5. **建议具体修复方案** - 而非仅仅"调查一下"
6. **使用一致的类别** - 便于筛选
7. **积极提升** - 不确定时，添加到 `TOOLS.md` 或 `SOUL.md`
8. **定期回顾** - 陈旧的学习记录会失去价值

## Gitignore 选项

**学习记录保留在本地**（每个开发者独立）：
```gitignore
.learnings/
```

此仓库默认采用此方式，避免意外提交敏感或杂乱的本地日志。

**在仓库中跟踪学习记录**（团队共享）：
不要添加到 .gitignore - 学习记录成为共享知识。

**混合方式**（跟踪模板，忽略条目）：
```gitignore
.learnings/*.md
!.learnings/.gitkeep
```

## 升级与卸载

升级前请阅读 `CHANGELOG.md`——其中包含每个版本的说明，Hook 变更需要重新复制 Hook 并重启网关。
要禁用或移除 Skill，请按 `references/uninstall.md` 操作：
`.learnings/` 是用户数据（删除前请审核），已提升到 `SOUL.md`/`TOOLS.md`/`AGENTS.md` 的内容会保留，直到手动删除。

## 自动提取为 Skill

当学习经验的价值足以成为可复用 Skill 时，使用提供的辅助工具将其提取出来。

### Skill 提取条件

学习经验在满足以下**任一**条件时符合提取资格：

| 条件 | 描述 |
|------|------|
| **重复出现** | 有 `See Also` 链接指向 2 个以上相似问题 |
| **已验证** | 状态为 `resolved` 且有有效的修复方案 |
| **非显而易见** | 需要实际调试/调查才能发现 |
| **广泛适用** | 非项目特定；在多个代码库中有用 |
| **用户标记** | 用户说"把这个保存为 Skill"或类似表达 |

### 提取工作流

1. **识别候选项**：学习经验满足提取条件
2. **运行辅助工具**（或手动创建）：
   ```bash
   ~/.workbuddy/skills/self-improving-agent-cn/scripts/extract-skill.sh skill-name --dry-run
   ~/.workbuddy/skills/self-improving-agent-cn/scripts/extract-skill.sh skill-name
   ```
3. **自定义 SKILL.md**：用学习内容填充模板
4. **更新学习记录**：将状态设为 `promoted_to_skill`，添加 `Skill-Path`
5. **验证**：在新的会话中读取 Skill，确保其自包含

### 手动提取

如果你偏好手动创建：

1. 创建 `skills/<skill-name>/SKILL.md`
2. 使用 `assets/SKILL-TEMPLATE.md` 中的模板
3. 遵循 [Agent Skills 规范](https://agentskills.io/specification)：
   - YAML 前置元数据包含 `name` 和 `description`
   - 名称必须与文件夹名匹配
   - Skill 文件夹内不能有 README.md

### 提取检测触发器

注意以下信号表明学习经验应成为 Skill：

**在对话中：**
- "把这个保存为 Skill"
- "我老是遇到这个问题"
- "这对其他项目也有用"
- "记住这个模式"

**在学习条目中：**
- 多个 `See Also` 链接（重复出现的问题）
- 高优先级 + 已解决状态
- 类别：`best_practice` 且广泛适用
- 用户反馈称赞该解决方案

### Skill 质量门槛

提取前验证：

- [ ] 解决方案已经过测试并可工作
- [ ] 描述在没有原始上下文的情况下依然清晰
- [ ] 代码示例自包含
- [ ] 没有项目特定的硬编码值
- [ ] 遵循 Skill 命名约定（小写、连字符）

---

> **来源**：基于 [pskoett/self-improving-agent v4.0.0](https://github.com/pskoett/self-improving-agent) 翻译，MIT 许可证。
> 翻译日期：2026-07-29
