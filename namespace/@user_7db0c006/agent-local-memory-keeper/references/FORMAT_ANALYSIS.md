# 记忆系统文件格式与存储架构（当前实装）

> 📌 **功能变更以根目录 `CHANGELOG.md` 为唯一权威源**。

> 本文说明 agent-local-memory-keeper **当前真实**的存储架构与数据模型。
> 历史说明：早期曾以「每记忆一 JSON 文件 + index.json」为主格式，并评估过 SQLite 为"过度工程"；**`store/index.db`（SQLite，WAL）现为权威源**，本文以当前实装为准。

## 结论先行

**当前权威源 = `store/index.db`（SQLite，WAL）。**

- `entries` 表：每条记忆一行，`data` 列存**完整记忆 JSON**，其余列（id / category / scope / tier / status / importance / confidence / access_count / accessed_at / created_at / brand_mentions 等）为可索引字段。
- `embeddings` 表：持久化语义向量（含 `model` 列，后端切换自动失效重建）。
- `inverted` 表：标签 / 关键词倒排索引，支撑字段硬过滤。
- `memories/` 与 `memories/archive/`：真实 JSON 文件，**可整体备份 / 迁移 / 人眼检查**（与 SQLite 双向同步）。
- `index.json`：人类可读导出 / 兜底（SQLite 损坏时由 `rebuild` 从文件重建）。

> 设计取舍：SQLite 提供事务原子、并发安全、SQL 强检索与 ANN 向量近邻；JSON 文件保留"AI 像翻文件夹一样看记忆"的直观性与可调试性。二者并存，SQLite 拍板、文件可读可迁。

---

## 单条记忆 JSON 全字段数据模型

```json
{
  "id": "LRN-20260724-001",
  "category": "best_practice",        // best_practice / workflow / fact / preference / error / correction ...
  "summary": "一句话经验（AI 引用时最先读）",
  "body": "完整叙述 / 因果 / 反例",
  "tags": ["导出", "金蝶"],
  "scope": "universal",               // universal / project / ephemeral
  "project": "",                      // scope=project 时填项目标识
  "tier": "working",                  // seed / working / curated / core
  "status": "active",                 // active / superseded / archived
  "importance": 0.7,                  // 0~1，主排序信号
  "confidence": 1.0,                  // 0~1，置信度校准后微调
  "access_count": 0,                  // ⚠️ **不再自增**：频次权威已移到 store/recall_counts.json（见字段要点）
  "accessed_at": "2026-07-24T10:00:00",
  "created_at": "2026-07-24T09:00:00",
  "recorded_by": "agent",             // agent / workbuddy_sync / ...
  "version": 1,
  "relations": {
    "see_also": [],
    "superseded_by": "LRN-20260724-002",   // correction 推翻本记忆时填
    "corrected_by": "",
    "conflict": []
  }
}
```

### 字段要点
> 含 `type` 封闭清单、`settled`/`probe_until`/`thermal`、`route_type` 等格式分化渲染字段。当前引擎以 SQLite 权威源 + RRF 召回 + 置信度校准 + reflect 去重合并 + 格式分化渲染为底座。

- **`category`**：经验类型（旧字段，保留向后兼容，路由/分层/检索均以 `type` 为准）。已落地 `type` 封闭互斥清单（`TYPE_CANON` = BP/WF/PF/PREF/FACT/DOC）+ 判定规则表（`references/TYPE_TAXONOMY.md`），消除"AI 跨会话归类不一致"；`category` 只作追溯。
- **`status / tier / importance / confidence`**：状态、成熟度、重要度、置信度四轴。当前并存；后续版本明确分工——`importance` 主排序、`tier` 人工置顶档、`confidence` 校准微调（不再三轴重叠计量）。
- **访问频次（单一权威）**：权威存储是 **`<root>/store/recall_counts.json`**（`{id: {count, last}}`），写入方为 recall 命中 / `touch` / `recall --outcome` / 近重复吸收，**每次使用只计一次**。记忆文件里的 `access_count` **只作旧库兼容、不再自增**（历史真库 204/211 条恒 0，而热源有真值 —— 这正是「双写脱节」病根，已根治）。所有下游统一经 `_access_count_of()` 读该热源：`_decay`（沉淀门槛 + 排序权重）、`_doctor`（晋升筛选 + dashboard 频次列）、`_reflect`（归档续命）、`recall --filter "access_count>N"`、`promote_rules`。`accessed` / `accessed_from` 属**访问证据**（另一条线），驱动「7 天内使用 ≥3 次」的频率晋升。
- **`relations.superseded_by`**：correction 推翻旧记忆的关系边——后续版本 `correction` 不再作为独立"类别"占用配额，而是"新经验 `superseded` 旧经验 + 关系"。

---

## 为什么 SQLite 权威源 + 文件可读并存（当前实装）

1. **事务原子 / 并发安全**：多窗口并发由乐观 mtime 守卫 + 进程间锁串行化，避免半截写 / 双份脏数据。
2. **强检索 + 向量近邻**：SQL 字段过滤 + `embeddings` 表 ANN 检索（≥50 条持久化加速），千条库 query < 0.3s。
3. **可调试 / 可备份**：某条损坏只影响该文件（`doctor` 标 corrupt），`memories/` 整体可备份迁移，`index.json` 兜底。
4. **明文落盘（可读性优先）**：`summary`/`body` 与 `index.json` 摘要均为明文——便于人眼检查、grep 与脱敏分发。

> 何时才该考虑"纯单文件 / 纯数据库"二选一：当前混合架构在千条量级已验证够用；仅当达 10 万+ 条且需复杂联表全文索引时，才需进一步评估拆分。当前不急于改。

---

## 格式分化渲染（render_hot / render_cold）

记忆**只存一份 canonical 完整内容**（summary + body + tags + type + 元数据）；热 / 冷只是不同「渲染视图」，记忆在 hot↔cold 流动时**只换渲染、绝不丢信息**（设计基线 §6.2）。

| 呈现场景 | 函数 | 格式目标 |
|---|---|---|
| 热记忆（喂 LLM 前部 / primacy） | `render_hot(mem)` | 紧凑单行：`[TYPE] summary ｜ 标签… ｜ 要点…`；省 token、易解析、无 emoji 噪音；body 仅取首 60 字作「要点」 |
| 冷记忆（落向量 / embedding） | `render_cold(mem)` | 完整多行叙述：`[TYPE]` / `摘要:` / `详述:` / `标签:` / `范围:`；保留上下文与因果、关键词丰富，保 embedding 语义质量 |

- `recall` 会在每条结果附 `render` 字段：hot 用紧凑渲染、warm/cold 用完整渲染，消费方可直接拼进 prompt。（注：`render_hot`/`render_cold` 为内部渲染辅助函数，非 CLI 入口；`recall_v30` 等旧引擎函数已清理。）
- `_embed_text_for(mem)` 统一走 `render_cold`，即落向量文本用完整叙述（设计基线 §6.2）。更换渲染不影响 canonical 原文。

---

## 一句话总结

> 给 AI 用的本地记忆系统，**「SQLite 权威源 + JSON 文件可读可迁 + index.json 兜底」是当前实装的最优解**：原子、并发安全、检索强、可调试、可备份，且保留 AI 直接读文件的心智模型。
