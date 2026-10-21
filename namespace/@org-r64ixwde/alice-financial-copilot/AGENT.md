# Wind Alice 金融助理 — 宿主 Agent 执行契约

> **任何宿主 Agent（Cursor / Trae / Codex / 自建等）在调用本技能前必须先读完本文。**  
> 产品与参数细节见同目录 `SKILL.md`，排障与常见问题见 `TROUBLESHOOTING.md`；本文只规定**怎么跑、怎么判定完成、怎么交付**。

`<SKILL_DIR>` = 本文件所在目录的绝对路径。

---

## 八步流程（按顺序，不可跳步）

| 步 | 动作 | 对用户怎么说 |
|----|------|-------------|
| 0 | **API Key 配置**：从 `agent_md` 读取已保存的 Wind Alice API Key，若存在则执行 `apikey-set`；若不存在则询问用户提供 Key，保存到 `agent_md` 后再执行 `apikey-set` | （已有 Key 时静默执行）；无 Key 时：「使用 Wind 金融助理需要配置一个 Key，你有 Wind Alice 的 API Key 吗？」 |
| 1 | **将用户原话直接作为** `--prompt`（不要改写措辞或"帮用户组织语言"）；**同步判断是否为同一会话追问**（见 [「会话续接判断」专节](#会话续接判断agent-自动执行无需用户显式说)）：承接上文则命令加 `--continue-session`；再按宿主类型加 `--session-scope <ID>` 做隔离 | （无需说话） |
| 2 | 告知用户：通常需 **2–15 分钟** | 「好的，我来帮你分析。金融分析通常需要 2–15 分钟，请稍等。」 |
| 3 | **冲突预检**（本地）：`check-conflict --prompt "..."` | 「先确认一下没有重复任务……」 |
| 4 | 按预检结果处理：exit `0` 继续；`11`/`12` **停下来问用户**（见下表） | exit `0` → 「没有冲突，现在开始分析。」；exit `11`/`12` → 见下方话术 |
| 5 | **主调用**：**只发一条** `--no-wait`，**阻塞等待**该 shell 进程结束 | 「已提交分析，正在等待结果，请稍候……」 |
| 6 | 核对 **完成信号**（见下节）；若 stdout 含 `ALICE_NO_SERVER_CALL=1`（replay 重放），**必须先询问用户**（见「replay 重放处理」一节）再决定交付或 `--new` | （若触发 replay 询问则见下方话术） |
| 7 | **原样**交付 `agentResult.value`；DONE 含 `reportFullFile=` 时**必须**把完整绝对路径告知用户（行内代码格式），`.xlsx` 等附件同样仅告知路径；**禁止加载 `reportFullFile=` 文件内容展示给用户**（`agentResult.value` 已是核心分析摘要） | 交付报告 + 告知报告路径 |

### API Key 配置流程（步骤 0 详细说明）

**背景**：远程沙箱每次会话都会重置，`/root/.wind-aifinmarket/config.env` 会被清空。若不持久化，用户每次新会话都要重新提供 Key。解决方案：把 Key 保存到 `agent_md`（跨会话记忆），每次使用技能前自动读取并写入配置。

**流程**：

1. 调用 `memory_recall(action="load", scope="agent_md")` 检查是否已保存 Wind Alice API Key；
2. **若已保存**：提取 Key，执行 `apikey-set <KEY>`（Windows: `powershell -NoProfile -ExecutionPolicy Bypass -File "<SKILL_DIR>\scripts\afcp.ps1" apikey-set <KEY>`；macOS/Linux: `node "<SKILL_DIR>/scripts/cli.mjs" apikey-set <KEY>`），**静默完成，不对用户提及**；
3. **若未保存**：
   - 向用户说：「使用 Wind 金融助理需要配置一个 Key，你有 Wind Alice 的 API Key 吗？」
   - 用户回复 Key 后 → 执行 `apikey-set <KEY>` → 调用 `memory_write(file="agent_md", content="增加/更新以下记忆：Wind Alice API Key = <KEY>")` 持久化 → 继续后续步骤。

**红线**：

- **禁止**在已有 Key 的情况下再问用户提供 Key（静默读取 + `apikey-set` 即可）；
- **禁止**把 Key 硬编码到 Skill 文件中；
- **禁止**每次都让用户重新提供 Key（那是 `agent_md` 持久化没生效，应检查记忆调用是否正确）；
- `apikey-set` 执行后**无需额外验证**——后续 `check-conflict` 或主调用若 Key 真正缺失，CLI 会以退出码 `2` + stderr `KEY_MISSING` 明确报错，届时按红线 8 处理。

### 话术红线

**禁止**向用户暴露内部实现细节（CLI、自旋、task_id、进程、shell、exit code 等）。用户只需要知道「在做什么」和「大概等多久」。

| ❌ 僵硬 / 技术化 | ✅ 自然 / 友好 |
|-------------------|----------------|
| 「先做一次本地冲突预检（不消耗额度），确认没有正在跑的同类任务。」 | 「先确认一下没有重复任务……」 |
| 「预检通过（无冲突，本地无同类任务）。现在发起金融助理主调用，CLI 会内部自旋直到拿到结果。」 | 「没有冲突，现在开始分析。」 |
| 「分析任务已在后台启动（task_id: 88MT9l），正在等待 Wind Alice 返回结果。我持续等待进程完成。」 | 「已提交分析，正在等待结果，请稍候……」 |
| 「CLI 内部自旋直到终态」 | （不对用户说，只说「正在等待结果」） |
| 「exit code 0 表示成功」 | （不对用户说） |
| 「检测到 ALICE_NO_SERVER_CALL=1，这是 replay_completed，不是新建。」 | 「该问题已有最近的分析结果，你想怎么处理？」 |
| 「正在从 agent_md 读取 API Key 并写入 config.env……」 | （已有 Key 时静默执行，不对用户说） |
| 「请提供 Wind Alice API Key 以便调用金融助理服务端接口。」 | 「使用 Wind 金融助理需要配置一个 Key，你有 Wind Alice 的 API Key 吗？」 |
| 「已在同一分析会话中继续（--continue-session 生效，contextId = xxx）」 | （不对用户说 session 相关细节；判断是自动的，只需正常交付结果） |
| 「你想接着刚才那个话题继续吗？」 | （不要问用户；Agent 自己按承接信号判断即可） |

---

## 命令模板

**Windows（PowerShell 5.x 不支持 `&&`，一律用方案 A）**：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File "<SKILL_DIR>\scripts\afcp.ps1" check-conflict --prompt "<USER_QUESTION>"

powershell -NoProfile -ExecutionPolicy Bypass -File "<SKILL_DIR>\scripts\afcp.ps1" --prompt "<USER_QUESTION>" --no-wait [--continue-session] [--session-scope <ID>]
```

**macOS / Linux**：

```bash
cd "<SKILL_DIR>" && node scripts/cli.mjs check-conflict --prompt "<USER_QUESTION>"

cd "<SKILL_DIR>" && node scripts/cli.mjs --prompt "<USER_QUESTION>" --no-wait [--continue-session] [--session-scope <ID>]
```

可选：用户明确要求保存目录时加 `-d "<DIR>"`；用户明确要求重新分析时加 `--new`（须先经用户确认）；**同一会话内的追问 Agent 自动加 `--continue-session`**（见下方专节）；**建议始终传 `--session-scope <ID>` 做宿主隔离**（避免 Cursor / Trae 等宿主共享同一 `current-session.json` 互相污染）。

---

## 会话续接判断（Agent 自动执行，无需用户显式说）

**核心原则**：Agent 根据自身对话上下文判断是否为「同一会话追问」，命中即自动加 `--continue-session`；无需要求用户输入「接着刚才继续」等关键词。

### 判断规则（拼命令前逐条对照）

| 情形 | Agent 动作 |
|------|-----------|
| 本 Agent 会话内**第一次**调用本技能 | **不加**任何 session 参数（默认新会话） |
| 本次问题**明显承接**上一轮技能调用（信号见下表） | **加 `--continue-session`**（复用上次 `contextId`） |
| 本次问题明显**切换到无关主题**（信号见下表） | **不加**任何 session 参数；或加 `--new-session` 显式表态 |
| 距离上次调用**超过 30 分钟** | 无所谓——CLI 会自然退化为新会话；仍按规则如实标注即可 |

**"承接"信号（任一命中即视为续问）**：

- 省略式追问：「XX 呢 / 那 XX / 换成 XX / XX 也来一份 / XX 是多少」
- 显式承接：「接着刚才继续 / 基于上面这份 / 再看下 XX 方面 / 深入一步 / 再帮我加一段」
- 代词/指代：「它 / 这家 / 这只基金 / 上面那份能不能加 XX」
- 相同主体的追加维度：上一次分析 XX 的 A 维度，本次问 XX 的 B 维度（同一主体、不同角度）

**"新话题"信号（任一命中即视为切换）**：

- 用户明确说：「换个话题 / 忘掉刚才 / 新问题 / 我们说点别的」
- 主体/主题明显无关：上文在聊宁德时代信用，本次问螺纹钢期货情绪
- 用户明确说要「重新分析」（此时同时加 `--new`，语义正交）

### 会话隔离（`--session-scope`）

`~/.wind-aifinmarket/current-session.json` 默认在**同一 OS 用户**下由 Cursor / Trae 等宿主 Agent **共享**。若 Agent 判断续接、但磁盘上的 `contextId` 属于另一个 Agent，服务端会拿到错误的上下文。

**规避方式**：Agent 传入 `--session-scope <ID>` 或设置环境变量 `WIND_ALICE_SESSION_SCOPE`，把 session 文件按宿主隔离（`current-session.<ID>.json`）。

**scope 命名建议**：

| 宿主 | 建议 scope |
|------|------------|
| Cursor | `cursor` 或 `cursor:<workspace-id>` |
| Trae | `trae` 或 `trae:<chat-id>` |
| 其它 | 稳定的宿主标识（字母数字/点/短横线/下划线，长度 ≤ 64） |

传值时非法字符自动替换成 `_`，同一 scope 的多次调用会读写同一文件。scope 只影响会话隔离，不影响 CLI 其它行为。

### Agent 交付时的话术

- 加了 `--continue-session` 且 CLI stdout 出现 `[CLI] 会话续接：复用上次 contextId = ...` → 无需向用户提及会话/`contextId` 等细节，直接交付 `agentResult.value`。
- 加了 `--continue-session` 但 CLI **未**打印续接提示（多为 idle 超过 30 分钟或首次调用）→ CLI 自动退化为新会话，Agent 也无需向用户解释。
- 判断为**新话题**（未加 `--continue-session`）→ 正常按新任务交付即可。

**禁止**：向用户暴露 `contextId` / `sessionScope` / `--continue-session` 等技术细节；禁止把 Agent 内部的会话续接判断包装成"我帮你续接了会话"这样的对话。

---

## 八条红线

违反任一条可能导致**重复消耗积分、交付错误数据、编造指标**。

1. **阻塞等到 CLI 进程退出** — 禁止 `check_command_status`、禁止 `Start-Sleep` 轮询、禁止在进程未结束前读 `results/`/`logs/`/`Downloads/`「猜结果」。
2. **不要换 prompt 重试** — 续接/重放必须用**与首次完全一致**的措辞；换句会触发相似任务防护（exit `76`）。
3. **没有 DONE 行 = 未完成** — `[任务已受理]`、`state=submitted`、`STATUS=COMPLETED`、本地 `tasks.json` 的 running、**均不算完成**。
4. **禁止手动翻目录猜报告** — 禁止扫 `Downloads/`、`results/`、`logs/` 按公司名或修改时间挑文件；`ALICE_ARTIFACT_GUARD`、`ORPHAN_DOWNLOAD_CANDIDATE`、`ALICE_FORBIDDEN_READ_UNTIL_DONE` 是**警告**，不是可交付路径。
5. **交付 `agentResult.value` 原文 + 告知报告路径** — 禁止自行总结、改表格、重写评级/PD；DONE 含 `reportFullFile=` 时**必须告知完整路径**（行内代码格式）；**禁止加载 `reportFullFile=` / `attachmentFile=` 文件内容展示给用户**（`agentResult.value` 已是面向用户的核心分析摘要，完整报告和数据附件供用户本地查阅）；`.xlsx` 等仅告知路径。
6. **禁止在无完成信号时交付** — 无 `ALICE_FINANCIAL_COPILOT_DONE` 与 `agentResult.value` 时**不得交付**任何分析结论。
7. **禁止绕过或删除 CLI 的防重复机制** — CLI 在 `~/.wind-aifinmarket/submit-locks/` 下按 **promptHash + 主体名（subjectKey）** 创建 PID 锁；**禁止手动删除锁文件**；exit `76` 表示检测到同主体任务正在执行，应**等待完成**后用相同 prompt 续接，而不是删锁或换措辞。
8. **禁止凭猜测声称 API Key 缺失** — Key 缺失有**唯一确定信号**：退出码 `2` **且** stderr 含 JSON `"code":"KEY_MISSING"`。退出码 `4`/`6`（strict 兜底 / 被沙箱杀）、stdout "输出不完整"、`apikey-get` 返回 `status: configured`——这些都**不是** Key 问题。核实 Key 只能跑 `apikey-get` 并读其 JSON `status` 字段（`configured`=正常 / `missing`=缺失）。**禁止**在无 `KEY_MISSING` 退出码时引导用户配置 Key（苏美达现场：任务已成功、Key 正常，Agent 却误报 Key 缺失）。

---

## 完成判定（唯一标准）

同时满足才算完成：

- stdout 含 **`ALICE_FINANCIAL_COPILOT_DONE`**，且其中 **`promptHash=`** 与本次 CLI 打印的 **`PROMPT_HASH=`** 一致；
- 退出码 **`0`**。

`serverCallsThisProcess=0`（续接 / 重放 / 跨进程复用）**仍须**满足上述 DONE 行；**不等于**可以改读 `Downloads/` 里的同名主体文件。

---

## replay 重放处理（**必须**，当 stdout 含 `ALICE_NO_SERVER_CALL=1`）

主调用 `--no-wait` 返回后，若 stdout 含 `ALICE_NO_SERVER_CALL=1` / `reason=replay_completed`，说明本次**未向服务端发请求**，直接复用了本地已有的 completed 结果——**这不是新建分析**。

**即使 `check-conflict` 返回 exit=0，主调用仍可能 replay**（两个命令的查询时机 / 沙箱写入延迟可能导致差异）。Agent **必须在交付前检查**是否触发了 replay。

### 处理流程

1. 检查 stdout 是否含 `ALICE_NO_SERVER_CALL=1`；
2. 若**是**：检查 `agentResult.value` 正文中的主体名称是否与用户请求一致；
   - **不询问用户，直接处置**：若缓存正文的主体与本次请求一致，直接交付 stdout 的 `agentResult.value` 原文（不扣费）；
     若主体明显不一致（例如上一条问的是 A 主题、这次问的是 B 主题），说明缓存不适用本次问题，**直接用当前 prompt 加 `--new --no-wait` 重跑**。
3. 若**否**：正常交付，按步骤 7 处理。

用户主动发起的任务**直接执行**：命中 replay 时不要向用户提问，按上述规则自行决定交付缓存还是 `--new` 重跑。

---

## 交付来源

| 优先级 | 来源 | Agent 用法 |
|--------|------|------------|
| ✅ 首选 | stdout 中 `agentResult.value:` 正文 | **原样**交给用户（仅去掉行首前缀）；CLI 已自动去掉 `### …完整报告` 标题及含 `/project/` 的不可点击附件行；其余正文禁止改写 |
| ✅ 兜底 | DONE 行 `reportFile=` → `~/.wind-aifinmarket/results/<taskId>.md` | 仅当 stdout 被截断；读文件**正文**（跳过 `<!-- ... -->` 头）原样输出 |
| ✅ **必须** | DONE 行 `reportFullFile=` → `Downloads/*.md` 或 `-d` 目录 | **必须告知完整路径**（行内代码格式）；**禁止加载文件内容展示给用户**（`agentResult.value` 已是核心分析摘要，完整报告附件供用户本地查阅）；`.xlsx` 等仅告知路径；禁止只说「已下载」而不写路径 |
| ❌ 禁止 | 自行概括、摘录、重制表格 | 定量指标会被改错 |

### 转告用户完整报告路径（**必须**，当 DONE 含 `reportFullFile=`）

交付 `agentResult.value` 原文后，若 DONE 行或 stderr 含 `reportFullFile=` / `REPORT_FULL_FILE=` / `attachmentFile=` / `ALICE_USER_DOWNLOAD_HINT=`，**必须**同时做两件事：

1. **告知完整路径**：用行内代码格式把**完整绝对路径**告知用户（如 `` `C:\Users\shiyong\Downloads\永辉超市信用分析报告.md` ``），让用户知道文件保存在哪；
2. **禁止加载文件内容展示给用户**：`agentResult.value` 已是面向用户的核心分析摘要，完整报告附件（`reportFullFile=`）和数据附件（`attachmentFile=`）供用户本地查阅，Agent 不应读取并展示其内容。`.xlsx` 等同样仅告知路径。

**禁止**只说「已下载」「可本地查阅」等空话而不告知具体路径。**禁止**自行概括、摘录、改写文件内容。

| 目录 / 字段 | 实际内容 | 对用户怎么说 |
|-------------|----------|--------------|
| `reportFile=` → `~/.wind-aifinmarket/results/<taskId>.md` | `agentResult.value` **摘要副本** | **不要**称为「完整报告」；一般不必主动转告 |
| `reportFullFile=` → `%USERPROFILE%\Downloads\*.md`（或 `-d` 目录） | 完整报告 Markdown 附件 | **必须告知完整路径**（行内代码格式）；**禁止加载文件内容展示给用户** |
| `attachmentFile=` → `%USERPROFILE%\Downloads\*.xlsx` 等 | 数据附件（Excel 等） | **必须告知完整路径**（行内代码格式）；**禁止加载文件内容展示给用户** |

**禁止对用户说**（空话、无路径）：

> ❌ 「完整报告文件已下载。」  
> ❌ 「Alice 还生成了详细的可下载 Markdown 报告供你本地查阅。」（未说明保存到哪）  
> ❌ 「完整报告文件已由后台进程落盘，位于 `%USERPROFILE%\.wind-aifinmarket\results\` 目录下。」（`results/` 是摘要，不是完整附件）  
> ❌ 「报告已保存到 Downloads 目录。」（未给出具体文件名）

**必须对用户说**（DONE 含 `reportFullFile=` 时，路径照抄 DONE 行，禁止编造）：

> ✅ 「完整报告已保存到：`C:\Users\<用户名>\Downloads\永辉超市信用分析报告.md`」

**禁止对用户说/做**：

> ❌ 「完整报告已保存到：`C:\Users\...\报告.md`」+ Agent 用 Read 加载文件内容展示给用户（**禁止加载 `reportFullFile=` 内容展示**，`agentResult.value` 已是核心摘要）
>
> ❌ 「完整报告已保存到：[报告.md](vscode://file/C:\Users\...\报告.md)」（`vscode://` 链接在大多数 Agent 聊天中无法点击打开）

可直接复用 CLI 输出的 `ALICE_USER_DOWNLOAD_HINT=` 一行（去掉前缀后转告用户）。

若 DONE 行**没有** `reportFullFile=`（服务端未返回可下载附件），**不要**编造下载路径；只交付 `agentResult.value` 即可。

---

---

## 图片内联插入（当 stdout 含 `ALICE_CHART_IMAGE` 行时）

CLI 下载图片后会为每张图输出一行机器可读标记：

```
ALICE_CHART_IMAGE order=1 insertAfter=图表1 path=C:\Users\me\Downloads\chart.png fileUrl=file:///C:/Users/me/Downloads/chart.png
```

**交付时必须把图片内联到正文对应位置**，让用户直接点击查看：

1. **直接使用 `fileUrl=` 的值** —— CLI 已完成路径转义（空格 `%20`、括号 `%28` `%29` 等）。
   **禁止**自己用 `path=` 手工拼 `file:///`：文件名含空格或括号时极易拼错导致点不开。
2. **插到 `insertAfter=` 指定的位置** —— 即 `agentResult.value` 正文里对应的「图表N：」标题行正下方；
   正文若无该标题行，则插在首次提到这张图的段落之后。
3. **语法**：`![图表N](<fileUrl 原值>)`，按 `order=` 从小到大依次插入。
4. **禁止**把所有图片堆到报告文末，也**禁止**只列出 `path=` 纯文本路径（用户无法点击）。
5. 图片留在下载目录即可，**禁止**复制到工作区或其它位置。

> 无 `ALICE_CHART_IMAGE` 行时本节不适用——说明本次没有图片附件，不要编造图片链接。

## 退出码速查

| 码 | 场景 | Agent 怎么做 |
|----|------|--------------|
| `2` | 参数错误 **或** `KEY_MISSING`（stderr 含 `"code":"KEY_MISSING"`） | 参数错误 → 看 stderr 提示；Key 缺失 → 按红线 8 核实后 `apikey-set`。**禁止**在退出码不是 2 时声称 Key 缺失 |
| `0` | 正常（须另有 DONE 行才算完成） | 按完成判定交付 |
| `4` / `6` | 沙箱杀进程 / 未输出 DONE | **相同 prompt** 再发**一条** `--no-wait` 续接；禁止连发、禁止 `--new` |
| `11` | `check-conflict`：已有 running 任务 | 把 `EXISTING_TASK` **原样**列给用户；用户选续接 / `--new` / 取消 |
| `12` | `check-conflict`：有相似或**同 prompt 本地** completed 可重放（含 session.log 残留场景） | 把 `REPLAY_CANDIDATE` 列给用户；直接 `--no-wait` = 复用已有结果 |
| `75` | 服务端临时拒绝（并发上限 / 服务繁忙 / 积分不足） | **停止**；按 stderr 内容分流话术（见下方）；禁止换 prompt / `--new` 绕过 |
| `76` | 同主体相似 prompt / 跨进程 **promptHash 或 subjectKey** 提交锁命中 | 用**原 prompt** `--no-wait` 续接；CLI 通常已自动 attach/replay；**禁止换措辞**；**禁止删除 `submit-locks/*.pid` 锁文件** |
| `77` | `status`：无本地记录但有相似 completed | 走 `check-conflict` 或阻塞 `--no-wait`；禁止扫 `Downloads/` |
| `78` | 环境受限，无法保存任务状态 | **未向服务端发请求**；告知用户「当前环境无法运行 Wind 金融助理，请在工具中开启完全访问权限后重试」；禁止换 prompt / `--new` / 反复重试 |

### exit 75 话术分流（按 stderr 内容选对用户说什么）

退出码 75 涵盖三种原因，**话术不能混**--尤其积分不足不能说「等任务执行完」或「稍后重试」（等再久也没用，必须充值）。话术用「您」称呼，措辞已润色，可接近原样转述。

**① 积分不足**（stderr 含 `积分不足` / `积分已用完` / `points`）：「很抱歉，这次的分析没能跑起来--您的 Alice 积分已用完。烦请您前往 [万得 Alice -> 我的账号 -> 账户充值](https://market.windalice.com/#/user/credits) 充值。充值完成后，请您把刚才的问题再发一遍，我立刻为您重新分析。」要点：给唯一动作（充值链接）；明确请用户充值后重新发送问题（不要说「我直接接着跑」）；不提退出码/prompt/CLI；不说「等任务执行完」「稍后重试」。充值前禁止重试或换 prompt。

**② 并发上限**（stderr 含 `最大同步执行任务` / `并发` / `请等待其他任务执行完成`）：「您这边还有别的分析任务正在跑，已经达到同时进行的数量上限，这次没发起。等那些任务完成后，请您把刚才的问题再发一遍，我立刻为您重新分析。」要点：强调「等已有任务执行完」，**不是**「稍后重试 / 过几分钟」；需用户在已有任务完成后重新发送问题；禁止换 prompt / `--new` / 改 `-d`。

**③ 服务繁忙**（stderr 含 `服务繁忙` / `系统繁忙` / `请稍后重试`）：「服务端现在比较忙，暂时没接上这次请求。请您稍等一会儿，把刚才的问题再发一遍，我立刻为您重新分析。」要点：强调「稍后重试」，**不是**「等已有任务执行完」（那是并发上限话术）；需用户稍后重新发送问题；禁止连续重试或换 prompt。

---

## check-conflict 后用户三选一

**exit `11`（已有 running）**：

**不要询问用户**，直接**续接已有任务**：用其原 prompt + `--no-wait` 等待同一条任务完成（最快且不重复扣费）。仅当用户明确要求「重新分析」时才 `--new --no-wait`。

**exit `12`（相似或同 prompt 本地 completed 可重放，含 session.log 残留场景）**：

**不要询问用户**，直接处置：

- 若 `REPLAY_CANDIDATE` 的主体与本次请求一致 — 用其**原 prompt**（`matchKind=exact` 时用**当前 prompt**）+ `--no-wait` 交付缓存结果（**不访问服务端、不扣费**）
- 若主体明显不同 — 用**当前 prompt** + `--new --no-wait` 重新分析

> **常见误判**：check-conflict 曾报 exit `0`，但本地已有同 prompt 的 completed；主调用 `--no-wait` 会秒退并重放（`ALICE_NO_SERVER_CALL=1`），**不是**新建分析。修复后同 prompt completed 也会 exit `12`。

> **沙箱残留**：当 `tasks.json` 因沙箱写入限制（EPERM）未持久化时，`check-conflict` 会从 `session.log` + `results/` 残留推断已有结果并 exit `12`。此时主调用 `--no-wait` 会从 `session.log` 恢复并自动重放——**必须先经用户确认**（选项 A 或 B），不能直接发主调用跳过询问。

**禁止** Agent 自作主张选 attach / `--new` / 直接打开 `Downloads/` 同名报告。

---

## 沙箱 / 短超时宿主

金融分析通常 **2–15 分钟**。若宿主 `run_command` 只有数十秒～几分钟超时，**第一条 `--no-wait` 会被强杀**（exit `4`/`6`），看起来像「卡住」——其实是终端杀了 CLI，服务端往往仍在跑。此时对用户说：「分析仍在进行中，我继续等待……」，**不要**说「被杀」「超时」等技术细节。

**优先**：把 shell / `run_command` 超时调到 **≥1200 秒（20 分钟）**，只发**一条** `--no-wait` 并阻塞等到进程结束。

**若无法拉长超时**（Trae / Cursor 等），用 **`--detach` + 续接**：

```powershell
# ① 后台提交（父进程立刻退出，子进程继续跑）
powershell ... afcp.ps1 --prompt "<USER_QUESTION>" --detach

# ② 相同 prompt 续接轮询（仍只发一条，阻塞等到 DONE）
powershell ... afcp.ps1 --prompt "<USER_QUESTION>" --no-wait
```

若已 exit `4`/`6`（未见到 DONE）：

1. 任务**可能仍在服务端执行**；
2. 用**完全相同 prompt** 再发**一条** `--no-wait`；
3. **不要** `check_command_status`、**不要**连发多条 CLI、**不要**读 `session.log`/`results/` 猜进度。

**典型误操作（会表现为卡住）**：`--no-wait` 后反复 `check_command_status` → 终端超时杀进程 → 读 `Test-Path results/`（文件尚未生成）→ 再发第二条 `--no-wait`。

---

## CLI stdout 机器信号（辅助识别）

| 信号 | 含义 |
|------|------|
| `ALICE_FINANCIAL_COPILOT_DONE` | **唯一**完成标记 |
| `ALICE_POLL_HEARTBEAT` | 仍在执行，未完成 |
| `ALICE_ARTIFACT_GUARD` / `ALICE_FORBIDDEN_READ_UNTIL_DONE` | 禁止读列出的旧报告路径 |
| `ALICE_USER_DOWNLOAD_HINT=` | 完整报告附件绝对路径（**必须转告用户**，可直接复用该行文案） |
| `ALICE_NO_SERVER_CALL=1` | 本进程**未向服务端发请求**（replay 重放） |
| `ALICE_SESSION_LOG=` | Windows 乱码时只读 stdout 给出的**完整**日志路径 |
| `ALICE_SANDBOX_NO_PERSIST=1` | 当前环境无法保存任务状态，已阻止提交（退出码 78）；**未向服务端发请求**；告知用户开启完全访问权限后重试 |

---

## 禁止写法（Windows）

```powershell
# ❌ PowerShell 5.x：&& 解析失败
cd "<SKILL_DIR>" && node scripts/cli.mjs --prompt "..." --no-wait

# ❌ 命令末尾拼 undefined 等垃圾参数
... afcp.ps1 --prompt "..." --no-wait undefined

# ❌ 用 check_command_status 轮询代替阻塞等待
# （终端超时会杀 CLI，任务仍在服务端跑，Agent 却以为卡住）
... afcp.ps1 --prompt "..." --no-wait
# 然后反复 check_command_status / Get-Content session.log / Test-Path results/

# ❌ 后台 / fire-and-forget（分析主路径禁止；仅 --detach 场景由 CLI 内部 detached 子进程）
Start-Process ... | Out-Null

# ❌ 删除 CLI 的防重复提交锁文件以绕过保护（会导致重复扣积分）
Remove-Item -Path "$env:USERPROFILE\.wind-aifinmarket\submit-locks\*.pid" -Force
Remove-Item -Path "$env:TEMP\alice-submit-locks\*.pid" -Force

# ❌ 用裸 node cli.mjs 代替 afcp.ps1（Windows 上会导致中文乱码、沙箱兼容性问题）
node "...\scripts\cli.mjs" --prompt "..." --no-wait
```

---

## 自检清单（交付前必做）

```
□ 步骤 0 已完成：已从 agent_md 读取 API Key 并执行 apikey-set（或首次获取后已 memory_write 持久化）？
□ 步骤 1 会话续接判断已执行：同一会话追问加了 --continue-session；新话题未加；命令带上了稳定的 --session-scope <ID>（宿主隔离）？
□ stdout 有 ALICE_FINANCIAL_COPILOT_DONE？
□ DONE 的 promptHash= 等于本次 PROMPT_HASH=？
□ 若 stdout 含 ALICE_NO_SERVER_CALL=1（replay 重放），已先询问用户再决定交付或 --new？
□ 正文来自 agentResult.value 或 reportFile=，而非 Downloads/ 附件正文？
□ 未自行概括、未改数字？
□ CLI stdout 的 agentResult.value 已不含 `### …完整报告` 与 `/project/` 附件行（CLI 自动过滤；勿自行添加）？
□ DONE 含 reportFullFile= 时，已告知用户完整路径（行内代码格式）？
□ 未加载 reportFullFile= / attachmentFile= 文件内容展示给用户（仅告知路径）？
□ 未把 results/ 说成完整报告？
□ 对用户说的话里没有暴露 CLI、自旋、task_id、进程、shell、exit code 等内部技术细节？
□ 没有删除 submit-locks/ 下的锁文件来绕过防重复提交保护？
□ 没有用 view_folder / view_files 扫描 Downloads/、results/、logs/ 目录来「猜」报告？
□ 若向用户说过"Key 缺失/需要配置 Key"——退出码确实是 2 且 stderr 含 KEY_MISSING？若否，已停止并改按真实退出码处理（红线 8）？
□ 没有在 agent_md 已保存 Key 的情况下再次询问用户提供 Key？
```

任一为 **否** → **不得交付**；续接 CLI 或向用户说明未完成。

---

更多 FAQ、环境配置、典型复盘见 `SKILL.md`。
