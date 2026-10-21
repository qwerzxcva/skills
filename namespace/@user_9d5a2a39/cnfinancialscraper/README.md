# cn-financial-scraper v10.0.0

> 中国大陆金融数据爬取与分析综合工具 v10.0.0 — 2334 家机构 / 43 大类 / 60+ 商业财经媒体源 / **79 MCP 工具 + 8 Resource + 10 Prompt**
> 🆕 v10.0.0 三轨升级（爬取调度 / 网页操作 / MCP 数据获取）

## ⚡ 快速上手（30 秒开始）

```bash
# 安装（自动使用国内镜像）
python setup_env.py --recommended

# 交互式对话（推荐）
python run_sentiment.py

# 命令行直接用
python run_sentiment.py "贵州茅台最近7天的舆情"
python run_sentiment.py "工银瑞信基金最近3天的负面新闻" --export excel
```

**Windows 用户**：`python run_sentiment.py` 一键启动（交互式对话）。

```python
# Python API
from scripts import parse_financial_product
result = parse_financial_product("https://fund.eastmoney.com/000001.html", "fund")
print(f"基金名称: {result['product_name']}")
```

---

## 🆕 v8.0.0 反爬深度增强 + 数据分析深度增强

针对"爬虫容易被识别封禁 IP"与"爬到的内容堆在一起无法直接用"两个老问题，
v8.0.0 推出两个新模块：`scripts/anti_block_enhanced.py` 与 `scripts/analysis_enhanced.py`。

### A. 反爬深度增强（`scripts/anti_block_enhanced.py`）

| 组件 | 关键能力 |
|------|---------|
| **ProxyPool 代理池** | 多代理轮换（轮询/加权随机/三种策略）+ 健康评分（成功率+延迟+连失惩罚）+ 故障自动剔除 + 手动批量恢复 + 可选持久化 |
| **RequestBehaviorProfile 行为画像** | 模拟人类阅读停顿（1.5-6s 随机 + 8% 长停顿 15-45s + 鼠标节律抖动）+ Referer 链路（搜索引擎/同域/上次页 三态分布）|
| **TLSClientFactory TLS 指纹工厂** | 按依赖优先级 curl_cffi → scrapling → stdlib 自动选最优（最佳 JA3 模拟）|
| **CrawlBudgetController 预算控制** | 每日/每小时每域请求预算，到达自动暂停并返回 `wait_seconds_until_available`，窗口结束自动续期 |
| **IPReputationTracker IP 信誉** | 按代理/出口维度记录成功率；连续失败指数退避（带 ±30% 抖动），而非固定冷却 |
| **CaptchaDetector 验证码识别** | 识别 reCAPTCHA / hCaptcha / GeeTest / 易盾 / 阿里云滑块 / 腾讯防水墙 / 同盾 / 短信验证 / 2FA 等 10 种 |
| **SessionWarmer 会话预热** | 首次访问目标域前先访问首页/列表页建立可信 Cookie 与 Referer（30 分钟 TTL）|
| **AntiBlockPipeline 一站式** | `before_request` / `after_request` 一行接线 8 个能力，决策信息含 `proxy / delay / referer / warm_ok / budget_ok` |

```python
from scripts.anti_block_enhanced import (
    ProxyPool, RequestBehaviorProfile, CrawlBudgetController,
    IPReputationTracker, CaptchaDetector, SessionWarmer,
    AntiBlockPipeline, TLSClientFactory,
)

# 代理池（多代理轮换 + 加权评分 + 故障自动剔除）
pool = ProxyPool(["http://1.1.1.1:8080", "socks5://2.2.2.2:1080"],
                 file_path="data/proxies.json", strategy="weighted")
proxy = pool.pick()
try:
    resp = http_get(url, proxy=proxy, timeout=30)
    pool.report(proxy, success=True, latency_ms=120)
except Exception as e:
    pool.report(proxy, success=False, error=str(e))

# 行为画像（模拟阅读停顿 + Referer 链路）
beh = RequestBehaviorProfile()
delay = beh.next_delay()                          # 1.5-6s 随机 + 长停顿概率 8%
referer = beh.next_referer(url, query="贵州茅台")    # 来自搜索引擎/同域/上次页

# TLS 指纹工厂（按依赖自动选最优）
name, get_fn = TLSClientFactory.pick()             # curl_cffi > scrapling > stdlib

# 预算控制（每日/每小时每域）
budget = CrawlBudgetController({
    "cls.cn":     {"daily": 5000, "hourly": 500},
    "jisilu.cn":  {"daily": 1000, "hourly": 100},
    "default":    {"daily": 10000, "hourly": 1500},
})
if budget.allow("cls.cn"):
    make_request(); budget.consume("cls.cn")
else:
    time.sleep(budget.wait_seconds_until_available("cls.cn"))

# IP 信誉（指数退避 + 抖动）
ip = IPReputationTracker(file_path="data/ip_rep.json", base_backoff=30, max_backoff=1800)
if not ip.allow("proxy-A"):
    time.sleep(ip.wait_seconds("proxy-A"))

# 验证码识别
html = http_get(url).text
if (sig := detect_captcha(html)):
    log.warning(f"检测到 {sig.kind}: {sig.advice}")

# 会话预热（首次访问前先建可信 Cookie / Referer）
SessionWarmer().warm(url, fetcher=lambda u: http_get(u))

# 一站式管道（推荐）
pipeline = AntiBlockPipeline(proxies=[...], budgets={...})
decision = pipeline.before_request(url)
# ... 用 decision["proxy"] + decision["delay"] + decision["referer"] 发起请求 ...
result = pipeline.after_request(decision, resp, elapsed_ms=120)
print(pipeline.status())   # 全部子模块状态
```

### B. 数据分析深度增强（`scripts/analysis_enhanced.py`）

| 组件 | 关键能力 |
|------|---------|
| **KeywordExtractor 关键词与实体** | 中文 2-gram/3-gram 滑动窗口；抽取 A 股代码 / 基金代码 / 金额 / 百分比；凝固度算法自动发现新词 |
| **CrossSourceVerifier 跨源验证** | 编辑距离 + Jaccard 混合相似度聚类事件；可信度（多源 × 权威度 × 频次）；冲突检测（不同来源情感不一致）|
| **TrendAnalyzer 趋势与异常** | 时间桶（hour/day/week）；移动平均；WoW 周环比；z-score 异常检测；线性外推预测；定性标签（上升/下降/平稳）|
| **PeerBenchmark 同业对标** | 按 group_key 分组；百分位排名；均值/中位数对比；偏离度（百分比偏离）；同维度排名 |
| **InsightGenerator 洞察生成** | 把统计/趋势/验证/关键词综合成可读洞察；按 risk > warn > opportunity > info 分级排序；每条含证据链 |
| **TimeBucketAggregator 时间分桶** | 按任意粒度聚合任意字段（含 sentiment_split），用于绘制热力图与堆叠图 |
| **enhanced_aggregate 一站式** | 一次调用得到全部分析结果（与 `data_aggregator.aggregate_snapshots` 平级）|

```python
from scripts.analysis_enhanced import (
    extract_keywords, verify_cross_source, analyze_trend,
    benchmark_against_peers, generate_insights,
    aggregate_by_time_bucket, enhanced_aggregate,
)

# 关键词与实体
kw = extract_keywords(articles)
print("热门股票:", kw.stock_codes[:5])
print("高频金额:", kw.amounts[:3])
print("新词:", kw.new_words[:5])

# 跨源交叉验证
events = verify_cross_source(articles, similarity_threshold=0.55)
for ev in events[:5]:
    print(f"{ev.title_canonical} ({ev.mention_count} 次, {len(ev.sources)} 源, "
          f"置信度 {ev.confidence}, {'冲突' if ev.conflict else '一致'})")

# 趋势与异常
trend = analyze_trend(articles, granularity="day", ma_window=7)
print(f"趋势: {trend.trend_label}（峰值 {trend.peak_bucket}={trend.peak_value}）")
print(f"异常: {trend.anomalies}")
print(f"预测: {trend.forecast}")

# 同业对标
peer = benchmark_against_peers(
    "贵州茅台",
    metrics_by_target={
        "贵州茅台": {"annual_return": 0.25, "volatility": 0.15, "max_drawdown": -0.12},
        "五粮液":   {"annual_return": 0.18, "volatility": 0.18, "max_drawdown": -0.15},
        "泸州老窖": {"annual_return": 0.22, "volatility": 0.16, "max_drawdown": -0.13},
    },
    group_key="白酒",
)
print(peer.percentile, peer.rank)

# 洞察生成
insights = generate_insights(
    stats, trend=trend, verified=events, keywords=kw, top_n=8)
for i in insights:
    print(f"[{i.level}] {i.title} — {i.detail}")

# 一站式聚合
result = enhanced_aggregate(articles, days=7)
# → {"statistics", "keywords", "verified_events", "trend",
#    "by_time_bucket", "insights"}
```

### v8.0 与既有能力的协同

| 已有能力 | v8.0 增强点 |
|---------|-------------|
| `domain_rate_limiter`（域级限速） | `CrawlBudgetController` 增加"每日上限"维度，跨域统一管理 |
| `block_detector`（软拦截文本检测） | `CaptchaDetector` 识别具体验证码种类并给出建议 |
| `domain_health_tracker`（域健康度） | `IPReputationTracker` 在 IP/出口维度跟踪，指数退避抖动 |
| `url_deduplicator`（URL 去重） | 无变化；可与 ProxyPool 一起持久化 |
| `tls_fingerprint_client`（JA3 单客户端） | `TLSClientFactory` 自动按依赖优先级选最优客户端 |
| `data_aggregator`（基础聚合） | `analysis_enhanced.enhanced_aggregate` 一站式增强聚合 |
| `analyzer.calculate_risk_metrics` | 无变化；与 `TrendAnalyzer` 并存，分别做基金风险与舆情趋势 |

### 测试

- `tests/test_v800_anti_block_enhanced.py` — 70+ 用例（ProxyPool/Behavior/Budget/IP/Captcha/Warmer/Pipeline）
- `tests/test_v800_analysis_enhanced.py` — 35+ 用例（Keyword/Verifier/Trend/Peer/Insight/Bucket）
- 全部离线、纯函数/monkeypatch、不发网络请求；运行 `python runtests.py` 验证

---

## 🆕 v7.7.0 新增：四模块全面优化（爬取 / 语音 / 下载 / 分析）

| 特性 | 说明 | 模块 |
|------|------|------|
| **自适应爬取** | `AdaptiveCrawlPolicy`：失败早停风控止损 / 连续失败降并发 / 全域沦陷提前终止 / 死域快速跳过 / 耗时统计；`batch_smart_crawl(..., adaptive=True)` | `crawl_enhancer.py` |
| **知识库语音指令** | 「总结到知识库 / 同步到 ima / 负面总结进 dify / 总结茅台到知识库 / 查一下知识库里的XX / 用知识库校对」语音直达；「命令」播报清单；TTS 数字归一化 | `voice_interface.py` |
| **下载断点续传** | `download_file`：Range 206 续传（.part 残文件）、已存在跳过、sha256 校验、min_bytes 拒收、原子落盘 | `http_utils.py` |
| **批量下载** | `batch_download(urls, concurrency=3)` 并发批量带统计（ok/failed/elapsed），单个失败不阻断 | `http_utils.py` |
| **分析指标扩展** | `calculate_risk_metrics` 新增 Sortino / 胜率 / 单日最佳最差 + 结果缓存（同序列重复计算命中） | `analyzer.py` |
| **趋势分析** | `nav_trend_analysis(nav)`：区间收益 / 回归斜率年化 / 距峰值回撤 / 近期波动比 → 强上行/缓步上行/震荡/下行四档 | `analyzer.py` |

```python
from scripts import batch_smart_crawl, batch_download, nav_trend_analysis
from scripts.http_utils import download_file

stats = batch_smart_crawl(urls, concurrency=4, adaptive=True)["stats"]     # 早停/降级/耗时
download_file(url, save_dir="data", expect_sha256=digest, min_bytes=1024)  # 续传 + 校验
batch_download(pdf_urls, save_dir="data/ann", concurrency=3)               # 并发批量
trend = nav_trend_analysis(nav_series)   # {"trend": "强上行", "off_peak": 0.0, ...}
```

---

<details>
<summary>📜 v7.6.0 知识库总结同步与校对（`knowledge_sync.py` / `run_knowledge.py`）</summary>

把爬取/汇总的数据**按需求总结**进主流知识库，并可从知识库**反向校对**爬取结果。

| 特性 | 说明 | 模块 |
|------|------|------|
| **按需总结** | `summarize_to_notes(mode=overall/target/negative, requirement=...)` 聚合→去重→统计→Markdown 笔记（含 frontmatter/来源链接） | `knowledge_sync.py` |
| **IMA 适配** | OpenAPI：创建笔记（import_doc）→关联知识库（add_knowledge）→检索（search_knowledge） | `ImaAdapter` |
| **Dify 适配** | Knowledge API：自动定位/创建 dataset、create-by-text 写入、同名文档 update-by-text、retrieve 语义检索 | `DifyAdapter` |
| **Obsidian 适配** | 直写 Vault 目录 Markdown + YAML frontmatter（Obsidian 自动索引） | `ObsidianAdapter` |
| **本地兜底** | `data/knowledge_base/` + `_index.json`，无凭证即可用；同内容摘要幂等跳过 | `LocalKnowledgeAdapter` |
| **知识库校对** | 检索→标题相似匹配→「标签+数字」事实比对，输出 verified / conflict / no_match | `verify_against_knowledge_base` |
| **同步日志** | 每次推送写入 `data/knowledge_sync_log.json`（保留最近 200 条） | `sync_to_knowledge_base` |

```python
from scripts import sync_to_knowledge_base, verify_against_knowledge_base, get_adapter

# 按需求总结并推送到 IMA（凭证：IMA_OPENAPI_CLIENTID / IMA_OPENAPI_APIKEY 或 ~/.config/ima/）
sync_to_knowledge_base(target="ima", mode="overall", requirement="重点关注处罚与业绩")
# 从知识库反向校对爬取数据（数字/事实冲突检测）
verify_against_knowledge_base(articles, adapter=get_adapter("dify"))   # DIFY_API_KEY
```

```bash
python run_knowledge.py --target local --mode overall          # 本地兜底库同步
python run_knowledge.py --target obsidian --mode target --target-name 招商银行 \
    --requirement "重点关注处罚与业绩" --output preview.md      # 仅预览不推送
python run_knowledge.py --verify data/crawled.json --target dify  # 校对
python run_knowledge.py --search "招商银行 处罚" --target local   # 检索
```

</details>

---

<details>
<summary>📜 v7.5.0 编码修复与爬取强化</summary>

| 特性 | 说明 | 模块 |
|------|------|------|
| **编码修复** | 六级编码检测链（BOM→域名记忆→Content-Type 归一化+严格验证→meta charset 字节级→chardet→中文启发式）；gb2312/gbk 统一 gb18030；声明编码不符自动纠错；GBK JSON API 兼容 | `http_utils.py` |
| **下载加固** | 走多策略重试链 + 同源 Referer 注入 + GBK Content-Disposition 文件名乱码修复 + 反爬 HTML 页不落盘为文档 + 文本文件自动转码 UTF-8 | `http_utils.py` `announcement_scraper.py` |
| **爬取强化** | SSL 证书失败自动 https→http 降级重试；200 空响应自动重试；域名编码记忆复用 | `http_utils.py` |
| **机构名单扩充** | 2301 → 2334 家；6 类精选名录 +33 家（支付/券商资管/地方 AMC/互联网小贷/基金销售/征信）；修复 `load_curated` 路径回归；无 requests 环境公告下载标准库兜底 | `institution_expander.py` `data/curated.json` |

```python
from scripts.http_utils import http_get, download_file
# 下载加固：重试链 + Referer + 反爬校验 + 文本转码，乱码/失败双修复
download_file(url, save_dir="data/downloads")
```

</details>

---

<details>
<summary>📜 v7.3.0 五大增强（上一版本）</summary>


| 特性 | 说明 | 模块 |
|------|------|------|
| **机构名单完善** | 2270 → 2301 家 / 33 → 43 大类；新增 11 类持牌名录（地方 AMC/支付/评级/征信商查/相互保险/养老金/券商资管/金融基础设施/互联网小贷/证券咨询/第三方销售），同时清理历史重复行；修复扩充引擎边迭代边删除的潜在缺陷 | `institution_expander.py` `data/curated.json` |
| **智能多级爬取** | `SmartFetcher` 三级降级链（API 直连→HTTP→浏览器兜底）+ 软拦截自动识别；`batch_smart_crawl` 批量并发 + 持久化去重 + 成功率/分域统计 | `crawl_enhancer.py` |
| **网页内容识别** | 零依赖识别引擎：表格/键值块/文章条目/分页/金融数字抽取 + 页面类型判别（list/data/article/home）+ `smart_extract` 一站式；`browser_pro.smart_page_extract` 浏览器接线 | `web_recognizer.py` `browser_pro.py` |
| **数据分析汇总** | 快照聚合 + 模糊去重（Jaccard×包含度）+ 情感/来源/时间分布 + 机构截面 + 机构简报 + Markdown/JSON 导出 | `data_aggregator.py` |
| **语音交互** | 说一句话→语音识别→舆情引擎→语音播报；Windows SAPI 零依赖（PowerShell 5.1），可选 vosk/pyttsx3 升级；STT 不可用自动降级文本输入 | `voice_interface.py` `run_voice.py` |
| **MCP 工具 64→67** | `smart_crawl_batch` / `recognize_webpage` / `aggregate_sentiment` | `mcp_server.py` |

```bash
python run_voice.py                        # 语音交互模式（v7.3.0）
```
```python
from scripts.crawl_enhancer import batch_smart_crawl      # 智能批量爬取
from scripts.web_recognizer import smart_extract          # 网页内容识别
from scripts.data_aggregator import aggregate_snapshots, export_markdown  # 汇总分析
```

</details>

---

<details>
<summary>📜 v7.2.0 爬取硬化与 bug 修复（上一版本）</summary>


| 特性 | 说明 | 模块 |
|------|------|------|
| **软拦截检测接线** | 200 反爬页（验证码/访问被拒等短 HTML）自动识别为失败并多策略重试，避免脏数据入库 | `http_utils.py` `anti_block_utils.py` |
| **Retry-After 遵从** | 429/503 重试等待优先取服务端 Retry-After 声明（限幅 60s） | `http_utils.py` |
| **URL 去重器** | 批量爬取去重：归一化（host 小写/默认端口/fragment/尾斜杠）+ 跨进程 JSON 持久化 + 按域名统计 | `anti_block_utils.py` `UrlDeduplicator` |
| **7 处 bug 修复** | 空 POST 退化为 GET；download_file 保存 4xx/5xx 错误页；HTTPError url property 冲突致 raise_for_status 崩溃；熔断 sleep 持全局锁阻塞其他域名；裸域名 reset 失效；过期 cookie 误保留 | 同上 |

</details>

---

## 🆕 v7.1.0 新增：定期报告分析解读

| 特性 | 说明 | 模块 |
|------|------|------|
| **财报自动解读** | 自动拉取东财 RPT_LICO_FN_CPD 财务数据（含同比/环比增速字段），规则引擎生成自然语言解读：业绩概览、盈利能力（ROE/毛利率）、现金流质量、✅亮点信号、⚠️风险提示、综合评分(0-100)与评级 | `report_interpreter.py` |
| **多路输入** | `interpret_stock`（股票代码直连）/ `interpret_data`（任意财务 dict，中英文字段兼容）/ 离线多期序列 | 同上 |
| **纯规则零依赖** | 阈值引擎 + 模板评语，无 LLM 依赖、无 pip 依赖，可嵌入批量巡检 | 同上 |
| **MCP 工具** | `interpret_financial_report`（64 个工具） | `mcp_server.py` |

<details>
<summary>📜 v7.0.0 核心升级（上一版本）</summary>

## v7.0.0 核心升级（上一版本）

| 特性 | 说明 | 模块 |
|------|------|------|
| **机构名单完成** | 1330 → 2270 家 / 33 大类；live 名录直连（基金 167/期货 181）+ 精选数据 + list 文件反向吸收；新增民营银行 19、外资法人银行 41、AMC 5、村镇银行 60、保险经纪 48、保险公估 36 等类型；名单数字口径与实际数据一致 | `institution_expander.py` `data/curated.json` |
| **网络拦截 / API 挖掘** | 监听页面 XHR/fetch，自动捕获背后 JSON 接口 + 分页规律 → `data/api_registry.json` 去重累积，接口可 HTTP 直连复用 | `browser_pro.py` `discover_api` |
| **操作宏** | JSON 操作序列录制（注入 JS 捕获真实交互）与 {{参数}} 回放；goto/click/fill/upload/download/drag/extract 等 15+ 动作 | `browser_pro.py` `MacroPlayer` |
| **文件上传/下载/拖拽** | set_input_files / expect_download 落盘 / 类人拖拽 / contenteditable 富文本 / 键盘组合键 | `browser_pro.py` |
| **异步并发标签池** | async_playwright + semaphore 多页并发批量抓取，sync 模式不变 | `browser_pro.py` `AsyncBrowserPool` |
| **gzip 自动解压** | urllib 响应自动解压 gzip/deflate/br（此前压缩流导致 json() 乱码） | `http_utils.py` |
| **A股名单双源容灾** | 东财 push2 多镜像轮换 + 新浪 Market_Center 兜底，5542 只入库（含北交所 335） | `stock_list_updater.py` |
| **宏观零依赖直连** | CPI/PPI/PMI/GDP/M2 纯 HTTP 序列（akshare 缺失也可用），消除"新浪宏观待上线" | `market_data_scraper.py` |
| **官网批量补全** | 多引擎搜索 + 可达性验证回填 URL，聚合域/政务域过滤，断点续跑 | `url_completer.py` |
| **MCP 工具 55→63** | discover_api / play_macro / browser_upload / browser_download / async_batch_fetch / expand_institutions / complete_institution_urls / update_stock_list | `mcp_server.py` |

</details>

<details>
<summary>📜 v6.0.0 核心升级（上一版本）</summary>

## 🆕 v6.0.0 核心升级

| 特性 | 说明 | 模块 |
|------|------|------|
| **数据源商业化** | 监管资讯改由东财/新浪/巨潮商业 API 提供；移除政府网站与官方媒体源（含 gov.cn 域名全项目清除） | `regulatory_scraper.py` `scrapable_registry.py` |
| **媒体源扩充** | 新增和讯/金融界/凤凰财经/汇通/英为财情/智通/界面/蓝鲸/富途/阿思达克/上海有色等 12 家商业财经媒体 | `data/sentiment_sources.json` |
| **浏览器深度类人化** | 阅读停顿(2-8s) / 4 种滚动模式 / iframe 合并 / 会话保持 / 验证码人工接管 / 随机悬停 / 多标签切换 / 粘贴式输入 / 崩溃自愈 | `browser_scraper.py` |
| **反爬升级** | 封禁特征词库 20+ 中文/英文文案；UA 池与 Sec-CH-UA 更新至 Chrome 133 | `anti_block_utils.py` `http_utils.py` |
| **解析智能** | readability 风格正文抽取 `extract_main_content`；JSON-LD 文章类型；选择器缓存置信度衰减重学 | `web_parser.py` |
| **真实 PDF 导出** | Playwright 渲染 HTML → 真实 PDF（修复此前"仅提示手动转换"）；新增 HTML 网页版报告 | `report_exporter.py` |
| **zip 批量下载增强** | 并行爬取 / 进度回调 / 失败重试清单 failed.json / 增量去重打包 `package_incremental` | `crawl_packager.py` |
| **测试** | 脱敏回归断言（gov.cn 零残留）+ 新增浏览器/导出/zip 测试 | `tests/` |

</details>

<details>
<summary>📜 历史版本更新（v4.0 ~ v5.0）</summary>

### v5.0 — 媒体源扩充与结构化数据
- 媒体源 48 → 81 站点（后 v6.0 调整为 60+ 商业源）；结构化数据（期货/宏观/Shibor/港股美股）；浏览器 proxy/并发标签页；真实风险指标；新 MCP 工具 51→55

### v4.9 — 应对数据源被封
- akshare 兜底适配器 + RSS 数据源 + 反爬增强工具集（域限速/Cookie/错误码/TLS指纹/指数退避）

### v4.7 — 8类数据 + 对比回测
- 新增两融余额/大宗交易/ETF资金流/龙虎榜席位/股东增减持/LPR/国债收益率曲线/北交所
- 同类数据横向对比与回测（4 维质量评分）+ 监管政策文件下载 + 浏览器类人爬取加固

### v4.3 — 全网舆情爬虫（对话式）
- 对话式 NLU 入口 + 4 类 60+ 商业财经媒体源 + 11 类目标机构 + 情感分类 + 多格式导出 + 定时任务

### v4.2 — 浏览器自动化
- Playwright 集成 + STEALTH_JS 反检测 + 类人操作

### v4.1 — 海外机构 + 术语翻译
- 9 大类 210 家全球金融机构 + 600+ 金融术语词典 + 腾讯云 TMT 翻译

### v4.0 — 定时/打包/压缩/报告
- 定期自动爬取 + 批量 ZIP + 内容智能压缩 + 增强文件解析 + 金融写作引擎 + 6 套报告模板 + 研究报告全流程生成

</details>

## 安装（三层依赖，按需选择）

```bash
python setup_env.py                # 核心层（零 pip 依赖，舆情/HTTP 可用）
python setup_env.py --recommended  # 推荐层 + bs4/lxml/docx/openpyxl（解析+导出）
python setup_env.py --full         # 全功能 + scrapling/playwright/mcp/akshare
```

| 你想做什么 | 需要的依赖层级 | 安装命令 |
|---|---|---|
| 舆情监控、机构查询、HTTP 爬取、行情数据 | 核心层 | `python setup_env.py` |
| PDF/Word/Excel 解析、报告导出 | 推荐层 | `python setup_env.py --recommended` |
| 动态页面爬取、浏览器自动化、类人操作 | Playwright | `pip install playwright && playwright install chromium` |
| 期货/宏观/Shibor/港股美股结构化数据 | akshare | `pip install akshare` |
| 全部功能 | 全功能 | `python setup_env.py --full` |

### 安装验证

```bash
python -c "from scripts import search_institution; print('安装成功！')"
```

## MCP 工具

通过 MCP 协议暴露 **67 个工具**，可直接在 Claude Code 中调用：

| 工具 | 功能 |
|------|------|
| `query_institution` | 查询机构名单（按类型/关键词） |
| `smart_crawl_batch` | 🆕 智能批量爬取（API→HTTP→浏览器降级 + 去重 + 成功率统计） |
| `recognize_webpage` | 🆕 网页内容识别（表格/键值/条目/分页/数字/页面类型） |
| `aggregate_sentiment` | 🆕 舆情快照汇总分析（去重/统计/截面，可导出 Markdown） |
| `discover_api` | 🆕 网络拦截挖掘页面背后 JSON 接口（含分页规律） |
| `play_macro` | 🆕 回放网页操作宏（{{参数}} 替换） |
| `browser_upload` | 🆕 文件上传（选择器+提交） |
| `browser_download` | 🆕 文件下载落盘到 data/downloads/ |
| `async_batch_fetch` | 🆕 异步并发批量抓取（多标签页池） |
| `expand_institutions` | 🆕 机构名单扩充（live+精选+list 三路合并） |
| `complete_institution_urls` | 🆕 机构官网批量补全（断点续跑） |
| `update_stock_list` | 🆕 A股全量名单更新（双源容灾） |
| `interpret_financial_report` | 🆕 定期报告分析解读（业绩/盈利/现金流/亮点/风险/评分评级） |
| `scrape_webpage` | 爬取指定 URL |
| `scrape_institution` | 按机构名爬取官网 |
| `parse_financial_product` | 解析基金/ETF/股票/债券页面 |
| `crawl_financial_news` | 最新金融新闻 |
| `search_announcements` | 搜索公告 |
| `download_announcement` | 下载公告 PDF |
| `query_broker_reports` | 券商研报查询 |
| `get_company_reports` | 上市公司综合报告 |
| `parse_document` | PDF/Word/Excel 解析 |
| `export_stock_report` | 导出 PPT/PDF/Word/Excel |
| `batch_crawl_institutions` | 批量爬取机构 |
| `search_report_index` | 全量报告索引搜索 |
| `analyze_document` | 深度分析金融文档 |
| `organize_documents` | 批量整理文档目录 |
| `compare_documents` | 多文档并排对比 |
| `get_stock_realtime` | A 股实时行情 |
| `get_fund_nav_history` | 基金历史净值 |
| `crawl_cls_telegraph` | 财联社 7x24 电报 |
| `get_convertible_bond_data` | 可转债数据 |
| 🆕 `schedule_crawl_task` | 创建定期自动爬取任务 (v4.3 扩展支持 `crawl_sentiment` / `crawl_sentiment_export`) |
| 🆕 `list_scheduled_tasks` | 查看所有定时任务及状态 |
| 🆕 `cancel_scheduled_task` | 取消/暂停/恢复定时任务 |
| 🆕 `batch_crawl_and_package` | 批量爬取+自动打包 ZIP |
| 🆕 `compress_crawl_results` | 分析压缩爬取结果为 2-3 页摘要 |
| 🆕 `parse_file_enhanced` | 增强文件解析（PPT/HTML/Markdown） |
| 🆕 `analyze_file_deep` | 深度文件分析（主题/财务/风险） |
| 🆕 `generate_research_report` | 生成图文并茂的研究报告 |
| 🆕 `export_research_report` | 导出报告为 Word/PPT/HTML/PDF |
| 🆕 `quick_crawl_summary` | 一键快速爬取+压缩摘要 |
| 🆕 `crawl_global_sentiment` | **v4.3** 一键全网舆情爬取（单/多机构 + 多媒体 + 情感筛选） |
| 🆕 `export_sentiment_report` | **v4.3** 导出舆情快照为 Word/Excel/CSV/JSON |
| 🆕 `list_sentiment_targets` | **v4.3** 查看 12 大类目标机构库 |
| 🆕 `list_sentiment_sources` | **v4.3** 查看媒体源（4 类商业财经媒体） |
| 🆕 `add_sentiment_target` | **v4.3** 新增自定义舆情目标 |
| 🆕 `analyze_risk_metrics` | **v5.0** 真实风险指标分析（年化/波动/回撤/夏普/卡玛） |
| 🆕 `analyze_product` | **v5.0** 产品综合分析（风格/组合复刻/相似推荐） |
| 🆕 `analyze_portfolio_replication` | **v5.0** 组合复刻分析 |
| 🆕 `get_structured_data` | **v5.0** 结构化市场数据（期货/宏观/Shibor/港股美股） |

## 项目结构

### 核心模块（必装）

```
cn-financial-scraper/
├── SKILL.md                      # Skill 完整说明（含FAQ和场景演示）
├── README.md                     # 本文件
├── setup_env.py                  # 一键安装脚本
├── mcp_server.py                 # MCP 服务器（67 个工具）
├── requirements.txt              # Python 依赖
├── _meta.json                    # 元数据
│
├── scripts/                      # 核心脚本
│   ├── __init__.py              # 包初始化
│   ├── http_utils.py            # HTTP 公共基础设施（限流/重试/缓存）
│   ├── scraper.py               # 基础爬虫（三级降级+自动重试）
│   ├── web_parser.py            # 网页解析（基金/ETF/FOF/股票）
│   ├── institution_scraper.py   # 机构爬虫
│   ├── announcement_scraper.py  # 公告爬取
│   └── data_validator.py        # 数据完整性验证
│
└── data/                         # 数据文件
    ├── institution_registry.json # 2301 家机构注册表（43 大类）
    └── *_list.json              # 各类机构名单（43类）
```

### 扩展模块（按需使用）

```
scripts/
├── research_report_scraper.py    # 券商研报（评级/分析师/目标价）
├── comprehensive_report_scraper.py # 综合报告统一入口
├── company_report_scraper.py     # 上市公司年报/半年报/季报
├── news_scraper.py               # 新闻爬取（东方财富/同花顺）
├── document_parser.py            # 文档解析（PDF/Word/Excel）
├── document_analyzer.py          # 文档分析整理（深度分析+批量整理+对比）
├── report_exporter.py            # 报告导出（PPT/PDF/Word/Excel）
├── batch_institution_crawler.py  # 批量爬取（并发+断点续爬）
├── report_indexer.py             # 全量报告索引（SQLite+断点续扫）
├── analyzer.py                   # 产品分析（风险指标+投资风格）
├── visualization_reporter.py     # 可视化报告（ASCII图表）
├── realtime_monitor.py           # 实时监控（动态页面检测）
├── full_institution_crawler.py   # 全量爬虫（从监管机构获取）
├── institution_updater.py        # 季度自动更新
├── scrapable_registry.py         # 可爬取机构注册表

# 🆕 v4.0 新增模块
├── crawl_scheduler.py            # 定期自动爬取调度引擎
├── crawl_packager.py             # 批量爬取结果 ZIP 打包
├── content_compressor.py         # 内容智能压缩（2-3页精华摘要）
├── enhanced_parser.py            # 增强文件解析（PPT/HTML/Markdown/CSV）
├── financial_writer.py           # 金融分析写作引擎 + ChartBuilder
├── report_templates.py           # 6套金融报告模板库
├── research_report_generator.py  # 研究报告全流程生成器
├── sentiment_chat.py             # 对话式舆情 NLU 入口
├── sentiment_crawler.py          # 全网舆情爬虫（60+ 商业财经媒体源）
├── sentiment_exporter.py         # 舆情报告导出
├── search_engine.py              # 百度/搜狗/DDG 多引擎搜索
├── structured_market_data.py     # 结构化市场数据（期货/宏观/Shibor）
├── analyzer.py                   # 真实风险指标分析（v5.0 重写）
├── browser_scraper.py            # 浏览器类人爬取（v5.0 增强）
├── akshare_fallback.py           # akshare 兜底适配器
└── http_utils.py                 # HTTP 公共基础设施（限流/重试/缓存）

# 🆕 v7.3.0 新增模块
├── crawl_enhancer.py             # 智能多级爬取（API→HTTP→浏览器降级链 + 批量统计）
├── web_recognizer.py             # 网页内容识别（表格/键值/条目/分页/数字）
├── data_aggregator.py            # 数据分析汇总（快照聚合/去重/截面/导出）
└── voice_interface.py            # 语音交互（Windows SAPI 零依赖，可选 vosk）
# 入口：run_voice.py（语音循环）
```

### 模块功能速查

| 需求 | 使用模块 | 示例 |
|------|----------|------|
| 查询机构名单 | `institution_scraper.py` | `search_institution("华夏基金")` |
| 解析基金/股票 | `web_parser.py` | `parse_financial_product(url, "fund")` |
| 下载公告 | `announcement_scraper.py` | `AnnouncementManager().search("贵州茅台")` |
| 查询研报 | `research_report_scraper.py` | `BrokerReportManager().query("600519")` |
| 批量爬取 | `batch_institution_crawler.py` | `BatchInstitutionCrawler().crawl_by_type("基金")` |
| 生成报告 | `report_exporter.py` | `ReportExporter().export_to_ppt(data)` |
| 文档分析 | `document_analyzer.py` | `DocumentAnalyzer().analyze("report.pdf")` |
| 数据验证 | `data_validator.py` | `python scripts/data_validator.py` |
| 🆕 定期自动爬取 | `crawl_scheduler.py` | `create_scheduled_task("每日新闻", "daily")` |
| 🆕 批量打包ZIP | `crawl_packager.py` | `batch_crawl_and_package(names="华夏基金")` |
| 🆕 内容压缩摘要 | `content_compressor.py` | `compress_content(source, focus="财务")` |
| 🆕 增强文件解析 | `enhanced_parser.py` | `parse_file_enhanced("slides.pptx")` |
| 🆕 金融写作 | `financial_writer.py` | `generate_report(data, template_id="stock_research")` |
| 🆕 报告模板 | `report_templates.py` | `render_template("fund_evaluation", data)` |
| 🆕 研究报告生成 | `research_report_generator.py` | `generate_research_report("600519", "stock_research")` |

## 全量金融机构名单（2301 家 / 43 大类）

| 文件 | 内容 | 数量 |
|------|------|------|
| `data/institution_registry.json` | 统一注册表（含 URL） | 2301 家 |
| `data/state_owned_bank_list.json` | 国有大型商业银行 | 9 家 |
| `data/joint_stock_bank_list.json` | 股份制商业银行 | 12 家 |
| `data/policy_bank_list.json` | 政策性银行 | 3 家 |
| `data/city_commercial_bank_list.json` | 城市商业银行 | 157 家 |
| `data/rural_commercial_bank_list.json` | 农村商业银行 | 167 家 |
| `data/private_bank_list.json` | 🆕 民营银行 | 19 家 |
| `data/foreign_bank_list.json` | 🆕 外资法人银行 | 41 家 |
| `data/fund_company_list.json` | 基金管理公司 | 167 家 |
| `data/securities_list.json` | 证券公司 | 131 家 |
| `data/insurance_list.json` | 保险公司 | 181 家 |
| `data/trust_company_list.json` | 信托公司 | 67 家 |
| `data/private_fund_list.json` | 私募基金管理公司 | 64 家 |
| `data/foreign_institution_list.json` | 外资金融机构 | 60 家 |
| `data/futures_list.json` | 期货公司 | 181 家 |
| `data/futures_risk_mgmt_list.json` | 期货风险管理子公司 | 94 家 |
| `data/finance_company_list.json` | 企业集团财务公司 | 201 家 |
| `data/insurance_asset_list.json` | 保险资产管理公司 | 34 家 |
| `data/consumer_finance_list.json` | 消费金融公司 | 40 家 |
| `data/financing_guarantee_list.json` | 融资担保公司 | 30 家 |
| `data/financial_lease_list.json` | 金融租赁公司 | 94 家 |
| `data/auto_finance_list.json` | 汽车金融公司 | 41 家 |
| `data/wealth_management_list.json` | 银行理财子公司 | 33 家 |
| `data/fund_subsidiary_list.json` | 基金子公司 | 41 家 |
| `data/financial_holding_list.json` | 金融控股公司 | 63 家 |
| `data/third_party_list.json` | 第三方销售机构 | 43 家 |
| `data/reinsurance_list.json` | 再保险公司 | 11 家 |
| `data/money_broker_list.json` | 货币经纪公司 | 6 家 |
| `data/aic_list.json` | 金融资产投资公司(AIC) | 5 家 |
| `data/amc_list.json` | 🆕 金融资产管理公司 | 5 家 |
| `data/village_bank_list.json` | 🆕 村镇银行 | 60 家 |
| `data/insurance_broker_list.json` | 🆕 保险经纪公司 | 48 家 |
| `data/insurance_assessor_list.json` | 🆕 保险公估公司 | 36 家 |
| `data/city_investment_list.json` | 城投机构 | 102 家 |
| `data/local_amc_list.json` | 🆕 地方资产管理公司 | 17 家 |
| `data/payment_list.json` | 🆕 支付机构 | 12 家 |
| `data/credit_rating_list.json` | 🆕 信用评级机构 | 11 家 |
| `data/credit_service_list.json` | 🆕 征信与商查机构 | 5 家 |
| `data/mutual_insurance_list.json` | 🆕 相互保险组织 | 4 家 |
| `data/pension_mgmt_list.json` | 🆕 养老金管理公司 | 8 家 |
| `data/wm_subsidiary_list.json` | 🆕 券商资管子公司 | 6 家 |
| `data/financial_infra_list.json` | 🆕 金融基础设施机构 | 7 家 |
| `data/internet_loan_list.json` | 🆕 互联网小贷公司 | 4 家 |
| `data/securities_consulting_list.json` | 🆕 证券投资咨询机构 | 1 家 |

> 口径说明：v7.0.0 起名单数字 = 实际 JSON 数据条数（此前部分类型 count 字段为宣称值，已修正）。
> 扩充引擎 `scripts/institution_expander.py` 支持 live 名录直连（基金/期货）、
> curated 精选数据（`data/curated.json`，28 类合并单文件）与 list 文件反向吸收三路合并去重。

```bash
python -m scripts.scrapable_registry stat          # 统计
python -m scripts.scrapable_registry list 基金管理公司  # 按类列出
python -m scripts.scrapable_registry search 华夏     # 关键词搜索
```


## 🆕 v4.3 全网舆情爬虫 — 实战场景

### 场景 A — 单机构 + 单一情感（对话式）

> "帮我爬一下贵州茅台最近7天的舆情"

```python
from scripts import chat_handle
print(chat_handle("帮我爬一下贵州茅台最近7天的舆情")["reply"])
```

对话式触发后，引擎自动完成：
1. 抽取目标：贵州茅台（listed_company）
2. 媒体默认：authoritative + financial_vertical
3. 时间窗：7 天
4. 情感：负面优先（用户用了"舆情" 一词）
5. 输出：对话提示 + data/sentiment_snapshots/<id>.json

### 场景 B — 多机构 + 负面新闻 + 多格式导出

> "看下华夏基金、招商银行、中国人寿过去3天的负面新闻，并导出 Excel/Word"

```python
from scripts import crawl_sentiment, export_sentiment
snap = crawl_sentiment(
    targets=["华夏基金", "招商银行", "中国人寿"],
    days=3, negative_only=True,
    source_categories=["authoritative", "financial_vertical"],
)
outputs = export_sentiment(snap, fmt="all")
for k, v in outputs.items():
    print(k, v)
```

### 场景 C — 定时任务

> "每天早上 9 点爬一下银行的舆情并导出全部格式"

```python
schedule_crawl_task(
    name="每日银行舆情",
    frequency="daily",
    action="crawl_sentiment_export",
    sentiment_categories=["commercial_bank"],
    sentiment_source_categories=["authoritative", "financial_vertical"],
    sentiment_negative_only=True,
    sentiment_export_format="all",
)
```

### 场景 D — 类别查看 / 自定义目标

```python
from scripts import list_sentiment_targets, add_custom_sentiment_target
print(list_sentiment_targets())
add_custom_sentiment_target("custom", "恒生电子")
```

### CLI 调试

```bash
python -m scripts.sentiment_crawler --stats
python -m scripts.sentiment_crawler --list-sources
python -m scripts.sentiment_crawler --list-targets
python -m scripts.sentiment_crawler     --categories fund_company,listed_company     --source-categories authoritative,financial_vertical     --days 7 --negative-only --max 30
```

### 严重度阈值

| 严重度（正面） | 阈值（情感分数） |
|----------------|------------------|
| 低度利好 | 6 – 14 |
| 中度利好 | 15 – 29 |
| 重大利好 | ≥ 30 |

| 严重度（负面） | 阈值 |
|----------------|------|
| 低度关注 | 6 – 11 |
| 中度舆情 | 12 – 24 |
| 高危舆情 | ≥ 25 |

## 能力边界

| 类别 | 说明 |
|------|------|
| ✅ **完全支持** | 机构名单查询、基金/ETF/FOF/股票产品解析、A股公告搜索下载、券商研报、新闻资讯、舆情监控、批量爬取（断点续爬）、文档解析（PDF/Word/Excel/PPT/HTML）、报告导出（Word/PPT/Excel）、风险指标分析、结构化市场数据（期货/宏观/Shibor） |
| ❌ **不支持** | 需登录的页面（如微信公众号后台、券商内部系统）、付费墙内容（如 Wind 终端数据）、实时 WebSocket 推送、移动端 APP 内嵌页面、验证码自动破解（需第三方打码服务） |
| ⚠️ **部分支持** | 动态渲染页面（需 Playwright，用 `mode="realtime"`）、反爬极严的网站（如某些银行官网，成功率 30-50%）、大批量爬取（需控并发 ≤5 + 断点续爬）、海外网站（需代理，部分有地域限制） |

**预期成功率**：天天基金 95%+ / 东方财富 90%+ / 同花顺 85%+ / 基金公司官网 70-90% / 银行官网 30-50% / 反爬严格的网站 20-40%。

> 💡 **提示**：如果你的目标网站反爬严格，建议先用 `mode="realtime"` 走浏览器，配合 proxy 和低频率（≥3 秒/请求）。

## 数据验证

```bash
# 验证数据完整性
python scripts/data_validator.py

# 验证结果示例
# ✅ institution_registry.json: 验证通过，共 1330 家机构
# ✅ fund_company_list.json: 验证通过，共 160 家机构
# ...
# 📈 汇总: 28/28 通过
```

## ❓ 常见问题（FAQ）

> 📘 更多故障排查见 [TROUBLESHOOTING.md](TROUBLESHOOTING.md)（9 个章节 / 30+ 个解法 / 错误码速查表）
> 🔒 安全审计与漏洞披露见 [SECURITY.md](SECURITY.md)

### 🔥 高频问题

| 问题 | 解决方案 |
|------|----------|
| 舆情爬取返回空 | 1）检查目标名称（`list_sentiment_targets`）；2）扩大时间范围（`days=7`）；3）增加媒体源类别 |
| 结构化数据返回 None | 需安装 akshare：`pip install akshare`，未装时自动返回 None 不报错 |
| 动态页面爬不到内容 | 默认 `mode="static"` 只走 HTTP，SPA 页面需 `mode="realtime"`（需 Playwright） |
| 银行官网成功率低 | 银行反爬严格（30-50%），建议：浏览器模式 + proxy + 低频率（≥3秒/请求） |
| pip 安装很慢 | 国内镜像：`pip install -i https://pypi.tuna.tsinghua.edu.cn/simple -r requirements.txt` |
| `ModuleNotFoundError: playwright` | `pip install playwright && playwright install chromium` |

### 安装问题

| 问题 | 解决方案 |
|------|----------|
| playwright 安装失败 | 运行 `playwright install --with-deps chromium`，或设置镜像 `set PLAYWRIGHT_DOWNLOAD_HOST=https://npmmirror.com/mirrors/playwright` |
| 模块找不到 | 运行 `pip install -r requirements.txt` |
| 多 Python 环境冲突 | 详见 [TROUBLESHOOTING.md §1.4](TROUBLESHOOTING.md#14-不同-python-解释器混乱) |

### 爬取问题

| 问题 | 解决方案 |
|------|----------|
| 返回空数据 | 使用动态渲染：`mode="realtime"` |
| 频繁超时 | 增加超时时间：`timeout=60` |
| 验证码拦截 | 降低爬取频率，稍后重试；或接入第三方打码服务 |
| IP 被封 403 | 暂停 5-10 分钟 + 切换代理 + 降频（详见 [TROUBLESHOOTING.md §3.1](TROUBLESHOOTING.md#31-ip-被封--一直-403)） |
| 中文乱码 | 用 `decode_response()` 自动嗅探编码（详见 [TROUBLESHOOTING.md §4.1](TROUBLESHOOTING.md#41-中文乱码--unicodedecodeerror)） |

## 支持的数据源

| 类型 | 平台 |
|------|------|
| 实时行情 | 🆕 新浪财经 (hq.sinajs.cn) |
| 快讯电报 | 🆕 财联社 (cls.cn) |
| 深度分析 | 🆕 华尔街见闻 (wallstreetcn.com) |
| 可转债 | 🆕 集思录 (jisilu.cn) |
| 官方公告 | 上交所/深交所 (sse.com.cn/szse.cn) |
| 基金 | 天天基金、东方财富、各基金公司官网 |
| ETF | 各大交易所、天天基金 |
| 公告 | 天天基金、巨潮资讯 |
| 研报 | 东方财富研报中心 |
| 新闻 | 东方财富、同花顺、财联社 |
| 行情 | 雪球 (xueqiu.com) |
| 组合 | 且慢、蛋卷基金、雪球 |
| 宏观 | 🆕 CPI/PPI/PMI/GDP/M2 零依赖 HTTP 直连（东财 datacenter）+ akshare 兜底 |

## 许可证

MIT License
