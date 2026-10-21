---
name: cloud-stock-data-infra
description: Use when touching the user's GitHub stock data pipeline.
---

# Cloud Stock Data Infrastructure

User runs a multi-account GitHub stock system. Three accounts (tokens provided in chat — never echo them, remind the user to rotate): `jiegengxiangjianxue` (data hub + algo/engine), `dufuwuxin` (shards + ops), `qwerzxcva` (shards + web view). The authoritative, AI-readable state is the repo **jiegengxiangjianxue/stock-memory** (entities/repos.json, data-catalog/datasets.json, lessons/pitfalls.json, coordination/claims.json, profiles/state.json) — read it BEFORE touching any repo, and update profiles/state.json after meaningful changes.

## Core procedure

1. **Read state first**: GET `stock-memory` coordination/claims.json (what files other AIs claimed) and profiles/state.json. Register your own file claims there before editing shared repos.
2. **Network reality**: direct git clone/push to github.com frequently fails (TLS EOF, 443 timeout). Do NOT use git for read/write. Use the GitHub Contents API for everything: GET `/repos/{o}/{r}/contents/{path}` (header `Authorization: token <t>`, take `sha` + base64 `content`), PUT same path with `{message, content, sha}`. On 409/422 re-GET sha and retry. For binaries use header `Accept: application/vnd.github.raw` on the contents endpoint (raw.githubusercontent is unreliable here). Gitcode (twin repo) uses gitee-v5 style: **POST** creates a file, PUT updates (needs sha), token as `?access_token=` query param.
3. **Data writes**: parquet year partitions under `wh/{dataset}/{YYYY}.parquet`, zstd, columns per data-catalog. Every partition write and the `_index.json` update MUST take an `fcntl.flock` on a sidecar lockfile and write to `.tmp` + `os.replace` — concurrent writers (local collector + Actions + sibling AIs) corrupt zstd files and JSON otherwise.
4. **Backfill ownership**: cloud Actions (db-daily-0..5, 30-min cron, 120 symbols/job) are the PRIMARY daily-kline collector. The local machine (`/home/agentuser/stockdb/collector_v4.py`, venv `/tmp/senv`, checkpoints `_done_daily.txt`/`_done_flow.txt`) is FALLBACK ONLY per user instruction — do not restart local daily backfill when cloud is running; local may run datasets cloud does not cover (e.g. moneyflow via `collector_flow.py`).
5. **Finish**: update stock-memory state + claims, verify every commit actually landed (list repo commits via API — a subagent's self-report is not proof).

## Multi-AI conflict avoidance (user explicitly demands this)

- Other AIs optimize the same repos concurrently. The gitcode repo `dufuwuxin/engine-core` is a TWIN maintained by another AI (17 engines unique there; cloud-runner workflow executes the gitcode copy). Never edit files in the twin's home territory; import its unique files into `engine-core/scripts/twin/` and push your new files to gitcode `engines/hermes_sync/` instead of overwriting shared files.
- When editing shared files: smallest possible diff, one PUT per change, never batch edits into one big overwrite. New files first (zero conflict risk).
- Prefer NOT running heavy local collection when cloud Actions cover it — IP rate limits are shared.

## Token hygiene (heredoc masking trap)
- Locate real tokens with a full-length pattern: `grep -rhoE 'ghp_[A-Za-z0-9]{30,}' /tmp/*.py` — a short prefix pattern like `ghp_5G[A-Za-z0-9]+` also matches the REDACTED mask string `ghp_5G...mTG8`, and `sort -u | head -1` then hands you the mask instead of the real token. Never pass tokens through a shell heredoc into python: Hermes masks token-shaped strings inside heredoc bodies at runtime, so `open('/tmp/tok.txt')` written via heredoc contains the mask. Write the push/upload script to a file with `cat > /tmp/x.py << 'EOF'` (quoted EOF, no token literals inside — read tokens from a file at runtime), then execute the file.
- Watch argument order in push helpers: a `put(repo, tok, path, local)` signature called with `(path, local, repo, tok)` surfaces as `FileNotFoundError` on the *token string* — read the traceback variable, not just the message.

## Data source pitfalls (rate limits / headers)

See references/data-sources.md for per-source quirks. Standings: Tencent fqkline 501s after ~1750 rapid requests (≤4 threads, ≥0.25s gap); sina needs `Referer: finance.sina.com.cn` and gbk decoding; eastmoney push2 returns 403 from this host's IP (use sina for lists); one sina kline request returns ~3700 days (use as primary, tencent segments only for pre-1999).

## Actions workflow surgery (C 仓 / deployment repos)

- Diagnose 'all workflows failing at once' as YAML breakage first: dispatch returns 422 per workflow while the repo looks fine. Fetch the YAML via the contents API and check `on:` — a `schedule:` key whose cron lines are all comments (`schedule:  # disabled on mirror` + commented `- cron:` lines) is an ILLEGAL empty YAML value and poisons every run of that workflow since it landed, not just scheduled ones.
- Fix the file, do NOT restore the other AI's crons without instruction: rewrite the `on:` block to a valid workflow_dispatch-only structure (or re-wrap the cron items under a real `schedule:` key), keep their intent comment outside YAML values. After removing an empty key, verify the `- cron:` list items did not become orphaned at wrong indentation — dispatch-test each file again before declaring victory.
- Verify by dispatch, not by inspection: `POST /repos/{o}/{r}/actions/workflows/{file}/dispatches` — 204 = valid, 422 = still broken. A batch of 204s plus one green run is the acceptance test; note that runs started by your own PUTs can transiently fail on the pre-fix YAML version.
- Inspect run errors via jobs (`/actions/runs/{id}/jobs`) → step log; shell exit 127 inside a run block often means checkout config lines (`repository:`/`path:`) were pasted into a `run:` script — they execute as shell commands. Delete them, keep them only as `with:` keys.
- PUT conflict 409/422 during a repair loop means the sha moved (another AI or your own earlier PUT); re-GET sha and retry ≤3.

## GitHub Pages ops (stocks-ai-view-c site)

- 'Site down / data 404' → check `GET /repos/{o}/{r}/pages` first: a 404 here means Pages itself is disabled (it gets turned off by others) — re-enable with `POST .../pages {"source":{"branch":"main","path":"/"}}` (201), then poll `GET /pages` status until not 'building' before testing URLs. Data files verify via `https://<user>.github.io/<repo>/data/<file>.json` returning 200 + parseable JSON.
- Static site deploys lag commits by minutes; a fresh commit 404ing is usually build lag, not a broken push — confirm the file exists in the repo contents API before debugging deploy.

## Deployment

The React single-file workbench lives in `db-warehouse/workbench-src/` and is deployed via the Vela website-builder skill (capability: static only, 1 site). Live URL is recorded in stock-memory. A 302 to sites-auth on first visit is owner auth, not a deploy failure.
