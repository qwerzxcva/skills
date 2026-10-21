# alice-financial-copilot 排障与常见问题

> **执行契约**见 [`AGENT.md`](./AGENT.md)；**技能说明与 CLI 参数**见 [`SKILL.md`](./SKILL.md)。

---

## 任务幂等性与停止行为

CLI 跨进程在 `~/.wind-aifinmarket/tasks.json` 按 **taskId** 记录任务，`~/.wind-aifinmarket/results/<taskId>.md` 存每条任务的 `agentResult.value` 落盘副本。基于 prompt 的 `promptHash`（trim + 折叠空白后 SHA-256）做幂等。

- **默认调度（`--no-wait`）**：同 prompt **running** → 续接；**completed** → 重放落盘（不新建）；无记录 → 新建。
- **默认调度（阻塞 SSE）**：同 prompt **running** → 续接；**completed** → 新建；无记录 → 新建。
- **`--new`**：用户明确要求并行新建；**须先 check-conflict 询问用户**。
- **状态同步**：收到 `agentResult` → completed；服务端提示 / jsonrpc 错误 / 流静默结束 → failed；Ctrl+C → **保持 running**（服务端仍在跑，下次自动续接）。
- **attach 失败自动回退**：attach 模式下 60s 无 SSE / jsonrpc 错误 / 4xx → 自动删旧记录新建任务（单进程内最多 1 次）。
- **自动清理**：running > 6h 强清；completed > 6h 清；failed > 3d 清；总条数 > 200 裁到 100。

---

## CLI 执行失败处理

**CLI 失败时，立即停止；绝不用 WebSearch 或其它信息源拿"近似的金融分析"敷衍用户。**

- `KEY_MISSING`（**仅当** exit=2 且 stderr 含 JSON `"code":"KEY_MISSING"` 时才成立）：按 `SKILL.md`「环境与配置」检查 Key 后重试。**禁止**在退出码不是 2、或 stderr 没有 `KEY_MISSING` 字段时，凭"进程被杀""输出不完整""apikey-get 返回 missing"等迹象猜测 Key 缺失——这些与 Key 无关（典型反例：exit=6 是 strict 兜底，Key 配得好好的）。若需核实 Key 状态，用 `apikey-get` 并读其 JSON 的 `status` 字段：`configured` = 正常，`missing` = 确实缺失；**禁止**把 `configured` 读成 `missing` 或凭空下结论。
- exit=75 / `[严重] 服务端拒绝任务`：临时拒绝，先看 stderr 判因——`积分不足` 需用户充值（https://market.windalice.com/#/user/credits ），**充值前重试无效**；`达到最大同步执行任务数目` 需等已有任务跑完；`服务繁忙` 才是等几分钟。三档话术见 `AGENT.md`「exit 75 话术分流」。一律禁止换 prompt / `--new`。
- 服务端用户提示（体验账户 / 数据受限）：原样转述，不要替换为外部信息源。
- macOS Gatekeeper / Windows SmartScreen / 企业安全软件拦截：按系统提示放行后重试。
- 网络 / 服务端 5xx：CLI 内置最多 10 次重连，耐心等。
- 仍失败：向用户展示完整错误，让用户处理；**绝不**回退到其它信息源伪造"看似合理"的金融分析。

---

## 常见问题

**Q1：提示「WIND_API_KEY 未配置」 / Key 失效怎么换？ / 每次新会话都要重新配？**

A：从 [Wind Alice → 我的账号 → 总览](https://market.windalice.com/#/user/overview) 复制（或点「重置」换新）Key，然后写入：Windows 用 `powershell ... -File "<SKILL_DIR>\scripts\afcp.ps1" apikey-set <KEY>`；macOS/Linux 用 `node scripts/cli.mjs apikey-set <KEY>`。`apikey-get` 验证脱敏末四位；`apikey-clear` 清除。CLI **不读**环境变量与 skill 目录内 `config.json`——只读 `~/.wind-aifinmarket/config.env`。

**跨会话持久化（Agent 必做）**：远程沙箱每次会话重置会清空 `config.env`。Agent 应在首次获取 Key 后通过 `memory_write(file="agent_md", ...)` 持久化；后续每次会话开始时 `memory_recall(scope="agent_md")` 读取并 `apikey-set`，不再询问用户。详见「环境要求 → 3. API Key 持久化配置」与「Agent 调用流程 → 步骤 0」。

**Q2：能否同时分析多个公司？报告附件在哪？怎么改下载目录？**

A：(a) 可以——把多家主体写进同一个 prompt（建议 ≤ 5 家）。(b) 完整报告附件会静默落到 `~/Downloads/`（Windows `%USERPROFILE%\Downloads`），供用户本地查阅；Agent **不要**把附件正文展示给用户，DONE 含 `reportFullFile=` 时**仅告知完整路径**。(c) 用户对话中说"下载到 X" → Agent 加 `-d "X"`。**向用户交付时只用 stdout 的 `agentResult.value` 原文**（截断时读 `reportFile=` 兜底），禁止读 `Downloads/` 附件展示。

**Q3：PowerShell 报 `&& 不是有效语句分隔符` / 中文乱码？**

A：(a) PowerShell 5.x 不支持 `&&`——Windows **只能用方案 A**（`afcp.ps1` 绝对路径，见「调用红线」）。(b) 若 live 仍乱码，读 CLI 输出的 `ALICE_SESSION_LOG=` 路径（`Get-Content -Encoding UTF8`），或直接用 Cursor / VS Code 打开 `.log` / `.md` 文件。

**Q4：用户 Ctrl+C 停掉后再发同样 prompt，会重新跑还是续接？**

A：**自动续接**。`tasks.json` 保留了 `taskId / contextId`，下次同 prompt 启动会通过 `tasks/resubscribe` 接续，**不重复扣额度**。若续接时旧任务已失败，CLI 会自动回退到新建任务（同一进程内最多 1 次）。想真正丢弃，用 `--new`。

**Q5：探针一直显示 `submitted`，可以 `--new` 吗？**

A：**不可以**。`submitted` 是排队态，高峰期几分钟内会转 `working → completed`。继续用**同一条** `--no-wait` 等即可（CLI 内部自旋，默认最长 60 分钟）。**只有**用户明确说"重新跑一遍"或服务端终态 `failed` 时才考虑 `--new`。

**Q6：退出码 75 是什么？**

A：服务端**临时拒绝**新任务（并发上限 / 服务繁忙 / 积分不足）。立即停止，**按 stderr 内容分流话术**——三种原因话术不能混，尤其**积分不足**不能说「稍后重试」或「等任务执行完」（等再久也没用，必须充值：https://market.windalice.com/#/user/credits ）。完整三档话术见 `AGENT.md`「exit 75 话术分流」。**禁止**换 prompt / `--new` / 改下载目录"绕过"——它们都会再占用并发槽。

**Q7：CLI exit=0 但 stdout 末尾只有 `[等待中]`，没看到 DONE 行，怎么办？**

A：这表示进程被沙箱 / 终端在 SSE 长连接中途 kill 了——`tasks.json` 永远停在 `running`、`results/<taskId>.md` 永远不出现。**唯一正确做法**：用**完全一致的 prompt** 再发**一条** `--no-wait`，让 CLI 内部自旋问服务端：

```powershell
# Windows（方案 A）
powershell -NoProfile -ExecutionPolicy Bypass -File "<SKILL_DIR>\scripts\afcp.ps1" --prompt "<和首次完全一致的 prompt>" --no-wait
```

```bash
# macOS / Linux
node scripts/cli.mjs --prompt "<和首次完全一致的 prompt>" --no-wait
# exit=0 + DONE 行 = 完成；exit=4（60min 触顶）再发一次同命令
```

**禁止**做的事：反复 `Get-Content tasks.json` / `Get-ChildItem results/`（CLI 已死、永远不会更新）、`--new`（占新并发槽）、连发多条 `--no-wait`（Trae「模型循环」熔断）、`--no-wait --once` 外层手工循环（脚本调试专用）。

> 注：strict 模式（默认开启）会把这种「exit=0 但无 DONE」改成退出码 `6`，让 Agent 一眼识别。

**Q8：CLI 还没输出 DONE，但 Downloads/ 里已有同名报告，能直接读吗？**

A：**不能。** `(1)` / `(2)` 后缀只表示同名冲突自动重命名，不代表「本次 prompt 的第 N 次运行」。若 `status -p "<prompt>"` 返回 `ALICE_ARTIFACT_GUARD` 或列出 `SIMILAR_COMPLETED_TASK` / `ORPHAN_DOWNLOAD_CANDIDATE` / `STALE_REPORT_CANDIDATE`，说明本地没有本次 prompt 的登记记录，或存在其它 prompt / 其它会话留下的同名主体文件。**必须**阻塞等待 `ALICE_FINANCIAL_COPILOT_DONE`（含匹配的 `promptHash=`），禁止用 `view_files` 扫目录猜报告。

**Q9：典型误读现场 —— Agent 做了什么错事？**

A：下列组合几乎必然把**上一次**的报告当成**这一次**的结果：

1. `run_command` 启动 `--no-wait` 后看到 `status: running`，转而用 `check_command_status` 轮询（**禁止**）；
2. `view_folder logs/` 后打开旧 session.log——这是**另一句 prompt** 的会话，不是本次请求；
3. 旧 log 末尾有 `ALICE_FINANCIAL_COPILOT_DONE`，Agent 未核对 `promptHash=` 与本次 `PROMPT_HASH=`；
4. 再 `view_files` 打开 `download/` 中的旧信用分析报告——磁盘上仍是旧附件；而 `tasks.json` 里本次任务仍是 **running**。

**正确做法**：阻塞等待 CLI 进程结束；stdout 必须含 `ALICE_FINANCIAL_COPILOT_DONE` 且 `promptHash=` 与本次 `PROMPT_HASH=` **完全一致**，再交付 stdout 中的 `agentResult.value` 原文。若进程被沙箱 kill（exit `4`/`6`），用**完全相同 prompt** 再发**一条** `--no-wait` 续接——**不要**读 logs/、download/、`tasks.json` 猜正文。

**Q10：detach + 连发多条 `--no-wait` 为什么会在 Downloads/ 里出现 `(1)(2)(3)` 多份同名报告？**

A：CLI **绝不覆盖**已有同名文件——`信用分析报告.md` 已存在时，新下载自动落到 `(1).md`。Agent 违规连发多条 `--no-wait` 时，多个进程几乎同时看到服务端 `completed`，在 `tasks.json` 写入 `downloadedFiles` 之前各自下载，于是短时间内连出多份副本。

**正确做法**：`--detach` 后**只**读 detach 打印的日志路径 + **最多一条** `status`/`--no-wait` 查 DONE；**禁止** detach 运行中再连发 `--no-wait`。

**Q11：为什么连发 `--no-wait` 会调两次接口？**

A：Agent 对同一用户问题连发多次 `--no-wait`（还用了 `check_command_status`）。其中某次让任务在本地变成 **completed**；**下一次** `--no-wait` 按旧规则可能误提交新任务（第二次扣费）。**修复后**：`--no-wait` 遇到本地 **completed** 直接 **replay_completed**，不再误提交新任务。

**Q12：换了一句 prompt，为什么又读了旧报告？**

A：本次 Agent 用 `帮我生成一份信用分析报告`，本地已完成的是 `帮我做一份信用分析报告`——**promptHash 不同**。Agent 在 `--no-wait` 轮询期间 `view_files` 读 `download/`——**明确违规**。CLI 启动时会打印 `SIMILAR_COMPLETED_REPORT` + `ALICE_FORBIDDEN_READ_UNTIL_DONE`；只有本次 `PROMPT_HASH=` 对应 DONE 后的 `agentResult.value` 才可交付。

**Q13：什么时候*不*该用本技能？**

A：用户的需求是纯 PDF 合并 / 拆分、普通 Word / PPT 排版、通用非金融写作、个人记账报销、银行客服、贷款办理、保险理赔等非金融事务时，让上层模型直接回答；不要硬套本技能。

**Q14：多 Agent 同时问同一主体为什么会「串台」？**

A：三个 Agent 用了**三种措辞**，产生**三个 promptHash**，服务端跑了**三次**分析，`download/` 里堆了多份同名报告，结论还不一致。

**CLI 已加固（v1.0+）**：

1. **同主体 running 自动续接**：`resolveTaskDispatchPlan` 在本地无 exact 记录时，会按主体名匹配相似 running，**自动 attach**，不再新建第三条任务。
2. **同主体 completed 自动重放**：`--no-wait` 模式下，30min 内有相似 completed 会 **replay_completed**（`ALICE_NO_SERVER_CALL=1`），不发服务端请求。
3. **running 防护与 replay 统一**：`findSimilarRunning` 与 `findSimilarCompleted` 共用 `comparePromptsForReplay`（含 subject 匹配）。
4. **跨进程主体锁**：除 promptHash 锁外，增加 `computeSubjectKey` 主体锁，防止多进程冷启动同时 submit。

**Agent 仍须遵守**（程序层不能替代 Agent 纪律）：

| Agent 措辞 | 典型错误 | 后果 |
|------------|----------|------|
| `帮我出一份信用分析报告` | `--detach` + 手工 `Get-Content` 日志 + 读 `download/` | 可能交付旧 prompt 的报告 |
| `给我做一份信用分析报告` | 连发 8 次 `--no-wait` / `--watch` + 读 `tasks.json` 挑 completed | 误读其它 taskId 的摘要 |
| `给我一份信用分析报告` | 相对规范，但仍可能与上两者并行扣费 | 用户看到三份不同结论 |

**共同违规**（违反任一条即可能串台）：

1. **没用 `afcp.ps1` 方案 A**——`cd && node` / `Set-Location; node` 在 PowerShell 5.x 易失败；命令末尾拼 `undefined` 是 Agent 工具 bug。
2. **没做 `check-conflict`**——exit=12 时应先问用户「重放还是新建」，而不是默默再开一条分析。
3. **连发多条 CLI** / `check_command_status` / `--detach` 后轮询——应**只发一条** `--no-wait` 并阻塞等到 DONE。
4. **DONE 之前读 `download/`、`tasks.json`、`results/`**——旧报告可能绑定**另一个 promptHash**；`ALICE_FORBIDDEN_READ_UNTIL_DONE` 不是报告路径。
5. **换措辞当「重试」**——不同措辞会被判为相似任务；应续接/重放**原 prompt**，不要换句。

**正确做法（单 Agent）**：`check-conflict` → 若 exit=12 问用户 → **一条** `afcp.ps1 ... --no-wait` 阻塞等待 → stdout `ALICE_FINANCIAL_COPILOT_DONE` 且 `promptHash=` 一致 → 交付 `agentResult.value` **原文**，禁止展示 `download/` 附件。

**Q15：为什么 Agent 交付的关键指标与真实报告不一致？**

A：Agent 违规组合：(1) 连发多条 `--no-wait` 且用 `check_command_status` 轮询，未阻塞等到 DONE；(2) 读 `results/` 或 `download/` 附件后**自行概括**成表格——定量指标会被改错。**正确做法**：阻塞等到 `ALICE_FINANCIAL_COPILOT_DONE` → 将 stdout 的 `agentResult.value` **原文**交给用户（截断时读 `reportFile=` 兜底）→ 禁止概括 → DONE 含 `reportFullFile=` 时**仅告知完整路径**（禁止加载文件内容展示），禁止自行概括改写。

**Q16：任务明明成功了，为什么 Agent 却说"找不到 API Key"？**

A：这是**凭 stderr 噪声 / 子命令返回脑补出"Key 缺失"结论**的典型误判，本次现场已复现。真实情况：API Key 配得好好的（`config.env` 存在且有效），任务已在服务端成功完成、报告已落盘。Agent 错误链路：

1. `--no-wait` 主调用进程被沙箱 / IDE 终端在 SSE 长连接中途 kill（exit=6 strict 兜底，或 exit=0 无 DONE）；
2. Agent 不识别这是"被杀"，反复 `check_command_status` 说"输出似乎不完整"；
3. 转去跑 `status` / `apikey-get` 子命令想"排查"，却**没读懂返回值**（`apikey-get` 的 JSON `status: configured` 被忽略或误读成 `missing`）；
4. 最终向用户下结论"需要先配置 API Key"，引导用户做根本不必要的配置。

**为什么这是错的**：

- `request.js` 主路径在发请求**前**就会 `getApiKey()`（`request.js:877`），Key 真缺失会立刻 `die("KEY_MISSING")` exit=2，**绝不可能**"已经发了服务端请求再说没 Key"——这在逻辑上自相矛盾。
- strict 兜底输出（`request.js` `installStrictExitHook`）**只**说"未输出 DONE，请用相同 prompt 续接"，**不含**任何 Key 配置文案。
- `apikey-get`（`printApiKeyStatus`）是只读探针，返回 JSON：`status: configured`（正常，含脱敏 key）/ `missing`（缺失）/ `error`（读文件失败）。**必须按 `status` 字段判定**，禁止凭印象。

**正确做法**：

1. 退出码 **不是 2** 且 stderr **不含** `"code":"KEY_MISSING"` → **禁止**声称 Key 缺失；
2. 想核实 Key → 跑 `apikey-get`，**读 JSON 的 `status` 字段**：`configured` = Key 没问题，往别处查；
3. 进程被杀（exit=4/6）→ 任务**可能仍在服务端跑**，用**完全相同 prompt** 再发**一条** `--no-wait` 续接（见 Q7）；
4. 想确认任务真实状态 → 跑 `status --prompt "<原 prompt>"`，它会从本地 `tasks.json` 给出 `completed`/`running`/`failed` 及落盘路径，**不访问服务端**；
5. **禁止**把"输出不完整""进程退出""apikey-get 某行看不懂"等同于"Key 缺失"。

> 一句话：Key 缺失有**唯一的确定信号**（exit=2 + `KEY_MISSING` JSON）；其它一切"看起来不对劲"都**不是** Key 问题，应按对应的退出码 / 信号处理（续接、等 DONE、报真实错误），不要引导用户去配置一个根本没问题的 Key。
