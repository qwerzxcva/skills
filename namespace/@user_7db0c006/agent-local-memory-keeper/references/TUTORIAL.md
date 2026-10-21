# Agent 记忆系统 · 完整上手教程（一步步 + 真实返回样例）

> 📌 **版本权威源**：本文档提及的 `vX.Y.Z` 仅作历史语境参考，**当前版本与功能变更以根目录 `CHANGELOG.md` 为唯一权威源**（见 `SKILL.md` 文件头 `version` 字段）。

> 这份教程是 `SKILL.md` 的「深读版」。设计上：`SKILL.md` 是给 AI 加载的**权威规则单**（必须一次读全，所以保持紧凑）；
> 这份教程是给「人 / 想看清每一步发生了什么」的**完整叙事**，放在 `references/` 下不撑爆主文件。
> 不想看原理，直接跑 `python scripts/demo_walkthrough.py` 看一遍端到端演示也行。

---

> 💬 **这份教程的每个命令，都能直接对 AI 说人话完成**（AI 在后台跑等价命令并回显）：
> | 你想做 | 直接对 AI 说 | 等价命令（下方对照） |
> |---|---|---|
> | 初始化 / 换存储路径 | 「初始化记忆库」「把记忆存到 D:/我的记忆」 | `memory_ops/__init__.py init` + `AI_MEMORY_STORE` |
> | 记一条经验 | 「记一下这个坑：……（用自然语言描述）」 | `deposit` |
> | 调出相关记忆 | 「帮我找关于 XX 的记忆」「刚才记的那条调出来」 | `recall` |
> | 纠正旧结论 | 「纠正之前记的 XX：其实应该是……」 | `deposit --corrects` |
> | 自动整理 | 「帮我整理今天记的」「去重整理一遍」 | `reflect --auto` |
> | 危险操作先预览 | 「把要删/改的先列出来给我确认」 | `--dry-run` |
> | 健康自检 | 「检查一下装好没」 | `keeper_setup.py doctor` |
> | 一键配好 | 「帮我一键配好」「顺便开自动记忆」 | `keeper_setup.py all` / `hooks --scheduler` |
> 下面每个命令段上方都标了「💬 不想敲命令？」提示，照表说即可。

## 0. 准备

引擎在 `scripts/memory_ops/__init__.py`。**开箱即用，无需配环境变量**：记忆默认存在跨平台零配置路径（Windows `~/AI记忆`、mac/Linux `~/.ai-memory`），首次使用自动建目录与索引；库不在默认位置时写 `~/.keeper/store_root` 或设 `AI_MEMORY_STORE`。想换路径再设 `AI_MEMORY_STORE`：

> 💬 **不想敲命令？** 直接对 AI 说你要做的事（如「记一下…」「帮我找…」「帮我一键配好」），AI 会在后台跑等价命令并回显——你不用手敲。
```bash
# 仅当你想改路径时才需要（可选）：
export AI_MEMORY_STORE=D:/我的记忆    # Windows PowerShell: $env:AI_MEMORY_STORE="D:/我的记忆"
# 一条命令完成首次准备（创建目录+索引），非技术用户也能直接用：
python scripts/memory_ops/__init__.py init
```

不需要联网就能用（**默认已是语义后端**，首次用到时自动下载一次约 90MB 模型；若下载失败会静默退回词法级——召回质量下降但不报错，可用 `doctor` 的 `fell_back_to_lexical` 判定）。命令报错时除了机器可读的 JSON，还会带 `hint` 人话字段（如「没找到这条记忆。常见原因：1) id 拼错…」），照着排查即可。

> 💡 **想更省事？** 中文语义 / 自动记忆（钩子+守护） / IMA 同步 / 换存储路径 这些「装后步骤」已收口成**一条命令**（`keeper_setup.py`，见下方 **§0.5**）。新用户直接看 §0.5；或干脆对 AI 说「帮我一键配好」，它替你跑完，不用手敲任何命令。

---

## 0.5 一键配置（推荐新用户）

上面的命令你**全都可以不敲**。所有「装完还要做的隐藏步骤」收口进 `scripts/keeper_setup.py` 向导，且自带六项就绪自检 `doctor`：

> 💬 **不想敲命令？** 直接对 AI 说你要做的事（如「记一下…」「帮我找…」「帮我一键配好」），AI 会在后台跑等价命令并回显——你不用手敲。
```bash
# 一条命令全配
python scripts/keeper_setup.py all
# 随时看「装好没」——绿红表一眼懂
python scripts/keeper_setup.py doctor
```

`all` 会依次收口：存储路径持久化 → 中文语义后端探测/安装 → 钩子注册 + 守护进程启动 + 每周调度自启。

**更省事：直接对话。** 在加载了本技能的会话里，说下面任一句，AI 在后台替你跑对应动作、每步回显「已设 XX」，最后跑 `doctor` 给绿红总览——你不用懂命令、不用敲环境变量：

| 你对 AI 说 | AI 执行 |
|---|---|
| 「帮我一键配好」/「全部默认配好」 | `keeper_setup.py all` |
| 「开后台自动记忆」 | `keeper_setup.py hooks --scheduler`（钩子+守护+调度自启；装完重启 WorkBuddy 生效） |
| 「配 IMA 同步」 | **优先 MCP 自动发现**：会话连了 IMA MCP 时 AI 直接列出你的可写知识库让你选（如「AI记忆」），不用去地址栏翻 ID；再 `keeper_setup.py ima --kb-id <ID>` |
| 「现在装好没」 | `keeper_setup.py doctor`（六项绿红自检） |

---

## 1. 记第一条经验

> 💬 **不想敲命令？** 直接对 AI 说你要做的事（如「记一下…」「帮我找…」「帮我一键配好」），AI 会在后台跑等价命令并回显——你不用手敲。
```bash
python scripts/memory_ops/__init__.py deposit \
  --category best_practice \
  --tags 导出,金蝶 \
  --summary "金蝶导出用网页版最稳" \
  --body "金蝶客户端导出大文件常 timeout，改用网页版后台导出更稳。" \
  --scope project --project PROJ_A
```

返回（成功即 `ok` + 新记忆 `id`，CLI 输出如下）：

```json
{"ok": true, "id": "LRN-20260720-001"}
```

磁盘上多了 `memories/LRN-20260720-001.json`，并登记进 SQLite 索引（`index.json` 同步导出，可作兜底）。不写 `--scope` 时系统按内容自动初判。

**这条记忆存进磁盘后长什么样**（真实 `memories/LRN-20260720-001.json` 的核心字段；语义向量**不进此 JSON**，单独存 `store/index.sqlite` 的 `embeddings` 表，避免文件膨胀）：

```json
{
  "id": "LRN-20260720-001",
  "category": "best_practice",
  "summary": "金蝶导出用网页版最稳",
  "body": "金蝶客户端导出大文件常 timeout，改用网页版后台导出更稳。",
  "tags": ["导出", "金蝶"],
  "scope": "project",
  "project": "PROJ_A",
  "type": "BP",
  "status": "active",
  "tier": "working",
  "confidence": 1.0,
  "importance": 0.7,
  "belief_strength": 1.0,
  "created": "2026-07-20",
  "accessed": "2026-07-20",
  "thermal": "warm",
  "embedding_status": "neural:fastembed:BAAI/bge-small-zh-v1.5",
  "provenance": "agent",
  "version": 1
}
```

字段分两类：**你给的**（summary / body / tags / category / scope / project）、**系统自动维护的**（type / status / tier / importance / thermal / embedding_status / belief_strength / version 等 40+ 项）。其中 `embedding_status` 是召回质量信号——真语义后端可用时显示 `neural:...`；若 fastembed 加载失败降级，则显示 `lexical_degraded`（此时召回质量下降，命令行会一次性告警提示，不会悄悄换）。完整字段 schema 见 `references/` 下对应文档。

---

## 2. 用的时候调出来（看返回长什么样）

> 💬 **不想敲命令？** 直接对 AI 说你要做的事（如「记一下…」「帮我找…」「帮我一键配好」），AI 会在后台跑等价命令并回显——你不用手敲。
```bash
python scripts/memory_ops/__init__.py recall --tag 导出
```

返回：

```json
{
  "ok": true,
  "count": 1,
  "entries": [
    {
      "id": "LRN-20260720-001",
      "category": "best_practice",
      "summary": "金蝶导出用网页版最稳",
      "tags": ["导出", "金蝶"],
      "tier": "working",
      "status": "active",
      "scope": "project",
      "project": "PROJ_A",
      "file": "LRN-20260720-001.json"
    }
  ]
}
```

`--query "金蝶怎么导出不超时"` 走中文语义排序；`--scope universal` / `--project PROJ_A` 收窄。

---

## 3. 发现以前记错了 → 存纠正，旧的自动让位

> 💬 **不想敲命令？** 直接对 AI 说你要做的事（如「记一下…」「帮我找…」「帮我一键配好」），AI 会在后台跑等价命令并回显——你不用手敲。
```bash
python scripts/memory_ops/__init__.py deposit \
  --category correction --corrects LRN-20260720-001 \
  --summary "金蝶导出其实用客户端批量更稳" \
  --body "新版本客户端已修复 timeout，反而比网页快。"
```

返回新 id `LRN-20260720-002`。再召回：

```json
{
  "ok": true,
  "count": 1,
  "entries": [
    { "id": "LRN-20260720-002", "category": "correction",
      "status": "active", "summary": "金蝶导出其实用客户端批量更稳" }
  ]
}
```

旧的 `LRN-20260720-001` 已被标 `superseded`，默认召回不返回——**真相永远收敛到最新**，不会两个矛盾结论一起冒出来。

---

## 4. 存完一堆，让它自己整理

> 💬 **不想敲命令？** 直接对 AI 说你要做的事（如「记一下…」「帮我找…」「帮我一键配好」），AI 会在后台跑等价命令并回显——你不用手敲。
```bash
python scripts/memory_ops/__init__.py reflect --auto
```

返回 findings（无矛盾时各列表为空）：

```json
{ "duplicates": [], "contradictions": [], "stale": [],
  "promote_candidates": [], "scope_review": [] }
```

`reflect` 做四件事：去重、纠错、分类复评、过期归档。**它永不删除**，只把过期记忆搬到 `memories/archive/`（沉底，可找回）。

> 🗄️ **180 天归档机制**：`reclaim`（批处理归档清理 + IMA 镜像，**独立 op**，并非 `archive` 别名）把沉淀超 180 天 / 超额的软删记忆**批量转为已归档**（沉到 `archive/`，永不删除）并重新生成 IMA 导出。`archive` 则是**单条**软删归档（`archive --id <id>`，可 `unarchive` 找回），二者底层同 `archive_sweep` 但命令各自注册。`reclaim --review`（或 `python scripts/keeper_setup.py archive --review`）每周复查归档项是否过时 / 有更优方法替代。终态从「删除」改为「归档 + IMA 镜像」，守住「将来遇到了还能找到」。

---

## 5. 危险操作：先预览，再确认

删除前先看会动哪个文件（不执行）：

> 💬 **不想敲命令？** 直接对 AI 说你要做的事（如「记一下…」「帮我找…」「帮我一键配好」），AI 会在后台跑等价命令并回显——你不用手敲。
```bash
python scripts/memory_ops/__init__.py delete --id LRN-20260720-002 --dry-run
```

```json
{ "dry_run": true, "op": "delete", "id": "LRN-20260720-002",
  "file": "D:/.../memories/LRN-20260720-002.json" }
```

同时 stderr 会打印「危险操作预览」告诉我们文件在哪、删了怎么恢复。确认无误再正式删（加 `--yes` 关闭提示）：

> 💬 **不想敲命令？** 直接对 AI 说你要做的事（如「记一下…」「帮我找…」「帮我一键配好」），AI 会在后台跑等价命令并回显——你不用手敲。
```bash
python scripts/memory_ops/__init__.py delete --id LRN-20260720-002 --yes
# 返回 {"ok": true, "id": "LRN-20260720-002"}
```

不确定要不要彻底删？用 `archive` 代替（沉底不删，`recall --deep` 还能召回）。

---

## 6. 健康自检

> 💬 **不想敲命令？** 直接对 AI 说你要做的事（如「记一下…」「帮我找…」「帮我一键配好」），AI 会在后台跑等价命令并回显——你不用手敲。
```bash
python scripts/memory_ops/__init__.py doctor
```

```json
{
  "entries": 1, "files": 1, "corrupt_files": [], "index_without_file": [],
  "missing_files": [],
  "dangling_relations": [
    { "id": "LRN-20260720-001", "rel": "superseded_by", "target": "LRN-20260720-002" }
  ],
  "status_mismatch": [], "scope_mismatch_candidates": [], "total_token_estimate": 53
}
```

`dangling_relations` 提示"被纠正的记忆还链着已删的旧版"——这是正常线索，用 `rebuild` 或补一条 `link` 即可理顺。

> 🩺 **装好没？（就绪自检）**：上面是「库内健康」深查。想快速看「钩子 / 守护 / 语义 / IMA 都通了吗」，跑：
> ```bash
> python scripts/keeper_setup.py doctor
> ```
> 它输出六项绿红表（存储根 / 中文语义 / 钩子注册 / 守护进程 / IMA 同步 / 召回冒烟），比 `memory_ops.py doctor` 更适合装后一眼确认。

---

## 7. 多窗口并发冲突长什么样

若你在一个窗口读取某记忆后、写回前，另一个窗口已改了它，写回会被拦下：

```json
{ "ok": false, "error": "write_conflict",
  "msg": "写入冲突：记忆 LRN-... 在您读取后被另一个进程修改过（磁盘 mtime ... 与您读取时的 ... 不一致）。已中止本次写入……先用 recall --id <id> 重新读取最新内容，合并修改后再写；或运行 doctor --fix 检查一致性。" }
```

按提示重读再合并即可，不会互相覆盖吞掉修改。

---

## 8. 进阶场景速查

| 想做 | 命令 |
|---|---|
| 项目记忆只在本项目召回 | `deposit --scope project --project PROJ_A`；召回 `recall --scope project --project PROJ_A` |
| 重要经验每次启动都带 | `promote --id <id> --tier core` |
| 归类错了手动改 | `reclassify --id <id> --scope universal --reason "..."` |
| 两条经验关联 | `link --id <id> --rel see_also --target <另一条id>` |
| 索引坏了重建 | `rebuild` |
| 启用真语义神经检索（可选） | `pip install fastembed` → 设 `AI_MEM_EMBED_BACKEND=fastembed`（受限网络加 `HF_ENDPOINT=https://hf-mirror.com` + `HF_HUB_DISABLE_XET=1`）；**完整装法/验证/排错见 `references/INSTALL.md`** |
| 一键配置向导（推荐） | `python scripts/keeper_setup.py all` 收口全部装后步骤；`doctor` 看就绪绿红表 |

完整数据模型见 `references/FORMAT_ANALYSIS.md`；向量后端与召回调优见 `references/FEATURES.md` §6–§7；命令全表见 `references/COMMANDS.md`。

---

## 9. 会话钩子（装完 skill 即生效）与 IMA 云端镜像一键同步

### 9.1 钩子：不用再手跑安装脚本

钩子**默认自动注册**。你装完 skill 后第一次跑任意命令（如 `deposit` / `recall`），`memory_ops.py` 会检测 `~/.workbuddy/settings.json`：

- 若还没 keeper 钩子 → 自动调 `install_hooks.py` 注册（幂等，保留 WorkBuddy 内置 hook），stderr 打印 `🔌 [keeper] 首次自动注册会话钩子…`；
- 若已注册 → 跳过，什么都不做。

> 💬 **不想敲命令？** 直接对 AI 说你要做的事（如「记一下…」「帮我找…」「帮我一键配好」），AI 会在后台跑等价命令并回显——你不用手敲。
```bash
# 想看将要做什么（不改动）：
python install_hooks.py --dry-run
# 想彻底关掉自动注册（仍保留手动能力）：
export KEEPER_AUTO_INSTALL_HOOKS=0
```

重启 WorkBuddy 后，钩子生效：会话开局自动注入相关经验、结束自动蒸馏要点、本地弱召回时提示走 IMA 兜底。

> ✅ **最可靠的一步到位**：不想等首次命令触发自动注册，直接跑 `python scripts/keeper_setup.py hooks --scheduler`——它会注册 5 个钩子 + 启动守护进程 + 注册每周调度自启（等价于 `install_hooks.py` + `setup_scheduler.py`）。纯靠 AI 对话的用户尤其推荐这条，避免「只靠 AI 却从没手动跑过命令、钩子一直没注册」的坑。

### 9.2 IMA 云端镜像：配置一次 + 一段可贴指令

把记忆镜像到 IMA 知识库原本要手拼「导出 → create_media → COS 上传 → add_knowledge → search」五步，且 `create_media`/`add_knowledge` 是 IMA MCP 工具（脚本调不到，必须由 Agent 经 MCP 执行）。`ima_sync.py` 把"能脚本化的部分"一键做完。

**配置目标库（只需一次）**：**优先走 MCP 自动发现**——会话已连 IMA MCP 时，直接对 AI 说「配 IMA 同步」，AI 调 `get_addable_knowledge_base_list` 列出你的可写知识库让你选（如「AI记忆」），再 `keeper_setup.py ima --kb-id <ID>` 把 ID 写入 `config.json` + 注册表（跨 shell 立即可见）。配置后 `keeper_setup.py doctor` 的「IMA 同步」项立即变绿。未配置时 `ima_sync.py --push` 会直接报错给指引，不再「前半段成功、Agent 那步才失败」。

> 💬 **不想敲命令？** 直接对 AI 说你要做的事（如「记一下…」「帮我找…」「帮我一键配好」），AI 会在后台跑等价命令并回显——你不用手敲。
```bash
python scripts/ima_sync.py
```

输出（示意）：

```
=== [1/3] 导出 + 脱敏（_keeper_ima_push.py）===
域[work] 8 条 → C:\Users\<你>\.workbuddy\ima_push\keeper-镜像-work.md
=== [2/3] 脱敏后复检（verify_desensitization）===
✅ 脱敏复检通过：1 个域文档无敏感信息残留。
=== [3/3] 生成 Agent 推送指令 ===
------------------------------------------------------------
请把以下记忆镜像文件推送到 IMA 知识库（知识库ID：YOUR_IMA_KB_ID，名称「AI记忆」）。
这些文件已由 `python scripts/ima_sync.py` 自动**脱敏 + 复检通过**，可放心推送。
每个文件走三步（务必带 REPLACE 防堆积）：
1) create_media(content_type="text/markdown", file_name="<文件名>", file_size=<字节数>, knowledge_base_id="YOUR_IMA_KB_ID") → media_id + cos_credential
2) python scripts/ima_cos_upload.py <cos_credential.json> <文件绝对路径> text/markdown
3) add_knowledge(knowledge_base_id="YOUR_IMA_KB_ID", media_id=<第1步>, duplicate_name_strategy=DUPLICATE_NAME_STRATEGY_REPLACE)
文件清单（共 1 个）：
- C:\Users\<你>\.workbuddy\ima_push\keeper-镜像-work.md （6180 字节）
------------------------------------------------------------
👉 把上面这段指令直接发给 Agent 即可完成入库。
```

**关键点**：

- **脱敏是强制的、且双重保险**：`_keeper_ima_push.py` 先 strip 凭证/真实路径/邮箱并替换占位；`verify_desensitization()` 再扫一遍，**任何残留敏感信息直接失败退出**，绝不交付明文文件。
- **入库由 Agent 做**：把打印出的那段指令直接发给 Agent，它经 IMA MCP 完成 create_media / add_knowledge（脚本无法代调 MCP，这是设计使然）。也可直接说「把 ima_push 下的记忆镜像推到 IMA 知识库」。
- **永不堆积**：文档用稳定文件名 + `REPLACE`，每周重推原地替换。
- **归档项带标记**：已归档/被取代记忆推到 IMA 时自动加 `【归档】` 前缀 + `#归档` 标签，与活跃记忆区分但仍可检索（跨设备冷存储兜底）。
- 指定知识库（推荐）：`python scripts/keeper_setup.py ima --kb-id <KB_ID>`（写入 config.json + 注册表，跨 shell 立即可见）；也可直接 `python scripts/ima_sync.py --kb-id <KB_ID>`（默认 `IMA_KB_ID` 或内置已知库 `YOUR_IMA_KB_ID`）；`--open` 尽力打开 IMA 网页。
