---
name: complexity-scanner
slug: complexity-scanner
displayName: 项目复杂度检测工具
description: 检测项目文件复杂度（圈复杂度、认知复杂度、耦合度），提供拆分建议，降低耦合度。支持 iOS (Swift/ObjC)、Android (Kotlin/Java)、Web (TS/JS/React) 项目。
version: 1.0.0
---

# complexity-scanner 项目复杂度检测工具

检测项目文件复杂度，提供拆分建议，降低耦合度。支持 iOS、Android、Web 多平台项目。

## 适用场景

- 代码审查时快速发现高复杂度文件
- 重构前评估项目复杂度现状
- CI/CD 流水线中自动检测复杂度
- 团队统一代码质量标准
- 跨平台项目统一复杂度分析

## 使用方法

```bash
# 扫描当前目录
bash ~/.claude/skills/complexity-scanner/run.sh .

# 扫描指定项目
bash ~/.claude/skills/complexity-scanner/run.sh /path/to/project

# 只分析 TypeScript 文件
bash ~/.claude/skills/complexity-scanner/run.sh /path/to/project --lang ts

# 分析多种语言
bash ~/.claude/skills/complexity-scanner/run.sh /path/to/project --lang ts,swift,kotlin

# 输出 JSON 格式
bash ~/.claude/skills/complexity-scanner/run.sh /path/to/project --format json

# 保存报告到文件
bash ~/.claude/skills/complexity-scanner/run.sh /path/to/project --format json --output report.json

# 只看最复杂的 10 个文件
bash ~/.claude/skills/complexity-scanner/run.sh /path/to/project --top 10

# 只看严重问题
bash ~/.claude/skills/complexity-scanner/run.sh /path/to/project --critical-only
```

## 命令行选项

| 选项 | 简写 | 说明 | 默认值 |
|------|------|------|--------|
| `--lang` | `-l` | 只分析指定语言（逗号分隔） | 全部 |
| `--threshold` | `-t` | 圈复杂度告警阈值 | 15 |
| `--file-threshold` | | 文件行数告警阈值 | 300 |
| `--func-threshold` | | 函数行数告警阈值 | 50 |
| `--fanout-threshold` | | 依赖扇出告警阈值 | 10 |
| `--nesting-threshold` | | 嵌套深度告警阈值 | 4 |
| `--exclude` | `-e` | 排除目录（逗号分隔） | - |
| `--format` | `-f` | 输出格式（table/json/summary） | table |
| `--depth` | `-d` | 最大扫描深度（0=不限） | 0 |
| `--output` | `-o` | 输出 JSON 到文件 | - |
| `--top` | | 只显示最复杂的 N 个文件 | 全部 |
| `--critical-only` | | 只显示严重问题 | false |

## 支持的语言

| 语言 | 扩展名 | 平台 |
|------|--------|------|
| TypeScript | `.ts` | Web |
| JavaScript | `.js`, `.mjs`, `.cjs` | Web |
| TSX | `.tsx` | Web (React) |
| JSX | `.jsx` | Web (React) |
| Swift | `.swift` | iOS |
| Kotlin | `.kt`, `.kts` | Android |
| Java | `.java` | Android |
| Objective-C | `.m`, `.mm` | iOS |

## 分析指标

| 指标 | 说明 |
|------|------|
| **代码行 (LOC)** | 有效代码行数，不含空行和注释 |
| **函数数** | 文件内函数/方法数量 |
| **CC 最大** | 最大圈复杂度（分支/循环计数） |
| **CC 均值** | 平均圈复杂度 |
| **扇出 (Fan-out)** | 当前文件导入的外部依赖数 |
| **扇入 (Fan-in)** | 导入当前文件的其他文件数 |
| **嵌套深度** | 最大代码嵌套层级 |
| **耦合分** | 综合耦合度评分 |

## 复杂度等级

| 等级 | 评分范围 | 说明 |
|------|----------|------|
| 🟢 低 | < 15 | 代码结构良好 |
| 🟡 中 | 15-34 | 建议关注 |
| 🔴 高 | 35-59 | 建议重构 |
| ⛔ 危险 | ≥ 60 | 需要立即处理 |

## 建议类型

| 图标 | 类型 | 说明 |
|------|------|------|
| 📦 | split-file | 拆分文件 |
| 🧩 | extract-module | 提取模块 |
| 🔧 | reduce-complexity | 降低复杂度 |
| 🔗 | reduce-coupling | 降低耦合 |
| 📐 | reduce-nesting | 降低嵌套 |
| ✂️ | split-function | 拆分函数 |
| 💉 | use-dependency-injection | 使用依赖注入 |

## 依赖

- Node.js 18+
- npm（首次运行自动安装依赖）

## 特点

- **多平台支持**：统一分析 iOS/Android/Web 项目
- **AST 级分析**：TypeScript 使用 Compiler API 精确解析
- **语言感知**：每种语言使用定制的复杂度计算规则
- **耦合度分析**：跨文件 fan-in/fan-out 依赖分析
- **可操作建议**：针对每个问题给出具体拆分/解耦方案
