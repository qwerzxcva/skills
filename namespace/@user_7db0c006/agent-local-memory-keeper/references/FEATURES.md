# 进阶能力详解

六项核心记忆增强能力（§1–§6）+ 召回调优（§7–§9）。功能变更以根目录 `CHANGELOG.md` 为权威源。

---

## 1. RRF 多信号召回（#P0）

**问题**：原 recall 用单点积混合分排序，对"换种说法""只部分词重叠"的记忆容易漏召回。

**做法**：采用 RRF（Reciprocal Rank Fusion）多信号融合排序。每条记忆由多路弱信号各自排名，再用 `fused += 1/(k+rank)`（k=60）汇总：

| 信号 | 含义 |
|---|---|
| `sem` | 语义混合分 = `0.6·emb_c + 0.3·tf + 0.2·syn_hit`（主信号，兼作召回地板） |
| `jac` | Jaccard 词重叠 `_sim(query, text)`（中英混合 token） |
| `rec` | 时间衰减 `recency(accessed/created)`，越新越高 |
| `conf` | 记忆自身置信度 `confidence` |
| `brand` | query/记忆 共同提及品牌占比（仅当 query 含品牌时参与） |

召回门 = `sem>=min_score` ∪ 强信号(substring/brand/syn 命中) ∪ `fused>=rrf_weak`。在"不退化旧召回"与"补强部分匹配"间取平衡。

**验证**：品牌重叠能把 Redis 记忆顶到首位；改写措辞召回正确。

**边界**：recency/confidence 信号可能让"零词重叠但最近刚用过"的记忆越过弱门浮出；重要结果仍建议先看分数/summary。

---

## 2. 主动矛盾 / 重复扫描（#P0）

**问题**：记重了、或新结论与旧结论打架，长期没人发现。

**做法**：纯词法零依赖的矛盾/重复检测：先按共享标签/品牌/主体预筛候选对，再用 Jaccard 预筛（≥0.3），最后算 embedding 余弦（≥0.7）标记疑似矛盾/重复。只报告候选对供裁决，不合并不删。

**用法**：
```bash
python scripts/memory_ops/__init__.py doctor --contradictions
# 或自动软标记：doctor --contradictions --fix  → 双方 relations.conflict 互记对方 id（非破坏性）
```
**返回**：`contradiction_candidates: [{a, b, score, summary_a, summary_b, shared}]`，降序。

**边界**：余弦阈值 0.7 偏向"近重复"；逻辑冲突但措辞不同的记忆可能漏检——这类靠 `deposit --corrects` 显式闭环更稳。

---

## 3. 记忆版本链 + 真回滚（#P0）

**问题**：`overwrite` 原地改写了内容，改错了想回到旧版却没有历史。

**做法**：
- `overwrite` 改前自动把当前版快照到 `versions/<id>.v<N>.json`（`_snapshot_version`，同版不重复）。
- `versions --id <id>` 列出历史版本（含摘要），`rollback --id <id> --to-version N --yes` 恢复：
  - 先快照当前版（undoable），再载入目标版本，`version=当前+1`、`restored_from=N`、`status=active` 落盘；
  - 更新索引与向量/倒排。
- 回滚后仍可用 `rollback` 再回到任意版本（版本链保留，`versions` 显示 `[1,2,...]`）。

**用法**：
```bash
python scripts/memory_ops/__init__.py versions --id LRN-20260720-003
python scripts/memory_ops/__init__.py rollback --id LRN-20260720-003 --to-version 1 --yes
```

**验证**：deposit→overwrite(v2, 快照 v1)→rollback 到 v1（成为 v3, restored_from=1）→versions 显示 [1,2]，回滚可再撤销。测试通过。

---

## 4. 可视化 Dashboard（#P1）

**问题**：记了一堆记忆，结构/矛盾/聚类看不出来。

**做法**：`dashboard` 生成**单文件、零依赖** HTML（`store/dashboard.html`），双击即开。包含：健康卡片、记忆树（按 category 聚合）、分层/召回策略、聚类关系图、矛盾高亮、全部记忆表。

**用法**：先 `cluster`（才有聚类图）→ `dashboard` → 浏览器打开。

**边界**：未聚类时聚类图提示"先跑 cluster"；聚类图为关系结构图（非真实 2D 坐标降维）。

---

## 5. 元记忆：召回策略可审计 / 可微调（#P1）

**问题**：召回为什么这么排，是个黑盒；想针对自己的语料调权重却无从下手。

**做法**：
- 默认权重落盘进 `store/meta.json` 的 `recall_strategy`（`report` 时写入），`dashboard` / `report` 直接展示——"为什么这么排"可解释。
- 可在 `config.json` 的 `recall` 块逐项覆盖（覆盖项在 `recall_strategy_overridden` 标注）：
```json
{ "recall": { "rrf_k": 40, "min_score": 0.04, "sem_emb": 0.7 } }
```
- `_rank_query` 读取该配置（config 优先于默认），权重即时生效、无需改代码。

**配置文件放哪（容易踩）**：候选两处，**`store/config.json`（标准位，优先）→ `root/config.json`**
（兼容旧库，兜底），同名键**后者胜**；历史遗留把参数写进 `keeper` 块也认（`recall` 块优先）。
改完**无需重启**：缓存键含配置内容签名，配置一变缓存自动失效。

**可覆盖的全部项**（见 `RRF_DEFAULTS`）分三类：
- **排序权重**：`sem_emb` / `sem_tf` / `sem_syn` / `rrf_k` / `min_score` / `rrf_weak` / `rrf_jac_min` /
  `sem_magnitude_blend` / `sem_exempt_lowconf_cos` / `semantic_gate` / `low_conf_downweight`
- **性能/缓存**：`cache_ttl_seconds`（召回缓存 TTL 秒；默认 60）、`ann_auto_large`
  （库 > 256 条时自动启用 ANN）
- **cross-encoder 重排（默认关）**：`rerank_enabled` / `rerank_model` / `rerank_top` /
  `rerank_weight` / `rerank_doc_chars`
```json
{ "recall": { "rerank_enabled": true, "rerank_top": 5, "rerank_doc_chars": 200, "rerank_weight": 0.6 } }
```
  - 语义：只对 RRF **top-N 的「内部顺序」**重排（**不改召回集合**、不动 N 之外的候选）；
    任何异常（模型缺失/加载失败/编码报错）**静默回退原序** —— "开着"最差等于"没开"。
  - 🔴 **代价（本机 CPU 实测，2026-09-16）**：模型约 **1.04GB**；
    **成本主项是「候选文档总字符数」，约 1.1 ms/字符**（不是条数）。
    **成本 ≈ 1.1ms × `rerank_top` × `rerank_doc_chars`**，与库规模无关（只重排 top-N）。
  - ✅ **默认档 = 实测出的「便宜档」（`top=5` / `doc_chars=200`）**：1.8s/次，拿到 **90%** 的质量增益。
  - **实测档位表**（76 条真实 query 开/关对照，报告第十三节）：

    | 档位 | hit@1 | hit@3 | MRR | p50 延迟 |
    |---|---|---|---|---|
    | 不开重排 | 0.566 | 0.789 | 0.686 | 0.30s |
    | **默认档 `top=5`×200 字** | **0.803** | 0.842 | 0.829 | **1.83s** |
    | `top=5`×1200 字 | 0.816 | 0.855 | 0.837 | 4.08s |
    | `top=20`×200 字 | 0.816 | 0.855 | 0.838 | 3.95s |
    | 满配 `top=20`×1200 字 | **0.829** | 0.868 | 0.849 | 11.65s |

    要「最后那 2.6 个点」，把两项都调大即可（约 6.4 倍成本）。**质量收益零倒退**：最多 24 条升 / 0 条降。
    ⚠️ 「约 0.7s/次」是**用 30 字合成短文本**测的，**低估约 20 倍**（上表为真实长度实测）。
  - 可选模型（fastembed 支持列表内）：`BAAI/bge-reranker-base`（中文可用）/
    `jinaai/jina-reranker-v2-base-multilingual` / `Xenova/ms-marco-MiniLM-L-6-v2`（英文，约 80MB 快）。
  - ⚠️ 首次下载中文模型若报 `401 Unauthorized`：设 `HF_HUB_DISABLE_XET=1` + `HF_ENDPOINT=https://hf-mirror.com`。

**查看**：
```bash
python scripts/memory_ops/__init__.py report   # 看 recall_strategy
```

**边界**：仅影响排序权重，不改变"召回集合门槛"的安全语义（语义地板 ∪ 强信号 ∪ RRF 弱门）；调参需自测召回质量。

---

## 6. 中文同义/改写召回弱？换神经 embedding 后端

**现象**：query 与记忆的表述差异大（如"装饰器缓存" vs "用 decorator 做 cache"），只有少量词重叠或完全没有同义词桥接时，默认词法向量可能漏召。

**根因**：默认 `AI_MEM_EMBED_BACKEND=fastembed`（开箱即用）；若显式设 `auto`，会依次探测 `fastembed` → `sentence_transformers`，都未安装则回退到**词法级**向量（字符 bi-gram + 词 hashing）。词法向量对"字面不完全重叠但语义等价"的改写天然弱于语义向量。

**解决**：安装任一神经后端即可，无需改业务代码：

```bash
# 推荐：ONNX 推理，无 torch，体积小
pip install fastembed

# 或传统 torch 路线
pip install sentence_transformers
```

然后启动时指定（`auto` 也会自动探测到）：

```bash
export AI_MEM_EMBED_BACKEND=fastembed
export AI_MEM_EMBED_MODEL=BAAI/bge-small-zh-v1.5   # 默认，可省略
python scripts/memory_ops/__init__.py recall --query "..."
```

`recall` 的语义混合分会自动使用更高质量的语义向量，RRF 其它信号（词重叠、recency、confidence、brand）保持不变。

**边界**：
- 首次使用会自动下载模型（需联网一次），之后完全离线。
- 若环境受限无法下载模型，仍可使用词法级；此时建议给记忆多打标签、或把同一经验用多种说法写进 `body`，靠 TF-IDF / 同义词桥接弥补。
- 切换后端后，已落盘的旧向量会被 `rebuild` / 下次 `recall` 自动检测并增量重嵌，无需手动迁移。

---

## 7. ANN 快速搜索的 50 条阈值

> 🔑 **一句话原则：ANN 不是越多越好——记忆 <50 条时硬开 ANN 反而是负优化（线性扫描更精确更快），仅 ≥50 条才自动启用，>256 条才需要显式 `--ann`。小库 / 中库别硬开。**

**现象**：记忆不到 50 条时，`recall --ann` 不会真正启用 ANN 索引，看起来"快速搜索没生效"。

**根因与取舍**：`_ann_candidates` 里硬阈值 `len(store) < 50` 时回退全量线性扫描。这不是功能缺失，而是**性能取舍**：
- 50 条以内，线性扫描 + embedding 余弦的计算量极小，通常比"建索引 + 索引查询"更快；
- 线性扫描结果更精确（无 ANN 近似损失）；
- 避免小库时反复建索引的额外 I/O。

**可调**：已通过环境变量 `AI_MEM_ANN_MIN_MEMORIES` 暴露阈值，默认 50：

```bash
# 想让 20 条就尝试建 ANN 索引
export AI_MEM_ANN_MIN_MEMORIES=20
python scripts/memory_ops/__init__.py recall --query "..." --ann
```

**建议**：保持默认 50 是最佳实践；只有明确需要测试 ANN 行为或库虽然小但查询延迟敏感时才调低。

---

## 8. 跨语言召回引导（中英混合环境）

**场景**：中文提问找英文记忆，或反过来。

| 信号通道 | 跨语言能力 | 说明 |
|---------|-----------|------|
| TF-IDF / Jaccard | 弱 | 中英文无直接词重叠 |
| Embedding 余弦 | **强**（需神经后端） | 多语言模型可跨语言语义匹配 |
| 品牌重叠 | **强** | "Redis"、"K8s" 等品牌名中英文一致 |
| 同义词子串 | 中 | 仅覆盖预置同义词表 |

**提升跨语言召回的 3 个实践**：

1. **双语标签**：`deposit` 时在 `tags` 中同时写中英文关键词（如 `缓存,cache,Redis`）。
2. **安装神经后端**：`fastembed` 默认模型具备中英跨语言语义能力（见 §7）。
3. **body 补充双语描述**：对高频跨语言经验，在 `body` 中补一句另一种语言的摘要。

**边界**：纯词法后端下，跨语言召回仅靠品牌名/英文术语重叠 + 双语标签弥补。

---

## 9. 批量导入 / 性能基准 / MCP 服务（运维与集成工具）

三类不属「记忆增强」但提升可操作性的工具，均以 `memory_ops` 引擎 op 形式提供，并经 `mem_bridge.py` 统一入口转发：

- **批量导入 `import`**：把既有经验库（JSONL / JSON / CSV / Markdown，或 `export --format jsonl` 的整库导出）批量灌入 keeper，复用 `deposit` 的去重 / 分类 / 落盘全流程；大批量走 `defer_index` + 末尾 `flush_memory_index` 一次落盘。**默认 `--dry-run` 预览、必须 `--execute` 才真正落盘**、`--keep-ids` 复用原 id、`--on-error skip|abort` 容错、`--report` 落逐条结果。适合把散落笔记 / 旧库一次性迁入，或跨库 round-trip 迁移。
- **性能基准 `benchmark`**：在隔离库上批量写入 N 条合成记忆测写入吞吐，再随机 recall M 次测 p50/p95/avg 时延与空召回率，输出 JSON 报告（`--out`）。默认全量扫描基线（确定可复现），`--ann` 测 ANN 加速比——用于容量规划与回归比对的客观数字。

> ⚠️ **`benchmark` 护栏（D5）**：**必须显式传 `--root <隔离目录>`**——引擎拒绝向默认真实库写入合成记忆（防污染召回结果）；经 `mem_bridge benchmark` 时 `--root` 为必填参数，缺失直接拒绝，**不会静默退化到真实库**。

- **MCP 服务 `mcp`**：纯 stdlib 实现 JSON-RPC 2.0 over stdio，零外部依赖，把 keeper 暴露为标准 MCP 服务（工具 `deposit / recall / doctor / stats / export`），可被 Claude Desktop / Cursor / 自研 agent 直接连接。长驻进程在 store 锁之外拉起，避免服务内部自锁死。

> ⚠️ **MCP 服务接入须知**：
> - **secrets 更严**：MCP `deposit` 命中 secrets 默认 **`raise` 拒绝写盘（fail-closed）**，比批量 `import` 的 `quarantine`（隔离落盘）更严；客户端收到结构化错误而非静默隔离。
> - **错误形态**：工具异常统一返回结构化 JSON `{"ok":false,"error":<异常类型>,"message":<文本>}`，便于程序化判断。
> - **`export` 大库防护**：`export` 支持 `limit` 截断（md 按 `## ` 记忆块、jsonl 按行），大库务必显式传 `limit` 防整库 dump 撑爆缓冲；仅应在可信本地客户端连接，勿暴露给不可信网络。
