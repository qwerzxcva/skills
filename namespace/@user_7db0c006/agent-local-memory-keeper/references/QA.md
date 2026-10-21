# QA · 常见问题与避坑速查（故障排查索引）

> 📌 **功能变更以根目录 `CHANGELOG.md` 为唯一权威源**。

> 本文件是**问题→解法**的故障排查索引（你"踩到某个坑"时来查）。
> 🤖 **主要供 AI 内部排查引用**：普通用户无需通读——直接对 AI 描述你遇到的问题，它会据此定位并对话式引导你解决（无需你自己翻这篇）。
> **红线 / 边界**的单一真源是 `SKILL.md`「红线与边界」；**用法类反模式**的单一真源是 `SKILL.md`「📌 反模式清单」；**高级功能触发时机**见 `SKILL.md`「场景对话实操」。本文件**不再重述红线**，只保留本节未覆盖的**操作细节**并标注指针。
> 如与 `SKILL.md` 某段不一致，以 `SKILL.md` 为准并请反馈。

> **⚡ 遇到问题先跑谁（速查决策）**：
> | 现象 | 先跑 | 说明 |
> |---|---|---|
> | 记不进 / 找不到 / embedding 降级 / 自动记没生效 | `doctor` + `audit`（对 AI 说人话，AI 会自动跑） | 读真实状态定位，对话式引导修复；`doctor` 七项绿红自检 |
> | **召回了已归档的记忆 / 该召回的没召回** | `doctor --fix` | 索引与文件漂移，以文件为准回填（见 §14） |
> | 手动改/删过 `memories/*.json` 后出错 | `rebuild` 或 `doctor --fix` | 重建索引/同步，记忆不丢（见 §四·4） |
> | 想看能开哪些功能 / 装好没 | `audit` / `doctor` | `audit` 答"该开哪些"，`doctor` 答"装好没" |

---

## 🆕 新手最常遇到的 5 个问题（先看这里）

> 下面 5 个是**新用户 90% 会碰到的**，按出现频率排序；点链接跳到详细解法。其余冷门问题在下方分节索引。

| # | 你大概率会问 | 一句话解法 | 详见 |
|---|---|---|---|
| 1 | **装完还要配置吗？** | 不用——装完即全开、零配置，直接能记能找 | [§一 Q：装完还要配置吗](#一安装与配置) |
| 2 | **第一次 recall 卡住 / 半天没反应？** | 多半在下载中文语义模型（约 90MB，会显示进度条）；不想等就设 `AI_MEM_EMBED_BACKEND=lexical` 零下载跑 | [§一 Q4b](#一安装与配置) |
| 3 | **钩子/弹窗是什么、是不是 bug？** | 不是 bug——是 AI 自动加载"和当前对话相关的记忆"，silent 模式无弹窗 | [SKILL.md「关于弹窗」/「钩子模式」] |
| 4 | **误删了记忆能恢复吗？** | 能——系统默认只软删/归档，从不真删；`recall --deep` 找回，`rebuild` 重建索引 | [§一 Q5 备份](#一安装与配置) / [§二](#二日常使用) |
| 5 | **守护进程/定时任务必须装吗？** | 不必——只想手动记/找可完全不装；要"自动记忆"才跑 `keeper_setup.py hooks --scheduler` 一条命令 | [§七 会话钩子](#七会话钩子) / [COOKBOOK] |

> 💡 想更省事？直接对 AI 说"帮我一键配好"，它替你跑完所有装后步骤，不用手敲任何命令。

---

## 一、安装与配置

**Q：装完 skill 还要配置吗？（开箱即用）**
- **不用。** 装完即全开、零配置：默认已启用 中文语义(fastembed) · silent 钩子(无弹窗) · 反馈校准 · 分类/分层/矛盾检测。`deposit`/`recall`/`reflect` 直接能用。
- **只有 2 项需你按需手动开**（都因外部/重资源，非常规默认）：① IMA 云端同步（需外部知识库）② 本地 LLM/Ollama（~5GB）。其余语义模型等一律开箱即用。
- 想一键确认就绪：跑 `python scripts/keeper_setup.py doctor`（绿红自检），或 `all`（零配置重跑一遍）。

**Q4：需要联网吗？**
- 默认**纯本地、零云端**。词法召回与 ANN 均本地；`fastembed` 为本地 ONNX 推理（仅首次下载模型需联网一次）。
- **线上模式**：若本机跑不了本地模型（无 GPU / 内存小 / 不想装），可改走「在线模型」——
  分类由线上 LLM 完成、语义向量由云端 embeddings 生成，**本地零模型、零算力**，首次落库后召回只做本地余弦。
  详见 `references/LIMITS.md` §「线上模型（无本地模型也能用）」。

**首次安装中文语义模型（fastembed）**
- 必须联网 ~10s-2min 让 `fastembed` 拉模型；**国内网络会自动 fallback 到 hf-mirror.com**；之后断网也完全可用（模型已缓存到 `~/.workbuddy/cache/agent-local-memory-keeper/models/`）。
- 想避免首次 `recall` 时才被动下载：跑 `python scripts/keeper_setup.py all`（含预热步骤，装完即下好）；或 `init --download-models` 预拉模型。
- 无网又想用语义召回：手动把模型文件拷到 `~/.workbuddy/cache/agent-local-memory-keeper/models/fast-bge-small-zh-v1.5/`（从能联网的机器拷）。

**Q4b：第一次 recall 卡住 / 半天没反应？**
- 大概率是首次加载语义模型在下载（约 90MB）。终端会输出 `[↓ embedding] 首次加载中文语义模型…` 进度提示，不再静默卡住。
- 若网络慢，系统已自动切 `hf-mirror.com`；仍慢可手动设 `HF_ENDPOINT=https://hf-mirror.com` 与 `HF_HUB_DISABLE_XET=1` 后重试。
- 若不想等，按 `Ctrl+C` 中断后设 `AI_MEM_EMBED_BACKEND=lexical` 即可零离线、零下载运行（召回质量略降）。

**Q4c：报错里看到 error_code（如 NET-001 / EMB-001）是什么意思？**
- 复杂错误会带 `error_code` 和 `next_steps` 数组，按数组里的步骤执行即可，不用猜。
- `NET-001` = 网络超时；`EMB-001` = 语义模型加载失败；`FS-001` = 文件权限不足；`UNEXPECTED` = 其他意外。每个都附 `doc_link` 指向本文对应位置。

**Q5：记忆存在哪？怎么备份？**
- 默认跨平台路径：Windows `~/AI记忆`、mac/Linux `~/.ai-memory`，首次自动建；改位置设 `AI_MEMORY_STORE` 或写 `~/.keeper/store_root`。
- 整库 `backup` 导出 ZIP，`restore` 恢复；`memories/` 与 `memories/archive/` 为真实文件，可整体复制迁移。
- 存储根可用 `AI_MEMORY_STORE` 环境变量覆盖。

---

## 二、日常使用

**Q1：误删了能恢复吗？**
- ① `versions --id <id>` 看历史版本 → `rollback --id <id> --to-version N --yes` 回滚（**任何写入都自动留快照**，不只是 overwrite）；
- ② `backup`/`restore` 整库 ZIP 恢复。
- 删除前优先用 `archive`（沉底不销毁，随时 `unarchive` 找回）。

**Q1b：记忆文件能直接手改 / 手删吗？**
- 不建议。记忆文件、`index.json`、`store/` 都由各 op 维护一致。务必走 op 操作。
- 若手动改/删导致索引脱节：跑 `rebuild`（重建索引与向量库，记忆本身不丢）或 `doctor --fix`（同步索引状态、剪枝悬空关系）。

**Q2：`reflect` 会删我的记忆吗？**
- 不会。`reflect` 只做去重 / 纠错 / 晋升 / 归档，**绝不删除** active 记忆。遗忘路径统一为 `decay`（确定性降权沉底）+ `reflect --auto`（归档到 `memories/archive/`，可经 `recall --deep` 找回）——整套机制无"批量硬删"命令，从设计上杜绝误删 active 记忆。

**Q6：`delete` 被拒 / 没生效？**
- 不带 `--yes` 会被安全拒绝、文件仍在。确定删除加 `--yes`；不确定先 `--dry-run` 预览。

**Q7：敏感信息会被记下来吗？**
- 不会。`deposit` 写前扫 secrets 一票否决；命中自动隔离进 `quarantine/`，可用 `list_quarantine` 列出、`review_quarantine --id <qid> --action release|purge|keep`（release 默认脱敏替换 `***` 后放行入活跃库；`--no-redact` 关脱敏）复审，绝不静默落盘。对 AI 说"看看被拦下的记忆 / 把那条放行"即可触发。
- ⚠️ **绝不记 secrets / token / 私钥 / 明文密钥**，只记提炼后的经验。

**Q10：可以批量导入历史会话吗？**
- 可以。两条路径：
  - **从 WorkBuddy 历史会话沉淀（推荐）**：AI 在 WB 会话用 `conversation_search` 检索历史会话 → 整理成文本 → `harvest --from-conversations --session <file>` 沉积（会话来源打 `wb_session` 标签 + 幂等去重，重复跑不重复沉积）。这是"WB 云记忆 → keeper 语义库"的桥。
  - **从现有 keeper 记忆自学习**：`harvest --self-learn` 跨记忆抽关键经验，再人工 review。
- ⚠️ **不要直接整库抄对话原文**——会污染召回、降低信噪比；`harvest --from-conversations/--session` 已做抽取 + 去重，只落"值得长期记的"经验点。

**Q11：怎么知道哪些被频繁召回、哪些在变冷？**
- 跑 `report`：看"分层概览"与"召回策略"，列 HOT/WARM/COLD 各层记忆数与最近被召回次数；`promote --auto` 自动晋升高频/已确认记忆，`report` 同时汇总"高频但未分类/低置信"候选。

**Q12：能跨设备同步吗？**
- **两条路，先看清差别再选**：

| | `backup` → ZIP → `restore` | `scripts/keeper_sync.py out` / `in` |
|---|---|---|
| 语义 | **整库克隆（覆盖式）** | **合并式同步**（按 id 覆盖 + 新增） |
| 目标机自己的新记忆 | ❌ **会被覆盖丢失** | ✅ 保留（包外独有条目不动） |
| 携带内容 | 全量：`memories/`（含 archive）+ `store/index.db` + `config.json` / `index.json` / `classifier.json` | 记忆本身（active+superseded+archived）；配置/分类器不搬 |
| 适合场景 | 换新电脑、灾难恢复、目标机不要自己的东西 | **两台电脑各干各活、双向轮流同步** |
| 落盘门槛 | `restore <zip> --yes` | `in --dir <目录> --execute`（默认仅预演） |

- **常用推荐**：多台电脑各干各活 → 用 `keeper_sync.py`（见 `COMMANDS.md`「独立脚本」一节与 `SKILL.md`「场景对话实操」⑥ 维护/进阶）。它走 export/import 而非拷 SQLite，**没有 WAL/SHM 撕裂风险**，且导入后自动做状态收敛 + 幂等自校验。
- 整库搬家/换机 → `backup` 导出 ZIP → 拷到另一台 → `restore <zip> --yes`。
- ❌ **不要直接 rsync / 网盘同步 `memories/` 与 `store/`**：SQLite WAL/SHM 可能跨设备撕裂（云同步盘还会产生冲突副本），必须先 `backup` 或停服。

**Q14：删了归档还能找回吗？**
- 能。归档是 `memories/archive/` 物理存在，`unarchive --id <id>` 即可迁回。**真删（`delete --yes`）后无任何途径恢复**——红线 A2/A3 见 `SKILL.md`「红线与边界」，操作上务必先 `archive` 后 `delete`。

**Q15：高级功能有哪些命令？不想翻文档。**
- 直接跑 `commands`：
  ```bash
  python scripts/memory_ops/__init__.py commands
  ```
- 它会列出所有命令、一句话用途、以及「日常三板斧」「每周整理」「换说法搜不到」等常用组合。

---

## 三、语义召回与跨语言

**Q3：中文换个说法搜不到？**
- 默认后端没装 `fastembed` 会回退**词法级**向量（字符 bi-gram），对无同义桥接的深度改写较弱。
- 中文用户推荐：① 装 `fastembed` 开真语义（改写召回率 ~30%→90%+）；或 ② 走**线上 embeddings**（云端生成向量，本机零模型）。装后跑 `report` 确认后端。

**Q8：中英文混合记忆怎么召回最好？**
- 系统用中英文混合分词 + RRF 多信号融合，**同语言内**效果最好。跨语言依赖三桥梁：① 共同英文术语/品牌名；② 神经/在线 embedding 的跨语言语义能力；③ 同义词子串命中。
- 最佳做法：关键术语中英文都写进 `tags`/`body`（如 `tags: "缓存,cache"`）；开神经/在线语义；双语关键描述补进 body。

**Q9：库膨胀怎么办？**
- ① <100 条 → `decay --apply` + `reflect --auto`；② 100-1000 条 → 注册每周自动化流水线；③ >1000 条 → 启用 ANN + 升级 taxonomy 给高频域独立热位。

**Q13：AI 反复"再确认"陷入死循环怎么办？**
- 默认 `feedback` 每会话 3 次 + `inject` 每会话 6 次双闸门，超过即跳过。三道闸：① 说"不用给我做置信度校准"；② 说"不用给我注入经验"；③ `KEEPER_FEEDBACK_SESSION_CAP=0` 全关。

---

## 四、避坑详解（❌错法 → ✅正法 → 💥踩了会怎样 → 🔧怎么避）

> 📌 本節是 `SKILL.md`「📌 反模式清单」的**场景化详解**：在 ❌→✅ 速查之外，补「踩了会怎样」+ 具体命令/检查。速查仍看 `SKILL.md` 那张表。
> 🔴 **红线级强保证**（删必须 `--yes` / `reflect` 绝不删 / 重要记忆分类强制 / IMA 强制脱敏）见 `SKILL.md`「红线与边界」，本節只展开它**未覆盖**的独特避坑。语义 / 跨语言类避坑见 §三。

### 1. 中文换说法搜不到
- ❌ **错法**：处于**已降级为词法**的状态（非正常态；默认是语义后端）时，用完全不同的说法搜同一件事。
- ✅ **正法**：装 `fastembed` 开真语义（中文改写召回率 ~30%→90%+），或走线上 embeddings（云端向量、本机零模型）。装后 `report` 确认后端。
- 💥 **踩了会怎样**：明明记过却 recall 不到，误以为"没记住"，又重复记一条 → 库里出现重复/低质记忆。
- 🔧 **怎么避**：`python scripts/memory_ops/__init__.py report` 看 `embed_backend`；若为 `lexical` 就装 `fastembed` 或设 `AI_MEM_EMBED_BACKEND=online`。

### 2. 跑 `audit` 报错 / 没建议
- ❌ **错法**：库才两三条就去跑 `audit` 看"该开哪些功能"。
- ✅ **正法**：先把库养到 ≥10 条再跑 `audit`。
- 💥 **踩了会怎样**：库太小，`audit` 给不出有意义的开启建议，你以为功能坏了。
- 🔧 **怎么避**：先正常使用一阵（记十几条）再 `audit`；或跳过 `audit` 直接看 `SKILL.md`「🔧 配置指引」按需开。

### 3. `converse` 跑得太频繁 / 自动记太多
- ❌ **错法**：把 `--set-threshold` 设得很低（如 3），每次对话都触发自主沉淀。
- ✅ **正法**：保持默认关，或 `--set-threshold 50`（每 50 轮才收尾一次）；"先别自动记"→ `KEEPER_AUTO_CAPTURE=0`。
- 💥 **踩了会怎样**：对话里噪音记忆暴涨、上下文被无关沉淀污染，且每次沉淀都吃 CPU。
- 🔧 **怎么避**：`converse --set-threshold 50`；或 `KEEPER_AUTO_CAPTURE=0` 全关自动记。

### 4. WorkBuddy 反复触发 inject（记忆被反复注入）
- ❌ **错法**：让 AI 在注入了记忆的上下文里继续"基于这些经验"长篇发挥，形成无界循环。
- ✅ **正法**：`KEEPER_INJECT_DAILY_CAP=N` 调高上限，或直接说"不用注入"切 silent。
- 💥 **踩了会怎样**：每轮都把同一批记忆灌进上下文，token 浪费、且 AI 陷入"复述经验"而非做事。
- 🔧 **怎么避**：`KEEPER_INJECT_DAILY_CAP=6`（默认）调高；或 `hooks --mode silent`；或对话说"不用注入"。

### 5. AI 反复"再确认"死循环
- ❌ **错法**：每次召回后都回 `good`/`bad` 校准，且话术开放让 AI 继续追问。
- ✅ **正法**：说"不用校准"；或 `KEEPER_FEEDBACK_SESSION_CAP=0` 全关。
- 💥 **踩了会怎样**：每会话被追问 3+ 次"这条有用吗"，体验烦、且形成自反馈回路。
- 🔧 **怎么避**：默认 `feedback` 每会话 3 次 + `inject` 6 次双闸门已兜底；仍烦就 `KEEPER_FEEDBACK_SESSION_CAP=0`。

### 6. 手动改 / 删 `memories/*.json` 后 recall 出错
- ❌ **错法**：直接用编辑器改或删 `memories/` 下的 json 文件。
- ✅ **正法**：所有增删改走 op（`deposit`/`archive`/`delete`/`reclassify`）；改坏用 `rebuild` 或 `doctor --fix`。
- 💥 **踩了会怎样**：`index.db` 与磁盘文件脱节 → recall 返回陈旧/缺失、或报索引不一致；严重时以为记忆丢了（其实文件还在）。
- 🔧 **怎么避**：绝不手改 json；若已改坏，`python scripts/memory_ops/__init__.py rebuild`（重建索引，记忆不丢）或 `doctor --fix`。

### 7. 重要经验被挤出热位
- ❌ **错法**：库变大后，高 importance 记忆和一堆普通记忆混在热位，没给核心经验留固定配额。
- ✅ **正法**：`promote --tier core` 把关键记忆钉在 core；或在 taxonomy 给专属域独立 `heat_budget`。
- 💥 **踩了会怎样**：常用的重要经验被新记忆挤到温/冷位，召回时排不到前面，等于"记了但想不起来"。
- 🔧 **怎么避**：`promote --id <id> --tier core`；或 taxonomy 给高频域设 `heat_budget`。

### 8. 重复 trigger word 命中多条记忆
- ❌ **错法**：用太宽的关键词触发（如单字 tag），一次召回捞回一堆不相关的。
- ✅ **正法**：用 `domain`/`scene`/`subdomain` 精确过滤，而非仅靠宽泛 tag。
- 💥 **踩了会怎样**：召回结果噪声大，真正相关的被淹没，AI 用错经验。
- 🔧 **怎么避**：`recall --query "X" --domain investment --scene rebalance` 精确收窄。

### 9. 跑 `cluster` 报"未达嵌入要求"
- ❌ **错法**：库 <8 条已嵌入记忆就去 `cluster --apply`。
- ✅ **正法**：先 `recall` 几次完成嵌入（或暂不开聚类）；库 ≥8 条已嵌入再跑。
- 💥 **踩了会怎样**：直接报错退出，你以为聚类坏了。
- 🔧 **怎么避**：先正常使用、让记忆完成首次嵌入；或暂跳过聚类。

### 10. `deposit --corrects` 报"找不到旧 id"
- ❌ **错法**：旧记忆已被 archived，还拿原 id 去 `--corrects`。
- ✅ **正法**：先 `recall --deep --id <id>` 确认旧记忆是否还在（含归档）。
- 💥 **踩了会怎样**：纠正失败，新结论无法挂到旧结论上，形成两条孤立记忆而非"新取代旧"。
- 🔧 **怎么避**：`recall --deep --id <旧id>` 确认存在；已归档就先 `unarchive` 再 `--corrects`。

### 11. 备份文件很大
- ❌ **错法**：以为 `backup` 只备份 json，结果 zip 巨大，吓一跳。
- ✅ **正法**：`backup` 默认带 `index.json`（含摘要明文）；脱敏分发只拷 `memories/`+`store/`，**别带 `index.json`**。
- 💥 **踩了会怎样**：备份 zip 比预期大数倍，若含敏感 summary 还不能直接发给别人。
- 🔧 **怎么避**：脱敏分享只拷 `memories/`+`store/`（不含 `index.json`）；库里摘要是明文，分发前自行确认无敏感内容。

### 12. `recall` 不返回任何结果
- ❌ **错法**：query 太抽象（如"那个事情"），或过滤条件太严。
- ✅ **正法**：① 加 `--domain`/`--scene` 收窄；② 拆成具体词再查；③ `report` 看召回策略是否太严。
- 💥 **踩了会怎样**：以为记忆丢了，其实只是 query 没命中。
- 🔧 **怎么避**：`recall --query "具体词" --domain <域>`；`report` 看分层/策略；`recall --deep` 放宽到归档。

### 13. `recall` 召回了已归档的记忆 / 该召回的没召回（索引与文件不一致）
- ❌ **错法**：以为 `archive` 后记忆就从召回里消失，却发现它又被召回；或反之，明明是活跃记忆却召回不到。
- ✅ **正法**：跑 `doctor --fix`（以记忆文件为准，回填 SQLite 索引状态、剪枝悬空关系、移除无文件索引条目，**不删记忆内容**）；或最彻底地从文件重建 `rebuild`。
- 💥 **为什么会这样（根因）**：keeper 的**记忆文件**（`memories/*.json`，内容真源）与 **SQLite 索引镜像**（`store/index.db` 的 `entries.data` 列，承载 recall 的过滤字段 `status`/`tags`/`tier`/`scope`…）是两份数据，靠每个写操作"改文件 + 同步索引"手动保持一致。若某个操作只写了一边（或你曾手动改/删过 json），就会出现**双向漂移**：
  - **文件=archived 但索引=active** → 已归档记忆被当活跃**泄漏召回**（隐私/整洁隐患）；
  - **文件=active 但索引=archived** → 活跃记忆被**误杀**、排查不到。
  这是"静默数据正确性"问题——运行时**不会报错**，只有 `doctor` 能扫出来。
- 🔧 **怎么避**：① 绝不手改 json（见 §四·4）；② 所有增删改走 op；③ `doctor`（就绪自检）会扫"索引↔文件一致性"，发现漂移用 `doctor --fix` 一键以文件为准回填。

> ⚠️ 这一条是"记录与召回对不上"的真问题，不是 query 没命中（§13）。若 `doctor --fix` 后仍有异常，再考虑 `rebuild`。

> **隐藏坑**：模型给"我现在能确认"反复重写而非真正回答——这是编排层+feedback 话术共同导致的"自反馈循环"。`KEEPER_INJECT_DAILY_CAP` 调小（如 3）可显著降低频率；或直接说"不用校准/不用注入"切断。

---

## 四·B、反模式清单（❌ 错误做法 → ✅ 正确做法）

> 📌 **反模式清单已集中到 `SKILL.md`「反模式清单」一节为单一真源**（与 `SKILL.md` 同步维护，避免两处漂移）。
> 直接看 → `SKILL.md`「📌 反模式清单（❌ 错误做法 → ✅ 正确做法）」。本文件不再重复罗列。

---

## 五、这样用效果最好（最佳实践）

> 红线级强保证（先 `archive` 再 `delete`、`reflect` 不删等）见 `SKILL.md`「红线与边界」；本节点补充日常实践建议。

- **记什么**：只记有用的结构化经验（坑/纠正/最佳实践/跨项目规则），别当录音笔搬对话。好处：召回命中可复用结论；代价：需主动判断值不值得记。
- **记错了**：用 `deposit --corrects <旧id>` 存新结论，旧记忆自动标 `superseded`，关系链保留。
- **中文换说法搜不到**：装 `fastembed` 或开线上 embeddings。好处：改写 query 也能召回；代价：首次下载/配置一次。
- **怕误删**：先 `archive` 再 `delete --yes`；不确定先 `--dry-run`（红线 A1/A2 见 `SKILL.md`「红线与边界」）。
- **敏感信息**：不建议记；`deposit` 扫 secrets 会拒写或隔离。
- **定期整理**：每周 `reflect --auto`（只去重/纠错/晋升/归档，绝不删 active）。
- **重要记忆常驻**：`promote --tier core` 或靠反复召回升 importance；core 位有限，别什么都标重要。
- **跨语言召回**：关键术语 tags 双语都写（如 `缓存,cache,Redis`）。
- **不确定开哪些功能**：跑 `audit`（只读）按库规模和环境给建议。
- **备份**：定期 `backup` 整库 ZIP，是误删/损坏的最后保险。

---

## 六、场景分类可信度（重要记忆必读）

> **自动分类（scene）不是权威，是建议值。**
> - 写入方**显式传 `scene=`**（尤其 `importance≥0.7` / `confidence≥0.9` 的重要记忆）时，覆盖自动猜测。
> - 自动分类会带 `scene_confidence`（LLM 分类或关键词规则）与 `scene_via`（llm / rule / explicit）。**`scene_via=="rule"` 或 `scene_confidence<0.7` 的记忆是"猜的"，用之前请核对场景。**
> - 周六维护自动化已加 `doctor --low-confidence`，会把这些低置信记忆汇总出来供复核纠正。
> - 详见 `references/LIMITS.md` §「场景分类（scene）可信度」。

---

## 七、会话钩子

> 💡 装完 skill 即生效，无需手跑脚本——首次运行任意命令时自动注册（幂等）。

**Q16：装完 skill 钩子会自动生效吗？**
- ✅ **默认自动注册**。首次运行 `deposit` / `recall` / `init` 等任意命令时，`memory_ops.py` 的 `_ensure_hooks()` 会检测 `~/.workbuddy/settings.json`：若尚未含 keeper 钩子，就自动调用 `install_hooks.py` 注册（**幂等、保留 WorkBuddy 内置 hook**），打印一行 `🔌 [keeper] 首次自动注册会话钩子…` 到 stderr。重启 WorkBuddy 后钩子即生效。
- 想**关闭**自动注册：设环境变量 `KEEPER_AUTO_INSTALL_HOOKS=0`（仍可在需要时手动跑 `python install_hooks.py`）。
- 想**看明细 / 手动跑**：`python install_hooks.py --dry-run`（只打印将做什么，不改文件）。
- 想**只关弹窗、保留功能钩子**：`python install_hooks.py --set-mode silent`（或 `keeper_setup.py hooks --mode silent`）。该模式持久化于 `hooks_config.json`，自动注册与重装都遵循，不会复活弹窗钩子。可 `--set-mode full` 恢复、`--status` 查看当前状态。

**Q17：自动注册会覆盖我已有的 hook 吗？**
- **不会**。`install_hooks.py` 只**追加** keeper 所需的 5 个钩子条目，完整保留 WorkBuddy 内置的 `leak_scan` / `code_lint` / `pre_tool_use_guard` / `bash_guard` / `git_guard` 等，绝不覆盖既有条目。

**Q18：怎么验证钩子真在 fire？**
- 重启 WorkBuddy 桌面版后，查看 `~/.workbuddy/hooks/hook_audit.log`（每次注入/召回/沉淀都有审计行，**唯一可靠判据**）；或发无关消息看是否出现 `## 🔎 本地记忆弱召回提示`（IMA 兜底，不受 `inject_enabled` 影响）。
  - ⚠️ **默认不再自动注入**：`## 🧠 当前生效的 AI 经验` 段落需 `inject_enabled=true` 才出现（`store/config.json` 的 `keeper.inject_enabled=true` 或 env `KEEPER_INJECT_ENABLED=1`）；看不到它**不等于**钩子没装。

---

## 八、IMA 云端镜像（一键同步 + 脱敏红线）

**Q19：怎么把记忆同步到 IMA 知识库？**
- 一条命令搞定**导出 + 脱敏 + 脱敏后复检 + 推送指令生成**：
  ```bash
  python scripts/ima_sync.py
  ```
- 它产出 `~/.workbuddy/ima_push/keeper-镜像-<domain>.md`（每个域一个文档），并**自动脱敏 + 脱敏后再扫一遍**（任何残留敏感信息直接失败，绝不交付明文文件），最后打印一份**可直接贴给 Agent 的推送指令**。把那段指令发给 Agent 即可完成入库（create_media → COS 上传 → add_knowledge REPLACE，走 IMA MCP）。
- 指定知识库：`python scripts/ima_sync.py --kb-id <KB_ID>`（默认读 `IMA_KB_ID` 或内置已知库 `YOUR_IMA_KB_ID`「AI记忆」）；`--open` 会尽力打开 IMA 网页。

**Q20：推送前为什么要脱敏？**
- IMA 是**明文存储**，把真实路径 / 凭证 / 邮箱传上去等于泄露。`ima_sync.py` 背后调 `_keeper_ima_push.py` 自动 strip 凭证/真实路径/邮箱，并把绝对路径替换为 `<user_home>/...`、`<workspace>/...`、`<AI记忆库>` 等占位；**脱敏后还会再跑 `verify_desensitization()` 复检一遍**——漏网即报错退出，双重保险。
- ⚠️ **永不要**在 `ima_bridge.py export` 的裸导出（无脱敏）产物上直接上传，那会明文泄漏凭证。

**Q21：同步流程还是好长？**
- `ima_sync.py` 把"从零拼五步流程"压成了**一条命令 + 一段可贴指令**。真正的入库步骤（create_media / add_knowledge）是 **IMA MCP 工具**，脚本调不到、必须由 Agent 经 MCP 执行——这是设计使然；`ima_sync.py` 已把每一步的参数（KB id、文件名、字节数、REPLACE 策略）全部填好，Agent 照做即可，你无需记任何步骤。也可直接对 Agent 说：「把 ima_push 下的记忆镜像推到 IMA 知识库」。

**Q22：IMA 里文档越推越多怎么办？**
- 文档用**稳定文件名** `keeper-镜像-<domain>.md` + `DUPLICATE_NAME_STRATEGY_REPLACE`，每周重推**原地替换**，知识库永不堆积。旧格式/测试文档（如 `keeper记忆镜像_20260801.md`）只能去 IMA 界面手动删一次。
