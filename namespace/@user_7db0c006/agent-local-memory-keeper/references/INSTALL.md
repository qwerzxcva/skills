# 安装与排错（INSTALL）

> 📌 **版本权威源**：本文档提及的 `vX.Y.Z` 仅作历史语境参考，**当前版本与功能变更以根目录 `CHANGELOG.md` 为唯一权威源**（见 `SKILL.md` 文件头 `version` 字段）。

> 本文件从 `SKILL.md` 概述抽出，专门讲"怎么把可选依赖装对、怎么验证、装不上怎么办"。
> 🤖 **排错段主要供 AI 内部引用**：你装依赖遇到报错，直接把报错贴给 AI，它会据此定位并给出修复命令，无需自己通读本文。
> **零依赖开箱即用**：**默认已是语义召回**（`fastembed`，首次用到时自动安装 + 下载约 90MB，之后完全离线），不用手配任何东西就能记 / 找 / 整理。只有想开「本地 LLM」时才需额外装；想省掉那 90MB 模型也可退回纯词法（见下文「语义后端三选一」）。
> 最省事路径：`python scripts/keeper_setup.py all`（一键收口全部装后步骤 + 六项就绪自检）。详见 `references/TUTORIAL.md` §0.5。

---

## ① 中文语义召回（fastembed，最推荐的可选增强）

**装到哪个 Python？（最关键，装错就「装了却没生效」）** 必须装到**运行 `memory_ops.py` 的那同一个 Python**，否则脚本看不到包、会静默回退词法级（表现就是明明装了，`report` 却还是 `lexical`）。判断方法：你平时怎么跑 skill 命令，就用那个 `python` 装：

```bash
# 用你执行 skill 的同款 python（前后必须同一个）
python -m pip install fastembed
# 若你走 WorkBuddy 托管 python，路径形如（换成你的用户名）：
"C:/Users/你的用户名/.workbuddy/binaries/python/versions/3.13.12/python.exe" -m pip install fastembed
```

**验证装成功（必做一步，确认不是 lexical 回退）**：
```bash
python scripts/memory_ops/__init__.py report    # 看「语义召回后端」一行，应为 fastembed（不是 lexical 即生效）
# 或：python scripts/memory_ops/__init__.py doctor
```

首次会联网下载约 90MB 的中文 ONNX 模型（`BAAI/bge-small-zh-v1.5`，fastembed 默认拉取 `Qdrant` 优化变体）到 `~/.workbuddy/cache/agent-local-memory-keeper/models`，约 10s-2min；**之后完全离线**（完整 BAAI 原仓库约 182MB 但不会被下载）。想避免首次 `recall` 时才被动下载，可装完后预拉模型：
```bash
python scripts/memory_ops/__init__.py init --download-models
```

**装不上？三种情况对症下药**：
- **网络受限 / 慢**：系统已自动探测 HuggingFace 可达性，不可达时会自动切换 `hf-mirror.com`；若仍慢，可手动再设——PowerShell：`set HF_ENDPOINT=https://hf-mirror.com` 与 `set HF_HUB_DISABLE_XET=1`；Linux/mac：`export HF_ENDPOINT=https://hf-mirror.com` 与 `export HF_HUB_DISABLE_XET=1`，然后 `python -m pip install fastembed`。
- **完全离线**：从能联网的机器把 `~/.workbuddy/cache/agent-local-memory-keeper/models/` 整个目录拷到本机相同路径（模型已含在内），无需联网即可用。
- **装完 `report` 仍是 `lexical`**：八成装到了别的 Python——重跑上面「装到哪个 Python」，确认 `python` 路径与跑 `memory_ops.py` 的是同一个。可用 `python -c "import fastembed; print('ok')"` 验证「当前这个 python」能否 import。

> ⚠️ **首次安装中文语义模型时**：必须保持联网状态 ~10s-2min 让 `fastembed` 拉模型；**国内网络会自动走 hf-mirror 镜像**；**之后**再断网也完全可用（模型已缓存到本地 `~/.workbuddy/cache/agent-local-memory-keeper/models/`）。若机器没网又想用语义召回，需手动把模型文件放入 `~/.workbuddy/cache/agent-local-memory-keeper/models/`（从能联网的机器拷过来）。

---

## ② 本地 LLM（Ollama，重，可选）

另装 Ollama 并 `ollama pull` 一个模型（~5GB），再 `llm-setup --enable-llm`。机器内存 / GPU 不够强别开，否则拖慢每次 reflect。配置见 `references/LIMITS.md` §3。

---

## 模型能力灵活组合（本地 / 线上 / 混合）

**核心原则：本地模型是「可选项」，不是「必选项」。** 场景分类 / 语义嵌入 / reflect 三能力**各自独立**可选本地或线上，按机器实况自由组合，不强求全本地或全线上。最推荐主路径是「Agent 即模型」——你对话的这个 LLM 本身就是分类器/语义理解器。

| 组合 | 场景分类 | 语义嵌入 | reflect | 适合 |
|---|---|---|---|---|
| **① 极简零配置** | Agent 显式传（或关键词兜底） | 词法 lexical（零安装） | 关 | 不想装任何东西 |
| **② 全本地** | 本地 Ollama LLM | 本地 fastembed | 本地 LLM | 有 GPU/内存、要零云端 |
| **③ 全线上** | 在线 LLM 端点 | 在线 `/v1/embeddings` | 在线 LLM | 本机跑不了本地模型 |
| **④ 混合（推荐）** | Agent 显式传（最准零开销） | 本地 fastembed 或 在线 | 可选线上 | 兼顾准确、离线、灵活 |

**各能力可独立切换**：
- **场景分类 scene** — 在线 LLM（`deposit` 未显式传 `scene` 时自动调）；无 LLM 退化为关键词规则。配置 `config.llm`（见 `references/LIMITS.md` §3）。
- **语义嵌入** — 云端 `/v1/embeddings`；`AI_MEM_EMBED_BACKEND=online` + `AI_MEM_EMBED_ONLINE_URL=...`（见 `references/LIMITS.md` §2/§3）。
- **reflect 自进化** — 在线 LLM；`config.llm`（同上）。

**语义通道决策（三选其一档，不叠加）**：

| 通道 | 后端 | 何时选 | 配置 | 代价 |
|---|---|---|---|---|
| **① 显式传值（推荐主路径）** | 无（Agent 自己分类） | 你在对话里，AI 就是分类器 | 记时直接说 `scene=/domain=/subdomain=`，零误判零配置 | 0 |
| **② 本地模型 `fastembed`** | 本地嵌入 + 词法兜底 | 本机有内存/GPU，要离线真语义 | `pip install fastembed`（首装联网一次约 90MB） | 常驻 100–150MB、召回多 10–30ms |
| **③ 线上 embeddings/LLM** | 云端 `/v1/embeddings` + 在线分类 | 本机跑不了模型（无 GPU/小内存） | `AI_MEM_EMBED_BACKEND=online` + OpenAI 兼容端点 | 首次联网、在线失败回退词法 |

> ⚠️ **不要同时硬开 ②+③**：本地与线上嵌入是两套向量空间，同时落库会造成召回语义分塌缩——按机器实况选其一。

---

## 会话钩子（首次使用自动注册）

默认自动注册：首次运行任意命令时 `memory_ops.py` 检测 `settings.json`，未含 keeper 钩子就自动调 `install_hooks.py`（幂等、保留 WB 内置 hook）。如需关闭设 `KEEPER_AUTO_INSTALL_HOOKS=0`。

手动装（一次性，排查/重装用）：
```bash
# 用 keeper 的 venv python 跑 skill 包根目录的安装器
"C:/Users/<你的用户名>/.workbuddy/binaries/python/envs/default/Scripts/python.exe" ^
  "C:/Users/<你的用户名>/.workbuddy/skills/agent-local-memory-keeper/install_hooks.py"
# 或先用 --dry-run 看将要做什么（不改动任何文件）
```
它会做三件事（全部幂等）：① 把 `hooks/*.py` 复制到 `~/.workbuddy/hooks/`；② 把 `keeper_daemon/`（钩子毫秒级 recall 的**加速件，仅"自动记忆模式"需要**；手动 `deposit`/`recall` 可跳过）复制到 `~/.workbuddy/keeper_daemon/`；③ 把 5 个钩子条目幂等合并进 `settings.json` 的 `hooks.*`（完整保留 WorkBuddy 内置 hook）。

> 🪶 **不想装守护进程？** 守护进程是"自动记忆模式"的可选增强，不是必需。若你只打算**手动**记 / 找，或选**线上 embeddings 后端**（本地零模型），可完全跳过第②步——直接 `deposit` / `recall` 照常工作。想要全自动记忆再跑 `python scripts/keeper_setup.py hooks --scheduler`（一条命令收口）。

**验证钩子真在 fire**：重启 WorkBuddy 后，查看 `~/.workbuddy/hooks/hook_audit.log`（唯一可靠判据）。

> ⚠️ **会话开局注入受 `inject_enabled` 门控，默认不注入**。因此「没看到 `## 🧠 当前生效的 AI 经验` 段落」**不再等于**钩子没生效。想恢复自动注入：`store/config.json` 设 `keeper.inject_enabled=true`，或设 env `KEEPER_INJECT_ENABLED=1`。

> 定时调度（`setup_scheduler.py` / `install_hooks.py --setup-scheduler`）、IMA 同步实操等 —— 见 `references/COOKBOOK.md`。

---

## 更新后：部署同步与引导（重装 / 升级必读）

> ⚠️ **技能更新不会自动刷新你机器上的"部署物"**。skill 目录换成新版本后，下面这几样仍停在旧版，直到你跑一次同步——这是"更新完感觉没生效"的头号原因。

**哪些部署物会滞后**（都在 `~/.workbuddy/` 下，**独立于 skill 目录**）：

| 部署物 | 位置 | 更新后的表现 | 怎么同步 |
|---|---|---|---|
| 会话钩子副本 | `~/.workbuddy/hooks/*.py` | **静默跑旧代码**（新版修好的钩子问题你享受不到） | `python install_hooks.py`（重跑复制，幂等） |
| 守护进程副本 | `~/.workbuddy/keeper_daemon/` | 同上 | 同上 |
| 定时调度 | 系统任务（schtasks / launchd / systemd） | 仍指向旧路径或旧命令 | `python setup_scheduler.py --uninstall` 后重新注册 |
| `settings.json` 钩子条目 | `~/.workbuddy/settings.json` | 命令路径可能失效 | `install_hooks.py`（幂等，就地更新命令路径） |

**一条命令收口（推荐）**：

```bash
python scripts/keeper_setup.py hooks --scheduler   # 复制最新钩子与守护 + 重新注册调度
```

**验证**：重启 WorkBuddy 后看 `~/.workbuddy/hooks/hook_audit.log` 是否在新增（唯一可靠判据）；再跑 `python scripts/keeper_setup.py doctor` 确认就绪。

### 🔴 从「带加密的旧版」升级上来 —— 先看这一条

若你的记忆库目录里有 `store/salt.bin`（或 `store/enc_key.txt`），说明这个库由**旧版**创建，而旧版**曾经内置 at-rest 加密**、本版**已把加解密能力整体移除**。这种库要特别处理：

| 关心的问题 | 事实 |
|---|---|
| 会自动解密 / 自动迁移吗？ | **都不会**。密文本身是**合法 JSON**，本版读出来既不报错也不留日志，只会把密文当明文用 —— 表现就是**召回出乱码**。 |
| 会把库搞坏吗？ | **不会**。本版对这类库**直接拒绝按明文读写**（fail-closed），返回结构化错误 `legacy_encrypted_store`（退出码 `13`）并打印三条出路。这是**刻意设计**：把「静默乱码」换成「响亮拒绝」。 |
| 能在这种库上写入吗？ | **不要**。本版写的是**明文**，会与既有密文**混库**；此后一旦降级回旧版，旧版的「明文写 fail-closed」会让**整库读不出来**。 |

**先确认自己的库属于哪一类**：

```bash
python scripts/memory_ops/__init__.py doctor        # 报 legacy_encrypted_store 即是「带加密的旧库」
ls "<你的库目录>/store/salt.bin"                     # 有 → 带加密的旧库；无 → 正常明文库
```

**三条出路**（拒绝时的错误消息里也会逐条打印，含具体版本号）：

1. **继续用这个库** → 换回旧版并恢复密钥（环境变量 `AI_MEM_ENCRYPTION_KEY`，或放好 `store/enc_key.txt` / `~/.ai-memory-keys/<库路径哈希>.key`）。这个库**只在旧版下可用**。
2. **把数据搬进明文库** → 需要旧版 + 原密钥做**一次性迁移**：在旧版环境下用原密钥逐条读出（读出来即明文）并导出，写入一个**全新目录**；确认新库没有 `store/salt.bin`、且内容能正常读出后，再让本版 `--root` 指向它。
   ⚠️ 旧版的 `rekey` **不支持轮换成明文库**（其 `--new-key` 帮助原文即如此）⇒ **只能走「导出 → 新建」，没有一键通道**。
3. **用新库** → 直接 `--root <一个全新空目录>`（或设 `AI_MEMORY_STORE`）即可用；旧库原样留档，随时可回到第 1 条。

> 💡 **迁移前想留个底**：`backup` 命令在**这类库上是放行的**（它不读记忆数据），可先把旧库整个打包留档。同理放行的还有 `quickstart` / `commands` / `release-audit` —— 其余全部命令在旧库上均以退出码 `13` 拒绝。

> 🔄 **首次下载（新装）该做什么**：装完对 AI 说一句 **"帮我一键配好"**（等价 `keeper_setup.py all`）——按你机器实况把钩子 / 守护 / 中文语义 / 调度一次配齐；随后**重启 WorkBuddy** 让钩子生效。只想手动记 / 找也完全可以，什么都不配即可。
