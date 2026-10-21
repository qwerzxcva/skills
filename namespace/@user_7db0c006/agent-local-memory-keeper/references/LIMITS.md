# LIMITS · 限制与边界总览（唯一总览）

> 📌 **版本权威源**：本文档提及的 `vX.Y.Z` 仅作历史语境参考，**当前版本与功能变更以根目录 `CHANGELOG.md` 为唯一权威源**（见 `SKILL.md` 文件头 `version` 字段）。

> 本文件聚合 `SKILL.md` 内联 ⚠️ + `references/FEATURES.md` 各 § 边界 + 线上模型/IMA 边界，
> 作为「想一次性看清楚全部限制」的唯一入口。`SKILL.md` 内联 ⚠️ 改为短指针指向本文件。
> 如与 `SKILL.md` 冲突，以 `SKILL.md` 为准并请反馈。

---

## 0. 一句话边界

- **本地优先、本地模型可选**：本地模型（嵌入/LLM）是「可选项」而非「必选项」——能跑本地就用本地，跑不了就走线上模型或纯词法，**场景分类/语义嵌入/reflect 三能力各自独立可选本地或线上，按机器实况自由组合，不强求全本地或全线上**。
- **最推荐主路径 = Agent 即模型**：你对话的这个 LLM 本身就是分类器/语义理解器，记经验时显式传 `scene=/domain=/subdomain=`（零误判、零配置），召回时用自身语义理解。脚本侧本地/线上后端只是无 Agent 自动化场景的备选。
- 记忆存「经验结论」，不搬对话原文；不记 secrets。
- 自动分类（scene/type/scope）都是**建议值非权威**，重要记忆显式传值并核对。
- SQLite 是权威存储；`index.json`/`memories/` 是副本/兜底。并发写由 SQLite WAL + 事务保障。
- **召回质量取决于语义后端（最易被忽略的边界）**：**默认即为语义后端**（`fastembed`，中文改写召回率约 90%+）；但它**静默降级**——模型加载/下载失败时自动退回词法兜底，此时「换种说法问同一事」的深度改写召回掉到约 30%，且**不报错**（功能看起来正常）。若「明明记过却搜不到」，先确认是不是降级态：看 `doctor` 的 `embed_backend.fell_back_to_lexical`（`true` 即已降级）。线上 embeddings 是零本地算力选项。向量空间随后端不同而不同，切换后存量向量自动重嵌一次。

> **版本怎么选**：以根目录 `CHANGELOG.md` 为唯一权威源（本文件不再重复版本号，避免双源漂移）。

---

## 1. 存储与并发

| 项 | 限制 / 边界 | 解法 |
|---|---|---|
| 存储根 | 回退链 `AI_MEMORY_STORE` → `~/.keeper/store_root` → 平台默认（Windows `~/AI记忆`、mac/Linux `~/.ai-memory`） | 设环境变量，或写 `~/.keeper/store_root` |
| 权威存储 | SQLite（`store/index.db`，WAL + 事务）；`index.json`/`memories/` 副本 | 以 SQLite 为准 |
| 并发写 | 多写者由 SQLite 事务串行 | 直接多进程写同 store 安全 |
| 跨设备同步 | 直接 rsync `memories/` 会因 WAL/SHM 撕裂 | 必须 `backup` ZIP 再 `restore` |
| 向量空间 | 不同嵌入后端（lexical/fastembed/online）向量空间不同；切换后存量向量自动重嵌（需一次联网/算力） | 切换后端跑 `recall` 首次自动刷新 |
| 向量维度 | online 模型维度可能 ≠ 512；跨维度余弦在切换期间返回 0（已加固不崩） | 同后端内一致即可 |

---

## 2. 语义 / 嵌入后端

| 后端 | 是否需本地模型 | 首次联网 | 质量 | 适用 |
|---|---|---|---|---|
| lexical（默认回退） | 否 | 否 | 中（深度改写弱） | 任何环境，零依赖 |
| fastembed（神经） | 是（本地 ONNX，~90MB） | 是（仅首次拉模型） | 高（中文 ~90%+） | 本机有算力/GPU |
| sentence_transformers | 是（依赖 torch，较重） | 是 | 高 | 已有 torch 环境 |
| **online** | **否（云端推理）** | 是（每次落库联网） | 取决于所选云端模型 | **本机跑不了本地模型** |

- 嵌入向量落库缓存到 SQLite（`model` 列标记），**召回时只做本地余弦，不再联网**。
- 在线失败自动回退 lexical，绝不报错卡死。
- 配置（环境变量，key 绝不写进文件）：
  ```
  AI_MEM_EMBED_BACKEND=online
  AI_MEM_EMBED_ONLINE_URL=https://<你的在线端点>/v1   # OpenAI 兼容 /v1/embeddings
  AI_MEM_EMBED_ONLINE_KEY_ENV=AI_MEM_EMBED_ONLINE_KEY  # API key 所在环境变量名
  AI_MEM_EMBED_MODEL=text-embedding-3-small            # 复用模型名变量
  ```

---

## 3. 模型能力灵活组合（本地 / 线上 / 混合）

> **本地模型是「可选项」，不是「必选项」。** 场景分类 / 语义嵌入 / reflect 三能力**各自独立**可选本地或线上，按机器实况自由组合：能跑本地（Ollama + fastembed）就全本地、跑不了就全线上、也可混合（如 Agent 显式传 scene + 本地 fastembed）。详见 `references/INSTALL.md`「模型能力灵活组合」节的四种组合矩阵。

**什么可以走线上模型：**
- **场景分类（scene）**：`deposit` 未显式传 `scene` 时，优先调在线 LLM 分类（带 confidence）；无 LLM 配置则退化为关键词规则（带置信度）。推理在云端，本地零算力。
- **语义嵌入**：见 §2 online 后端。
- **reflect 自进化 / 矛盾检测**：可配置在线 LLM（`config.llm.enabled=true`，`backend=openai` + `base_url` + `api_key_env`），同 §4 配置。

**LLM 配置（`<记忆根>/config.json` 或环境变量）：**
> ⚠️ **路径易错**：LLM 配置在**记忆根下的 `config.json`**（如 `<你的记忆库目录>\config.json`），
> **不是** `store/config.json`——后者只放 keeper 运行时开关（`keeper` 块，见 `SKILL.md` 配置表）。
> 代码依据：`memory_ops._llm_config_path(root)` 返回 `os.path.join(root, "config.json")`。
> 环境变量（`KEEPER_LLM_ENABLED` / `KEEPER_LLM_BACKEND` / `KEEPER_LLM_BASE_URL` /
> `KEEPER_LLM_MODEL` / `KEEPER_LLM_KEY`）优先级高于文件，零改配置即可启用。
```json
{
  "llm": {
    "enabled": true,
    "backend": "openai",
    "base_url": "https://<你的在线端点>/v1",
    "model": "gpt-4o-mini",
    "api_key_env": "KEEPER_LLM_KEY"
  }
}
```
- 默认 `base_url=http://localhost:11434/v1`（Ollama 本地）；改为你的在线端点即走云端。
- **隐私**：reflect 只发记忆「元信息」（id/summary/tags/category/tier/scope），**不发 body 正文**；在线模式记忆出域（按 token 计费），请评估敏感度。

**性能影响：** 分类/嵌入推理全在云端，本地只做向量点积 + 文件/SQLite IO。**零本地模型、零本地算力，不影响电脑性能与使用体验。**

---

## 4. 分类边界（scope / scene / type）

| 轴 | 取值 | 自动分类方式 | 边界 / 注意 |
|---|---|---|---|
| scope | universal / project / ephemeral | 关键词规则 + 学习模型（`classifier.py`） | 无信号默认 universal（宁可留着不误埋） |
| scene | SCENE_CANON（含投资 5 场景） | **在线 LLM 优先 → 关键词兜底** | 见 §5 |
| type | BP/WF/PF/PREF/FACT/DOC | 规则 + **在线 LLM 优先** + 学习先验 + 嵌入原型补判 | LLM 低置信回退规则 |

- 显式传值（deposit `--scene` / `--domain` 等）**覆盖**自动猜测。
- 多轴正交：domain=讲什么，scene=何时用，互不替代。

---

## 5. 场景分类（scene）可信度

> **自动分类不是权威，是建议值。重要记忆用之前请核对。**

- `deposit` 落 `scene_confidence`（0~1）与 `scene_via`（llm / rule / explicit）。
- **`scene_via=="rule"` 或 `scene_confidence<0.7` = 关键词猜的**，脆弱（实测历史 ~20-30% 误判，如"复盘+事故""调仓+复盘"平局取错）。
- **重要记忆（`importance≥0.7` / `confidence≥0.9`）写入方务必显式传 `scene=`**，覆盖自动猜。
- 周六维护自动化加 `doctor --low-confidence`，汇总低置信记忆供复核纠正。
- `recall` 返回条目已带 `scene_confidence` / `scene_via`，渲染层可标注。

---

## 6. 安全

| 项 | 边界 |
|---|---|
| secrets | `deposit` 写前扫 API key/PAT/Bearer/jwt/私钥，一票否决；命走 `quarantine` 隔离待复审 |
| 推断偏好 | 绝不从"沉默"推断偏好，只记显式说出/纠正/沉淀的经验 |
| 危险操作 | `delete/overwrite/archive` 执行前打印预览，`--dry-run` 只预览；`delete` 必须 `--yes` |
| 不记明文密钥 | 只记方法，不记 key 本身 |
| 发布物零敏感 | 本 skill 目录**不含任何 API key / token / 密码 / 个人标识**；IMA 与 LLM 凭证均由运行时经环境变量或 MCP 注入，绝不落盘到 skill 文件（已全量扫描确认） |

---

## 7. 自动化 / 注入闸门

- **捕获默认开、注入默认关**（两件事常被混为一谈）：**捕获** = `auto_capture` 默认**开**——AI 在对话里静默沉淀、每 20 轮自动整理一次，你**不必**每次说"记一下"；**注入** = `inject_enabled` 默认**关**——AI 不会自动把记忆塞进上下文（省 token），要看时靠你开口或 `recall`。只想"明说才记"：说"先别自动记"（`KEEPER_AUTO_CAPTURE=0`）。
- 防自反馈双闸门：`KEEPER_INJECT_DAILY_CAP`（每会话/每日 inject 上限，默认 6）、`KEEPER_FEEDBACK_SESSION_CAP`（feedback 上限，默认 3，0=全关）。
- 反复"再确认"死循环 → 说"不用校准"/"不用注入"或调上述 env 为 0。

---

## 8. 域隔离 / 投资适配限制

- `domain` 走原生字段；`sub:`/`param:`/`until:`/`quirk:`/`st:` 前缀标签承载多维，**零迁移、旧库兼容**。
- `param:` 必须含 `=` 才落（避免误标）。`until:` 支持 `2026Q4`/`2026.12.31`/`2026-12-31` 归一。
- 结构化数值**范围过滤**（`--filter "sharpe>2 AND maxdd<0.15"`）**已落地**（含中文别名归一：`夏普→sharpe`、`回撤/最大回撤→maxdrawdown`、`动量→momentum`），字段与算子见 `references/COMMANDS.md` §recall `--filter`。

---

## 9. IMA 知识库桥接（可选语义层 · ✅ 已打通·实测可用）

> 作用：把本地记忆镜像到 IMA 云端 RAG，获得强语义泛化召回，**本地零算力**。桥接为纯加性可选能力——无 IMA 时记忆系统完全自洽。

**配置你的知识库**：在 IMA 里建一个知识库（如 "我的经验库"），记下它的知识库 ID（下文记为 `<KB_ID>`）。后续推送都指向它。

> 🔴 **明文存储 · 推送前必须脱敏（P0）**：IMA 知识库对上传内容**不做加密、无访问控制细化**，文档以明文存储且可被任何能访问该 KB 的人/端检索。本 skill 的 `memory_ops` 本地库**本就是明文落盘**，桥接导出同样是明文。因此**任何推送脚本在渲染上传前都必须先脱敏**——strip `skh_`/`ak_`/`LY..`(IMA secret)/`api_key|secret|token|password` 赋值/绝对 admin 路径/`@邮箱`。本 skill 提供的 `scripts/ima_bridge.py export` **不含脱敏**（它是纯导出原语），如果你直接用它的产物上传，**等于把凭证明文推上云**。生产编排见下方「推荐生产接线」。

**两种用法**：

### A. 最小原语（理解原理 / 手动试一次）
适合验证链路，不建议直接用于含敏感记忆的库：
1. **导出语料**（纯本地）：`python scripts/ima_bridge.py export --root <store根> --out corpus.jsonl` —— 全部记忆渲染成单文件 `corpus.jsonl`（一个大 blob，无脱敏、无分域）。
2. **创建 media**（agent 调 IMA MCP `create_media`）：`content_type=text/markdown`、`file_name=<名>.md`、`file_size=<实际字节数，必须与上传文件一致>`、`knowledge_base_id=<KB_ID>`，返回 `media_id` + `cos_credential`（短时效临时凭证）。
3. **上传到 COS**（用返回的凭证）：`python scripts/ima_cos_upload.py creds.json <单条.md> text/markdown` —— 官方 `cos-python-sdk-v5` 做 PUT（自动处理 STS token 与 v5 签名，直连 `bucket.cos.region` 标准端点，**不要手工拼 `custom_domain`**，本沙箱下 `custom_domain` 主机被出口代理 Lego Server 拦截返回 403 空 body）。
4. **入库**（agent 调 IMA MCP `add_knowledge`）：`knowledge_base_id=<KB_ID>`、`media_id=<第 2 步>`、**务必带 `duplicate_name_strategy=DUPLICATE_NAME_STRATEGY_REPLACE`**（同名文档原地替换，KB 永不堆积；不带则每次推送都新增重复文档）。⚠️ 必须先完成第 3 步上传，否则报"文件未上传"。
5. **检索**（agent 调 IMA MCP `search_knowledge`）：`knowledge_base_id=<KB_ID>`、`query=<提问>`。

### B. 推荐生产接线（脱敏 + 防堆积 + 辅助召回，当前部署采用）
用一个**编排脚本**一次性做完「导出 → 脱敏 → 按域拆分 → 本地镜像 → 生成 manifest」，再由自动化逐域走 A.2–A.4(REPLACE)。当前部署的编排器是随包发布的 `scripts/_keeper_ima_push.py`（端口化：store 根走 `AI_MEMORY_STORE`、输出目录 `~/.workbuddy/ima_push`、脱敏覆盖任意用户主目录），它做了：
- **脱敏**：渲染前 `desensitize()` strip 上述所有敏感模式（P0 闸门）。
- **按域拆分**：每条记忆 = 一个 `## N. 标题` 段（IMA 按 H2 切 chunk，召回精准）；文档级用**稳定文件名** `keeper-镜像-<domain>.md`（不含日期）+ REPLACE → 每周重推原地替换。
- **结构化标签**：每条带 `> 域/子域/类型/重要度/状态/创建` 元数据行 + `**标签**:` 行（IMA 无 API 级 tags，靠正文标签化）。
- **剔除噪声**：测试探针(ZZZPROBE)、同内容去重（superseded/active 同体）。
- **本地镜像**：同步写 `~/.workbuddy/ima_mirror/<domain>.md`，供 SessionStart / UserPromptSubmit 钩子**本地词法补充**（钩子子进程不能调 MCP，靠镜像文件兜底）。
- **用户入口 `scripts/ima_sync.py`**：一步完成「调 `_keeper_ima_push.py` 导出 → 对每份文档跑 `verify_desensitization()` 脱敏后复检 → 打印可直接贴给 Agent 的 MCP 推送指令（create_media→COS上传→add_knowledge REPLACE，含 KB id 与字节数）」。复检命中任何残留敏感信息即失败退出，绝不交付明文。普通用户跑 `python scripts/ima_sync.py` 即可，无需记 A.1–A.5 步骤。

**钩子辅助召回层（让 IMA 真正成为「辅助记忆系统」而非保险箱）** —— 这两个钩子已落地并注册到 `settings.json`，是本集成相对「纯手动 search_knowledge」的关键增量：
- `session_start_keeper_inject.py`：会话开局注入本地 keeper top-5 + 从本地镜像补 **archived/衰减** 记忆（冷存储兜底）+ 常驻指令（KB id，提示 agent 弱召回时查 IMA）。⚠️ **受 `inject_enabled` 门控、默认不注入**（`store/config.json` 的 `keeper.inject_enabled=true` 或 env `KEEPER_INJECT_ENABLED=1` 才注入）；未开启时钩子不会注入。
- `user_prompt_recall.py`：每次提问本地 0 命中时，**不再静默放过**，而是注入 IMA 语义召回兜底提示（含 KB id），由 agent 决定要不要 `search_knowledge`。

**边界 / 已知问题**：
- Python 不直接调 IMA MCP（MCP 由 agent 运行时注入）；桥接脚本只负责「导出语料 + COS 上传」，推送/搜索由 agent 用 IMA MCP 完成。
- IMA 是云端语义召回**补充层**，不替代本地按轴精确召回（scene/domain/tag 硬过滤仍在本地）；本地 keeper 永远是 source of truth（无加密、无门控、无 decay 治理）。
- **迁移清理**：IMA **没有删除 API**。旧格式/测试文档（如 `keeper记忆镜像_20260801.md`、`_ima_test.md`）只能去 IMA 界面手动删一次；REPLACE 只替同名文档，不会清掉旧名文档。切换接线后记得清一次。
- ✅ **已打通（实测 2026-08-01）**：原 `ima_cos_upload.py` 手工 HMAC 签名在 IMA 下发的 STS 临时凭证下稳定触发 `SignatureDoesNotMatch`（与凭证是否有效无关）；改用官方 `cos-python-sdk-v5` 后一次上传成功。真实记忆已推送进 IMA 知识库（KB id `YOUR_IMA_KB_ID`「AI记忆」）并云端 `search_knowledge` 召回验证通过。

**可分发性（✅ 已解决）**：让 IMA 真正落地且安全的编排器 `_keeper_ima_push.py` 已并入 `scripts/`；5 个事件钩子由 4 个脚本承载（`session_start_keeper_inject.py` / `user_prompt_recall.py` / `post_tool_use_error_capture.py` / `memory_auto_capture.py`，共享模块 `keeper_hook_common.py`），含 IMA 辅助召回层，位于 `hooks/`；错误捕获由 `post_tool_use_error_capture.py` 承担（无独立的 `bash_error_capture.py`）。钩子的硬依赖 `keeper_daemon/`（毫秒级 recall）已并入 `keeper_daemon/`。新增 `install_hooks.py` 安装器专门处理「钩子 ↔ `settings.json`」耦合——SkillHub 全新安装后跑一次 `python install_hooks.py` 即把钩子拷到 `~/.workbuddy/hooks/`、daemon 拷到 `~/.workbuddy/keeper_daemon/`、并**幂等合并** 5 个钩子条目进 `settings.json`（完整保留 WorkBuddy 内置 hook）。详见 SKILL.md「钩子模式」节。所有路径端口化（不再硬编码具体 Windows 用户名主目录），任意用户名机器可用。

---

## 三层架构与真源边界

记忆系统融合两类设计强项——「语义召回/冷热分层/矛盾检测/防自反馈/IMA/投资适配」与「promotion 终点（系统提示）、状态机、高频固化、hook 自动捕获」——形成三层并存：

- **① 语义召回层（开箱即用）**：SQLite 是系统真源；向量语义召回 + 结构化 `attrs` + filter DSL + 冷热分层 + 矛盾检测 + 防自反馈闸门 + IMA 桥接(✅已打通·实测可用，见 §9) + 投资适配。
- **② 行为规则层（手动触发）**：高频/已确认经验经 `export-rules` 固化进 `AGENTS.md`/`CLAUDE.md`，成为 AI 每轮行为规则（记忆终点=改变行为）。`AGENTS.md` 为导出物，带自动生成头，用户不应手改。
- **③ 轻量文件层（opt-in）**：`--flat` 跳过 SQLite 与 LLM，纯 Markdown 文件 + grep 召回，给零依赖用户。

**真源边界**：SQLite 是主真源；`--flat` 模式切换后 `keeper_flat.md` 成为该会话真源（与 SQLite 互斥）；`AGENTS.md` 单向导出（SQLite→AGENTS.md），逆向可用 `import-rules` 回灌。

## 10. 融合路线图（已落地）

- ✅ **Phase A–E（已落地）**：状态机 `state`/优先级 `priority`/领域 `area` + 触发词典 + 行为规则层 `export-rules`/`hot-rules`/`import-rules` + 轻量路径 `--flat` + hook 自动捕获 + 技能萃取脚手架。

## 11. 协同增强（已落地，对齐 WorkBuddy 协同方案）

> 设计基线：只补净缺口 + 增强，不重造已有机制。

- ✅ **C1 about_axis 四轴**（user/self/relationship/world）：`memory_schema.py` 加枚举 + `normalize_about_axis`；`_deposit_impl`/`deposit`/entry 镜像纯加性；CLI `--about-axis`；filter DSL 白名单加 `about_axis`。与 category/area 正交。
- ✅ **B2 触发词打分升级**：`trigger_dict.infer_trigger_hints` 扩为 5 元组（area/priority/importance/about_axis/reason），多命中合并；「记住→0.9」「我偏好→user+0.7」「我们→relationship」「市场/外部→world」。
- ✅ **C2 复述自动加权**：`touch()` + recall 命中均调 `_apply_rehearsal_weight`（α=0.05 可调，按访问间隔指数衰减），与 decay 互补。
- ✅ **B1 recurrence 自动候选**：`recurrence_report(--auto-candidate)` 标「跨≥2 任务 + 30 天」组为 `promotion_candidate=True`，供周评审批准。
- ✅ **B3 staging 隔离开关**：`auto_sourced=true` 默认**已包含**在 recall（`--include-auto` 向后兼容、默认开）；需严格 staging 隔离时用 `--exclude-auto` 显式排除。
- ✅ **C3 周评审自动化**：WorkBuddy 自动化（每周一 09:00，automation-1785201200702）跑评审卡，不自动改库。
- ✅ **B4 publish 规范文档化**：`export-rules` 复用 `<!-- memory-keeper auto-rules -->` zone（幂等/写前 `.bak`/可回滚）；规范「低频 + 需确认 + 人格层优先编入 user/self/relationship」。

### publish 使用规范
1. 经验固化走 `export-rules`/`hot-rules`，写入 `AGENTS.md` 的 `<!-- memory-keeper auto-rules start/end -->` zone——只覆盖 zone 内、写前自动 `.bak`、重跑幂等可回滚。
2. **低频 + 需确认**：建议周评审（automation-1785201200702）确认后再固化，避免错误经验被写进行为规则。
3. `about_axis=user/self/relationship` 的偏好类记忆优先编入 WB 人格层（IDENTITY/SOUL/USER.md），`world` 类编入事实层。
4. 被动捕获（auto_sourced）项默认**已包含**在 recall；需严格 staging 隔离时用 `--exclude-auto` 显式排除。

---

## 12. 性能与规模预期（软指引）

> 没有硬上限——库可以一直长，下面是"什么时候会开始吃力"的经验区间，帮你判断要不要调策略。**普通用户（几十到几百条）基本遇不到。**

| 库规模 | recall 行为 | 何时需要注意 |
|---|---|---|
| < 50 条 | 线性扫描（词法/向量全量比对），**最快最准** | 无需任何动作；ANN 自动不启用（开了反而慢） |
| 50–256 条 | 自动启用 **ANN 加速**（结果与全量一致，实测 ~8× 提速） | 默认即开，无需配置 |
| > 256 条 | ANN 仍是默认；超大库（>256）显式 `recall --ann` 可剪枝进一步加速 | 库 >500 条时 `doctor --contradictions` / `cluster` 吃 CPU，放进**周/月低频任务**，别进每日 |
| > 1000 条 | 建议升级 `taxonomy` 给高频域独立热位 + 保持 ANN | 关注热点记忆是否被新记忆挤沉（用 `promote --tier core` 钉住核心） |
| **≈ 1 万条** | 🔴 **冷召回实测约 197.6s**（1k ≈ 7.4s → 1w ≈ 197.6s，**超线性**；瓶颈是 SQLite 向量全量加载 + 余弦，非纯文件 I/O） | **必须**定期 `reflect --auto`（去重·归档）+ `decay`（沉底冷记忆）压信噪比，并让召回走向量化（ANN / 守护进程常驻）——否则单次召回以分钟计 |
| > 10k 条 | 语义召回仍可用，但**延迟需你主动管理**，不是"免费无限" | 同上一行；注意「词法兜底模式实测可到数千条无压力」说的是**另一件事**（无模型的词法后端），不能拿来给语义后端的大库背书 |

> ⚠️ **本表"≈1 万条"一行是实测而非估计**：同库 1w 冷召回已达 **197.6s**（超线性）——"能跑"与"好用"在大库上差距很大。复现方法见 `references/_design/` 压测文档；自测跑 `benchmark --root <隔离目录>`（**必须**隔离目录）。

- **模型加载成本**：神经嵌入（fastembed ~90MB ONNX）首次落盘缓存、复用；开启守护进程后模型常驻、召回毫秒级，无重复加载成本。
- **性能自测**：想看真实数字，跑 `benchmark --root <隔离目录>`——**必须 `--root` 指定隔离目录**，禁止对真库跑（防污染召回）。
- 逐项"吃资源项"与低配替代见 `SKILL.md`「🔧 配置指引」；硬限制（并发/存储）见 §1。
