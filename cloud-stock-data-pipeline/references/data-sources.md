# 免费行情数据源实录

## 腾讯
- 日K: `web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={code},day,,{end},{count},qfq`, 必带 `Referer: https://gu.qq.com`
- 限速: 并发跑约 1750 次请求后开始返回 501 Not Implemented——并发 <=4 且每请求间隔 >=0.25s
- 指数全史: `.../kline/kline` 同域, 每页最多 800 根, 用 end 往前翻
- 实时: `qt.gtimg.cn/q={codes}`, GBK 编码, 批量 60/请求; 字段 p44/p45 单位亿元, p46 才是 PB (p43 是振幅)

## 新浪
- 日K: `money.finance.sina.com.cn/.../CN_MarketData.getKLineData?symbol={code}&scale=240&ma=no&datalen=N`, N 给 5120 实际返回 ~3700 日; 需 `Referer: https://finance.sina.com.cn`
- 资金流全史: `vip.stock.finance.sina.com.cn/.../MoneyFlow.ssl_qsfx_lscjfb?daima={code}&num=10000`, 2010 起, 每请求间隔 >=1s
- 全市场列表: `Market_Center.getHQNodeData?page={n}&num=100&node=hs_a`, GBK; 分页会漂移, 用 set 去重
- 实时: `hq.sinajs.cn/list=` 必带 Referer 否则 403

## 东方财富
- push2 clist 接口目前 403 (常规 UA/Referer 组合无效), 列表改用新浪
- 日K kline 可用: `push2his.eastmoney.com/api/qt/stock/kline/get?secid={1.sh|0.sz}{code}&fields1=f1,f2,f3,f4,f5,f6&fields2=f51,f52,f53,f54,f55,f56,f57&klt=101&fqt=1&beg=19900101&end=20500101&lmt=1000000`, 需 UA + `Referer: https://quote.eastmoney.com`; 单次约 1000 根, 翻页用返回首行日期作早边界; 实测 ~97 只/min
- 财务全史: `datacenter-web.eastmoney.com/api/data/v1/get` (与 push2 不同子域, 不 403), 报表 `RPT_F10_FINANCE_MAINFINADATA` 需 UA+Referer emweb.securities.eastmoney.com; 字段映射 ROEJQ/TOAZZL/XSMLL/XSJLL/ZCFZL 等; 北向 `RPT_MUTUAL_DEAL_HISTORY` 001/002 (2014-11 起), 两融 `RPTA_RZRQ_LSHJ` (2010-03 起), 港股通名单 `RPT_MUTUAL_HOLD` MUTUAL_TYPE=003
- 腾讯排行/榜单接口 (proxy.finance.qq.com getBoardRankList) 返回空, 涨跌榜改用新浪全量列表自排序

## GitHub 读取
- parquet/二进制从仓库读: 走 API `contents` 拿 `git_url`, 再请求 blob 带 `Accept: application/vnd.github.raw`; raw.githubusercontent 对大文件/二进制不可靠
- contents API PUT 更新文件: 先 GET 拿 sha 再 PUT, 网络抖动时重试 3-4 次
