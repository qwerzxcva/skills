---
name: android-dev-workflows
description: |
  Android 工程工作流六件套。覆盖：需求拷问（烤问式对话收敛设计树）、Spec 固化（对话综合落盘）、TDD（红绿循环）、Bug 诊断（六阶段纪律，先建会变红的反馈回路）、双轴代码评审（规范轴 + Spec 轴独立报告）、架构体检（扫描加深机会并输出 HTML 报告）。

  方法论骨架源自 mattpocock/skills，Android 平台内容（Kotlin / Android / Gradle / ADB / Android Studio Profiler / LeakCanary）为 Android 重写。

  触发场景：
  - 用户说"帮我理一下需求"、"这个需求怎么做"、提出一句话需求，或准备开始一个边界不清的功能
  - 用户说"整理成 spec"、"把讨论结论固化"、"写个方案文档"
  - 用户希望测试先写地开发功能或修复 bug、提到"红绿重构"、"先写测试"、要求补单测
  - 用户说"诊断"、"排查"、"debug"，或报告报错 / 崩溃 / 异常 / 失败 / 卡顿
  - 用户要求"评审分支"、"评审这次改动"、"review 一下"
  - 用户说"架构体检"、"架构评审"、"看看哪里该重构"
---

# Android 工程工作流六件套

> 基于 Kotlin / Android / Gradle / ADB / Android Studio Profiler / LeakCanary，覆盖需求对齐到发布前评审的完整工程工作流。

## 核心能力总览

```
┌─────────────────────────────────────────────────┐
│  android-dev-workflows                            │
├─────────────────────────────────────────────────┤
│  00 需求拷问 ─ 烤问式对话，设计树分支收敛          │
│  01 Spec 固化 ─ 把对话综合成 docs/specs 文档      │
│  02 Android TDD ─ 红绿循环 + Android 接缝表       │
│  03 Bug 诊断 ─ 六阶段纪律，先建会变红的反馈回路    │
│  04 双轴代码评审 ─ 规范轴 + Spec 轴独立报告       │
│  05 架构体检 ─ 扫描加深机会，输出 HTML 报告        │
└─────────────────────────────────────────────────┘
```

## 快速路由

| 用户需求 | 参考模块 |
|----------|----------|
| 需求边界不清 / 帮我理需求 | 00 需求拷问 → `references/00-requirement-grilling.md` |
| 把讨论整理成 spec 文档 | 01 Spec 固化 → `references/01-to-spec.md` |
| 先写测试再开发 / 红绿重构 | 02 Android TDD（JUnit/Robolectric/mockk/turbine） → `references/02-tdd.md` |
| 排查报错 / 崩溃 / 卡顿 / 异常 | 03 Bug 诊断 → `references/03-bug-diagnosing.md` |
| 评审分支 / 评审这次改动 | 04 双轴代码评审 → `references/04-code-review.md` |
| 架构体检 / 看看哪里该重构 | 05 架构体检 → `references/05-architecture-review.md` |

## 完整开发工作流

```
1. 需求拷问 (00) → 设计树每个分支收敛
   ↓
2. Spec 固化 (01) → 输出 docs/specs/<feature-name>.md
   ↓
3. Android TDD (02) → 红 → 绿 → 重构循环
   ↓
4. 双轴代码评审 (04) → 规范轴 + Spec 轴
   ↓
5. Bug 诊断 (03) → 如遇问题，先建反馈回路
   ↓
6. 架构体检 (05) → 定期运行，寻找加深机会
```

## 核心纪律

1. **先收敛再动手** — 设计树前沿为空之前不写代码（见 `references/00-requirement-grilling.md`）
2. **Spec 只综合不采访** — `references/01-to-spec.md` 不写新问题，只固化已讨论内容
3. **测试只在预先约定的接缝上** — 没有确认的接缝不写测试（见 `references/02-tdd.md`）
4. **没有会变红的反馈回路，不准进入假设阶段** — 这是 `references/03-bug-diagnosing.md` 的灵魂
5. **双轴独立评审** — 规范轴与 Spec 轴分开报告，不在两轴间选"总冠军"（见 `references/04-code-review.md`）
6. **先圈范围再扫描** — 架构体检优先看近期频繁变动的区域，避免地毯式扫描（见 `references/05-architecture-review.md`）

## 参考文档

- `references/00-requirement-grilling.md` — 需求拷问（Android 必查维度、轮次格式）
- `references/01-to-spec.md` — 对话 → Spec 固化（含 Android 专项决策模板）
- `references/02-tdd.md` — Android TDD（JUnit/Robolectric/mockk/turbine）（好测试、接缝表、反模式、实操约定）
- `references/03-bug-diagnosing.md` — Bug 诊断六阶段（构建反馈回路 → 复现 → 假设 → 插桩 → 修复 → 收尾）
- `references/04-code-review.md` — 双轴代码评审（Android 崩溃/质量基线 + Fowler 坏味道基线）
- `references/05-architecture-review.md` — 架构体检（Android 典型坏信号、HTML 报告、拷问循环）
