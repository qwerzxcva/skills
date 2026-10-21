# Algorithm chain (v4) — seven stages

1. **Data**: wh/daily parquet → validated by engine-core/scripts/data_check.py (dup keys, OHLC logic, NaN, calendar gaps, negative prices; report to data/data_quality.json). Negative historical prices (pre-1992) are source artifacts, split out by symbol/period, not errors to fix.
2. **Factors**: algo-core/factor_lib.py registry; cyq.py uses per-day turnover_rate (float_shares snapshot in wh/float_shares.json; limit boards where high==low inject chips at 2x triangle area). Missing/backfill days fall back to mean-volume approximation with fallback_days counter.
3. **Signals**: BaseAlgo (lumibot-style initialize/generate_signals) in algo_base.py; adapters.py wraps pick_algo/ai_pick/patterns/pools into ALGOS registry returning [{symbol,score,meta}].
4. **Fusion**: engine_fusion.py = fast linear prior; each score fn returns (score, missing) — missing engines are excluded from weighting and agreement is scaled by available engines. agent_debate.py (bull→bear→manager→aggressive/conservative risk review, rule-scored with LLM hook) runs on TopN via decision.py optional import.
5. **Decision**: decision.py params from BASE/config.json; sizing via sizer.py kelly_sizer / atr_sizer (stop = entry − k·ATR14).
6. **Review**: pick_tracker T+1 settle → loss_attribution 4 buckets (beta / chase_high real 3-day prior gain>15% / idio / theme_fade same-theme limit-up count shrinking >30%).
7. **Adapt**: strategy_leaderboard (duckdb strategy_signal; rank → strategy_rank.json) + run_registry + drift_monitor (OOS degradation + win-rate below bootstrap CI → data/param_update.json). Backtests: analyzers.py (sharpe/max_dd/profit_factor/win_rate/SQN), slippage 0.1%, limit boards skipped as unfillable.

First-round real stats (context for drift calibration): limitup algo T+1 win rate ~29%, lowpos_pool ~27% — signal quality is the open problem, not plumbing.

## Intraday pick pipeline (morning/midday recommendations)
- Check `data/*.json` ts stamps (ai_picks, pools, premarket/midday_picks) BEFORE trusting a recommendation — scheduled engines only run in pre-open/post-close time windows, so a stale ts means the guard skipped the run; hand-dispatch the scheduler workflow and verify via the runs list (weekend failures of window-guarded engines are expected, not bugs).
- Verify engine picks against live quotes (Tencent qt.gtimg.cn batch) before presenting: cross-check entry_zone staleness (recommendation age), and whether the gate state (e.g. defensive) agrees with the pick style — a defensive gate recommending high-vol attack names is a structural bug to flag, not follow.
- All price codes in views/quotes are dot-less (`shXXXXXX`); the bs source uses `sh.XXXXXX` — normalize with `replace(code,'.','')` at the union boundary.

## Backtest gates (before registering ANY factor/portfolio)
- Monthly-frequency backtests MUST use the **month-end last trading day's single cross-section**. Mixing every intraday-day cross-section into one monthly portfolio (score and fwd-return paired per day, then pooled) inflates results 3-4× (measured: composite v3 +55.6%/yr mixed vs +16.6%/yr honest EOM) — the picked "top N" becomes (day,symbol) pairs that cannot be executed.
- Registration requires ≥3-year per-year LS audit. A 1-year positive window is noise: a reversal overlay scored +0.6%/month over 1 year but -4.4%/month over 3 (crash months knife-catching, e.g. single month -28.75%). Same for rolling-IC dynamic weighting: looked great mixed, -21.9%/yr honest EOM.
- Apply cost + turnover honestly: top50 monthly turnover ~95-100%, net = excess − turnover×0.7%. v3 true anchor: **+8.4%/yr net (+7.3% with 75-buffer band)** — NOT the older +4.2% or +42.7% figures; any historical number computed with mixed sections is void until re-audited.
- Red-flag discipline: when a backtest looks too good (>+30%/yr), decompose before celebrating — check universe mix (SH vs SZ vs BSE coverage gaps), execution feasibility, and benchmark construction before reporting.
- Repo name gotcha: the algorithms repo is `jiegengxiangjianxue1/stocks-algo` — there is no `algo-core` repo on GitHub despite that name appearing in older docs/chat.
- Dual-source price view: all engines take prices via `px_view.attach_px(con)` (qfq-first + bs only for symbols the main DB lacks) — a naive `union all` of both sources leaves ~28k duplicate (symbol,date) rows across ~2.4k dual-covered symbols that silently inflate momentum/volume factors and market-phase medians. attach_px is idempotent (skips the attach if t1 is present) and exposes full OHLC `o,c,h,l,v` — extend px_view for missing columns instead of attaching a second private view.
- After any data-hygiene fix (dedup, backfill, reweight), re-run historical backtests before comparing: absolute win rate drops when duplicate rows are removed (v4: 55.6%→47.4%) while beat-rate vs the same-day market is the stable metric — never mix pre/post-fix numbers in one table.
- factor_matrix NULL dates: unparseable date strings (compact-format gap in ~1.8k SZ symbols, mirrored by an empty px table for those symbols) become NULL after try_cast — drop them as dead data; they never join any cross-section.

## Shard worker gotchas
- Validate external input JSON shape in workers: `symbols.json` has arrived as `{"symbols": [str]}`, `[str]`, and `[dict]` — workers must accept all three (`s["symbol"] if isinstance(s, dict) else s`); a bare `r["symbol"]` genexpr crashes the whole shard run.
- Workflow dispatch needs the exact path from the workflows list (`POST /actions/workflows/{path}/dispatches`) — guessing a yml filename gives 404.

## Multi-AI coordination rules (stock-memory repo)
- `stock-memory` is the shared blackboard (data-catalog/ global/ projects/ global/coordination/MESSAGE_BOARD.md claims.json). Another AI writes to it directly on main — read MESSAGE_BOARD + claims.json BEFORE touching shared repos, and post a completion note after merges.
- Claim files in claims.json before editing shared files; prefer NEW files over overwriting (e.g. register factors via `register_into_factor_lib()` in a separate alpha_ext*.py, never edit factor_lib.py itself).
- Single source of truth: GitHub repos are canonical, gitcode dufuwuxin/engine-core is a mirror — the mirror drifts (old snapshots of cyq/patterns/etc.). After the other AI publishes there, diff against GitHub, keep the newer version in each file, and sync both directions; never assume either side is wholly current.
- When the other AI's work lands on branches or a mirror instead of main, merge it yourself (contents API, GET sha → PUT) and verify the child-agent's claimed commits exist via the commits API before reporting.
