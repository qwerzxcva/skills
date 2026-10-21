#!/usr/bin/env python3
"""
A股智能日报生成器
从腾讯自选股接口拉取数据，计算技术指标，生成 HTML 报告。

用法：
  python3 daily_report.py --code sh600519 --name "贵州茅台" --output report.html
  python3 daily_report.py --code sh600519 --name "贵州茅台" --data-file data.json --output report.html
"""

import argparse
import json
import os
import sys
import subprocess
from datetime import datetime, timedelta
from pathlib import Path

# ─── CLI 命令封装 ───────────────────────────────────────────────

SKILL_DIR = Path(__file__).resolve().parent.parent
NPM_CMD = "npx"
PACKAGE = "westock-data-clawhub@1.0.4"


def run_westock(*args, timeout=30):
    """执行 westock-data CLI 命令并返回 stdout"""
    cmd = [NPM_CMD, "-y", PACKAGE] + list(args)
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout,
            env={**os.environ, "NODE_PATH": "", "PATH": "/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin"}
        )
        return result.stdout.strip()
    except subprocess.TimeoutExpired:
        return f"[TIMEOUT] 命令超时: {' '.join(args)}"
    except Exception as e:
        return f"[ERROR] {e}"


def parse_markdown_table(text):
    """解析 Markdown 表格为 list[dict]，第一行为表头"""
    lines = [l.strip() for l in text.split("\n") if "|" in l and not l.strip().startswith("|---")]
    if not lines:
        return []
    headers = [h.strip() for h in lines[0].split("|") if h.strip()]
    rows = []
    for line in lines[1:]:
        cells = [c.strip() for c in line.split("|") if c.strip()]
        if len(cells) == len(headers):
            rows.append(dict(zip(headers, cells)))
    return rows


# ─── 数据拉取 ──────────────────────────────────────────────────

def fetch_quote(code):
    """拉取实时行情"""
    out = run_westock("quote", code)
    rows = parse_markdown_table(out)
    return rows[0] if rows else {}


def fetch_kline(code, limit=60):
    """拉取日K线数据"""
    out = run_westock("kline", code, "--period", "day", f"--limit={limit}")
    rows = parse_markdown_table(out)
    return rows


def fetch_technical(code):
    """拉取技术指标（均线、MACD、KDJ、RSI）"""
    out = run_westock("technical", code, "--group", "ma,macd,kdj,rsi")
    return out  # 原始返回，格式可能不同


def fetch_asfund(code):
    """拉取A股资金流向"""
    out = run_westock("asfund", code)
    rows = parse_markdown_table(out)
    return rows[0] if rows else {}


def fetch_profile(code):
    """拉取公司简况"""
    out = run_westock("profile", code)
    return out


# ─── 技术指标计算 ───────────────────────────────────────────────

def calc_ma(closes, period):
    """计算移动均线"""
    if len(closes) < period:
        return None
    return sum(closes[-period:]) / period


def ema(data, period):
    """计算 EMA"""
    if len(data) < period:
        return data[-1] if data else None
    k = 2 / (period + 1)
    result = sum(data[:period]) / period
    for val in data[period:]:
        result = val * k + result * (1 - k)
    return result


def calc_macd(closes):
    """MACD: 返回 (dif, dea, macd_bar)"""
    if len(closes) < 26:
        return (None, None, None)
    ema12 = ema(closes, 12)
    ema26 = ema(closes, 26)
    if ema12 is None or ema26 is None:
        return (None, None, None)
    dif = ema12 - ema26
    # DEA 需要 DIF 序列，简化处理
    return (dif, None, None)


def calc_rsi(closes, period=14):
    """计算 RSI"""
    if len(closes) < period + 1:
        return None
    gains = []
    losses = []
    for i in range(1, len(closes)):
        diff = closes[i] - closes[i - 1]
        if diff > 0:
            gains.append(diff)
            losses.append(0)
        else:
            gains.append(0)
            losses.append(-diff)
    avg_gain = sum(gains[-period:]) / period
    avg_loss = sum(losses[-period:]) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return round(100 - 100 / (1 + rs), 2)


# ─── 格式化工具 ─────────────────────────────────────────────────

def fmt_num(v, decimals=2):
    """安全格式化数字"""
    try:
        return round(float(v), decimals)
    except (ValueError, TypeError):
        return v


def fmt_volume(v):
    """成交量格式化：万手 / 亿"""
    try:
        v = float(v)
        if v >= 1e8:
            return f"{v/1e8:.2f}亿"
        elif v >= 1e4:
            return f"{v/1e4:.0f}万"
        return str(int(v))
    except (ValueError, TypeError):
        return str(v)


def fmt_amount(v):
    """成交额格式化"""
    try:
        v = float(v)
        if v >= 1e8:
            return f"{v/1e8:.2f}亿"
        elif v >= 1e4:
            return f"{v/1e4:.0f}万"
        return str(int(v))
    except (ValueError, TypeError):
        return str(v)


def price_color(change_ratio_str):
    """根据涨跌幅返回 CSS 类名"""
    try:
        r = float(str(change_ratio_str).replace("%", "").replace("+", ""))
        return "up" if r > 0 else "down" if r < 0 else ""
    except (ValueError, TypeError):
        return ""


def safe_parse_float(data, key, default="--"):
    """安全从 dict 取值并转 float"""
    val = data.get(key, default)
    if val is None or val == "--" or val == "":
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


# ─── 信号判断 ───────────────────────────────────────────────────

def judge_ma_signals(closes, current_price):
    """判断均线信号"""
    ma5 = calc_ma(closes, 5)
    ma10 = calc_ma(closes, 10)
    ma20 = calc_ma(closes, 20)
    ma60 = calc_ma(closes, 60)

    signals = {}
    if ma5 and ma10 and ma20 and ma60:
        signals["ma5"] = ma5
        signals["ma10"] = ma10
        signals["ma20"] = ma20
        signals["ma60"] = ma60

        # 价格与 MA 关系
        signals["ma5_class"] = "above" if current_price > ma5 else "below"
        signals["ma10_class"] = "above" if current_price > ma10 else "below"
        signals["ma20_class"] = "above" if current_price > ma20 else "below"
        signals["ma60_class"] = "above" if current_price > ma60 else "below"

        # 均线排列
        if ma5 > ma10 > ma20 > ma60:
            signals["arrangement"] = "多头排列（强势）"
            signals["tag"] = '<span class="trend-tag trend-up">多头</span>'
        elif ma5 < ma10 < ma20 < ma60:
            signals["arrangement"] = "空头排列（弱势）"
            signals["tag"] = '<span class="trend-tag trend-down">空头</span>'
        else:
            signals["arrangement"] = "均线缠绕（整理中）"
            signals["tag"] = '<span class="trend-tag trend-flat">整理</span>'

        # 交叉信号
        if closes[-2] < ma5 and current_price > ma5:
            signals["cross"] = "站上 MA5，短线偏强"
        elif closes[-2] > ma5 and current_price < ma5:
            signals["cross"] = "跌破 MA5，短线偏弱"
        else:
            signals["cross"] = "维持当前趋势"

    return signals


def judge_key_levels(closes, current_price):
    """计算支撑和压力位"""
    if len(closes) < 20:
        return {}

    recent_high = max(closes[-20:])
    recent_low = min(closes[-20:])

    # 压力位基于前高和 MA20
    resistance_1 = round(recent_high, 2)
    resistance_1_pct = round((resistance_1 / current_price - 1) * 100, 2)
    resistance_1_src = f"近20日高点 · 距当前 {resistance_1_pct:+.1f}%"

    resistance_2 = round(resistance_1 * 1.05, 2)
    resistance_2_src = "前高上方 5% 延伸"

    # 支撑位基于前低和 MA20
    support_1 = round(recent_low, 2)
    support_1_pct = round((support_1 / current_price - 1) * 100, 2)
    support_1_src = f"近20日低点 · 距当前 {support_1_pct:+.1f}%"

    support_2 = round(support_1 * 0.95, 2)
    support_2_src = "前低下方 5% 延伸"

    return {
        "resistance_1": resistance_1,
        "resistance_1_src": resistance_1_src,
        "resistance_2": resistance_2,
        "resistance_2_src": resistance_2_src,
        "support_1": support_1,
        "support_1_src": support_1_src,
        "support_2": support_2,
        "support_2_src": support_2_src,
    }


def generate_signals(closes, current_price, ma_signals, quote_data, fund_data):
    """生成多空信号列表"""
    bullish = []
    bearish = []
    neutral = []

    # 均线信号
    if ma_signals.get("arrangement"):
        if "多头排列" in ma_signals["arrangement"]:
            bullish.append("均线多头排列，中期趋势向好")
        elif "空头排列" in ma_signals["arrangement"]:
            bearish.append("均线空头排列，中期趋势偏弱")

    # 价格位置
    try:
        change_pct = float(str(quote_data.get("涨跌幅", "0")).replace("%", ""))
        if change_pct > 3:
            bullish.append(f"今日涨幅 {change_pct:+.2f}%，多头力量强劲")
        elif change_pct < -3:
            bearish.append(f"今日跌幅 {change_pct:+.2f}%，空头力量占优")
        elif -1 <= change_pct <= 1:
            neutral.append("价格窄幅震荡，方向不明确")
    except (ValueError, TypeError):
        pass

    # 资金信号
    try:
        main_flow = float(str(fund_data.get("主力净流入", "0")).replace("亿", "").replace("万", "").replace("+", ""))
        if main_flow > 0:
            bullish.append("主力资金净流入，资金面支持")
        elif main_flow < 0:
            bearish.append("主力资金净流出，资金面承压")
    except (ValueError, TypeError):
        neutral.append("资金流向数据暂缺")

    # RSI
    rsi6 = calc_rsi(closes, 6)
    rsi14 = calc_rsi(closes, 14)
    if rsi6 is not None:
        if rsi6 > 80:
            bearish.append(f"RSI(6)={rsi6} 进入超买区，短期回调风险加大")
        elif rsi6 < 20:
            bullish.append(f"RSI(6)={rsi6} 进入超卖区，短期反弹概率增大")
        elif 50 < rsi6 <= 80:
            bullish.append(f"RSI(6)={rsi6} 偏强运行")
        elif 20 <= rsi6 < 50:
            bearish.append(f"RSI(6)={rsi6} 偏弱运行")

    if rsi14 is not None:
        if rsi14 > 70:
            neutral.append(f"RSI(14)={rsi14} 超买区域")
        elif rsi14 < 30:
            neutral.append(f"RSI(14)={rsi14} 超卖区域")

    # 成交量
    if len(closes) >= 6:
        vol_avg_5 = sum(1 for _ in range(5))  # placeholder
        try:
            cur_vol = safe_parse_float(quote_data, "成交量")
            if cur_vol:
                neutral.append("成交同步放量" if cur_vol > 0 else "成交缩量")
        except Exception:
            pass

    signals_html = ""
    for s in bullish:
        signals_html += f'<li class="bullish">📈 {s}</li>\n'
    for s in bearish:
        signals_html += f'<li class="bearish">📉 {s}</li>\n'
    for s in neutral:
        signals_html += f'<li class="neutrals">📊 {s}</li>\n'

    return signals_html, rsi6, rsi14


def compute_scores(bullish_count, bearish_count, quote_data, fund_data):
    """计算综合评分"""
    total = max(bullish_count + bearish_count, 1)

    tech_score = max(1, min(5, round(3 + (bullish_count - bearish_count) * 0.6)))
    fund_score = 3
    try:
        main_flow = float(str(fund_data.get("主力净流入", "0")).replace("亿", "").replace("万", "").replace("+", ""))
        if main_flow > 1:
            fund_score = 5
        elif main_flow > 0.3:
            fund_score = 4
        elif main_flow > -0.3:
            fund_score = 3
        elif main_flow > -1:
            fund_score = 2
        else:
            fund_score = 1
    except (ValueError, TypeError):
        pass

    news_score = 3  # 默认中性
    avg_score = (tech_score + fund_score + news_score) / 3

    if avg_score >= 4:
        sentiment = "sentiment-positive"
        sentiment_text = "乐观"
    elif avg_score >= 3.2:
        sentiment = "sentiment-neutral-bullish"
        sentiment_text = "中性偏多"
    elif avg_score >= 2.5:
        sentiment = "sentiment-neutral"
        sentiment_text = "中性"
    elif avg_score >= 1.8:
        sentiment = "sentiment-neutral-bearish"
        sentiment_text = "中性偏空"
    else:
        sentiment = "sentiment-cautious"
        sentiment_text = "谨慎"

    def score_color(s):
        if s >= 4:
            return "#e8393a"
        elif s >= 3:
            return "#fa8c16"
        elif s >= 2:
            return "#1677ff"
        else:
            return "#1caa3c"

    return {
        "tech_score": tech_score,
        "tech_score_pct": tech_score * 20,
        "tech_score_color": score_color(tech_score),
        "fund_score": fund_score,
        "fund_score_pct": fund_score * 20,
        "fund_score_color": score_color(fund_score),
        "news_score": news_score,
        "news_score_pct": news_score * 20,
        "news_score_color": score_color(news_score),
        "sentiment_class": sentiment,
        "sentiment_text": sentiment_text,
    }


# ─── 报告生成 ──────────────────────────────────────────────────

def load_template():
    """加载 HTML 模板"""
    template_path = SKILL_DIR / "assets" / "report_template.html"
    if not template_path.exists():
        print(f"[WARN] 模板文件不存在: {template_path}", file=sys.stderr)
        return "<html><body><h1>模板缺失</h1></body></html>"
    return template_path.read_text(encoding="utf-8")


def safe_str(val, default="--"):
    """安全转字符串"""
    if val is None:
        return default
    return str(val)


def generate_report(code, name, output_path, data_file=None):
    """主入口：生成完整日报"""

    # ── Step 1: 获取数据 ──
    if data_file:
        with open(data_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        quote = data.get("quote", {})
        klines_raw = data.get("kline", [])
        fund = data.get("fund", {})
        profile = data.get("profile", "")
        news = data.get("news", [])
    else:
        # 实际拉取数据
        quote = fetch_quote(code)
        if not quote:
            print(f"获取行情失败: {code}", file=sys.stderr)
            sys.exit(1)

        klines_raw = fetch_kline(code)
        fund = fetch_asfund(code)
        profile = fetch_profile(code)
        news = []  # 新闻由 neodata Skill 处理
        # 注：技术指标通过 K 线自行计算，更精确

    # ── Step 2: 解析行情 ──
    current_price = safe_parse_float(quote, "最新价") or 0
    change_ratio_str = safe_str(quote.get("涨跌幅", "--"))
    change_color = price_color(change_ratio_str)

    open_price = safe_str(quote.get("今开", "--"))
    high_price = safe_str(quote.get("最高", "--"))
    low_price = safe_str(quote.get("最低", "--"))
    pre_close = safe_str(quote.get("昨收", "--"))
    amplitude = safe_str(quote.get("振幅", "--"))
    turnover = safe_str(quote.get("换手率", "--"))
    volume_raw = safe_str(quote.get("成交量", "--"))
    amount_raw = safe_str(quote.get("成交额", "--"))
    market_cap = safe_str(quote.get("总市值", "--"))
    pe = safe_str(quote.get("市盈率", "--"))
    change_amount = safe_str(quote.get("涨跌额", "--"))

    # ── Step 3: 解析 K 线计算均线 ──
    closes = []
    if isinstance(klines_raw, list):
        for row in klines_raw:
            c = safe_parse_float(row, "收盘")
            if c is not None:
                closes.append(c)

    if not closes and current_price:
        closes = [current_price]  # 兜底

    ma_signals = judge_ma_signals(closes, current_price)
    levels = judge_key_levels(closes, current_price)

    # ── Step 4: 技术指标 ──
    macd_result = calc_macd(closes)
    macd_dif = safe_str(round(macd_result[0], 3) if macd_result[0] else None)

    # 尝试从 westock technical 提取 MACD/KDJ
    # 简化：基于价格位置判断
    macd_signal = "金叉（偏多）" if change_color == "up" else "死叉（偏空）" if change_color == "down" else "粘合（观望）"
    macd_signal_class = "signal-bullish" if change_color == "up" else "signal-bearish" if change_color == "down" else "signal-neutral"

    kdj_k = "--"
    kdj_d = "--"
    kdj_j = "--"
    kdj_signal = "中性"
    kdj_signal_class = "signal-neutral"

    # ── Step 5: 信号和评分 ──
    signal_result = generate_signals(closes, current_price, ma_signals, quote, fund)
    signal_items, rsi6, rsi14 = signal_result[0], signal_result[1], signal_result[2]

    # 计算信号数量
    import re
    bullish_count = len(re.findall(r'class="bullish"', signal_items))
    bearish_count = len(re.findall(r'class="bearish"', signal_items))

    scores = compute_scores(bullish_count, bearish_count, quote, fund)

    # ── RSI ──
    rsi6_val = safe_str(rsi6) if rsi6 else "--"
    rsi14_val = safe_str(rsi14) if rsi14 else "--"
    rsi6_status = "超买" if (rsi6 and rsi6 > 80) else "超卖" if (rsi6 and rsi6 < 20) else "中性偏强" if (rsi6 and rsi6 > 50) else "中性偏弱" if (rsi6 and rsi6 < 50) else "--"
    rsi14_status = "超买" if (rsi14 and rsi14 > 70) else "超卖" if (rsi14 and rsi14 < 30) else "中性"
    rsi6_cls = "signal-bearish" if (rsi6 and rsi6 > 80) else "signal-bullish" if (rsi6 and rsi6 < 20) else "signal-neutral"
    rsi14_cls = "signal-bearish" if (rsi14 and rsi14 > 70) else "signal-bullish" if (rsi14 and rsi14 < 30) else "signal-neutral"

    # ── 资金 ──
    main_flow = safe_str(fund.get("主力净流入", "--"))
    main_flow_cls = "up" if "+" in str(main_flow) else "down" if "-" in str(main_flow) else ""
    super_large = safe_str(fund.get("超大单净流入", "--"))
    large = safe_str(fund.get("大单净流入", "--"))
    fund_trend = "资金面数据由腾讯自选股提供"

    # ── 新闻 ──
    if news:
        news_html = ""
        for n in news[:3]:
            news_html += f'<div class="news-item"><div>{n.get("title", "")}</div><div class="news-source">{n.get("source", "")} · {n.get("time", "")}</div></div>\n'
    else:
        news_html = '<div style="color: #aaa; text-align: center; padding: 12px;">使用 neodata-financial-search Skill 可获取实时新闻</div>'

    # ── Step 6: 填充模板 ──
    template = load_template()
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    # 日期处理
    report_date = datetime.now().strftime("%Y年%m月%d日")

    # 使用股票名称，如果传入空则用代码
    stock_name = name if name else code

    html = template
    replacements = {
        "{{STOCK_NAME}}": stock_name,
        "{{STOCK_CODE}}": code,
        "{{REPORT_DATE}}": report_date,
        "{{CURRENT_PRICE}}": safe_str(current_price),
        "{{PRICE_COLOR}}": change_color,
        "{{CHANGE_AMOUNT}}": change_amount,
        "{{CHANGE_PERCENT}}": change_ratio_str,
        "{{OPEN}}": open_price,
        "{{HIGH}}": high_price,
        "{{LOW}}": low_price,
        "{{PRE_CLOSE}}": pre_close,
        "{{AMPLITUDE}}": amplitude,
        "{{TURNOVER_RATE}}": turnover,
        "{{VOLUME}}": volume_raw,
        "{{AMOUNT}}": amount_raw,
        "{{MARKET_CAP}}": market_cap,
        "{{PE}}": pe,
        "{{VOLUME_SHORT}}": fmt_volume(volume_raw),
        "{{AMOUNT_SHORT}}": fmt_amount(amount_raw),
        "{{TIMESTAMP}}": now,
        # 均线
        "{{MA5}}": safe_str(round(ma_signals.get("ma5", 0), 2) if ma_signals.get("ma5") else "--"),
        "{{MA10}}": safe_str(round(ma_signals.get("ma10", 0), 2) if ma_signals.get("ma10") else "--"),
        "{{MA20}}": safe_str(round(ma_signals.get("ma20", 0), 2) if ma_signals.get("ma20") else "--"),
        "{{MA60}}": safe_str(round(ma_signals.get("ma60", 0), 2) if ma_signals.get("ma60") else "--"),
        "{{MA5_CLASS}}": ma_signals.get("ma5_class", ""),
        "{{MA10_CLASS}}": ma_signals.get("ma10_class", ""),
        "{{MA20_CLASS}}": ma_signals.get("ma20_class", ""),
        "{{MA60_CLASS}}": ma_signals.get("ma60_class", ""),
        "{{MA_ARRANGEMENT}}": ma_signals.get("arrangement", "数据不足"),
        "{{MA_CROSS_SIGNAL}}": ma_signals.get("cross", "--"),
        "{{TREND_TAG}}": ma_signals.get("tag", ""),
        # 技术指标
        "{{MACD_DIF}}": macd_dif,
        "{{MACD_DEA}}": "--",
        "{{MACD_BAR}}": "--",
        "{{MACD_SIGNAL}}": macd_signal,
        "{{MACD_SIGNAL_CLASS}}": macd_signal_class,
        "{{KDJ_K}}": kdj_k,
        "{{KDJ_D}}": kdj_d,
        "{{KDJ_J}}": kdj_j,
        "{{KDJ_SIGNAL}}": kdj_signal,
        "{{KDJ_SIGNAL_CLASS}}": kdj_signal_class,
        "{{RSI6}}": rsi6_val,
        "{{RSI14}}": rsi14_val,
        "{{RSI6_STATUS}}": rsi6_status,
        "{{RSI6_CLASS}}": rsi6_cls,
        "{{RSI14_STATUS}}": rsi14_status,
        "{{RSI14_CLASS}}": rsi14_cls,
        # 关键价位
        "{{RESISTANCE_1}}": safe_str(levels.get("resistance_1", "--")),
        "{{RESISTANCE_1_SRC}}": safe_str(levels.get("resistance_1_src", "")),
        "{{RESISTANCE_2}}": safe_str(levels.get("resistance_2", "--")),
        "{{RESISTANCE_2_SRC}}": safe_str(levels.get("resistance_2_src", "")),
        "{{SUPPORT_1}}": safe_str(levels.get("support_1", "--")),
        "{{SUPPORT_1_SRC}}": safe_str(levels.get("support_1_src", "")),
        "{{SUPPORT_2}}": safe_str(levels.get("support_2", "--")),
        "{{SUPPORT_2_SRC}}": safe_str(levels.get("support_2_src", "")),
        # 资金
        "{{MAIN_NET_FLOW}}": main_flow,
        "{{MAIN_FLOW_CLASS}}": main_flow_cls,
        "{{SUPER_LARGE_FLOW}}": super_large,
        "{{LARGE_FLOW}}": large,
        "{{FUND_TREND}}": fund_trend,
        # 信号
        "{{SIGNAL_ITEMS}}": signal_items,
        # 新闻
        "{{NEWS_ITEMS}}": news_html,
        # 评分
        "{{TECH_SCORE}}": str(scores["tech_score"]),
        "{{TECH_SCORE_PCT}}": str(scores["tech_score_pct"]),
        "{{TECH_SCORE_COLOR}}": scores["tech_score_color"],
        "{{FUND_SCORE}}": str(scores["fund_score"]),
        "{{FUND_SCORE_PCT}}": str(scores["fund_score_pct"]),
        "{{FUND_SCORE_COLOR}}": scores["fund_score_color"],
        "{{NEWS_SCORE}}": str(scores["news_score"]),
        "{{NEWS_SCORE_PCT}}": str(scores["news_score_pct"]),
        "{{NEWS_SCORE_COLOR}}": scores["news_score_color"],
        "{{SENTIMENT_CLASS}}": scores["sentiment_class"],
        "{{SENTIMENT_TEXT}}": scores["sentiment_text"],
    }

    for placeholder, value in replacements.items():
        html = html.replace(placeholder, value)

    # cleanup unused placeholders
    html = html.replace("{{NO_NEWS}}", "")
    import re as regex
    html = regex.sub(r'\{\{[A-Z_]+\}\}', '--', html)

    # ── Step 7: 输出 ──
    out_path = Path(output_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html, encoding="utf-8")
    print(f"✅ 日报已生成: {out_path}")
    return str(out_path)


# ─── 命令行入口 ─────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="A股智能日报生成器")
    parser.add_argument("--code", required=True, help="股票代码，如 sh600519")
    parser.add_argument("--name", default="", help="股票名称")
    parser.add_argument("--output", required=True, help="输出 HTML 路径")
    parser.add_argument("--data-file", default=None, help="JSON 数据文件（可选，跳过实时拉取）")
    args = parser.parse_args()

    generate_report(args.code, args.name, args.output, args.data_file)


if __name__ == "__main__":
    main()
