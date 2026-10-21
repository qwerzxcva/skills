# 恢复与排障手册（Recovery Runbook）

> 覆盖「跨进程锁失败 / 索引损坏 / SQLite 写失败 / 向量覆盖异常」四类高频故障的处置步骤。
> 所有命令默认 `root` 为你的记忆库；改路径加 `--root <库>`，或设 `AI_MEMORY_STORE` / 写 `~/.keeper/store_root`。

---

## 0. 第一性原则

1. **先备份，再动刀**：任何修复前先 `python scripts/memory_ops/__init__.py backup --root <库>`（见 §4）。
2. **只读优先**：`doctor` 默认只报告不动盘；确认后再加 `--fix` / `--repair`。
3. **不丢原始文件**：损坏文件移入同级 `corrupt/` 隔离区（保留原文，可 `--restore` 还原），不删除。

---

## 1. 跨进程写锁获取失败（lock fail-open）

**现象**：日志出现
```
[keeper] 警告(N): 获取跨进程写锁失败 ...（并发写可能丢 index 条目）
[keeper-json] {"event":"lock_fail_open", ...}
```
keeper 的写锁是 **fail-open**（拿不到锁也继续写，避免单点卡死），但并发写可能让 `index.json`/`index.db` 丢条目。

**处置**：
- 确认是否**多个 keeper 进程同时写同一库**（如 daemon + 手动命令 + 钩子并发）。同一库避免并行写。
- 若确需严格互斥，设环境变量 `KEEPER_LOCK_FAIL_CLOSED=1` 让拿不到锁直接报错（快速暴露并发源头），而非静默丢条目。
- 事后用 `doctor --fix` 重建索引（`index_without_file` / `orphan_files` 会补登记漏掉的条目）。

---

## 2. 索引与文件不一致 / 孤儿 / 损坏

**现象**：`doctor` 报告 `missing_files`（索引有、磁盘无）/ `orphan_files`（磁盘有、索引漏）/ `corrupt`（JSON 解析失败）。

**处置**：
- 只读预览：`python scripts/memory_ops/__init__.py doctor --root <库>`
- 安全修复：`python scripts/memory_ops/__init__.py doctor --fix --root <库>`
  - 损坏文件自动隔离进 `corrupt/`（仍可 `--restore <文件>` 还原）；
  - `orphan_files` 重新登记进索引；`missing_files` 清理悬空索引条目。
- 若 `doctor` 自身也读不了索引：直接重建——删除/改名 `index.json` 后重跑 `doctor --fix`（会从磁盘文件全量重建）。`index.db`（SQLite）损坏见 §3。

---

## 3. SQLite 权威源写失败（save_index 降级）

**现象**：
```
[⚠ save_index] SQLite 写失败(N): ...（已降级写 index.json 兜底，但权威源可能与文件不一致）
[keeper-json] {"event":"save_index_sqlite_fail", ...}
```
keeper 的双写策略：SQLite 是权威、index.json 是兜底。SQLite 写失败时降级写 index.json，**但两者可能短暂不一致**。

**处置**：
- 通常是磁盘满 / 权限 / 被杀导致。先解决底层存储问题。
- 设 `KEEPER_SAVE_STRICT=1` 让 SQLite 写失败直接抛错（流水线可感知、而非带病运行）。
- 修复后跑 `doctor --fix` 重对齐 SQLite 与 index.json（_db_upsert_entries 会重插权威条目）。
- SQLite WAL 残留：`backup` 已自动 `wal_checkpoint(TRUNCATE)`，正常单文件自包含；若手动拷库，先跑一次 `doctor` 触发 checkpoint。

---

## 4. 备份与还原

**备份**（推荐定期 + 发布前）：
```
python scripts/memory_ops/__init__.py backup --root <库>
```
- 备份前自动 `PRAGMA wal_checkpoint(TRUNCATE)`，保证 `index.db` 单文件自包含（见 F21）。
- 备份含记忆文件 + `index.json` + `index.db` + `taxonomy.json` + `clusters.json`。

**还原**：用备份目录整体覆盖回 `root`（备份即快照，无增量合并）。还原后跑 `doctor` 确认一致。

---

## 5. 向量覆盖异常（F21 指标）

**查看**：`python scripts/memory_ops/__init__.py stats --root <库>` 现含 `vector_coverage: {embedded, total, coverage}`。
- `coverage` 偏低：大量记忆尚未嵌入语义向量（召回退化为关键词）。
- **修复**：`python scripts/memory_ops/__init__.py embed --root <库>`（或 `doctor --fix` 内嵌回填）补全向量。
- `embedded=None`：vectors 表不可达（DB 未初始化/损坏）→ 先 §3 修复 SQLite。

---

## 6. 投资域专项

- `doctor` 现额外跑 **投资域不变式 lint**（`investment_invariants`）：**active** 的 verified factor/system 若缺 `validated_by` 出边，列入 `hints`（`severity:info`，**可选提示而非违规**，已降级）；`archived`/`superseded` 等非 active 条目自动排除（计入 `excluded_inactive`）。
  - 可选改进：对每条 verified 记忆 `link <ID> validated_by <其通过测试ID>`；不改不影响使用。
- 子域非法：`investment_seed.py` 播种时若子域不在 {data_catalog, factor, factor_test, system, data_integrity, backtest_integrity} 会**告警不阻断**。
- 分类树未生效（heat_budget 不提权）：`python scripts/investment_bridge.py seed --domain investment` 会合并 `references/investment_taxonomy.json` 到 `store/taxonomy.json`。

---

## 7. 发布后置校验（F3）

发布到 SkillHub 后，**务必**确认平台已把新版本置为 current：
```
python scripts/memory_ops.py release-audit     # 本地日志 ↔ 平台真实版本对账
```
- 这是本 skill 自带的发布账本，不依赖发布器版本。退出码：`0` 一致 / `2` 漂移 / `3` **未知**（断网、超时就是 3，**不是**出错）。
- 要处理的是两类：`missing_log`（平台发了、日志没记）与「本地落后线上」（多机并行时这正是**双主**的前兆，先把线上包取回做基准）。`bundled` / `unreleased_local` 只提示、不算漂移。
- 若 `latestVersion` 仍是旧版：去 SkillHub 后台手动「设为 current」（历史曾实证发布后未自动置）。

---

> 排障口诀：**先备份 → 只读 doctor 看报告 → 确认后 --fix/--repair → 再 doctor 复核 → 发布用 verify_publish 校验 current。**
