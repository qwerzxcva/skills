---
name: cn-financial-scraper
display_name: 中国金融机构数据爬取与分析
display_name_en: CN Financial Scraper
description_zh: 中国金融机构数据爬取与分析综合工具 v10.0.0：2334家/43大类机构名单、全网舆情监测（60+财经媒体源）、A股报告/公告/研报抓取、多源金融数据统一查询（v9 36种 + v10 24种 共60+查询类型，akshare/东方财富API/yfinance/RSS/Tushare/CoinGecko/ExchangeRate 9 适配器自动降级 + LRU+TTL 缓存）、类人浏览器深度爬取、爬取调度中心（CrawlerDispatcher智能按健康度选源+增量判断+断点续爬+反爬保护）、网页操作增强（Shadow DOM/iframe穿透+Cookie Banner自动+验证码OCR+人类行为轨迹+WebSocket监听）、MCP Resource（8个：媒体源/机构库/查询类型/报告模板/缓存/数据源健康/反爬状态/调度状态）+ MCP Prompt（10个高频模板）、真实风险指标分析与定期报告解读、反爬深度增强（代理池/行为画像/Header顺序随机化/指纹一致性/预算/IP信誉/验证码检测）与爬后深度数据分析。
description_en: "Comprehensive China financial-institution data scraping and analysis toolkit v10.0.0: 2,334 institutions across 43 categories, full-web sentiment monitoring (60+ finance media sources), A-share reports/announcements/research, unified multi-source financial data query (v9 36 + v10 24 = 60+ query types across 9 adapters: akshare / Eastmoney API / yfinance / RSS / Tushare / CoinGecko / ExchangeRate with LRU+TTL cache), human-like browser scraping, crawler dispatcher (CrawlerDispatcher with health-aware source selection + incremental + resume + anti-block protection), web operation enhancement (Shadow DOM / iframe piercing + Cookie Banner auto-dismiss + captcha OCR + human behavior trajectory + WebSocket recorder), MCP Resource (8: media-sources / institutions / query-types / report-templates / cache-index / data-source-health / anti-block-status / crawl-state) + MCP Prompt (10 high-frequency templates), risk metrics and periodic-report interpretation, anti-block hardening (proxy pool / free proxy discovery / behavior profile / header-order randomization / fingerprint-consistent sessions / crawl budget / IP reputation / captcha detection), and post-crawl analytics."
version: 10.0.0
description: |
  中国金融机构数据爬取与分析综合 Skill v10.0.0。2334家/43大类机构名单、60+财经媒体源舆情、
  A股报告/公告/研报、60+种查询9适配器金融数据（akshare/东财/yfinance/RSS/Tushare/CoinGecko/ExchangeRate 自动降级 + 缓存）、
  爬取调度中心（智能选源 + 增量 + 断点续爬）、网页操作增强（Shadow DOM / iframe / Cookie / OCR / 行为 / WS）、
  79 MCP 工具 + 8 Resource + 10 Prompt、类人浏览器、风险分析、定期报告解读。

  🆕 v10.0.0 三轨升级（爬取调度 / 网页操作 / MCP 数据获取）：
    调度：CrawlerDispatcher 4 策略智能选源 + BaseScraper 协议统一 + 增量 + 断点续爬 + 反爬包裹。
    网页：Shadow DOM / iframe 穿透 + Cookie Banner 自动 + 验证码 OCR（stdlib→ddddocr→tesseract）+ 人类行为轨迹 + WebSocket 监听。
    MCP：Tushare / CoinGecko / Alpha Vantage / ExchangeRate 4 适配器 + LRU+TTL 缓存 +
    8 Resource + 10 Prompt。
    v9.0.0（承接）5 适配器 36 查询 + 反爬深度（代理/Header/指纹/节奏）+ UA 池 24。
    v8.0.0（承接）反爬管道 + 数据分析增强（关键词/跨源/趋势/对标/洞察）。

  触发词：爬取机构、舆情爬取、全网舆情、网页爬取、智能爬取、汇总分析、语音交互、公告下载、
  券商研报、批量爬取、定时爬取、文档分析、东方财富、龙虎榜、监管动态、类人爬取、数据回测、
  Shadow DOM、iframe穿透、Cookie弹窗、验证码识别、人类行为、WebSocket监听、数字货币行情、
  外汇汇率、Tushare、CoinGecko、断点续爬、增量爬取、爬取调度、数据源健康。
  结构化数据、期货、宏观经济、港股美股、风险指标、组合复刻、夏普比率、
  多源数据、统一查询、数据源切换、免费代理、代理发现、Header随机化、指纹会话等
  （完整触发词见下方 auto_trigger）。
auto_trigger:
  keywords: [爬取机构, 机构名单, 网页爬取, 产品解析, 公告下载, 券商研报, 研报导出,
    批量爬取, 公司批量, 新闻资讯, 上市公司报告, 机构更新, 金融数据, 文档分析, 整理文档,
    文档对比, 基金分析, 基金净值, 净值查询, 年报, 季报, 半年报, 股票分析, 产品对比, 机构查询,
    定时爬取, 自动爬取, 打包下载, ZIP导出, 压缩摘要, 提取关键信息, 生成报告, 撰写报告,
    研报生成, 研究报告, 图表生成, 报告导出, 文件解析, PPT解析, HTML解析, 金融写作,
    全网舆情, 舆情爬取, 舆情监测, 网络舆情, 爬取舆情, 爬取负面, 爬取正面,
    爬取利空, 利好新闻, 负面新闻, 对话式舆情, 舆情定时, 自定义目标, 增加目标,
    东方财富, 龙虎榜, 北向资金, 监管动态, 监管处罚, 巨潮资讯, 基金净值排行,
    主权基金, 全球金融机构,
    网页归档, 全页抓取, 归档网页, 网页存档, 搜索爬取, 搜索抓取, 搜索引擎搜索,
    数据回测, 回测验证, 确认爬取, 类人爬取, 模拟浏览,
    并发爬取, 加速爬取, 回测过滤, 回测汇总, 样本预览, 输入校验, 风险提示,
    结构化数据, 期货行情, 期货数据, 宏观经济, GDP数据, CPI数据, Shibor, 同业拆借,
    港股行情, 美股行情, 风险指标, 夏普比率, 最大回撤, 组合复刻, 相似基金,
    API挖掘, 接口挖掘, 网络拦截, 操作宏, 宏录制, 宏回放, 宏文件, 文件上传, 文件下载,
    网页拖拽, 富文本输入, 组合键, 并发抓取, 并发池, 名单扩充, 扩充机构, 官网补全,
    补全官网, A股名单, 上市公司名单更新,
    定期报告解读, 财报解读, 年报解读, 半年报解读, 季报解读, 业绩解读, 财报分析,
    业绩分析, 财务解读, 年报分析, 中报解读, 一季报解读, 三季报解读, 财务点评,
    URL去重, 去重爬取, 软拦截, 反爬重试, 熔断限流,
    智能爬取, 多级爬取, 批量智能爬取, 内容识别, 表格识别, 网页识别, 页面识别,
    键值提取, 分页识别, 数字抽取, 汇总分析, 数据汇总, 快照聚合, 机构简报,
    语音交互, 语音爬取, 语音查询, 语音播报, 说话爬取,
    知识库, 知识库同步, 知识库总结, 知识库校对, ima知识库, dify知识库, obsidian,
    代理池, 代理轮换, 反爬增强, 行为画像, 拟人爬取, 阅读停顿, 请求指纹, JA3指纹,
    验证码识别, IP信誉, 爬取预算, 每日预算, 会话预热, 智能退避, 跨源验证, 实体抽取,
    趋势分析, 异常检测, 同业对标, 洞察生成, 时间分桶, 关键词云, 情感趋势, 词云,
    多源数据, 数据源切换, 自动降级, 金融数据查询, 统一查询, 数据路由,
    免费代理, 代理发现, 代理验证, Header随机化, 指纹会话, 请求节奏, 人类化延迟]
  patterns:
    - "(爬取|获取|看下|看看|查)(机构|公司|银行|基金|券商|保险)(的|这|那)?(舆情|新闻|资讯|报道)?"
    - "(爬取|导出|生成)\\s*\\S*(word|excel|docx|xlsx|报告|表格)"
    - "(正面|负面|舆情|利空|利好|网评|新闻|资讯)\\s*(信息|报道|新闻|消息|舆情)"
    - "(指定|设置)?(定时|每天|每周|每月|每小时)?\\s*爬取.{0,8}舆情"
    - "(新增|添加|新建)\\s*(自定义)?\\s*(目标|机构|公司)"
    - "(舆情|新闻)\\s*(导出|生成|报告)"
    - "(东方财富|龙虎榜|北向资金|监管|巨潮资讯|基金净值)"
    - "(查|搜|爬)(全球|海外|国外)\\s*(金融机构|央行|监管|交易所)"
    - "(归档|保存|下载|抓取)\\s*(网页|页面|文章|全文)"
    - "(搜索|查找|搜一下)\\s*.{0,10}(新闻|资讯|舆情|报道|年报)"
    - "(回测|验证|核实)\\s*.{0,5}(数据|内容|信息|新闻)"
    - "(并发|加速|多线程)\\s*.{0,5}(爬|抓)"
    - "(过滤|丢弃|筛选)\\s*.{0,5}(低质量|无效|失真)"
    - "(期货|宏观|港股|美股|Shibor|同业)\\s*(数据|行情|利率|指标)"
    - "(风险指标|夏普|回撤|组合复刻|相似基金)\\s*(分析|计算|推荐)?"
    - "(语音|说话|朗读)\\s*(爬取|查询|交互|播报)?"
    - "(识别|提取|抽取)\\s*.{0,6}(网页|页面|表格|内容|数字)"
    - "(总结|同步|校对|写入)\\s*.{0,8}(知识库|ima|dify|obsidian)"
    - "(代理|IP)\\s*(池|轮换|信誉|退避|被封)"
    - "(验证码|滑块|极验|reCAPTCHA|hCaptcha|被封禁|防封)"
    - "(跨源|交叉验证|多源|事件聚类|情感冲突|置信度)"
    - "(趋势|异常|spike|放量|突变|预测|外推)"
---

# cn-financial-scraper v9.0.0 — 多源金融数据爬取与分析

> **全量机构名单（2334家/43大类）** | **🆕 v9.0 多源 MCP 桥接 + 反爬深度升级** | **36种查询类型自动降级（akshare/东方财富/yfinance/RSS）** | **60+ 商业财经媒体源 + RSS + akshare 兜底** | **智能多级爬取 + 网页内容识别** | **数据分析汇总 + 语音交互**

## ⚡ 一键上手

直接对话即可触发，无需记忆命令：

```
帮我爬一下某上市公司最近7天的舆情
某基金公司最近3天的负面新闻，并导出 Excel
把这篇网页完整归档，包含图片和表格
搜索"贵州茅台2026半年报"然后把结果爬取下来
爬一下银行板块最近3天的舆情并导出 Word
```

**一键启动**（Windows 直接 `python run_sentiment.py` 或）：
```bash
python run_sentiment.py                          # 交互式对话
python run_sentiment.py "贵州茅台最近7天的舆情"     # 直接命令行
```

---

## 🧭 场景速查（想做什么 → 直接入口）

> 无需记忆命令，按「想做什么」直接找到入口。完整 API 与 MCP 工具表见 [README.md](README.md)。

| 你想做什么 | 直接入口 | 依赖 |
|---|---|---|
| 🆕 统一查询金融数据（股票/基金/期货/宏观/港股美股） | `get_financial_data("stock_quote", code="600519")` | 核心 |
| 🆕 查看所有可用数据源状态 | `list_data_sources()` | 核心 |
| 🆕 反爬系统状态报告 | `get_anti_block_status()` | 核心 |
| 🆕 发现免费代理并验证 | `discover_proxies(max_proxies=20)` | 核心 |
| 爬某公司/机构最近 N 天舆情 | `crawl_global_sentiment` 或 `python run_sentiment.py "XX最近7天舆情"` | 核心 |
| 查机构名单 / 机构信息 | `query_institution` / `search_institution` | 核心 |
| 爬单个网页内容 | `scrape_webpage(url)` | 核心 |
| 动态页面 / 类人浏览 / 验证码接管 | `browser_human_fetch(url)`（需 Playwright） | Playwright |
| 搜公告 / 券商研报 / 公司财报 | `search_announcements` | 推荐 |
| 股票 / 基金 / 可转债实时行情 | `get_financial_data("stock_quote", code="600519")` | 核心 |
| 期货 / 宏观(GDP·CPI·PPI·PMI) / Shibor / 港股美股 | `get_financial_data("macro_cpi")` | 核心 |
| 风险指标（年化/波动/回撤/夏普/卡玛） | `analyze_risk_metrics` / `calculate_risk_metrics` | 推荐 |
| 定期报告 / 财报解读 | `interpret_stock_report("600519")` / `interpret_stock` | 核心 |
| 生成研究报告 / 多格式导出 | `generate_research_report` / `quick_report` | 推荐 |
| 批量爬取 + 打包下载 | `CrawlPackager().package_batch_crawl` | 核心 |
| 搜索引擎搜索（中文优先） | `search_web` / `quick_search` | 核心 |
| 网页全页归档 | `quick_archive(url)` | 核心 |
| 扩充机构名单 / 补全官网 / 更新A股名单 | `expand_institution_list` / `UrlCompleter` / `StockListUpdater` | 核心 |
| 批量智能爬取（API→HTTP→浏览器降级） | `batch_smart_crawl(urls)` / `SmartFetcher` | 核心 |
| 网页内容识别（表格/键值/条目/分页/数字） | `smart_extract(html, url)` / `smart_page_extract(url)` | 核心 |
| 舆情快照汇总分析 / 机构简报 / Markdown 报告 | `aggregate_snapshots` / `build_institution_brief` | 核心 |
| 总结进知识库（IMA/Dify/Obsidian/本地）/ 知识库校对 | `python run_knowledge.py` / `sync_to_knowledge_base` / `verify_against_knowledge_base` | 核心 |
| 语音交互（说一句话爬取舆情） | `python run_voice.py` / `VoiceChat` | 核心（Windows） |
| 🆕 代理池轮换 / 故障剔除 / 加权评分 | `ProxyPool(proxies, strategy="weighted")` | 核心 |
| 🆕 免费代理发现与验证 | `discover_proxies(max_proxies=20)` | 核心 |
| 🆕 行为画像（阅读停顿+Referer 链路） | `RequestBehaviorProfile()` | 核心 |
| 🆕 TLS 指纹工厂（curl_cffi/scrapling/stdlib） | `TLSClientFactory.pick()` | 核心 |
| 🆕 Header 顺序随机化（Chrome/Firefox/Safari） | `HeaderOrderRandomizer()` | 核心 |
| 🆕 反指纹一致性会话 | `FingerprintSession()` | 核心 |
| 🆕 人类化请求节奏调度 | `RequestTempoScheduler()` | 核心 |
| 🆕 每日/每小时每域预算 | `CrawlBudgetController(budgets)` | 核心 |
| 🆕 IP 信誉与指数退避 | `IPReputationTracker()` | 核心 |
| 🆕 验证码识别（10 种） | `detect_captcha(html)` | 核心 |
| 🆕 会话预热 / 一站式反爬管道 | `SessionWarmer` / `AntiBlockPipeline` | 核心 |
| 🆕 关键词/实体抽取 + 新词发现 | `extract_keywords(articles)` | 核心 |
| 🆕 跨源交叉验证 + 冲突检测 | `verify_cross_source(articles)` | 核心 |
| 🆕 趋势/异常/外推预测 | `analyze_trend(articles)` | 核心 |
| 🆕 同业对标（百分位/排名/偏离） | `benchmark_against_peers(target, metrics)` | 核心 |
| 🆕 自动洞察生成（风险/机会分级） | `generate_insights(stats, ...)` | 核心 |
| 🆕 一站式增强聚合（含以上所有分析） | `enhanced_aggregate(articles, days=7)` | 核心 |

## 📚 文档导航（找什么 → 去哪里）

| 找什么 | 去哪里 |
|---|---|
| 快速开始 + 场景入口 | 本文件「一键上手」+「场景速查」 |
| 完整功能 / 机构清单 / 媒体源 / MCP 工具表 / 版本历史 | [README.md](README.md) |
| 故障排查（返回空 / 限流 / 依赖缺失 / 成功率低） | [TROUBLESHOOTING.md](TROUBLESHOOTING.md) |
| 安全审计 / 数据源合规 | [SECURITY.md](SECURITY.md) |
| 全部测试 | `python runtests.py`（920+ 个） |

---

## 能力矩阵

| 模块 | 能力 | 依赖层级 | 入口 |
|---|---|---|---|
| **机构名单** | 2301 家金融机构，43 大类，URL 注册表 | 核心 | `query_institution` |
| **全网舆情** | 4 类 60+ 商业财经媒体源 + RSS 直连 + 搜索引擎 + akshare 兜底，情感/严重度分级，模糊去重 | 核心 | `crawl_global_sentiment` |
| **网页爬取** | 六级降级链（Scrapling→Playwright→HTTP），缓存+熔断+重试 | 核心 | `scrape_webpage` |
| **浏览器爬取** | 深度类人操作（阅读停顿/4种滚动模式/贝塞尔鼠标/悬停/多标签/iframe合并）、会话保持、验证码人工接管、proxy、单例复用 | Playwright | `browser_human_fetch` |
| **公告/研报** | 巨潮公告 PDF、券商研报、公司财报 | 推荐 | `search_announcements` |
| **行情/数据** | 股票/基金/可转债/两融/大宗/ETF流/龙虎榜/LPR/国债/北交所 | 核心 | `get_financial_data` |
| 🆕 **多源金融数据桥接** | 36种查询类型统一入口，akshare→东方财富API→新浪→yfinance→RSS→搜索 自动降级，健康追踪 | 核心 | `financial_data_mcp.py` |
| **结构化数据** | 期货/宏观(GDP·CPI·PPI·PMI)/Shibor/港股美股 | akshare | `get_structured_data` |
| **产品分析** | 真实风险指标（年化/波动/回撤/夏普/卡玛）、风格、组合复刻、相似推荐 | 推荐 | `analyze_risk_metrics` |
| **搜索** | 百度/搜狗/DDG/SearXNG 多引擎，中文优先 | 核心 | `search_web` |
| **定期报告解读** | 财报自动解读（业绩概览/同比环比/ROE/毛利率/现金流/亮点/风险/评分评级），纯规则引擎零依赖 | 核心 | `interpret_stock_report` |
| **智能爬取** | 🆕 API→HTTP→浏览器三级降级链、批量并发+去重+成功率统计 | 核心 | `batch_smart_crawl` |
| **内容识别** | 🆕 表格/键值块/文章条目/分页/金融数字抽取、页面类型判别（零依赖） | 核心 | `smart_extract` |
| **汇总分析** | 🆕 快照聚合、模糊去重、情感/来源/时间分布、机构截面、Markdown/JSON 导出 | 核心 | `aggregate_snapshots` |
| **语音交互** | 🆕 语音输入→对话引擎→语音播报，Windows SAPI 零依赖（可选 vosk/pyttsx3 升级） | 核心 | `python run_voice.py` |
| **报告** | 研究报告生成、文档分析、图表、多格式导出（含真实 PDF / HTML 网页版） | 推荐 | `generate_research_report` |
| 🆕 **反爬深度增强** | 代理池 / 免费代理发现 / 行为画像 / TLS 指纹 / Header顺序随机 / 指纹一致性会话 / 请求节奏调度 / 预算控制 / IP 信誉 / 验证码识别 / 会话预热 / 一站式管道 | 核心 | `anti_block_enhanced.py` |
| 🆕 **数据分析深度增强** | 关键词实体抽取 / 跨源验证 / 趋势异常 / 同业对标 / 洞察生成 / 时间分桶 / 一站式聚合 | 核心 | `analysis_enhanced.py` |

> **依赖层级说明**：**核心** = 零 pip 依赖即可用 | **推荐** = `--recommended` 安装后可用（bs4/lxml/docx） | **Playwright** = 需额外 `pip install playwright && playwright install chromium` | **akshare** = 需额外 `pip install akshare`

### ⚠️ 能力边界（重要）

| 类别 | 说明 |
|---|---|
| ✅ **完全支持** | 机构名单查询、基金/ETF/FOF/股票产品解析、A股公告搜索下载、券商研报、新闻资讯、舆情监控、批量爬取（断点续爬）、文档解析（PDF/Word/Excel/PPT/HTML）、报告导出（Word/PPT/Excel）、风险指标分析、结构化市场数据（期货/宏观/Shibor） |
| ❌ **不支持** | 需登录的页面（如微信公众号后台、券商内部系统）、付费墙内容（如 Wind 终端数据）、实时 WebSocket 推送、移动端 APP 内嵌页面、验证码自动破解（需第三方打码服务） |
| ⚠️ **部分支持** | 动态渲染页面（需 Playwright，用 `mode="realtime"`）、反爬极严的网站（如某些银行官网，成功率 30-50%）、大批量爬取（需控并发 ≤5 + 断点续爬）、海外网站（需代理，部分有地域限制） |

**预期成功率**：天天基金 95%+ / 东方财富 90%+ / 同花顺 85%+ / 基金公司官网 70-90% / 银行官网 30-50% / 反爬严格的网站 20-40%。

---

## 安装（三层依赖）

```bash
python setup_env.py                # 仅核心（零 pip 依赖，舆情/HTTP 可用）
python setup_env.py --recommended  # + bs4/lxml/docx/openpyxl（解析+导出）
python setup_env.py --full         # + scrapling/playwright/mcp/akshare（全功能）
```

| 功能 | 需要的依赖 | 安装命令 |
|---|---|---|
| 舆情爬取 / 机构查询 / HTTP 爬取 | 无（核心自带） | `python setup_env.py` |
| PDF/Word/Excel 解析 + 报告导出 | bs4, lxml, python-docx, openpyxl | `python setup_env.py --recommended` |
| 浏览器自动化（动态页面/类人爬取） | playwright | `pip install playwright && playwright install chromium` |
| 结构化数据（期货/宏观/Shibor） | akshare | `pip install akshare` |
| 全球金融数据（美股/港股/ETF/外汇） | yfinance | `pip install yfinance` |
| TLS 指纹模拟（JA3 真实浏览器级） | curl-cffi | `pip install curl-cffi` |
| 全功能 | 全部 | `python setup_env.py --full` |

---

## 🆕 v10.0.0 三轨升级（爬取调度 / 网页操作 / MCP 数据获取）

### 1️⃣ 爬取调度中心（CrawlerDispatcher）

```python
from scripts.crawler_dispatcher import CrawlerDispatcher, quick_dispatch
r = quick_dispatch("https://example.com/news")  # 一键：按健康度选源 + 增量 + 反爬
# 手动：注册 + 调度 + 断点续爬（状态存 data/crawl_state/）
from scripts.crawler_dispatcher import ScraperRegistry, register_default_scrapers, DispatchConfig
reg = ScraperRegistry(); register_default_scrapers(reg)
disp = CrawlerDispatcher(reg, DispatchConfig(strategy=BEST_SCORE))
disp.queue_resume([url1, url2]); disp.run_resume()
```

### 2️⃣ 网页操作增强

```python
from scripts.browser_pro import (
    shadow_pierce, cookie_banner_dismiss,        # Shadow DOM / Cookie Banner
    human_click_path, start_websocket_recorder,  # 人类行为 / WebSocket
    resolve_captcha,                              # OCR（stdlib → ddddocr → tesseract）
)
# 链式穿透 / 弹窗接受 / 行为点击 / WS 监听 / 验证码识别
```

### 3️⃣ MCP 数据获取扩充（Tushare / CoinGecko / 外汇 / 缓存）

```python
from scripts.mcp_data_expansion import (
    CoinGeckoAdapter, ExchangeRateAdapter,    # 无需 key
    TushareAdapter, QueryCache,                # Tushare 需 TUSHARE_TOKEN
)
# 数字货币行情 / 实时外汇 / A 股全维度 / LRU+TTL 跨进程缓存
```

### 4️⃣ MCP Resource + Prompt（8R + 10P）

- **Resource**（`cnfs://<name>`）：media-sources / institutions / query-types / report-templates / cache-index / data-source-health / anti-block-status / crawl-state
- **Prompt**：analyze_institution_sentiment_30d / export_quarterly_report / query_stock_full_view / crawl_url_list / interpret_announcement / search_policy_documents / compare_two_funds / generate_research_report / monitor_page_changes / test_anti_block_effect

---

## v9.0.0 多源 MCP 桥接 + 反爬深度升级（承接）

### 多源金融数据统一查询（自动降级）

```python
from scripts.financial_data_mcp import query_financial_data, list_available_sources

# 统一查询入口 — 自动选择最佳数据源并级联降级
result = query_financial_data("stock_quote", code="600519")
print(result.source, result.data)

result = query_financial_data("macro_cpi")           # 宏观 CPI
result = query_financial_data("fund_nav", code="110011")  # 基金净值
result = query_financial_data("us_stock", symbol="AAPL")  # 美股（走 yfinance）
result = query_financial_data("hk_stock", code="0700")    # 港股
result = query_financial_data("futures")                    # 期货
result = query_financial_data("shibor")                     # Shibor 利率
# 支持 36 种查询类型，9 个数据源适配器
```

### 反爬深度增强（v9.0 新增组件）

```python
from scripts.anti_block_enhanced import (
    FreeProxyDiscovery, HeaderOrderRandomizer,
    FingerprintSession, RequestTempoScheduler,
)

# 免费代理发现 + Header 顺序随机化（Chrome/Firefox/Safari）
# + 反指纹一致性会话（30分钟/100请求自动轮换）
# + 人类化请求节奏（70%快浏览+20%阅读+10%长暂停）
```

### v8.0 数据分析深度增强（承接）

```python
from scripts.analysis_enhanced import (
    extract_keywords, verify_cross_source, analyze_trend,
    benchmark_against_peers, generate_insights,
    aggregate_by_time_bucket, enhanced_aggregate,
)

# 关键词/跨源验证/趋势/对标/洞察/时间分桶/一站式聚合
result = enhanced_aggregate(articles, days=7)
```

## 🆕 v7.7.0 四模块优化速查

- **爬取**（`crawl_enhancer.py`）：`AdaptiveCrawlPolicy` 自适应策略 — 失败早停风控止损、
  连续失败降并发、全域沦陷提前终止、死域快速跳过、耗时统计；`batch_smart_crawl(..., adaptive=True)`
- **语音**（`voice_interface.py`）：知识库语音指令接线 — 「总结到知识库/同步到ima/
  负面总结进dify/总结茅台到知识库/查一下知识库里的XX/用知识库校对」；「命令」播报清单；TTS 数字归一化
- **下载**（`http_utils.py`）：`download_file` Range 206 断点续传(.part) + 已存在跳过 + sha256 校验 +
  min_bytes 拒收 + 原子落盘；`batch_download(urls, concurrency=3)` 并发批量带统计
- **分析**（`analyzer.py`）：`calculate_risk_metrics` 新增 Sortino/胜率/单日最佳最差 + 结果缓存；
  `nav_trend_analysis(nav)` 趋势四档（强上行/缓步上行/震荡/下行）+ 距峰值回撤 + 近期波动比

## 📜 v7.6.0 知识库总结同步（承接）
- `sync_to_knowledge_base(target="ima", mode="overall", requirement=...)` / `verify_against_knowledge_base(articles)`；IMA/Dify/Obsidian/本地适配器

## 📜 v7.5.0 编码修复与爬取强化（承接）
- 六级编码检测链（gb→gb18030）+ download_file 重试/Referer/反爬页校验/SSL 降级

## 📜 v7.3.0 五大增强速查（上一版本）
- 机构名单完善 / 智能多级爬取 / 网页内容识别 / 数据分析汇总 / 语音交互

## 🆕 v7.2.0 爬取硬化速查
```python
from scripts.anti_block_utils import UrlDeduplicator
dedup = UrlDeduplicator("data/seen_urls.json")   # 跨进程持久化去重
if dedup.is_new(url):                            # 首次见到返回 True 并记录
    download_file(url, save_dir="data/downloads")
```

## 🆕 v7.1.0 / v7.0.0 / v6.0.0 新增模块速查
- **v7.1** 定期报告解读 `report_interpreter.interpret_stock_report("600519")`
- **v7.0** 网络拦截/API 挖掘（`discover_api`）+ 宏录制回放 + 异步并发标签池
- **v7.0** 机构名单扩充 / 官网补全 / A股名单（`expand_institution_list` / `UrlCompleter` / `StockListUpdater`）
- **v6.0** 深度类人浏览器 `BrowserScraper.humanlike_fetch()` / 真实 PDF 报告 / zip 批量下载

## 📜 v6.0.0 新增模块速查
- **深度类人浏览器** `BrowserScraper.humanlike_fetch()` — 阅读停顿/悬停/多标签/iframe合并；Cookie 持久化；验证码自动截图
- **真实 PDF 报告** `ComprehensiveExporter.export_all_formats(data, "600519")` — 含 PDF（Playwright 渲染）+ HTML
- **zip 批量下载** `CrawlPackager.package_batch_crawl(...)` — 失败自动重试 2 次 + 增量打包
- **监管资讯** `regulatory_scraper.get_regulatory_updates("all", limit=20)` — 东财/新浪/巨潮
- **正文抽取与 JSON-LD** `web_parser.extract_main_content(html)` — readability 风格

## 📜 v5.0.0 新增模块速查
- **结构化市场数据**（`structured_market_data.py`）— `get_structured_data("shibor"/"futures_spot"/"macro_cpi")` 等，未装 akshare 自动返回空
- **百度/搜狗搜索引擎**（`search_engine.py`）— `quick_search(query, engines=["baidu_html","sogou_html"])` 中文优先
- **浏览器增强** `BrowserScraper.extract_many([...], proxy=..., ad_block=True)` — 进程级单例复用
- **真实风险指标**（`analyzer.py`）— `calculate_risk_metrics(nav)` 计算年化/波动/回撤/夏普/卡玛（≥30 点才计算，不伪造）
- **舆情分类器增强** — 否定词处理、相对时间、严重度统一、模糊去重（标题相似 >0.85）

---

## 关键命令

| 命令 | 用途 |
|---|---|
| `python run_sentiment.py` | 交互式舆情对话 |
| `python run_voice.py` | 语音交互模式（v7.7.0 支持知识库语音指令） |
| `python run_knowledge.py --target local` | 知识库总结同步（v7.6.0） |
| `python runtests.py` | 跑全部测试（v9 958 + v10 153 ≈ 1110 个） |
| `python setup_env.py --full` | 全功能安装 |
| `python mcp_server.py` | 启动 MCP Server（stdio，**79 工具 + 8 Resource + 10 Prompt**） |
| `python scripts/scrapable_registry.py stat` | 机构名单统计 |
| `python scripts/structured_market_data.py` | 结构化数据自检 |

---

## 故障排查速查

| 症状 | 原因 | 解决 |
|---|---|---|
| cls/sina/jisilu/wallstreetcn 返回空 | 接口被封 | v5.0 已接线 akshare 自动兜底，无需手动处理 |
| 主站返回 200 但内容是验证码页 | 软封禁 | 自动检测并切浏览器兜底；`DomainRateLimiter` 按域限速 |
| 中文搜索召回差 | 默认引擎不合适 | 百度/搜狗优先（`baidu_html`/`sogou_html`） |
| 舆情抓取慢 | 每源冷启动 | v5.0 浏览器单例复用；`parallel_workers=4` 并发 |
| 行情/新闻请求被限流 | 频率过高 | 全部请求已统一走自适应限流（`RatelimitedSession`） |
| `ModuleNotFoundError: playwright` | 未装浏览器依赖 | `pip install playwright && playwright install chromium` |
| akshare 返回空 | 未装 akshare | `pip install akshare` |
| 更多 | — | [TROUBLESHOOTING.md](TROUBLESHOOTING.md) |

---

## ❓ 常见问题（FAQ）

### Q1: 舆情爬取返回空怎么办？
**A**: 1）检查目标名称是否正确（用 `list_sentiment_targets` 查看）；2）尝试扩大时间范围（`days=7`）；3）增加媒体源类别（`source_categories=["authoritative", "financial_vertical", "self_media"]`）。

### Q2: 结构化数据（期货/宏观）返回 None？
**A**: 需要安装 akshare：`pip install akshare`。未安装时函数自动返回 None，不会报错。

### Q3: 动态渲染页面（SPA）爬不到内容？
**A**: 默认 `mode="static"` 只走 HTTP。SPA 页面需用 `mode="realtime"`（需 Playwright）：
```python
result = scrape_webpage(url="...", mode="realtime")
```

### Q4: 爬取银行官网成功率很低？
**A**: 银行官网普遍反爬严格（验证码/IP 封禁），预期成功率 30-50%。建议：1）用 `browser_human_fetch` 走浏览器；2）加 proxy 轮换；3）降低频率。

### Q5: 如何自定义舆情监控目标？
**A**: 两种方式：
```python
# 方式 1：对话式
chat_handle("新增自定义目标：恒生电子")

# 方式 2：API
add_custom_sentiment_target("custom", "恒生电子")
```

### Q6: pip 安装依赖很慢怎么办？
**A**: 使用国内镜像：
```bash
pip install -i https://pypi.tuna.tsinghua.edu.cn/simple -r requirements.txt
# 或永久设置
pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple
```

> 📘 更多故障排查见 [TROUBLESHOOTING.md](TROUBLESHOOTING.md) | 🔒 安全审计见 [SECURITY.md](SECURITY.md)

---

## 详细文档

完整功能说明、机构清单、媒体源/目标库、MCP 工具表（71 个）、实战场景、版本历史，见 [README.md](README.md)。
