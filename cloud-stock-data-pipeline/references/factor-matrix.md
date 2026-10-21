# 因子矩阵 (factors_wide) 增量重算 — 内存与标签纪律

## 内存 (7GB 机器)
- 一次性 fetchdf 全表必被 OOM killer 杀 (症状: 进程消失, log 无 Traceback, exit 137)。逐批计算 + `INSERT INTO ... SELECT` + `CHECKPOINT`, 每批 ≤15 万行
- worker 数 ≤2; INSERT 前 `DESCRIBE` 目标表取列序, 显式补齐缺失列并按列序重排——目标表被其他工具加过列后 `SELECT * FROM tmp` 会列数不匹配
- 每批后落状态文件 (幂等断点), 重跑时跳过已完成批; todo 为空时正常退出, 不要在 final merge 阶段全表 fetchdf (用 SQL 库内完成 join/标签)
- ML 训练用 duckdb `USING SAMPLE N ROWS` 在库内抽样, 不要 fetch 全表再 sample

## 标签与检验纪律
- fwd_ret 标签必须 `pct_change().shift(-1)` (lead); lag 写成当日收益 → 泄漏 (corr=1.0, AUC=1.0 假象)。写完抽查: corr(ret_1d, fwd_ret_1d) 应 ≈0
- T+1 全因子 IC≈0 是正常结论 (日频不可预测); 筛因子用持有期匹配标签 (月频因子配 fwd_ret_22d)。IC 高先查机械重叠 (如 intraday_return 与 fwd 标签构造重叠)
- IC ≠ 可交易 alpha: IC 0.115 的 amihud LS 审计 -24%/yr (做多低流动性亏钱)。任何因子/策略注册前跑分年 LS 审计 (PASS/OBSERVE/REJECT), 全期+分年双检
- 纯多头回测必须报**相对等权基准的超额**: 2022-2026 全市场等权本身 +37%/yr, 不减基准的 +42.7% 是 beta 不是 alpha; 另报扣费后数字 (高换手策略 0.1% 成本即可吞光 alpha) 和最大回撤年 (如 2023 微盘崩盘)
- **月频回测必须用月末最后交易日单一截面**: 把月内所有交易日截面混进一个月度组合 (score 与 fwd_ret 逐日配对后 pooling), 虚增 3-4 倍收益 (实测 v3 +55.6%/yr 混合 vs +16.6%/yr 诚实月末), 选出的 "top N" 是不可执行的 (日,票) 对。所有历史回测数字凡用混合截面的一律作废待复检
- 分年 LS 审计窗口必须 ≥3 年: 1 年窗口正超额会反转 (反转因子 1 年 +0.6%/月、3 年 -4.4%/月, 大跌月接飞刀); IC 动态加权同样混合截面时好看、月末截面 -21.9%/yr
- 复检时先拆 universe 偏差: 沪/深/北交易所覆盖缺口会让 "超额" 变成市场间 beta, 分交易所重跑确认超额稳定才是真信号 (composite v3 诚实锚点: 月末截面 T+22 含成本 +8.4%/yr, 缓冲带版 +7.3%)
- ML 概率 (0.58-0.74) 是未校准值, 禁止当胜率表述; AUC 0.52-0.56 如实写"弱信号, 非交易依据"
