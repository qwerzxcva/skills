# 进阶操作手册（COOKBOOK）

> **本文件是「高级特性」的唯一真相源。**
> `SKILL.md` 只在入口放一句话 + 一句 `⚠️ 关键限制` + 一个跳转到这里；所有完整做法、验证、坑、卸载/回滚都集中在本文件。
> 看完本文件，你不需要再翻 `TUTORIAL.md` / `LIMITS.md` / `QA.md` 去拼碎片。
> 发版前由 `scripts/gen_cookbook.py` 校验本文件与代码 docstring 是否漂移。

> 📌 **本文件 vs `COMMANDS.md` 别搞混**：`COMMANDS.md` 是「命令参数权威表」——查某个命令怎么用、有哪些参数；本 `COOKBOOK.md` 是「高级操作实操手册」——讲怎么把钩子 / 守护进程 / 调度 / IMA 等**跑通、验证、回滚**，不重复列参数。两者互补。

统一模板：**做什么 → 前置 → 一条命令 → 验证 → ⚠️ 关键限制 → 卸载 / 回滚**

---

> 💬 **本手册的每个命令都能直接对 AI 说人话完成**（AI 在后台跑等价命令并回显）：
> | 你想做 | 直接对 AI 说 |
> |---|---|
> | 装/修钩子 | 「开一下自动记忆」「注册一下记忆钩子」 |
> | 启动/修守护进程 | 「把记忆守护进程起一下」「守护进程没起来帮我修」 |
> | 配定时调度 | 「把每周自动整理/IMA同步排上」 |
> | 配 IMA 同步 | 「配一下 IMA 云端同步」 |
> | 迁移/回滚 | 「把记忆库从 A 迁到 B」「回滚到上个版本」 |
> | 故障排查 | 「XX 不工作了帮我查」 |
> 下面每个命令段上方都标了「💬 不想敲命令？」提示。

## 1. 会话钩子（自动记 / 自动想起）

- **做什么**：把 5 个钩子注册进 `~/.workbuddy/settings.json`，让 AI 在对话里自动记（沉淀经验）、自动想起（注入 / 弱召回提示）。⚠️ **注入侧默认关**（`inject_enabled=false`），弱召回提示不受影响。
- **前置**：无。首次跑 `deposit` / `recall` 也会自动注册（见 `KEEPER_AUTO_INSTALL_HOOKS`，默认开）。
- **一条命令**：
> 💬 **不想敲命令？** 直接对 AI 说你要做的事（如「记一下…」「帮我找…」「帮我一键配好」），AI 会在后台跑等价命令并回显——你不用手敲。
  ```bash
  python install_hooks.py            # 真正安装（幂等；同时清理已退役钩子的历史注册）
  python install_hooks.py --dry-run  # 只打印将写入的钩子 / 将清理的退役条目，不改文件
  ```
- **验证**：重启 WorkBuddy 桌面版 → 看 `~/.workbuddy/hooks/hook_audit.log`（每次注入/召回/沉淀都有审计行，**这是钩子有没有生效的唯一可靠判据**）；或发无关消息看是否出现 `## 🔎 本地记忆弱召回提示`（IMA 兜底，该路径不受 `inject_enabled` 影响）。
  - ⚠️ **默认不再自动注入**：`## 🧠 当前生效的 AI 经验` 段落只在 `inject_enabled=true` 时出现（`store/config.json` 的 `keeper.inject_enabled=true`，或 env `KEEPER_INJECT_ENABLED=1`）。**仅凭「没看到注入段落」不能证明钩子没装。**
- **⚠️ 关键限制**
  - **追加** keeper 条目 + **移除**模式禁止条目 + **清理**已退役条目（`RETIRED_HOOK_FILES`，如 I13 已删的 `bash_error_capture.py`——它旧注册所在的 `PostToolUse` 在 silent 模式仍启用，不主动清理会永久残留且每次触发都空跑）；完整保留 WorkBuddy 内置 hook（`leak_scan` / `code_lint` / `pre_tool_use_guard` / `bash_guard` / `git_guard` 等），绝不覆盖。
  - 关自动注册：`KEEPER_AUTO_INSTALL_HOOKS=0`。
  - 手动注册（环境不让跑脚本时）：把 `hooks/` 下对应脚本文件复制到 `~/.workbuddy/hooks/`（清单见 `install_hooks.py` 的 `HOOK_FILES`：含 `keeper_hook_common.py` 共享模块、`_async_deposit.py` 异步落盘助手；旧版 `bash_error_capture.py` 已彻底删除，其捕获职责由 `post_tool_use_error_capture.py` 承担；运行 `install_hooks.py` 会一并清理它的历史注册），对照 `install_hooks.py` 的 `HOOK_DEFS` 在 `settings.json` 的 `hooks` 下补 `SessionStart` / `UserPromptSubmit` / `PostToolUse(Bash)` / `Stop` / `PreCompact` 五组命令（5 个事件钩子，由 4 个脚本承载：session_start / user_prompt / post_tool_use / memory_auto_capture）。
- **回滚**：`install_hooks.py` 写前自动 `.bak`；要撤销就恢复 `settings.json` 的 `.bak` 并删 `~/.workbuddy/hooks/keeper_*`。

---

## 2. 守护进程（神经召回常驻预热）

- **做什么**：把「语义召回流水线 + 模型」常驻成一个后台进程，消除每条消息 ~5s 的冷加载（首条 recall 后模型懒加载的成本）。
- **前置**：已装好本技能（神经后端所需的 fastembed 模型已就绪，见 `SKILL.md` 安装教程①）。
- **一条命令（通常不需要手动跑）**：
> 💬 **不想敲命令？** 直接对 AI 说你要做的事（如「记一下…」「帮我找…」「帮我一键配好」），AI 会在后台跑等价命令并回显——你不用手敲。
  ```bash
  # 方式 A：钩子/调度器会自动拉起（见 §1、§3）
  # 方式 B：手动启动（调试时用）
  python keeper_daemon/daemon.py
  ```
  正常流程里，**首次 recall 时 `keeper_recall_client.py` 会懒启动 daemon 并轮询自举**（≤30s），之后每条消息走 daemon 内 ~150ms 暖召回。
- **验证**：`ls ~/.workbuddy/keeper_daemon/.daemon-*.json`（**文件名带记忆库指纹，一库一份**）看到 `port` / `token` / `pid`；或直接看 recall 延迟从 ~5s 降到 ~150ms。
- **⚠️ 关键限制**
  - 绑定 `127.0.0.1` 随机端口，随机 16 字节 token 鉴权；**fail-open**：daemon 死 → 钩子毫秒级空返回兜底，下次调用自举复活。
  - **空闲退出**：`KEEPER_DAEMON_IDLE_SECONDS`（默认 `0` = 永不离线；设正整数 = 空闲 N 秒后退出释放内存）。
  - **按库单例**：同一个记忆库已有活进程则秒退，不会重复起；不同记忆库各自一个常驻（状态文件按库分开，互不串味）。复用前会向活进程核对它服务的是哪个库——只"探活"不核对，就可能把召回打到别的库上。
  - 不要手动 kill 后不清理状态文件——残留 STATE 会让客户端以为还活着；kill 后删 `keeper_daemon/.daemon-*.json` 即可。
  - **跨平台自启**：手动 `python keeper_daemon/daemon.py` 三平台都能跑；但「登录/开机自动拉起」仅 Windows/macOS/Linux 有调度器实现（见 §3），其余平台需手动启动或自写自启。
  - **环境变量持久化**：`AI_MEMORY_STORE` / `IMA_KB_ID` 等
    - **Windows**：持久化进注册表 `HKCU\Environment`（换机只改一处，重开终端自动继承）。
    - **macOS / Linux**：**无注册表**，这些 env **不会跨终端/重启自动保留**；需在 shell rc（`~/.zshrc` / `~/.bashrc` / `~/.profile`）里 `export`，否则新 shell 会退回默认记忆库路径。

---

## 3. 定时调度（daemon 自启 + IMA 周同步）

- **做什么**：注册「daemon 开机/登录自启」+「IMA 每周日 23:00 同步」两个调度项，**跨平台自动选实现**：
  - **Windows**：`schtasks` 计划任务 `KeeperRecallDaemon`（ONLOGON）+ `KeeperIMAWeeklySync`（WEEKLY/SUN/23:00）。
  - **macOS**：`launchd` plist `~/Library/LaunchAgents/com.keeper.recall-daemon.plist`（RunAtLoad+KeepAlive）+ `com.keeper.ima-weekly.plist`（StartCalendarInterval 周日23:00）。
  - **Linux**：`systemd --user` 单元 `~/.config/systemd/user/keeper-recall-daemon.service`（WantedBy=default.target）+ `keeper-ima-weekly.timer`（OnCalendar=Sun 23:00）。
- **前置**：**必须先把 daemon 部署好** —— 即先跑过 `python install_hooks.py`（或手动把 `keeper_daemon/` 放到 `~/.workbuddy/keeper_daemon/`）。否则 `setup_scheduler.py` 检测到 `daemon.py` 不在目标目录会直接 `[跳过]` daemon 任务（IMA 任务不受影响）。
- **一条命令**：
> 💬 **不想敲命令？** 直接对 AI 说你要做的事（如「记一下…」「帮我找…」「帮我一键配好」），AI 会在后台跑等价命令并回显——你不用手敲。
  ```bash
  python setup_scheduler.py              # 按当前平台注册两个调度项
  python setup_scheduler.py --dry-run    # 只打印将执行的命令（Windows=schtasks / macOS=launchctl / Linux=systemctl）
  python install_hooks.py --setup-scheduler   # 或钩子安装时一步到位（推荐）
  ```
- **验证**：
> 💬 **不想敲命令？** 直接对 AI 说你要做的事（如「记一下…」「帮我找…」「帮我一键配好」），AI 会在后台跑等价命令并回显——你不用手敲。
  ```bash
  # Windows
  schtasks /Query /TN "KeeperRecallDaemon"
  schtasks /Query /TN "KeeperIMAWeeklySync"
  # macOS
  launchctl list | grep com.keeper
  # Linux
  systemctl --user status keeper-recall-daemon keeper-ima-weekly.timer
  ```
  IMA 同步日志：`~/.workbuddy/ima_push/scheduler.log`
- **⚠️ 关键限制**
  - **跨平台但实现不同**：脚本按 `platform.system()` 自动选 Windows(schtasks) / macOS(launchd) / Linux(systemd)；三者同构（自启 daemon + 每周 IMA 同步）。
  - **Linux 需登录会话**：`systemd --user` 要求已登录会话；若机器无人登录（server/headless），先 `loginctl enable-linger $USER` 让 user 服务在登录前也能跑。注册失败脚本会打印提示，可手动 `systemctl --user start ...`。
  - **macOS 权限**：launchd 加载首次可能弹「终端/Python 控制后台」授权，允许即可；`KeepAlive=true` 会让 daemon 崩溃后自动重启。
  - **可能被系统策略禁用**：沙箱 / 企业策略禁用 `schtasks` 时任务会注册失败——此时需在允许的机器上跑，或先 `--dry-run` 看命令再手动建（不要试图用 PowerShell `Register-ScheduledTask` 等绕过沙箱策略）。
  - **触发时机**：daemon 自启是「登录/开机」事件，要**注销重新登录（或重启）**才生效，不是装完立刻起。
  - IMA 任务的 Windows `/TR` 实际指向一个 `.bat` 包装器（`keeper_ima_sync_run.bat`，承接 `>>` 日志重定向）——这是计划任务不解释 shell 重定向的 workaround，属正常；macOS/Linux 的日志由单元 `StandardOutPath` 直接接管，无包装器。
- **卸载**：
> 💬 **不想敲命令？** 直接对 AI 说你要做的事（如「记一下…」「帮我找…」「帮我一键配好」），AI 会在后台跑等价命令并回显——你不用手敲。
  ```bash
  python setup_scheduler.py --uninstall   # 按当前平台移除调度项（Windows 删任务+.bat；macOS unload+删 plist；Linux disable+删 unit）
  ```

---

## 4. IMA 同步（镜像到知识库）

- **做什么**：导出本地记忆 → 脱敏 → 复检 → 生成一段**可直接贴给 Agent 的推送指令**（含每文件的 `create_media` / `add_knowledge` 三步 MCP 调用）。
- **前置**：IMA MCP 已连接；默认推到内置已知库（`AI记忆`，KB id 读 `IMA_KB_ID` 或内置），或 `--kb-id <KB_ID>` 指定。
- **一条命令**：
> 💬 **不想敲命令？** 直接对 AI 说你要做的事（如「记一下…」「帮我找…」「帮我一键配好」），AI 会在后台跑等价命令并回显——你不用手敲。
  ```bash
  python scripts/ima_sync.py                # 导出 + 复检 + 打印推送指令
  python scripts/ima_sync.py --open         # 额外尽力打开 IMA 知识库网页
  python scripts/ima_sync.py --kb-id XXX    # 指定知识库 ID
  ```
- **验证**：输出显示「脱敏 + 复检通过」+ 一份推送指令；若复检失败会报错退出（不产出明文）。
- **🔴⚠️ 关键限制（最容易踩坑）**
  - **脚本不推送**：`create_media` / `add_knowledge` 是 **IMA MCP 工具，脚本调不到，必须由 Agent 经 MCP 执行**。跑完 `ima_sync.py` ≠ 记忆已进 IMA —— 还必须把生成的指令**贴给 Agent**，走完最后两步，记忆才真正进 IMA。
  - **IMA 是明文库**：脱敏强制；复检命中任何真实路径 / 凭证 / 邮箱会直接报错退出，绝不交付明文。切勿手动绕过复检把原文推上去。
  - 纯加性可选层：无 IMA 时记忆系统完全自洽，不依赖它。
- **回滚 / 清理**：IMA 侧用 `add_knowledge` 的 `REPLACE` 模式覆盖更新；要彻底清理在 IMA 网页端删对应知识库文档。本地导出在 `~/.workbuddy/ima_push/`，可随手删。

---

## 5. 数据迁移与回滚

- **数据迁移**（既有记忆库补 `type` / `settled` / `probe_until` / `thermal` 字段，幂等、不改原文；脚本 `scripts/migrate_v30.py`）：
> 💬 **不想敲命令？** 直接对 AI 说你要做的事（如「记一下…」「帮我找…」「帮我一键配好」），AI 会在后台跑等价命令并回显——你不用手敲。
  ```bash
  python scripts/migrate_v30.py                 # 用环境变量 AI_MEMORY_STORE
  python scripts/migrate_v30.py <root>          # 或显式指定记忆根目录
  ```
  - ⚠️ 可重复跑，安全；建议升级后对已存在的真实库跑一次。
- **升级 SkillHub 版本后重建钩子**（幂等，覆盖式）：
> 💬 **不想敲命令？** 直接对 AI 说你要做的事（如「记一下…」「帮我找…」「帮我一键配好」），AI 会在后台跑等价命令并回显——你不用手敲。
  ```bash
  python install_hooks.py          # 重新注册 5 个钩子（保留内置 hook）
  python setup_scheduler.py        # 重新注册调度任务（如用了 §3）
  ```
- **升级 / 换机后核对「线上到底发到几版」**（防多机并行「双主」——另一台机器发了版本、本机毫不知情）：
  ```bash
  python scripts/memory_ops.py release-audit
  ```
  - 退出码 `0` 一致 / `2` 漂移 / `3` **未知**（断网、超时就是 3，**不是**出错）。
  - 漂移看两条提示：`missing_log`（平台发了、日志没记）与「本地落后线上」；`bundled` / `unreleased_local` 只是提示，**不算漂移**（本地改了没发是正常态）。
  - 加 `--offline` 只做本地自检，会明确输出「无法判定一致性」。
- **备份保留策略**：`python scripts/memory_ops.py backup --zip <库外路径> --keep 7`——只保留最近 7 份，更旧的搬迁到同级 `_retired_*` 目录（**不删除**，可逆）。
- **通用回滚原则**
  - 钩子 / settings：`install_hooks.py` 写前自动 `.bak`，恢复即回滚。
  - 配置：`config.json` 改错 → 用 `config_doc_matches_code`（`verify_claims.py`）静态检查对称后再发。
  - 记忆数据：SQLite 是真源；任何导出器（IMA / flat / rules）都是派生，删派生不影响真源。

---

## 6. 故障排查速查

| 现象 | 可能原因 | 处理 |
|---|---|---|
| recall 每条都 ~5s | daemon 没起来 / 被 idle 退出 | 看 `keeper_daemon/.daemon-*.json`；首次 recall 会自动拉起；或注册 §3 调度任务 |
| `setup_scheduler.py` daemon 任务被 `[跳过]` | 没先部署 daemon | 先 `python install_hooks.py` |
| 注册任务报「系统策略禁用」 | schtasks 被禁 | 在允许的机器跑；或 `--dry-run` 后手动建 |
| IMA 同步跑完但记忆没进库 | 没把推送指令贴给 Agent | 见 §4 🔴 限制，走完 MCP 两步 |
| 复检报错退出 | 导出含真实路径/凭证/邮箱 | 检查 `AI_MEMORY_STORE` / 环境变量；不要绕过 |
| 钩子不 fire | settings 没注册成功 | `install_hooks.py --dry-run` 看是否列出 5 个钩子；重启 WorkBuddy |
| 发版门禁 `tests` 报 `rc=124`（超时） | 单道超时窗口太紧 / 同步用例被真库体量拖住 | 先用 `python scripts/publish_gate.py --only tests` 确认只有 tests 红；超时**按闸门分档**（tests 3600s），需要时用 `--timeout <秒>` 统一覆盖；若仍慢在同步用例，调 `AI_MEM_SYNC_TEST_MAX`（默认 60，`0` = 退回全量真库） |
| `%TEMP%` 被 `keeper_*` 目录吃满（上千个） | 门禁测试各自 `mkdtemp` 建沙箱、历史上从不回收（实测积到 1.4 GB） | 门禁已自动回收：**跑前**清超龄（mtime 早于 6 小时前）、**跑完**清本轮产生的；要保留现场排查加 `--keep-temp`。白名单前缀（`keeper_` / `plain_` / `mem_demo_`）之外的目录、以及固定共享沙箱（`keeper_gate_hooks` / `keeper_gate_daemon`）永不参与回收 |

---

## 7. 用对话创建 / 管理周维护自动化（WorkBuddy 自动化）

> 💬 **不用记命令**：这些全都对 AI 说一句话就能做，AI 在后台自动创建 / 管理 WorkBuddy 自动化任务（底层 `automation_update`），你不用碰任何调度语法。

| 你想做 | 直接对 AI 说 |
|---|---|
| 建每周记忆维护（推荐默认） | 「帮我设每周自动记忆维护」 |
| 看现有记忆相关自动化 | 「看看我的 keeper 定时任务」 |
| 临时改时间 / 关掉 | 「把记忆维护改到周六」「先暂停周维护」 |
| 跑一次看看 | 「现在手动跑一次周维护」 |

**推荐默认任务（AI 会创建这个）**：每周一次低频（实际时间以平台调度为准）串行五步、纯加性绝不删改记忆：
1. `harvest --root "<你的记忆库路径>" --self-learn --with-workbuddy --max-items 10 --yes`（WB 原生记忆单向沉淀到 keeper；已配好 `AI_MEMORY_STORE` 时可省略 `--root`）
2. `cluster --apply`（新+旧记忆重聚类）
3. `doctor --contradictions --fix`（矛盾检测与修复）
4. `decay --apply`（长期不命中的记忆降权沉底，`--deep` 可找回）
5. IMA 云端同步：`ima_sync.py` 导出+脱敏 → 经 IMA MCP 推送（脱敏未过则跳过，绝不交付明文）

> 🔴 铁律：周维护任务**绝不**包含 `reflect --auto` / `delete` / `archive --apply` 等会修改或删除记忆的命令；只做采集 + 聚类 + 矛盾修复 + 沉底 + IMA 同步这类非破坏性整理。其中 decay / IMA 同步均为非破坏性（沉底可被 `--deep` 找回，IMA 为单向镜像）。

### 7.1 把 WorkBuddy 历史会话沉淀成长期记忆（conversation_search → harvest）

> 💡 你过去在 WorkBuddy 的聊天里藏着大量可复用经验，但躺在云端"能搜不能召"。用下面三步把它们变成 keeper 的语义记忆：

1. **检索**：在 WB 会话里用 `conversation_search` 按回溯窗口（如最近 30 天）检索相关历史会话，把返回内容整理成一段文本文件（如 `history_session.txt`）。
2. **沉积**：`harvest --root "<你的记忆库路径>" --from-conversations --session history_session.txt --no-llm`（规则模式免费、确定性；想更智能可去掉 `--no-llm` 走 LLM 抽取）。
3. **幂等**：同一段历史会话重复跑 `harvest --from-conversations` 不会重复沉积（会话来源记忆打 `wb_session` 标签 + `provenance_key` 幂等键），可放心周任务里反复调用。

> 🔴 注意：`harvest --from-conversations` 自身**不联网**检索历史会话（CLI 无 WB tool 环境）——检索这步必须由 AI 在 WB 会话中用 `conversation_search` 完成。这是"WB 云记忆 → keeper 语义库"的桥，与 ① 原生记忆打通（会话结束自动沉淀 WB 文件记忆）互补：① 沉淀的是 WB 的**结构化文件记忆**，本配方沉淀的是 WB 的**云端历史会话**。

## 8. 配置体检 & 可开启功能（对话入口）

> 💬 **不用记命令**：这些全都对 AI 说一句话就能做，AI 在后台跑对应命令并回显——你直接就能问出"我还能开/配什么"。

| 你想做 | 直接对 AI 说 | 底层命令 |
|---|---|---|
| 看"我还能开/配什么（有益的）" | 「帮我看看记忆系统还能开/配什么」 | `audit`（只读能力体检+开关顾问） |
| 开 / 配 IMA 云端同步（防丢+跨设备） | 「配 IMA 知识库同步」 | `keeper_setup.py ima --kb-id <ID>`（先配知识库；需已连 IMA MCP） |
| 立即把记忆同步到 IMA | 「把记忆同步到 IMA」 | `ima_sync.py` 导出脱敏 → AI 用 IMA MCP 推送（周维护也会自动推） |
| 开 decay 自动沉底 | 「开启 decay 沉底」 | `decay --apply`（确定性降权，可 `--deep` 找回） |
| 调整 / 移除周维护里的某步 | 「把 decay 从周维护去掉」/「周维护别推 IMA 了」 | 编辑周维护自动化任务 |

> 速查表与有益度评级见 `SKILL.md`「🔧 配置指引」。

> 🔥 **低配 / 老机器提醒**：有些开启项很吃性能，务必看清再开——
> - **Ollama 本地 LLM**：模型 ~5GB，常驻吃内存/磁盘/GPU，**低配机器勿开**。
> - **fastembed 神经语义（默认开）**：常驻 100–150MB 内存；内存 ≤8GB 的老机器会明显变慢，可降级为 `embed lexical` 或 `记忆 --flat`。
> - **`doctor --contradictions` / `cluster`**：开销随库大小增长（矛盾扫描≈平方），**只放低频任务**，别进每日/每小时自动化。
> 完整逐项清单（含替代方案）见 `SKILL.md`「🔧 配置指引」。

> 本手册由 `scripts/gen_cookbook.py` 在发版前校验与代码 docstring 的一致性。如发现某条命令与实际不符，优先以脚本文件头 docstring 为准并回报。

## 9. 高级能力（图谱 / 蒸馏 / 画像 / 矛盾仲裁）

> 💬 **不用记命令**：直接对 AI 说「给记忆建个关系图谱」「帮我把相似记忆提炼成原则」「看看我的记忆画像」「自动仲裁矛盾记忆」即可。AI 后台跑对应命令并回显。
> 🔴 **安全铁律：全程「只标不删」**——图谱/蒸馏/仲裁只新增关系边、降权或标 `superseded`，绝不物理删除记忆；所有写操作先加 `--dry-run` 预览。

| 你想做 | 底层命令（先 `--dry-run` 预览） | 说明 |
|---|---|---|
| 建记忆关系图谱 | `graph --build` | 自动推断 supports/refutes/is_a/part_of 边，幂等只标不删 |
| 清理图谱悬空引用 | `graph --clean` | 清掉指向已删除记忆的失效关系边（不删记忆文件） |
| 图谱干净重算 | `graph --rebuild` | 清悬空 + 清空图衍生边 + 重算，消除历史 noise 边 |
| 自动仲裁强矛盾（旧条标 superseded） | `doctor --contradictions --fix --arbitrate` | score≥0.78 强矛盾对才裁，只标不删可 rollback；**离线真实仲裁被禁止，仅 `--dry-run` 预览，需 `KEEPER_LLM_*` 注入 LLM 才真写** |
| 带引用的答案合成 | `recall --query "…" --answer` | HyDE+LLM 合成；无 LLM 自动降级返回候选 |
| 召回时顺藤摸瓜关联记忆 | `recall --query "…" --hops 1` | 沿关系边补全关联记忆（`score=0.3` 排末尾） |
| 让 AI 直接合成答案（带引用） | `recall --query "…" --answer` | HyDE+LLM 合成；无 LLM 自动降级返回候选 |
| 预览"可提炼成原则"的记忆簇 | `distill --review` | 离线预览，不写记忆 |
| 把相似记忆提炼成一条原则 | `distill --apply` | 沉淀 `type=principle`，原记忆只降权不删（需 LLM） |
| 看用户画像（擅长/薄弱/重心） | `profile` | 离线，不跨域泄漏 |
| 记一条记忆时附决策理由 | `deposit --why "<理由>"` | 理由随 `recall` 暴露，便于复盘 |
| 自动仲裁强矛盾（旧条标 superseded） | `doctor --contradictions --fix --arbitrate` | score≥0.78 强矛盾对才裁，只标不删可 rollback |

### 9.1 关系图谱：建 → 查 → 清

- **做什么**：给记忆自动推断 `supports`/`refutes`/`is_a`/`part_of` 关系边，召回时可顺藤摸瓜。
- **前置**：无（离线即可）。
- **一条命令**：
  ```bash
  python scripts/memory_ops/__init__.py graph --build --dry-run   # 先预览将新增的边，不改库
  python scripts/memory_ops/__init__.py graph --build             # 真正落盘（只标不删，幂等）
  ```
- **验证**：`recall --query "…" --hops 1` 看是否补全关联记忆；`graph --clean` 检查有无悬空边。
- **⚠️ 关键限制**：只标不删；历史 noise 边用 `graph --rebuild` 干净重算（清悬空 + 清空图衍生边 + 重算）。
- **回滚**：`graph --clean`（清悬空）/ `graph --rebuild`（清空图衍生边重算），均不删记忆文件。

### 9.2 蒸馏成原则：预览 → 应用

- **做什么**：把相似记忆簇提炼成一条 `type=principle`，原记忆只降权不删。
- **前置**：需 LLM（`KEEPER_LLM_*` 注入）；离线只能预览。
- **一条命令**：
  ```bash
  python scripts/memory_ops/__init__.py distill --review   # 离线预览候选簇，不写记忆
  python scripts/memory_ops/__init__.py distill --apply    # 落盘原则（原记忆只降权不删）
  ```
- **验证**：recall 该主题应命中新 principle；`timeline --id <principle>` 看派生链（`derives_from`）。
- **⚠️ 关键限制**：`--apply` 需 LLM；原记忆保留永删；低质量簇先 `--review` 确认再 `--apply`。
- **回滚**：`versions --id <principle>` → `rollback --to-version N --yes`（principle 撤掉，原记忆不受影响）。

### 9.3 矛盾仲裁：离线预览 vs LLM 真写

- **做什么**：对 `score≥0.78` 强矛盾对，旧条标 `superseded`（只标不删，可 rollback）。
- **前置**：真实仲裁需注入 `KEEPER_LLM_*`；离线只能 `--dry-run` 看候选。
- **一条命令**：
  ```bash
  python scripts/memory_ops/__init__.py doctor --contradictions --fix --arbitrate --dry-run   # 离线看候选（不写）
  # 注入 LLM 后，才允许真写：
  python scripts/memory_ops/__init__.py doctor --contradictions --fix --arbitrate             # 真写（只标 superseded，可 rollback）
  ```
- **验证**：被裁记忆 `state=superseded`，默认 recall 不再命中；`recall --include-superseded` 仍可找回。
- **⚠️ 关键限制**：**离线真实仲裁被禁止**（防误杀）；非矛盾一律跳过，绝不误标旧真实记忆。
- **回滚**：`versions --id <旧条>` → `rollback --to-version N --yes`（旧条恢复 active）。

> LLM 走 `KEEPER_LLM_*` 环境变量注入（Agent 当前模型，零配置）；无 LLM 时图谱/画像/蒸馏预览/矛盾仲裁/图召回仍可离线跑。完整参数见 `COMMANDS.md` §P0 升级能力。

---

## 10. 卸载 / 退出 / 迁移（把 keeper 摘干净或搬走）

> 目标：让你**随时能干净退出**——不留钩子、不留调度、不留后台进程。**记忆库默认不会被删**，除非你明确要删。

- **做什么（从"少动"到"多动"，按需选）**：
- **一条命令收口（推荐，先预览再执行）**：`python scripts/keeper_setup.py uninstall`
  - 把下面 1)~3) 一次做完（停钩子 → 停守护进程 → 移除定时调度）；**默认 dry-run**，逐项列出将做的事，加 `--yes` 才执行。
  - `--purge-env` 才清环境变量（`KEEPER_*` / `AI_MEMORY_*`）；不加就留着，重装技能即恢复。
  1) **停钩子**（最常用，保留库）：`python scripts/keeper_setup.py hooks --mode off`（或对 AI 说"关掉自动记忆"）——移除 `settings.json` 里的 keeper 条目，**保留 WorkBuddy 内置 hook**；**重启 WorkBuddy 生效**。
  2) **停守护进程**：对 AI 说"关掉守护进程"（**别手动 kill**，避免残留锁）。若你本就用手动模式，多半没跑守护进程——它不是必需的。
  3) **移除定时调度**：`python setup_scheduler.py --uninstall`（Windows 删任务 + `.bat`；macOS unload + 删 plist；Linux disable + 删 unit）。
  4) **卸 skill 本体**：从 WorkBuddy 卸载该 skill 即可；`~/.workbuddy/hooks/` 下的 `keeper_*` 副本可手动删（**它们只是副本，删了不影响记忆库**）。
- **验证**：`python install_hooks.py --status` 显示无 keeper 钩子；`settings.json` 的 `hooks.*` 不含 keeper 文件；`hook_audit.log` 不再新增。
- **⚠️ 关键限制**
  - **卸 skill ≠ 删记忆**：记忆库在 `<记忆根>`（默认 Windows `~/AI记忆`；回退链见 `SKILL.md`「🔧 配置指引」），**独立于 skill 目录**，卸载 skill 完全不碰它。
  - **要真删库**：先 `backup --zip <库外路径>` 留底，再手动删记忆根目录（**不可逆**）。
  - **部署物不随技能更新自动刷新**：钩子/守护副本、调度项都独立于 skill 目录——升级 keeper 后需按 `INSTALL.md`「更新后：部署同步与引导」重跑同步。
- **回滚 / 重装**：重装 skill 后，钩子会在**首次跑命令时重新自动注册**；模式记在 `hooks_config.json`，不会偷偷把弹窗钩子加回来。
- **迁移到新机**：见 §5 数据迁移与回滚（`keeper_sync.py out|in` 合并式，保留目标机新记忆；整库克隆用 `backup`→`restore --yes`）。
