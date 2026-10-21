# 学习记录

开发过程中捕获的修正、洞察和知识缺口。

**类别**: correction | insight | knowledge_gap | best_practice
**区域**: frontend | backend | infra | tests | docs | config
**状态**: pending | in_progress | resolved | wont_fix | promoted | promoted_to_skill

## 状态定义

| 状态 | 含义 |
|------|------|
| `pending` | 尚未处理 |
| `in_progress` | 正在处理中 |
| `resolved` | 问题已修复或知识已整合 |
| `wont_fix` | 决定不处理（原因记录在 Resolution 中） |
| `promoted` | 已提升到 SOUL.md、TOOLS.md 或 AGENTS.md |
| `promoted_to_skill` | 已提取为可复用的 Skill |

## Skill 提取字段

当学习记录被提升为 Skill 时，添加以下字段：

```markdown
**Status**: promoted_to_skill
**Skill-Path**: skills/skill-name
```

示例：
```markdown
## [LRN-20250115-001] best_practice

**Logged**: 2025-01-15T10:00:00Z
**Priority**: high
**Status**: promoted_to_skill
**Skill-Path**: skills/docker-m1-fixes
**Area**: infra

### Summary
Docker 在 Apple Silicon 上因平台不匹配导致构建失败
...
```

---

