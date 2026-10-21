# Data source quirks — A-share collectors

## Symbol universe
- Full A-share list (incl. BSE, ~5575): sina `Market_Center.getHQNodeData?page=N&num=100&node=hs_a` (Referer: finance.sina.com.cn, gbk). Pages drift while paginating — dedupe by symbol.
- eastmoney push2 clist is 403 from this host — do not use for lists.

## Daily kline
- Sina primary: `CN_MarketData.getKLineData?symbol={code}&scale=240&datalen=5120` → ~3700 days in one request (needs Referer header). Fields day/open/close/high/low/volume.
- Tencent backfill for pre-1999: `web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={code},day,,{end},800,qfq` (Referer gu.qq.com). 501 Not Implemented = rate limited; back off, ≤4 threads, ≥0.25s between calls. Fallback host: ifzq.gtimg.cn root.
- Free float shares for turnover_rate: tencent qt.gtimg.cn per-code fields (batch once into symbols snapshot); turnover_rate = volume / float_shares. History uses current snapshot — note the approximation in code comments.

## Moneyflow
- Sina `MoneyFlow.ssl_qsfx_lscjfb?daima={code}&num=10000` returns full history (~2000-4000 days) per symbol in one call, 2010+. ~1s sleep between symbols; 3 threads ≈ 15-50/min depending on IP throttling.

## Write discipline
- fcntl.flock sidecar `.lock` + tmp-file `os.replace` for every parquet partition and `_index.json` — concurrent writers without locks produce 'ZSTD decompression failed' / truncated JSON.
- When a collector later rewrites a partition it must preserve computed columns (turnover_rate) or they are silently lost.
- Backfill checkpoint files (`_done_*.txt`) are append-only; a lost checkpoint only causes a harmless re-fetch because partitions merge dedup on (symbol, date).

## GitHub API specifics
- Contents API PUT: must include current `sha` for existing files; omit for new. 409/422 → re-GET sha, merge, retry (max 3).
- Raw parquet download: contents endpoint with `Accept: application/vnd.github.raw` (or git blobs API) — raw.githubusercontent.com is flaky from this host.
- Actions: free-plan schedule crons lag 10-60 min or skip under load — dispatch manually via `POST .../actions/workflows/{wf}/dispatches` when progress stalls. One workflow per shard repo, single job, `git pull --rebase` before push (parallel matrix jobs reject each other with fetch-first).
- Actions minutes quota ~2000/mo: 6 repos × 48 runs/day ≈ at limit; after backfill completes, switch cron to daily increment.

## Gitcode twin
- API: gitee-v5 style at `gitcode.com/api/v5/...?access_token=<t>`. Create file = POST, update = PUT with sha. Git operations (ls-remote/clone) work with `https://user:token@gitcode.com/...`.

## Backfill sizing rules
- Tencent fqkline returns 400-day windows; a symbol whose history is simply absent there (delisted, long suspension) is a data-source limit, not a bug — record it once, do not retry per symbol on every run.
- Sizing serial loops before launching: time 10-100 symbols, extrapolate; ~3-4 symbols/sec is normal for one-shot kline fetch + insert. Shard a 4-5k universe into 4 sequential shards (~10 min total) instead of parallel loops — parallel background shells orphan and duplicate each other; guard the whole run with `flock -n` on a lockfile so a second launch no-ops.
- For factor/backfill outputs sized for GitHub contents PUT: batch ~500 small JSON files into one `.tar.gz` (<2MB), PUT the tar to two repos, and only delete locals after BOTH PUTs verified. Keep tars well under the ~100MB contents limit.
- DuckDB gap-fill into an attached DB: insert with `where not exists (select 1 from q where sym=b.sym and q.d=b.d)` dedupe, then checkpoint; the source DB can be deleted afterwards.
- `asof` is a reserved word in DuckDB DDL — use `as_of`.
- Test replacement patches against the actual file text, not memory: a string-replace "patched OK" print can fire while the anchor never matched (f-string quote mismatches). Verify with `grep -c <new_marker>` after every scripted edit to engine files.
