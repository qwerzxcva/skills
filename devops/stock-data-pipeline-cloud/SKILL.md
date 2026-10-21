---
name: stock-data-pipeline-cloud
description: Use for the user's GitHub stock-data backfill pipelines.
version: 1.0.0
author: hermes-curator
license: MIT
metadata:
  hermes:
    tags: [stocks, github-actions, data-pipeline, a-share]
    related_skills: [tushare, akshare]
---

# 云端股票数据管道 (GitHub 分仓 + Actions)

## When to Use
- 用户要求维护/扩展其 GitHub 云端股票体系（db-warehouse、db-daily-N 等分片仓）。
- 用户要求回补 A 股历史数据、建数据分片仓、写回补 Actions workflow、排查 parquet/并发写入损坏。

为这位用户构建/维护 GitHub 云端股票数据体系时按此流程。用户有多账号架构：`db-warehouse`=源码中枢，`db-daily-N`=日K分片仓（分属不同账号避开单仓体量），Actions 定时回补。

## 流程

1. **凭据**：多账号各用一个 PAT。token 在仓库 remote URL 或 API header 中使用；绝不回显到输出或写入提交信息，结束时提醒用户轮换（聊天里明文出现过的 token 一律视为需轮换）。
2. **全市场符号表**：东财 push2 接口会 403；用新浪 `Market_Center.getHQNodeData`（`node=hs_a`，num=100，GBK 解码）分页拉全表，配 `getHQNodeStockCount` 校验总数，存 `symbols.json` 入每个分片仓。
3. **分片规则**：symbol 排序后 `codes[shard_id::total_shards]`。每仓放同一份 `shard_worker.py` + `symbols.json` + workflow，断点文件 `shard_{id}_done.txt`。
4. **回补主源**：新浪 `CN_MarketData.getKLineData` 单请求 datalen=5120 可拿约 3700 日（2011 起）；更早历史用腾讯 `web.ifzq.gtimg.cn/appstock/app/fqkline/get`（qfq，800 条/段往回翻页）。腾讯并发高时会 501——那是限速信号，降并发到 4 而非重试。
5. **存储**：`wh/{dataset}/{YYYY}.parquet`（zstd），写入前按 (symbol,date) 与已有分区去重合并，写 tmp 后 `os.replace` 原子替换。
6. **Actions**：schedule cron + workflow_dispatch，矩阵 job 并行，每 job 限时批次（如 120 只）+ 0.5s 限速；`concurrency` 防重叠；commit 用 bot 身份，空提交 `|| echo`。免费额度 2000 分钟/月——回补完成后把 cron 改成每日增量一次，6 仓×高频轮会打满额度。
7. **触发与验证**：workflow_dispatch 推送后查 `actions/runs`，job 日志用 `actions/jobs/{id}/logs`（run 未结束时的 zip 下载会得到非 zip 响应，用单 job 日志端点）。数据验证走 `contents` API 拿 `git_url` 再 `Accept: application/vnd.github.raw` 下载 parquet 读——raw.githubusercontent 对该场景不可靠。

## 铁律（每条都出过事故）

- **并发写同一 parquet 年分区必须 fcntl 独占锁**——多线程 merge 读改写同一文件会交叉产生 ZSTD corruption。
- **索引 json（_index.json）也要 fcntl 锁 + tmp 原子替换**——并发 json.dump 会撞出半截文件，下游读报 'Expecting value'。
- **push 空仓库用 `git init -b main` 本地 staging 再 push**，不要 clone 空 URL；push 卡死时加 `GIT_TERMINAL_PROMPT=0` 和 `timeout`。
- **execute_code 里的 git push 会卡超时**：长网络 git 操作放 terminal 工具，且逐仓执行。
- **本机后台回补用 `setsid nohup ... < /dev/null &` 从 terminal 起**——execute_code kernel 超时被杀时会带走普通 nohup 子进程。
- **报错先看 traceback 定位再改**：'int object is not iterable' 曾被误判为并发问题，实际是调用方把行数 int 传给了期望 rows 的参数——修错位置浪费一整轮重启。

## 爆满对策
全市场 A 股日线全史 zstd parquet 约 400–600MB，6 分片单仓 <100MB，不构成压力。体量大的数据集（minute1、资金流历史）按同模式另建 `db-min-*`/`db-flow-*` 分片仓，勿塞进 daily 仓。

## 参考
- [references/source-endpoints.md](references/source-endpoints.md) — A股免费数据源（新浪/腾讯/东财）实测端点、参数、限速与字段坑。
