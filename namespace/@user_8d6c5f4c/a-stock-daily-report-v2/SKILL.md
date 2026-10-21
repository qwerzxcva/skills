---
name: a-stock-daily-report
slug: a-stock-daily-report
category: 金融投资
description: Generate professional daily analysis reports for A-share (China) stocks. Covers real-time quotes, technical indicators (MA/MACD/KDJ/RSI/BOLL), capital flow, news sentiment, and short-term outlook with support/resistance levels. Use when the user asks for a stock daily report, technical analysis report, stock review, 股票日报, 个股分析报告, 技术面分析, or asks to analyze a specific A-share stock's daily performance.
description_zh: 生成A股个股智能日报，涵盖实时行情、技术指标、资金流向、新闻公告摘要及短期操作参考，适合个人投资者日常复盘使用。
version: 1.0.0
platforms: [WorkBuddy, Claude Code]
agent_created: true
allowed-tools: Read,Bash,Write,WebSearch
displayName: A股智能日报
displayName_en: A-Share Daily Report
visibility: public
monetization:
  type: paid
  pricing:
    single: 19.99
    currency: CNY
    subscription_monthly: 49.99
  trial: true
  trial_days: 3
---

# A股智能日报 (A-Share Daily Report)

> 一句话：输入股票代码/名称，自动生成一份结构化的技术面+资金面+消息面日报，适合个人投资者日常复盘。

## 触发条件

当用户提出以下意图时，优先使用本 Skill：

- "帮我看看 XX 股票今天怎么样"
- "生成 XX 的日报/分析报告"
- "分析一下 XX 的技术面"
- "XX 股票日线分析"
- 任何涉及 A 股个股的日报、技术分析、复盘请求

## 核心理念

本 Skill 不是预测涨跌，而是把多维度数据整合成一份**结构化、可复盘、有参考价值**的日报。每份报告都标注数据来源、时间戳和免责声明。

## 数据源

| 维度 | 数据源 | 命令 |
|------|--------|------|
| 实时行情 | westock-data | `npx -y westock-data-clawhub@1.0.4 quote <code>` |
| K 线数据 | westock-data | `npx -y westock-data-clawhub@1.0.4 kline <code> --period day --limit 60` |
| 技术指标 | westock-data | `npx -y westock-data-clawhub@1.0.4 technical <code> --group ma,macd,kdj,rsi` |
| 资金流向 | westock-data | `npx -y westock-data-clawhub@1.0.4 asfund <code>` |
| 公司简况 | westock-data | `npx -y westock-data-clawhub@1.0.4 profile <code>` |
| 新闻/公告 | neodata-financial-search | `python3 scripts/query.py --query "<股票名> 近期新闻公告"` |

## 执行流程

### Step 1: 解析用户输入

从用户输入中提取：
- 股票代码或名称（如 "600519"、"贵州茅台"、"sh600519"）
- 如果是名称，先搜索确认代码

```bash
# 搜索股票获取代码
npx -y westock-data-clawhub@1.0.4 search "贵州茅台"
```

### Step 2: 并行拉取数据

使用 Bash 工具并行执行以下命令（可使用 `run_in_background` 并发）：

```bash
# 1. 实时行情
npx -y westock-data-clawhub@1.0.4 quote sh600519

# 2. 日K线（60条，用于技术分析）
npx -y westock-data-clawhub@1.0.4 kline sh600519 --period day --limit 60

# 3. 技术指标
npx -y westock-data-clawhub@1.0.4 technical sh600519 --group ma,macd,kdj,rsi

# 4. 资金流向
npx -y westock-data-clawhub@1.0.4 asfund sh600519

# 5. 公司简况
npx -y westock-data-clawhub@1.0.4 profile sh600519
```

对于新闻/公告，调用 neodata-financial-search Skill：
```
查询 "<股票名称> 今天的重大新闻和公告"
```

### Step 3: 数据分析

从拉取的数据中提取核心指标：

**行情概览**
- 最新价、涨跌幅、涨跌额、振幅
- 今开/昨收/最高/最低
- 成交量、成交额、换手率
- 总市值、市盈率(PE)、市净率(PB)

**均线系统（基于 K 线收盘价计算）**
- MA5 / MA10 / MA20 / MA60 数值
- 价格与各均线的位置关系（上方/下方/粘合）
- 均线排列：多头排列 / 空头排列 / 缠绕整理
- 交叉信号：MA5 是否上穿/下穿 MA10/MA20

**MACD 指标**
- DIF / DEA / MACD 柱
- 金叉/死叉状态
- 顶背离/底背离判断（对比价格与 MACD 柱走势）

**KDJ 指标**
- K / D / J 值
- 超买区（>80）/ 超卖区（<20）
- 金叉/死叉

**RSI 指标**
- RSI(6) / RSI(14) 数值
- 超买/超卖/中性区域判断

**资金面**
- 主力净流入/流出
- 超大单/大单/中单/小单流向
- 近5日资金趋势

**消息面**
- 最新公告摘要（3条以内）
- 相关新闻要闻（3条以内）
- 机构研报观点（如有）

### Step 4: 生成综合判断

基于以上数据，生成以下判断（必须带有条件和置信度）：

**趋势研判**
- 短期趋势（5日）：上涨/震荡/下跌
- 中期趋势（20日）：多头/整理/空头
- 置信度：高/中/低

**关键价位**
- 支撑位 1（短期）和支撑位 2（中期）
- 压力位 1（短期）和压力位 2（中期）
- 每个价位标注来源：前低/前高/均线/缺口/筹码密集区

**技术信号汇总**
- 偏多信号列表
- 偏空信号列表
- 中性/观望信号列表

**综合评分**
- 技术面评分：1-5 分（多空综合）
- 资金面评分：1-5 分
- 消息面评分：1-5 分
- 综合投资情绪：乐观/中性偏多/中性/中性偏空/谨慎

### Step 5: 生成 HTML 报告

调用 `scripts/daily_report.py` 生成精美的 HTML 日报：

```bash
python3 <skill_dir>/scripts/daily_report.py \
  --code "sh600519" \
  --name "贵州茅台" \
  --output "<workspace>/outputs/<code>_<date>_日报.html"
```

脚本支持以下参数：
- `--code`: 股票代码（如 sh600519）
- `--name`: 股票名称
- `--data-file`: 可选，JSON 数据文件路径（预计算的数据直接用）

如果不使用脚本，则使用 `assets/report_template.html` 模板手动填充数据。

### Step 6: 呈现结果

使用 `present_files` 展示生成的 HTML 日报，同时用简洁的语言总结核心结论。

## 输出规范

- **报告标题**：`{股票名称}({代码}) 智能日报 | {日期}`
- **免责声明**：必须在报告底部标注「本报告由 AI 自动生成，仅供参考，不构成投资建议」
- **数据时间戳**：标注数据获取时间
- **中国股市惯例**：红色表示上涨、绿色表示下跌

## 批量日报模式

当用户提供多个股票代码时，为每只股票独立生成日报，然后汇总展示：

```bash
# 示例：用户说"帮我生成茅台、五粮液、招商银行的日报"
# 则为 sh600519、sz000858、sh600036 各生成一份
```

## 使用示例

**示例 1：单股日报**
```
用户：帮我看看贵州茅台今天怎么样
AI：加载 a-stock-daily-report Skill → 拉取数据 → 生成报告 → 呈现 HTML
```

**示例 2：自选股批量日报**
```
用户：帮我生成自选股的日报：茅台、宁德时代、比亚迪
AI：并发拉取3只股票数据 → 分别生成报告 → 打包呈现
```

## 收费说明

- 单次报告：¥19.99
- 月度订阅：¥49.99（不限次数）
- 新用户：免费试用 3 天

## 注意事项

1. 本 Skill 专注于 A 股市场（沪深京），港股/美股不在范围内
2. 技术指标为辅助参考，不构成买卖建议
3. 数据来源于腾讯自选股和 NeoData 金融搜索，可能延迟 15 分钟
4. 非交易日（休市/节假日）生成的是最近交易日数据
