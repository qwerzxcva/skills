---
name: cloud-stock-data-pipeline
version: 1.0.0
author: hermes-curator
license: MIT
metadata:
  hermes:
    tags: [stocks, github-actions, data-pipeline, parquet]
    related_skills: [stocks]
description: 补齐/回补 GitHub 股票历史数据、建分片仓库或修 Actions 回补管道时使用。
---

## When to Use
用户要求补齐历史行情数据、新建数据分片仓库、修复 GitHub Actions 回补 workflow、或构建/扩展 parquet 分区数据仓库时加载。仅查某只股票行情不需要此 skill。

# 云端股票数据管道 (GitHub 多账号分片 + Actions)

## 架构基线 (用户已有体系, 沿用勿重建)
- 分片规则: 全市场 symbol 排序后 `codes[shard::N]`, 每账号最多 2 个数据仓以分散配额
- 存储: `wh/{dataset}/{YYYY}.parquet` (zstd), 按 (symbol, date) 去重合并; 索引 `_index.json`
- 全市场 A 股 symbol 表: 新浪 `Market_Center.getHQNodeData` node=hs_a 分页拉取 (东财 push2 clist 会 403, 不要用)
- 记忆仓库 `jiegengxiangjianxue/stock-memory` 存账号/仓库拓扑与进度; 动手前先读它

## 流程
1. **探活用户给的仓库名**: 用户提供的 GitHub 链接常见拼写错误/已删, 逐个 GET `/repos/{owner}/{repo}` 确认后才能列入计划。
2. **回补器写法**: 新浪单请求可拿 ~3700 日为主力源, 腾讯分段 (800/段) 只补 1999 年前; qfq 前复权。多线程 worker + done 文件断点续传。
3. **并发写保护**: 任何 parquet 合并写和索引 json 写都必须 fcntl flock + 写 tmp 后 `os.replace` 原子替换——两个线程同时合并同一年分区会产出 zstd 损坏文件, 且坏文件在后续每次合并时级联报错。
4. **Actions workflow**: 每仓单 job (双矩阵 job 并发 push 同仓必然 fetch-first 被拒), push 前必须 `git pull --rebase origin main || true`。cron 30 分钟一批, batch 用 workflow_dispatch input 可调。
5. **验证部署**: 触发后不要只看 dispatch 204——等 run 结束后取 job logs grep `##[error]`, 并抽一个 parquet 从 API `git/blobs` + `Accept: application/vnd.github.raw` 下载用 pyarrow 读数验证。
6. **回补完成后**把 cron 从 30 分钟改为每日一次 (Actions 免费额度 2000 分钟/月, 6 仓 x 48 轮/天接近上限)。

## 运维巡检命令

## 分钟线源实测 (2026-10)
- 腾讯 mkline m5 翻页历史深度只有 ~6 个月 (再往前返空), 单页 800 根 — 「翻页到 2022」不成立
- 新浪 5 分钟 datalen>1970 返 null (~2个月) 且无翻页参数; money.finance 主域已封 (Service not valid), 可用域 quotes.sina.cn/cn/api/json_v2.php
- Baostock frequency=5 是免费 5 分钟全史唯一来源, 地板 = 2020-01-02; 按 2 年分段取, time 字段 YYYYMMDDHHMMSSsss (HHMM 在 [8:12])
- **Baostock 库内部无超时**: 断线时 login/query/rs.next() 会永久阻塞 (workflow 挂 9 小时无产出的根因)。把整个 baostock 调用放进 `multiprocessing.Process` + `p.join(hard_timeout)` (每票 120s), 超时 terminate——不要指望 try/except 或请求级 timeout 能救
- **日期列格式必须全库统一**: 不同源混存 `2026-10-15` 与 `20261016` 会让 duckdb `CAST(date AS DATE)` 全表报错、窗口过滤静默失败 (返回空)、去重失效产生双份行。采集写入前先归一到一种格式; 混入后用 pyarrow 逐分区重写修复
- **符号表完整性先于分析**: 初始符号表缺口会静默缩小数据面 (实测深市缺 1914 只, 含自选股)。新增任何分析对象前先查它在矩阵/仓库里; 用新浪 hs_a 全量表 (5576 只) 对照已有符号集生成缺失清单。东财 kline (`push2his.eastmoney.com/api/qt/stock/kline/get?secid=X.CODE&klt=101&fqt=1`, 需 UA+Referer quote.eastmoney.com) 是补缺口日线的好源, 单次约 1000 根需按早边界翻页
- execute_code 内 `nohup ... &` 启的长任务会随 kernel 回收被杀——用 Hermes terminal 工具 background=true 跑, 它有会话跟踪和完成通知
- Actions push 前顺序: 先本地 commit, 再 git pull --rebase origin main, 再 push — 反了必 non-fast-forward

### 运维巡检命令
- 各仓 run 状态: `GET /repos/{repo}/actions/runs?per_page=1`
- dispatch 前先 `GET /actions/workflows` 拿准确 workflow path (yml 文件名猜错 404); worker 读外部输入 JSON 要兼容多形态 (`symbols.json` 出现过 {"symbols":[str]} / [str] / [dict] 三种), 裸 `r["symbol"]` 会崩整轮
- 各分片进度: `raw.githubusercontent.com/{repo}/main/shard_{id}_done.txt` 行数
- GitHub API/网络间歇性 SSL EOF: 对 API 调用包 3-4 次重试+退避; git push 用 `GIT_TERMINAL_PROMPT=0 timeout 60 git push` 包住防止挂死; 大文件 (>1MB) contents raw 下载会静默截断, 用 curl `-H 'Accept: application/vnd.github.raw'` + 循环 `-C -` 断点续传到字节数与 API 报告一致
- token 不要回显到输出; 用户在聊天里贴过明文 token 时提醒轮换

## 详细资料
- 数据源接口的 UA/Referer/编码/限速细节: `references/data-sources.md`
- 因子矩阵/宽表的内存安全增量与标签纪律: `references/factor-matrix.md`
