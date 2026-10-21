---
slug: self-reflection
name: 三省引擎 v2.0 · 自我反省系统
displayName: 三省引擎 · 自我反省系统
version: 2.0.0
summary: 以「改变」为唯一 KPI 的反省引擎：四型反省 + 三级入口 + 三杠杆行动设计 + T+7 改变闭环。
description: 三省引擎 v2.0 把反省当成可执行的闭环：识别 → 反思 → 行动 → T+7 回查 → 分流修正。覆盖四型反省（A1 错误复盘 / A2 成功复盘 / A3 模式反省 / A4 了结反省）、三级入口（30 秒微反省 / 10 分钟标准 / 30 分钟+ 深潜）、三杠杆行动设计（环境改造 / 执行意图 / 问责伙伴）。配套日志脚本可归档、回查、聚合模式、计算验证率。
tags:
  - reflection
  - self-improvement
  - habit
  - journaling
  - mental-model
license: MIT
homepage: https://workbuddy.link/p/6wtswMsw9x29z7VqFppi8M
---

# 三省引擎 v2.0 · 自我反省系统

> 参考人类反省机制搭建 —— 以「改变」为唯一 KPI 的反省引擎
> 尹小辉 出品 · 2026-09-03 · 适用于 WorkBuddy / Claude Code / 通用 Agent 技能体系

## 唯一 KPI：改变

反省的目的只有一个 —— **改变**。

四个对象：行为的改变、认知的改变、自我认识的改变、与过去关系的改变。

检验只有三问：

1. 同境遇再来，做得不同了吗？
2. 想得不同了吗？
3. 放下了吗？

三个「否」，反省就是失败的 —— 无论过程多完整。**无改变产出的反省，本质是精神内耗。**

## 四型反省 · 先定目的再动流程

| 类型 | 目的 | 流程 |
|---|---|---|
| **A1** | 错误复盘 → 改进行为 | 九步深潜：情绪冷却 → 事实重构 → 归因矩阵 → 假设下探 → 偏差安检 → 三杠杆行动设计 |
| **A2** | 成功复盘 → 固化胜利 | 区分能力清单与运气清单，能力 × 条件的交集才是可复制配方 |
| **A3** | 模式反省 → 认识自己 | 同类问题 ≥ 2 次触发：画模式链、承认历史功能、给模式命名并替换 |
| **A4** | 了结反省 → 消化放下 | 写出 → 承认损失 → 收残值 → 封存。有些事的终点是放下，不是行动 |

另有 **模式 B** 每日三省（曾子忠 / 信 / 习三问）与 **模式 C** 项目复盘（AAR 四问 + 双栏固化）。

## 三级入口 · 别用大炮打蚊子

| 入口 | 时长 | 适用 |
|---|---|---|
| 微反省 | 30 秒 | 行动中的即时校正。三句话：差了什么 / 为什么 / 下次换什么动作 |
| 标准反省 | 10 分钟 | 三省日报、A1–A4 对应简表 |
| 深潜反省 | 30 分钟+ | 重大事件专用。九步全流程、模式完整分析 |

## 改变闭环 · v2.0 核心增量

```
反省 → 教训 → 行动设计 → T+7 回查 → 分流修正
```

| 回查结果 | 含义 | 下一步 |
|---|---|---|
| `verified` | 行为真的变了 | 关闭，教训升级为个人原则 |
| `untriggered` | 还没遇到该情境 | 等待，或重新设计触发条件 |
| `failed` | 触发了但没做 | 换杠杆：环境改造 / 加问责伙伴 |
| `third-time` | 认知没问题了 | 停止加深反省，专攻执行系统 |

> 验证率 < 50% 时，问题不在反省质量，在行动设计。
> 脚本 `verify` 自动管理回查队列，`patterns` 自动聚合同类事件。

## 三杠杆行动设计 · 环境优先于意志力

| 杠杆 | 做法 | 可靠性 |
|---|---|---|
| ① 环境改造 | 问「能否让这个错误**做不到**？」—— 错误路径加障碍，正确路径减障碍 | 最高 |
| ② 执行意图 | if-then：如果出现【触发情境】，我就【具体动作】 | 中 |
| ③ 问责伙伴 | 承诺发给指定的人，约定回查日（曾国藩「师友传阅」现代化） | 高（顽固项） |

## 理论依据 · 每一步都有出处

| 环节 | 人类机制 | 来源 |
|---|---|---|
| 目的分流 / 微反省 | 目标设定；行动中反思 | 目标理论；Schön |
| 情绪冷却 / 第三人称抽离 | 隔夜冷静；自我抽离 | Kross《Chatter》 |
| 摄像机视角 / 情绪粒度 | 事实与解读分离；情绪粒度 | CBT；Barrett |
| 差距评价 / 归因矩阵 | 事后回顾；三维归因 | 美军 AAR；Weiner |
| 假设下探 / 偏差安检 | 双环学习；自利偏差 · 后见之明 | Argyris；偏差研究 |
| 环境改造 / 执行意图 / 问责 | 摩擦力设计；if-then；承诺一致 | Wood；Gollwitzer；Cialdini |
| 了结通道 / 止损 | 蔡格尼克效应；自我同情 | Zeigarnik；Neff |
| 每日三省 / 行动校准 | 吾日三省吾身；知行合一 | 曾子；王阳明；曾国藩日课 |

## 安装 · 三步

```bash
# 方式 1：SkillHub 直接安装（推荐）
skillhub install self-reflection

# 方式 2：手动导入
# 1. 下载 self-reflection.skill（分发包）
# 2. 解压得到 self-reflection/ 目录（SKILL.md + references/ + scripts/）
# 3. 置入本机技能目录
```

## 触发词

`反省` · `复盘` · `吾日三省` · `吸取教训` · `日省` · `帮我放下这件事`

## 脚本命令速查

```bash
python scripts/reflection_log.py check       # 当日三省快检（30 秒）
python scripts/reflection_log.py add         # 归档一条反省（默认 T+7 回查）
python scripts/reflection_log.py list        # 列出待回查队列
python scripts/reflection_log.py verify      # T+7 回查：标 verified/failed/untriggered/third-time
python scripts/reflection_log.py patterns    # 模式聚合（同类自动归并）
python scripts/reflection_log.py stats       # 验证率统计（目标 ≥ 50%）
python scripts/reflection_log.py challenge   # 启动 / 续接 21 天三省挑战
```

数据本地化：`~/.self-reflection/log.db`（SQLite，零外部依赖）。

## 深入阅读

- **理论依据详表**：`references/theory.md`
- **8 套完整模板**：`references/templates.md`（微反省 / 标准 / A1-A4 / 每日三省 / AAR / 21 天挑战）
- **更新日志**：`CHANGELOG.md`

---

三省引擎 v2.0 · 尹小辉 出品 · 以改变为唯一 KPI