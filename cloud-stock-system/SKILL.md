---
name: cloud-stock-system
description: Use when operating the user's GitHub A-share stock repos.
version: 1.0
author: hermes-curator
license: MIT
metadata:
  hermes:
    tags: [stocks, backfill, github-ops, quant]
    related_skills: [stock-monitor]
---

# Cloud Stock System Ops

## When to Use
- Any work on the user's stock repos (db-warehouse, db-daily-*, algo-core, engine-core, stocks-ai-view, stock-memory): data backfill, engine-chain changes, workbench, or new data sources.

## Architecture (always verify current state first)
- Read `github.com/jiegengxiangjianxue/stock-memory` (entities/repos.json, data-catalog/datasets.json, profiles/state.json) BEFORE acting — it is the authoritative structured memory; state changes faster than chat context.
- Topology: `db-warehouse` = collector source + docs; `db-daily-0..5` = daily-K shards across 3 accounts (symbol-sorted `codes[shard::6]`); `algo-core` (algorithms) + `engine-core` (engine scripts) = algorithm chain; `stocks-ai-view` = view layer + 89-source registry.
- Data schema: `wh/daily/{YYYY}.parquet` zstd, columns `symbol,date,open,close,high,low,volume,turnover_rate`, dedup on (symbol,date).

## Git access: use contents API, not git
- This machine's git to github.com:443 fails intermittently (TLS EOF / connect timeouts). Do NOT burn time on `git clone` retries — use the REST contents API for all reads/writes:
  - Read: `GET /repos/{owner}/{repo}/contents/{path}` → base64 `content` + `sha`.
  - Write: `PUT` same path with `{message, content(base64), sha}` — always GET the sha first or the PUT fails.
  - Raw fetch of large/binary files: `GET /repos/.../git/blobs/{sha}` with `Accept: application/vnd.github.raw` (raw.githubusercontent is CDN-cached and unreliable for just-pushed files).
- Retry transient SSL EOF with 3-4 attempts + sleep; the API succeeds far more often than git. urllib raises `SSL: UNEXPECTED_EOF` in tight loops too — for large files (>1 MB) use curl with `-H 'Accept: application/vnd.github.raw'` to a file, looped with `-C -` (wget -c resume) until the byte count matches the API-reported size; multi-MB raw downloads truncate silently mid-body.
- Repos >1 GB or thousands of files (e.g. a full skills-library backup) CAN be pushed with git: `git push https://x-access-token:{token}@github.com/...` (plain clone drops the credential on redirect; embed the token in the push URL). GitHub Push Protection will reject commits containing secrets — grep the tree for `sk_live_`/`ghp_`/`tvly-` patterns first and scrub, then `git commit --amend` before re-pushing.
- GitCode mirrors: `git clone --depth 1` from gitcode yields an incomplete object store (fsck clean but push fails with index-pack failed / remote rejected, `cat-file` fatal on a missing blob) — always full-clone; content API PUTs false-report 400 there, use git push; token goes as `?access_token=` query param, not Bearer.

## Concurrent parquet writes
- Any writer that merges into a shared year-partition parquet (or rewrites `_index.json`) MUST hold an `fcntl.flock` on a lockfile and write to a `.tmp` then `os.replace`. Concurrent merge without the lock corrupts zstd files (symptom: 'ZSTD decompression failed' on read).
- Backfill collectors must patch NEW columns (e.g. turnover_rate) into merge logic — a collector that rewrites partitions from its own row shape silently drops columns added by other tools.

## Data source quirks (A-share)
- Tencent fqkline (`web.ifzq.gtimg.cn`): rate-limits to ~1750 requests then returns 501; keep concurrency ≤4 and ≥0.25s spacing; on 501 switch to `ifzq.gtimg.cn` root domain.
- Sina daily-K single request returns ~3700 bars (2011+); use it as primary, Tencent segmented fetch only for pre-1999 history. Requires `Referer: finance.sina.com.cn`; many Sina endpoints are GBK-encoded.
- Eastmoney push2 endpoints 403 from some egress IPs (WAF); have a Sina fallback for any eastmoney call.
- Sina moneyflow `MoneyFlow.ssl_qsfx_lscjfb?daima={code}&num=10000` returns the full history in one request (~4000 bars) — much faster than per-day loops.
- Full A-share symbol list (5575 incl. BSE): Sina `Market_Center.getHQNodeData` paged by 100, node=hs_a (eastmoney clist is 403-prone).
- Limit-up thresholds vary by board: main board 10%, ST 5%, ChiNext/STAR 20% — never use a single 10% rule across the market.

## GitHub Actions shards
- Free-plan scheduled workflows (cron */30) often fire 10-60 min late or skip; hand-dispatch via `POST /repos/{owner}/{repo}/actions/workflows/{wf}/dispatches` to keep backfill moving, and don't diagnose a fault before checking dispatch-first.
- One job per shard repo (never a 2-job matrix committing to the same repo) + `git pull --rebase` before push; two concurrent jobs hit non-fast-forward rejections and lose the done-file breakpoint.
- A failed push can lose the `shard_*_done.txt` breakpoint while parquet data still lands — verify actual symbol coverage in parquet (read one partition, count distinct symbols) before assuming data loss.

## Run long jobs in the background
- Long backfills: run via Hermes `terminal` with background=true (tracked proc_*) — `setsid nohup`/plain nohup children get reaped when the execute_code kernel is recycled; use `sleep`-loop polling in <=280 s chunks (execute_code kills at 300 s) or a notify-on-exit background terminal instead of in-kernel sleeps.
- factor_matrix.duckdb: date column was mixed VARCHAR (ISO + compact formats sort wrong) — now rebuilt as a real DATE column, 893k rows with unparseable dates (source-data gap in 1.8k SZ symbols, mirrored by an empty px table) deleted; treat NULL-date rows as dead data and drop them, they never join any cross-section.
- Scheduled pick pipelines stall silently: always check `data/*.json` timestamps (ai_picks, pools, pre/midday_picks) before trusting a morning recommendation — a stale ts means the Actions time-window guard skipped the run; hand-dispatch scheduler first, then verify via workflow runs list (weekend failures of window-guarded engines are expected, not bugs).
- Python deps live in `/tmp/senv` (duckdb, pyarrow, scikit-learn) — /tmp is wiped on reboot; recreate with `python3 -m venv /tmp/senv && /tmp/senv/bin/pip install duckdb pyarrow scikit-learn` when missing.
- Big DuckDB writes (factor matrix): batch INSERT + CHECKPOINT per batch; one-shot concat → write gets OOM-killed (exit 137) on 7 GB boxes. Downsample (e.g. 25%) before ML training to fit RAM.
- DuckDB `json.dump` on rows containing DATE objects raises TypeError — always pass `default=str`. A dropped-table DuckDB file never shrinks on checkpoint; reclaim space by ATTACHing a new file and `create table new.x as select * from old.x` (halved a 15 GB factor matrix this way), then delete the original.
- Long loops that spawn per-round Python subprocesses: guard with `flock` on a lockfile — a killed loop's orphaned children keep running and silently duplicate work (logs overwrite each other, results mix two code versions). Kill by exact pattern, never bare `pkill -f test*`; first SIGTERM a background terminal's shell then verify with `ps` before starting a replacement.

## Workbench (React site)
- Two deployments: Vela (`ws-*.lightvela.tech`, 302→sites-auth login is owner-auth, WeChat/QQ scan only — the agent cannot complete it) and GitHub Pages (dufuwuxin.github.io/stocks-ai-view-c, no login). When the user reports "site has no data", first open the Pages URL in a browser and read `document.body.innerText` — do not assume data files are missing.
- Root cause of "site blank but index quotes show": the frontend fetches warehouse JSON from `raw.githubusercontent.com`, which is frequently blocked/slow from CN browsers (Tencent realtime APIs connect fine, so the page half-works). Fix pattern: `data_origin_patch.js` fetchJSON must try the **same-origin `data/<file>` first** (Pages serves the repo's data/ dir), then fall back to raw GitHub, then gitcode. Deploy the data files into the Pages repo's `data/` by syncing them from the source shards. Sync is automated: `pages-data-sync` workflow (every 10 min) full-diffs the source repo's data/ into the Pages repo.
- Frontend render pipeline is fragile to null elements: `render()` runs sequential `renderXxx(d.field)` calls with NO try/catch — one `document.getElementById(...)` returning null for a removed element aborts every render after it (stuck "加载中…” panels that never resolve). Fix: null-guard each render target and wrap calls in the page's `_safe()` helper; also fix duplicate `id=` attributes (renderSummary updated only the first match, leaving the desktop card dead) and check that render functions actually have call sites (renderCloud was defined but never invoked). Verify fixes by reading per-element innerText in the browser, not the whole page.
- The Pages copy of data/ is a static sync of shard repos — re-sync after each session's data pushes, or the site serves stale snapshots. Browser cache: after changing JS, the user needs a hard refresh (Ctrl+Shift+R).
- Debugging in-browser: `browser_exec` + `js('document.body.innerText')` shows which blocks render ("加载中…” = fetch pending/failed, real numbers = OK); kernel-daemon IPC can time out on navigation — retry `ensure_real_tab()` once.

- skapp 凭据问题根因（10-21）：私仓 + fine-grained token 未授权该仓 → contents API 一律 404。解法：新建公开数据仓 skapp-data，app 全部仓库数据改 raw.githubusercontent.com 直读（?t= 时间戳防缓存），App 端零凭据；CI 跨仓同步必须用 PAT secret（GITHUB_TOKEN 只能写本仓，403）。建 repo secret 免 pynacl：venv pip install pynacl + SealedBox 加密 PUT /actions/secrets。eod-snapshot workflow 每日 15:35 生成快照+同步 8 文件到 skapp-data（含当日快照）并提交 skapp；坑：git pull --rebase 要 --autostash 且放 commit 之后；跨仓 step env 不能挂在别的 step。
- skapp 实时架构（10-21 v0.4.0）：用户指出全是静态→发现网站真实数据源=qwerzxcva/stocks-ai-view（公开仓，Actions 高频 push，data/ 1030 文件；dufuwuxin/stocks-ai-view-c 为备源；gh_sources.js 实现多仓取最新 ts）。app Repository 重写为 liveFile 多源降级（raw_A→raw_B→token API 兜底）直接读网站同仓：today_picks.json（signals/values/limit_up+market 脉搏）、decision.json（position_advice+cards 十维+avoid）、stock_names.json（搜索索引）。行情 30s/快讯 60s/引擎 120s 自动轮询（ViewModel init+while+delay）。坑：optDouble 返回 Double 但 data class 声明 Double? 后 .isNaN() 要安全调用。网站 pages 不发布 data/（github.io 404），前端本来就走 raw.githubusercontent。①strategy_rank.json 的 ranking 是数组非对象，Kotlin 旧代码 getJSONObject 会抛→解析失败；②推股/AI 选股 JSON 已加 name 字段（同步脚本从 symbols.json 富化）；③app 加个股详情 ModalBottomSheet（点卡片弹实时行情+加自选+跳 gu.qq.com 看K线，LocalContext 必须提升到组合层）；④「我的」页凭据接口=多行 token 任取首个有效行，无效自动回退匿名 raw；⑤策略卡展示胜率/T1均收/n。
- jiegengxiangjianxue/skapp：core/ Rust（sma/cross_rank/composite，cargo test 过；crates.io 本机不通，serde/pyo3 扩展靠 CI maturin）+ py/（datasrc 腾讯/新浪、engine analyze、pipeline eod_sync 快照→data/snapshots/，同步后删 data/live/）+ api/（FastAPI :8800，/api/v1/quote|analyze|news|snapshot 已实测）+ app/ Compose M3 + Actions eod-snapshot(UTC 7:35)。映射见 docs/REPO_MAP.md。
- 坑：①eod_sync HERE 三层 dirname ②新浪 jsonp 回调名空格需 %20 ③rustup-init 本机 segfault→用 apt rustc/cargo 1.75 ④contents API GET 404 无 sha 时当新建 ⑤内存 99% 满，新增条目前先删旧 ⑥顶层包名「py」与 pytest 依赖库 py 冲突→CI 测试挂 AttributeError module 'py' has no attribute 'path'，已改名 skapp_pkg/（连带 os.path.join(HERE,"py",...) 字符串路径也要改）⑦CI 排错：GET /actions/runs/{id}/jobs 取 job id 拉 logs。三条 CI（rust-core/py-tests/eod-snapshot）全绿。
- skapp APK（10-21）：android-apk workflow 构建→artifact + Release tag apk-v*。坑：⑧settings.gradle.kts 缺 pluginManagement{google()} 会报 AGP plugin not found ⑨M3 TopAppBar 是 ExperimentalMaterial3Api，需 @file:OptIn 且 file 注解必须在 package 之前 ⑩Kotlin `is 构造器(参数)` 非法，数据类判等用 (x as? T)?.field == v ⑪Sequence 链 sortedByDescending 返回 Sequence 需 toList ⑫release assets 下载需 Accept: application/octet-stream + -L，PK 魔数校验。app 已自足化：腾讯/新浪直连+仓内 data/search/symbols.json（5575 只名称索引）+ data/engine/*（decision/engine_fusion/ai_pick_v5/strategy_rank 网站同源产物，需同步脚本保持新鲜）。

## Memory & reporting conventions
- Update `stock-memory/profiles/state.json` after each milestone (done/in_progress/todo) so other AI sessions see current state.
- Workbench: single-file React+Tailwind CDN at db-warehouse/workbench-src/, deployed on Vela (302→sites-auth on visit is owner-auth, not a failure); texts are contenteditable + localStorage.
- User cares that reports state facts, not predictions; verify child-agent claims (commit shas) by listing the repo's commits before reporting success.
