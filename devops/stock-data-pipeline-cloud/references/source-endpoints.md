# A股免费数据源实测笔记

## 新浪（主力）
- 全表: `Market_Center.getHQNodeData?page=N&num=100&sort=symbol&asc=1&node=hs_a`，GBK；计数 `getHQNodeStockCount?node=hs_a`。必须带 `Referer: finance.sina.com.cn`。
- 日K: `CN_MarketData.getKLineData?symbol={sh600000}&scale=240&ma=no&datalen=5120` — scale 240=日线，datalen 最大有效约 5×1023（3700+ 日，2011 起），超出部分静默截断。
- 资金流全史: `MoneyFlow.ssl_qsfx_lscjfb?daima={code}&num=10000`，2010 起，限速约 1 req/s。
## 腾讯
- 日K qfq: `web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={code},day,,{end},800,qfq`，用 end=最早日期往回翻页；响应 key 可能是 `qfqday` 或 `day`。
- 指数全史: `.../kline/kline?param={code},day,,{end},800`（上证 1990 起）。
- 实时: `qt.gtimg.cn/q={codes}`，GBK，字段 p43 是振幅不是 PB（PB=p46），p44/p45 单位亿元。必须带 `Referer: gu.qq.com`。p[2]=code、p[1]=名称、p[3]=现价、p[32]=涨跌%、p[49]=量比、p[38]=换手%。
- 逐票日线增量（回补断档）：同一 fqkline 端点不带 end 参数拿最近 400 日，按 `date >= 'YYYY-01-01'` 过滤后入库；约 3-4 票/秒。某票连腾讯也 404/空 = 退市/长期停牌的数据源极限，记录一次、不要每轮重试。
- **限速**：连续约 1750 请求后 501 Not Implemented（这是限速不是 bug）；并发 8+ 时更早触发。降并发到 4、请求间隔 0.25–0.4s。
## 东财
- push2 clist 等接口对本机直连 403（带 Referer 也无效），勿依赖。
## schema
- daily: symbol, date, open, close, high, low, volume（qfq 前复权，价格 float）
- moneyflow_hist: symbol, date, trade, changeratio, turnover, netamount, r0..r3, r0_net..r3_net
