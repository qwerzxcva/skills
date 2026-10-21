# Skill 模板

用于从学习记录中提取创建 Skill 的模板。复制并自定义使用。

---

## SKILL.md 模板

```markdown
---
name: skill-name-here
description: "简洁描述何时以及为何使用此 Skill。包含触发条件。"
---

# Skill 名称

简要介绍此 Skill 解决的问题及其来源。

## 快速参考

| 场景 | 操作 |
|------|------|
| [触发条件 1] | [操作 1] |
| [触发条件 2] | [操作 2] |

## 背景

为什么这个知识很重要。解决了什么问题。来自原始学习记录的上下文。

## 解决方案

### 分步操作

1. 第一步及代码或命令
2. 第二步
3. 验证步骤

### 代码示例

\`\`\`language
// 示例代码，演示解决方案
\`\`\`

## 常见变体

- **变体 A**：描述及如何处理
- **变体 B**：描述及如何处理

## 注意事项

- 常见错误或警告 #1
- 常见错误或警告 #2

## 相关

- 相关文档链接
- 相关 Skill 链接

## 来源

从学习记录中提取。
- **Learning ID**: LRN-YYYYMMDD-XXX
- **Original Category**: correction | insight | knowledge_gap | best_practice
- **Extraction Date**: YYYY-MM-DD
```

---

## 精简模板

适用于不需要所有部分的简单 Skill：

```markdown
---
name: skill-name-here
description: "此 Skill 的功能和使用时机。"
---

# Skill 名称

[用一句话描述问题]

## 解决方案

[直接给出解决方案及代码/命令]

## 来源

- Learning ID: LRN-YYYYMMDD-XXX
```

---

## 带脚本模板

适用于包含可执行辅助工具的 Skill：

```markdown
---
name: skill-name-here
description: "此 Skill 的功能和使用时机。"
---

# Skill 名称

[介绍]

## 快速参考

| 命令 | 用途 |
|------|------|
| `./scripts/helper.sh` | [做什么] |
| `./scripts/validate.sh` | [做什么] |

## 使用方法

### 自动化（推荐）

\`\`\`bash
./skills/skill-name/scripts/helper.sh [args]
\`\`\`

### 手动步骤

1. 第一步
2. 第二步

## 脚本

| 脚本 | 描述 |
|------|------|
| `scripts/helper.sh` | 主要工具 |
| `scripts/validate.sh` | 验证检查器 |

## 来源

- Learning ID: LRN-YYYYMMDD-XXX
```

---

## 命名约定

- **Skill 名称**：小写，连字符分隔
  - 正确：`docker-m1-fixes`、`api-timeout-patterns`
  - 错误：`Docker_M1_Fixes`、`APITimeoutPatterns`

- **描述**：以动词开头，提及触发条件
  - 正确："处理 Apple Silicon 上的 Docker 构建失败。当构建因平台不匹配而失败时使用。"
  - 错误："Docker 相关内容"

- **文件**：
  - `SKILL.md` - 必需，主要文档
  - `scripts/` - 可选，可执行代码
  - `references/` - 可选，详细文档
  - `assets/` - 可选，模板

---

## 提取清单

从学习记录创建 Skill 之前：

- [ ] 学习记录已验证（状态：resolved）
- [ ] 解决方案具有广泛适用性（非一次性）
- [ ] 内容完整（包含所有需要的上下文）
- [ ] 名称遵循约定
- [ ] 描述简洁但有信息量
- [ ] 快速参考表格可操作
- [ ] 代码示例已测试
- [ ] 来源学习 ID 已记录

创建之后：

- [ ] 将原始学习记录更新为 `promoted_to_skill` 状态
- [ ] 在学习记录元数据中添加 `Skill-Path: skills/skill-name`
- [ ] 在新会话中读取 Skill 以验证自包含性
