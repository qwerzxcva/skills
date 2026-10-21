#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
stock-researcher MCP Server v11.0.0
===================================

把全球智能投研能力通过 MCP 协议暴露给 Claude Code / Claude Desktop 等客户端。

🆕 v11.0 新增 6 工具（14 → 20）：
  - ai_analyze_futures     AI 期货专项（持仓/基差/龙虎榜/跨期套利）
  - ai_analyze_money_flow  AI 资金流（主力/北向/融资/ETF申赎）
  - ai_analyze_index_forecast AI 指数预测（PE分位/RS评分/多周期）
  - ai_analyze_portfolio   AI 组合诊断（业绩归因/再平衡/集中度）
  - get_futures_quote      期货行情查询（含夜盘）
  - predict_multi_horizon  多周期预测（1d/5d/1M/3M/6M）

支持的能力（按工具分类）：

1. 数据查询类（多源自动降级 + 交叉验证）：
   - get_stock_quote     A 股/港股/美股实时行情
   - get_fund_nav        基金净值
   - get_macro_data      宏观经济数据
   - get_futures_quote   期货行情（含夜盘）🆕
   - list_data_sources   数据源状态

2. AI 分析类（需配置 DEEPSEEK_API_KEY，11 类模板）：
   - ai_analyze_stock          股票深度解读
   - ai_analyze_fund           基金深度解读
   - ai_analyze_market_regime  市场体制判断
   - ai_analyze_master_council 大师圆桌综合
   - ai_analyze_macro_outlook  宏观环境解读
   - ai_analyze_risk_report    组合风险评估
   - ai_analyze_sector_rotation 板块轮动分析
   - ai_analyze_futures        期货专项分析 🆕
   - ai_analyze_money_flow     资金流分析 🆕
   - ai_analyze_index_forecast 指数预测 🆕
   - ai_analyze_portfolio      组合诊断 🆕

3. 量化分析类：
   - run_master_council        六位投资大师圆桌评分
   - quick_predict             单股量化预测评分（v7.0 七维）
   - predict_multi_horizon     多周期预测（1d/5d/1M/3M/6M）🆕

4. 系统类：
   - get_skill_status    技能状态/版本/能力

启动方式（Claude Code mcpServers 配置）：
{
  "mcpServers": {
    "stock-researcher": {
      "command": "python",
      "args": ["./mcp_server.py"],
      "env": {
        "DEEPSEEK_API_KEY": "sk-...",
        "PYTHONDONTWRITEBYTECODE": "1"
      }
    }
  }
}
"""
from __future__ import annotations

import sys
import os
import json
import logging
import asyncio
from pathlib import Path
from typing import Any, Dict, Optional

# 禁止生成 .pyc
sys.dont_write_bytecode = True

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("stock_researcher_mcp")

# MCP SDK 导入
try:
    from mcp.server.fastmcp import FastMCP
    HAS_MCP = True
except ImportError as e:
    log.error(f"MCP SDK 不可用: {e}")
    log.error("请运行: pip install mcp")
    HAS_MCP = False
    sys.exit(1)

# 加载 stock_researcher 各模块（延迟加载，避免循环依赖）
def _safe_import(module_name: str, items: list):
    """安全导入模块，缺失时返回 None 占位。"""
    try:
        mod = __import__(module_name, fromlist=items)
        return {item: getattr(mod, item, None) for item in items}
    except Exception as e:
        log.warning(f"导入 {module_name} 失败: {e}")
        return {item: None for item in items}


# 顶层导入核心模块
data_multi_source = _safe_import("stock_researcher.data_multi_source", [
    "get_router", "DataSource", "DataCategory", "DataFreshness",
    "QueryResult", "self_check", "ExternalMCPAdapter",
])
ai_analysis_engine = _safe_import("stock_researcher.ai_analysis_engine", [
    "get_engine", "analyze", "self_check", "LLMConfig",
])
agents_master_council = _safe_import("stock_researcher.agents_master_council", [
    "MasterCouncil", "CouncilReport", "quick_master_council",
])
agents_master_input = _safe_import("stock_researcher.agents_master_input", [
    "MasterInput",
])
core_analyzer = _safe_import("stock_researcher.core_analyzer", [
    "StockResearcher",
])
prediction_v1100 = _safe_import("stock_researcher.prediction_v1100", [
    "predict_multi_horizon", "predict_horizon", "detect_asset_type",
    "calibrate_probability", "self_check",
])
constants = _safe_import("stock_researcher.constants", [
    "VERSION", "MARKET_CN", "MARKET_HK", "MARKET_US",
    "DISCLAIMER", "DOMESTIC_DIRECT_REQUIRED", "SCORE_MEANING",
])

server = FastMCP("stock-researcher")

VERSION = "11.0.0"


def _module_error(module_name: str) -> str:
    return f"❌ 模块 {module_name} 未正确加载"


# ============================================================================
# 1. 数据查询类工具
# ============================================================================

@server.tool()
async def get_stock_quote(code: str = "", market: str = "cn",
                          preferred_source: str = "") -> str:
    """v10.0 多源股票行情查询（akshare/东方财富API/新浪/yfinance 自动降级）。

    Args:
        code: 股票代码（A股：600519；港股：00700；美股：AAPL/TSLA/NVDA）
        market: 市场标识 (cn/hk/us)
        preferred_source: 优先数据源 (akshare/yfinance/finnhub/eastmoney_api)
    """
    router = data_multi_source["get_router"]()
    if router is None:
        return _module_error("data_multi_source")

    try:
        result = await asyncio.to_thread(
            router.query_stock_quote,
            code=code, market=market,
            preferred=preferred_source or None,
        )
        output = {
            "success": result.success,
            "source": result.source,
            "market": result.market,
            "code": code,
            "latency_ms": result.latency_ms,
            "tried": result.tried_sources,
            "timestamp": result.timestamp,
        }
        if result.success:
            output["data"] = result.data if isinstance(result.data, (dict, list)) else str(result.data)[:2000]
        else:
            output["error"] = result.error
        return json.dumps(output, ensure_ascii=False, indent=2, default=str)[:6000]
    except Exception as e:
        return f"❌ 查询异常: {str(e)[:200]}"


@server.tool()
async def get_fund_nav(code: str = "", preferred_source: str = "") -> str:
    """v10.0 多源基金净值查询（akshare/东方财富API 自动降级）。

    Args:
        code: 基金代码（如 110011、000001）
        preferred_source: 优先数据源
    """
    router = data_multi_source["get_router"]()
    if router is None:
        return _module_error("data_multi_source")

    try:
        result = await asyncio.to_thread(
            router.query_fund_nav,
            code=code,
            preferred=preferred_source or None,
        )
        output = {
            "success": result.success,
            "source": result.source,
            "code": code,
            "latency_ms": result.latency_ms,
            "tried": result.tried_sources,
            "timestamp": result.timestamp,
        }
        if result.success:
            data = result.data
            # DataFrame → list[dict]
            if hasattr(data, "to_dict"):
                data = data.to_dict("records")[:60]
            output["data"] = data if isinstance(data, (dict, list)) else str(data)[:2000]
        else:
            output["error"] = result.error
        return json.dumps(output, ensure_ascii=False, indent=2, default=str)[:6000]
    except Exception as e:
        return f"❌ 查询异常: {str(e)[:200]}"


@server.tool()
async def get_macro_data(macro_type: str = "gdp") -> str:
    """v10.0 宏观经济数据查询（GDP/CPI/PPI/PMI/M2）。

    Args:
        macro_type: 宏观数据类型
            gdp=GDP, cpi=CPI, ppi=PPI, pmi=PMI, m2=货币供应量M2
    """
    router = data_multi_source["get_router"]()
    if router is None:
        return _module_error("data_multi_source")

    try:
        result = await asyncio.to_thread(router.query_macro, macro_type=macro_type)
        output = {
            "success": result.success,
            "macro_type": macro_type,
            "source": result.source,
            "latency_ms": result.latency_ms,
            "tried": result.tried_sources,
            "timestamp": result.timestamp,
        }
        if result.success:
            data = result.data
            if hasattr(data, "to_dict"):
                data = data.to_dict("records")[:40]
            output["data"] = data if isinstance(data, (dict, list)) else str(data)[:2000]
        else:
            output["error"] = result.error
        return json.dumps(output, ensure_ascii=False, indent=2, default=str)[:6000]
    except Exception as e:
        return f"❌ 宏观查询异常: {str(e)[:200]}"


@server.tool()
async def list_data_sources() -> str:
    """v11.0 列出所有可用金融数据源状态与能力（含 v11.0 新增源）。无需参数。"""
    router = data_multi_source["get_router"]()
    if router is None:
        return _module_error("data_multi_source")

    try:
        sources = await asyncio.to_thread(router.list_available_sources)
        health = await asyncio.to_thread(router.get_health_status)
        output = {
            "available_sources": {k: v for k, v in sources.items() if v},
            "source_health": health,
            "routing_rules": sum(1 for k in data_multi_source.get("SOURCE_ROUTING", {})),
            "categories": [c.value for c in data_multi_source["DataCategory"]],
            "v11_new_sources": ["sina", "xueqiu", "futures_exchange", "tonghuashun", "external_mcp"],
            "v11_new_categories": ["futures_history", "money_flow", "sentiment"],
            "v11_features": [
                "ETag/If-Modified-Since 缓存",
                "时效分级 (realtime/delayed_15m/closing/estimated)",
                "多源交叉验证 (query_with_validation)",
                "3σ 异常值检测 (detect_anomaly)",
            ],
        }
        return json.dumps(output, ensure_ascii=False, indent=2)[:6000]
    except Exception as e:
        return f"❌ 查询失败: {str(e)}"


@server.tool()
async def get_futures_quote(code: str = "", preferred_source: str = "") -> str:
    """v11.0 期货行情查询（含主力/次主力/夜盘）。

    Args:
        code: 期货品种代码（如 AU、AU2502、CU.mian）
        preferred_source: 优先数据源（akshare / futures_exchange）
    """
    router = data_multi_source["get_router"]()
    if router is None:
        return _module_error("data_multi_source")

    try:
        result = await asyncio.to_thread(
            router.query,
            "cn",
            data_multi_source["DataCategory"].FUTURES,
            preferred_source=preferred_source or None,
            code=code,
        )
        output = {
            "success": result.success,
            "source": result.source,
            "code": code,
            "latency_ms": result.latency_ms,
            "tried": result.tried_sources,
            "freshness": result.freshness,
            "timestamp": result.timestamp,
            "source_count": result.source_count,
            "confidence": result.confidence,
        }
        if result.success:
            data = result.data
            if hasattr(data, "to_dict"):
                data = data.to_dict("records")[:40]
            output["data"] = data if isinstance(data, (dict, list)) else str(data)[:2000]
        else:
            output["error"] = result.error
        return json.dumps(output, ensure_ascii=False, indent=2, default=str)[:6000]
    except Exception as e:
        return f"❌ 期货查询异常: {str(e)[:200]}"


# ============================================================================
# 2. AI 分析类工具
# ============================================================================

@server.tool()
async def ai_analyze_stock(
    code: str = "",
    name: str = "",
    price: str = "",
    change_pct: str = "",
    high: str = "",
    low: str = "",
    volume: str = "",
    amount: str = "",
    pe_ttm: str = "",
    pb: str = "",
    div_yield: str = "",
    roe: str = "",
    gross_margin: str = "",
    net_margin: str = "",
    revenue_yoy: str = "",
    profit_yoy: str = "",
    ma_status: str = "",
    macd: str = "",
    rsi: str = "",
    trend: str = "",
    score: str = "",
    short_term_view: str = "",
    medium_term_view: str = "",
    bull_count: str = "",
    bear_count: str = "",
    neutral_count: str = "",
) -> str:
    """v10.0 AI 深度解读股票（需配置 DEEPSEEK_API_KEY）。基于实时行情+财务+技术+预测数据生成专业研判。

    Args:
        code: 股票代码
        name: 股票名称
        price/current price, change_pct: 涨跌幅
        high/low: 今日最高/最低
        volume/amount: 成交量/成交额
        pe_ttm/pb/div_yield: 估值三件套
        roe/gross_margin/net_margin: 财务质量
        revenue_yoy/profit_yoy: 同比增长
        ma_status/macd/rsi/trend: 技术面
        score: 综合评分
        short_term_view/medium_term_view: 短中期方向
        bull_count/bear_count/neutral_count: 大师共识统计
    """
    engine = ai_analysis_engine["get_engine"]()
    if engine is None:
        return _module_error("ai_analysis_engine")

    context = {
        "code": code, "name": name or code, "market": "A股",
        "price": price, "change_pct": change_pct,
        "high": high, "low": low,
        "volume": volume, "amount": amount,
        "pe_ttm": pe_ttm, "pb": pb, "div_yield": div_yield,
        "roe": roe, "gross_margin": gross_margin, "net_margin": net_margin,
        "revenue_yoy": revenue_yoy, "profit_yoy": profit_yoy,
        "ma_status": ma_status or "N/A", "macd": macd or "N/A",
        "rsi": rsi or "N/A", "trend": trend or "N/A",
        "score": score, "short_term_view": short_term_view,
        "medium_term_view": medium_term_view,
        "bull_count": bull_count, "bear_count": bear_count,
        "neutral_count": neutral_count,
    }
    try:
        result = await asyncio.to_thread(engine.analyze, "stock_analysis", context)
        output = {
            "success": result.success,
            "is_fallback": result.is_fallback,
            "model": result.model,
            "tokens_used": result.tokens_used,
            "latency_ms": result.latency_ms,
            "code": code, "name": name,
            "timestamp": result.timestamp,
        }
        if result.error:
            output["error"] = result.error
        output["analysis"] = result.content[:8000]
        return json.dumps(output, ensure_ascii=False, indent=2)[:10000]
    except Exception as e:
        return f"❌ AI 分析异常: {str(e)}"


@server.tool()
async def ai_analyze_fund(
    code: str = "",
    name: str = "",
    fund_type: str = "",
    ret_1m: str = "", ret_3m: str = "", ret_6m: str = "",
    ret_1y: str = "", ret_3y: str = "", ret_inception: str = "",
    vol: str = "", max_dd: str = "", sharpe: str = "", sortino: str = "",
    benchmark: str = "", alpha: str = "", beta: str = "", ir: str = "",
    top10_pct: str = "", industry_concentration: str = "", avg_pe: str = "",
    manager_name: str = "", manager_years: str = "",
    aum: str = "", rep_funds: str = "",
) -> str:
    """v10.0 AI 深度解读基金（需配置 DEEPSEEK_API_KEY）。

    Args:
        code: 基金代码
        name: 基金名称
        fund_type: 基金类型（股票/混合/债券/指数等）
        ret_1m/3m/6m/1y/3y/inception: 各阶段收益率
        vol: 年化波动率, max_dd: 最大回撤, sharpe/sortino: 风险调整收益
        benchmark/alpha/beta/ir: 相对基准
        top10_pct: 前十大持仓占比, industry_concentration: 行业集中度, avg_pe: 平均PE
        manager_name/manager_years: 经理姓名/从业年限
        aum: 管理规模（亿元）, rep_funds: 代表作品
    """
    engine = ai_analysis_engine["get_engine"]()
    if engine is None:
        return _module_error("ai_analysis_engine")

    context = {
        "code": code, "name": name or code, "fund_type": fund_type or "N/A",
        "ret_1m": ret_1m, "ret_3m": ret_3m, "ret_6m": ret_6m,
        "ret_1y": ret_1y, "ret_3y": ret_3y, "ret_inception": ret_inception,
        "vol": vol, "max_dd": max_dd, "sharpe": sharpe, "sortino": sortino,
        "benchmark": benchmark, "alpha": alpha, "beta": beta, "ir": ir,
        "top10_pct": top10_pct, "industry_concentration": industry_concentration, "avg_pe": avg_pe,
        "manager_name": manager_name, "manager_years": manager_years,
        "aum": aum, "rep_funds": rep_funds,
    }
    try:
        result = await asyncio.to_thread(engine.analyze, "fund_analysis", context)
        output = {
            "success": result.success,
            "is_fallback": result.is_fallback,
            "model": result.model,
            "tokens_used": result.tokens_used,
            "code": code, "name": name,
        }
        if result.error:
            output["error"] = result.error
        output["analysis"] = result.content[:8000]
        return json.dumps(output, ensure_ascii=False, indent=2)[:10000]
    except Exception as e:
        return f"❌ AI 基金分析异常: {str(e)}"


@server.tool()
async def ai_analyze_market_regime(
    sh_close: str = "", sh_chg: str = "",
    sz_close: str = "", sz_chg: str = "",
    gem_close: str = "", gem_chg: str = "",
    hs300_close: str = "", hs300_chg: str = "",
    star50_close: str = "", star50_chg: str = "",       # v11.0 新增
    pct_above_ma20: str = "", pct_above_ma60: str = "",
    new_high_low_ratio: str = "", mcclellan: str = "",
    ad_ratio: str = "",                                  # v11.0 新增
    hs300_vol: str = "", cn_vix: str = "",
    vol_skew: str = "", pcr: str = "",                   # v11.0 新增
    north_bound: str = "", margin_change: str = "", margin_total: str = "",
    etf_flow: str = "",                                  # v11.0 新增
    ah_premium: str = "", hsi_chg: str = "",             # v11.0 新增
    usdcny_change: str = "",                             # v11.0 新增
    hurst: str = "", trend_structure: str = "", momentum_score: str = "",
    regime_label: str = "",                              # v11.0 新增
) -> str:
    """v11.0 AI 市场体制判断（牛/熊/震荡 + 多维证据：PCR/波动率曲面/AH 折溢价）。

    Args:
        sh_close/chg: 上证指数收盘/涨跌幅
        sz_close/chg: 深证成指
        gem_close/chg: 创业板指
        hs300_close/chg: 沪深300
        star50_close/chg: 科创50（v11.0 新增）
        pct_above_ma20/60: 站上 20/60 日均线个股占比
        new_high_low_ratio: 新高-新低比
        mcclellan: McClellan 指标
        ad_ratio: A/D 比率（v11.0 新增）
        hs300_vol: 沪深300 波动率
        cn_vix: 中国 ETF 期权隐含波动率
        vol_skew: 波动率曲面 skew（v11.0 新增）
        pcr: 期权看跌/看涨比率（v11.0 新增）
        north_bound: 北向资金 5 日累计
        margin_change/total: 融资余额变化/总量
        etf_flow: ETF 当日净申赎（v11.0 新增）
        ah_premium: AH 折溢价指数（v11.0 新增）
        hsi_chg: 港股恒生涨跌幅（v11.0 新增）
        usdcny_change: 美元/人民币变化（v11.0 新增）
        hurst: Hurst 指数
        trend_structure: 趋势结构评分
        momentum_score: 动量评分
        regime_label: 当前体制分类（v11.0 新增）
    """
    engine = ai_analysis_engine["get_engine"]()
    if engine is None:
        return _module_error("ai_analysis_engine")

    context = {
        "sh_close": sh_close, "sh_chg": sh_chg,
        "sz_close": sz_close, "sz_chg": sz_chg,
        "gem_close": gem_close, "gem_chg": gem_chg,
        "hs300_close": hs300_close, "hs300_chg": hs300_chg,
        "star50_close": star50_close or "N/A", "star50_chg": star50_chg or "N/A",
        "pct_above_ma20": pct_above_ma20, "pct_above_ma60": pct_above_ma60,
        "new_high_low_ratio": new_high_low_ratio, "mcclellan": mcclellan,
        "ad_ratio": ad_ratio or "N/A",
        "hs300_vol": hs300_vol, "cn_vix": cn_vix,
        "vol_skew": vol_skew or "N/A", "pcr": pcr or "N/A",
        "north_bound": north_bound, "margin_change": margin_change, "margin_total": margin_total,
        "etf_flow": etf_flow or "N/A",
        "ah_premium": ah_premium or "N/A", "hsi_chg": hsi_chg or "N/A",
        "usdcny_change": usdcny_change or "N/A",
        "hurst": hurst, "trend_structure": trend_structure, "momentum_score": momentum_score,
        "regime_label": regime_label or "未分类",
    }
    try:
        result = await asyncio.to_thread(engine.analyze, "market_regime", context)
        output = {
            "success": result.success,
            "is_fallback": result.is_fallback,
            "model": result.model,
        }
        if result.error:
            output["error"] = result.error
        output["analysis"] = result.content[:8000]
        return json.dumps(output, ensure_ascii=False, indent=2)[:10000]
    except Exception as e:
        return f"❌ 市场体制分析异常: {str(e)}"


@server.tool()
async def ai_analyze_master_council(
    target: str = "",
    buffett_view: str = "", graham_view: str = "",
    lynch_view: str = "", soros_view: str = "",
    fisher_view: str = "", marks_view: str = "",
    bull_count: str = "", bear_count: str = "",
    neutral_count: str = "", avg_confidence: str = "",
    context: str = "",
) -> str:
    """v10.0 AI 大师圆桌综合（基于 6 位大师观点 + 量化数据）。

    Args:
        target: 分析标的
        buffett_view/graham_view/lynch_view/soros_view/fisher_view/marks_view: 6 位大师观点
        bull_count/bear_count/neutral_count: 多空中性统计
        avg_confidence: 平均置信度
        context: 综合数据（如量化评分、估值等）
    """
    engine = ai_analysis_engine["get_engine"]()
    if engine is None:
        return _module_error("ai_analysis_engine")

    ctx = {
        "target": target,
        "buffett_view": buffett_view or "未提供",
        "graham_view": graham_view or "未提供",
        "lynch_view": lynch_view or "未提供",
        "soros_view": soros_view or "未提供",
        "fisher_view": fisher_view or "未提供",
        "marks_view": marks_view or "未提供",
        "bull_count": bull_count, "bear_count": bear_count,
        "neutral_count": neutral_count, "avg_confidence": avg_confidence,
        "context": context or "无额外数据",
    }
    try:
        result = await asyncio.to_thread(engine.analyze, "master_council", ctx)
        output = {
            "success": result.success,
            "is_fallback": result.is_fallback,
            "model": result.model,
            "target": target,
        }
        if result.error:
            output["error"] = result.error
        output["analysis"] = result.content[:8000]
        return json.dumps(output, ensure_ascii=False, indent=2)[:10000]
    except Exception as e:
        return f"❌ 圆桌分析异常: {str(e)}"


@server.tool()
async def ai_analyze_macro_outlook(
    gdp_yoy: str = "", pmi_mfg: str = "", pmi_non_mfg: str = "",
    industrial_yoy: str = "",                            # v11.0 新增
    real_estate_yoy: str = "", retail_yoy: str = "",     # v11.0 新增
    export_yoy: str = "",                                # v11.0 新增
    cpi_yoy: str = "", ppi_yoy: str = "",
    core_cpi_yoy: str = "",                              # v11.0 新增
    m2_yoy: str = "", tsf_yoy: str = "", new_loans: str = "",
    new_deposits: str = "",                              # v11.0 新增
    lpr_1y: str = "", lpr_5y: str = "", bond_10y: str = "",
    dr007: str = "",                                     # v11.0 新增
    dxy: str = "", usdcny: str = "", cn_us_spread: str = "",
    cn_us_short_spread: str = "",                        # v11.0 新增
    fed_funds: str = "",                                 # v11.0 新增
) -> str:
    """v11.0 AI 宏观环境解读（增强房地产/社零/出口/DR007）。

    Args:
        gdp_yoy: GDP 同比
        pmi_mfg/non_mfg: 制造业/非制造业 PMI
        industrial_yoy: 工业增加值同比（v11.0 新增）
        real_estate_yoy: 房地产销售面积同比（v11.0 新增）
        retail_yoy: 社零同比（v11.0 新增）
        export_yoy: 出口同比（v11.0 新增）
        cpi_yoy/ppi_yoy: CPI/PPI 同比
        core_cpi_yoy: 核心 CPI（v11.0 新增）
        m2_yoy: M2 同比, tsf_yoy: 社融存量同比, new_loans: 新增贷款
        new_deposits: 新增人民币存款（v11.0 新增）
        lpr_1y/5y: 1 年/5 年期 LPR
        bond_10y: 10 年期国债收益率
        dr007: DR007（v11.0 新增）
        dxy: 美元指数, usdcny: 人民币汇率, cn_us_spread: 中美利差
        cn_us_short_spread: 中美短端利差（v11.0 新增）
        fed_funds: 美联储隔夜利率（v11.0 新增）
    """
    engine = ai_analysis_engine["get_engine"]()
    if engine is None:
        return _module_error("ai_analysis_engine")

    ctx = {
        "gdp_yoy": gdp_yoy, "pmi_mfg": pmi_mfg, "pmi_non_mfg": pmi_non_mfg,
        "industrial_yoy": industrial_yoy or "N/A",
        "real_estate_yoy": real_estate_yoy or "N/A",
        "retail_yoy": retail_yoy or "N/A", "export_yoy": export_yoy or "N/A",
        "cpi_yoy": cpi_yoy, "ppi_yoy": ppi_yoy,
        "core_cpi_yoy": core_cpi_yoy or "N/A",
        "m2_yoy": m2_yoy, "tsf_yoy": tsf_yoy, "new_loans": new_loans,
        "new_deposits": new_deposits or "N/A",
        "lpr_1y": lpr_1y, "lpr_5y": lpr_5y, "bond_10y": bond_10y,
        "dr007": dr007 or "N/A",
        "dxy": dxy, "usdcny": usdcny, "cn_us_spread": cn_us_spread,
        "cn_us_short_spread": cn_us_short_spread or "N/A",
        "fed_funds": fed_funds or "N/A",
    }
    try:
        result = await asyncio.to_thread(engine.analyze, "macro_outlook", ctx)
        output = {
            "success": result.success,
            "is_fallback": result.is_fallback,
            "model": result.model,
        }
        if result.error:
            output["error"] = result.error
        output["analysis"] = result.content[:8000]
        return json.dumps(output, ensure_ascii=False, indent=2)[:10000]
    except Exception as e:
        return f"❌ 宏观分析异常: {str(e)}"


@server.tool()
async def ai_analyze_risk_report(
    total_value: str = "", holdings_count: str = "", cash_pct: str = "",
    industry_hhi: str = "", max_weight_pct: str = "",
    last_rebalance_days: str = "", style_drift: str = "",  # v11.0 新增
    portfolio_vol: str = "", max_dd_1y: str = "", max_dd_3y: str = "",
    var_95: str = "", var_99: str = "", es_95: str = "",
    stress_2008: str = "", stress_covid: str = "", ir_shock: str = "",
    inflation_shock: str = "",                              # v11.0 新增
    beta_market: str = "", beta_size: str = "", beta_value: str = "",
    beta_momentum: str = "", beta_quality: str = "",
    avg_daily_turnover: str = "",                           # v11.0 新增
    days_to_liquidate: str = "", limit_up_holding_pct: str = "",  # v11.0 新增
    suspended_holding: str = "",                            # v11.0 新增
    highest_corr_pair: str = "", highest_corr_value: str = "",  # v11.0 新增
    lowest_corr_pair: str = "", lowest_corr_value: str = "",     # v11.0 新增
) -> str:
    """v11.0 AI 组合风险评估报告（增强流动性风险 / 相关性矩阵 / 通胀冲击）。

    Args:
        total_value/holdings_count/cash_pct: 组合规模/数量/现金比例
        industry_hhi: 行业集中度
        max_weight_pct: 个股最大权重
        last_rebalance_days: 上次调仓天数（v11.0 新增）
        style_drift: 风格漂移指标（v11.0 新增）
        portfolio_vol: 组合波动率
        max_dd_1y/3y: 1年/3年最大回撤
        var_95/99: VaR 95%/99%
        es_95: Expected Shortfall 95%
        stress_2008/covid: 2008/2020 压力测试
        ir_shock: 利率+100bp冲击
        inflation_shock: 通胀+200bp冲击（v11.0 新增）
        beta_market/size/value/momentum/quality: 因子暴露
        avg_daily_turnover: 持仓平均日成交额（v11.0 新增）
        days_to_liquidate: 变现 5% 用时（v11.0 新增）
        limit_up_holding_pct: 涨停板持仓占比（v11.0 新增）
        suspended_holding: 停牌/退市风险持仓（v11.0 新增）
        highest_corr_pair/value: 最高相关对（v11.0 新增）
        lowest_corr_pair/value: 最低相关对（v11.0 新增）
    """
    engine = ai_analysis_engine["get_engine"]()
    if engine is None:
        return _module_error("ai_analysis_engine")

    ctx = {
        "total_value": total_value, "holdings_count": holdings_count, "cash_pct": cash_pct,
        "industry_hhi": industry_hhi, "max_weight_pct": max_weight_pct,
        "last_rebalance_days": last_rebalance_days or "N/A",
        "style_drift": style_drift or "N/A",
        "portfolio_vol": portfolio_vol, "max_dd_1y": max_dd_1y, "max_dd_3y": max_dd_3y,
        "var_95": var_95, "var_99": var_99, "es_95": es_95,
        "stress_2008": stress_2008, "stress_covid": stress_covid, "ir_shock": ir_shock,
        "inflation_shock": inflation_shock or "N/A",
        "beta_market": beta_market, "beta_size": beta_size, "beta_value": beta_value,
        "beta_momentum": beta_momentum, "beta_quality": beta_quality,
        "avg_daily_turnover": avg_daily_turnover or "N/A",
        "days_to_liquidate": days_to_liquidate or "N/A",
        "limit_up_holding_pct": limit_up_holding_pct or "N/A",
        "suspended_holding": suspended_holding or "N/A",
        "highest_corr_pair": highest_corr_pair or "N/A",
        "highest_corr_value": highest_corr_value or "N/A",
        "lowest_corr_pair": lowest_corr_pair or "N/A",
        "lowest_corr_value": lowest_corr_value or "N/A",
    }
    try:
        result = await asyncio.to_thread(engine.analyze, "risk_report", ctx)
        output = {
            "success": result.success,
            "is_fallback": result.is_fallback,
            "model": result.model,
        }
        if result.error:
            output["error"] = result.error
        output["analysis"] = result.content[:8000]
        return json.dumps(output, ensure_ascii=False, indent=2)[:10000]
    except Exception as e:
        return f"❌ 风险评估异常: {str(e)}"


@server.tool()
async def ai_analyze_sector_rotation(
    rps_top10: str = "", rps_bottom10: str = "",
    inflow_top5: str = "", outflow_bottom5: str = "",
    smart_money_inflow_top3: str = "",                       # v11.0 新增
    smart_money_outflow_top3: str = "",                      # v11.0 新增
    etf_inflow_top3: str = "", etf_outflow_top3: str = "",   # v11.0 新增
    all_pe_pct: str = "", all_pb_pct: str = "",
    hot_themes: str = "",
) -> str:
    """v11.0 AI 板块轮动分析（增强聪明钱动向 + ETF 申赎方向）。

    Args:
        rps_top10: RPS 排名前 10 行业
        rps_bottom10: RPS 排名后 10 行业
        inflow_top5: 5日资金流入前 5
        outflow_bottom5: 5日资金流处前 5
        smart_money_inflow_top3: 聪明钱净流入前 3（v11.0 新增）
        smart_money_outflow_top3: 聪明钱净流出前 3（v11.0 新增）
        etf_inflow_top3: ETF 净申购前 3（v11.0 新增）
        etf_outflow_top3: ETF 净赎回前 3（v11.0 新增）
        all_pe_pct/all_pb_pct: 全A PE/PB 历史分位
        hot_themes: 当前热门主题
    """
    engine = ai_analysis_engine["get_engine"]()
    if engine is None:
        return _module_error("ai_analysis_engine")

    ctx = {
        "rps_top10": rps_top10 or "无数据",
        "rps_bottom10": rps_bottom10 or "无数据",
        "inflow_top5": inflow_top5 or "无数据",
        "outflow_bottom5": outflow_bottom5 or "无数据",
        "smart_money_inflow_top3": smart_money_inflow_top3 or "无数据",
        "smart_money_outflow_top3": smart_money_outflow_top3 or "无数据",
        "etf_inflow_top3": etf_inflow_top3 or "无数据",
        "etf_outflow_top3": etf_outflow_top3 or "无数据",
        "all_pe_pct": all_pe_pct, "all_pb_pct": all_pb_pct,
        "hot_themes": hot_themes or "无数据",
    }
    try:
        result = await asyncio.to_thread(engine.analyze, "sector_rotation", ctx)
        output = {
            "success": result.success,
            "is_fallback": result.is_fallback,
            "model": result.model,
        }
        if result.error:
            output["error"] = result.error
        output["analysis"] = result.content[:8000]
        return json.dumps(output, ensure_ascii=False, indent=2)[:10000]
    except Exception as e:
        return f"❌ 板块轮动分析异常: {str(e)}"


# ============================================================================
# 2.5 v11.0 新增 AI 工具（4 个）
# ============================================================================

@server.tool()
async def ai_analyze_futures(
    contract: str = "",
    symbol: str = "",
    exchange: str = "SHFE",
    delivery_month: str = "",
    price: str = "", change: str = "", change_pct: str = "",
    open: str = "", high: str = "", low: str = "", prev_settlement: str = "",
    open_interest: str = "", volume: str = "", oi_change: str = "",
    turnover: str = "",
    spot_price: str = "", basis: str = "", basis_pct: str = "",
    spread_near_far: str = "", roll_yield: str = "",
    top5_long: str = "", top5_short: str = "",
    oi_concentration: str = "", long_short_ratio: str = "",
    inventory: str = "", inventory_chg: str = "", spot_premium: str = "",
    atr: str = "", vol_20d: str = "", vol_60d: str = "",
    forecast_5d: str = "", forecast_20d: str = "",
) -> str:
    """v11.0 AI 期货专项分析（持仓/基差/龙虎榜/跨期套利/展期收益）。

    Args:
        contract: 合约代码（如 AU2502）
        symbol: 品种（AU/CU/AG 等）
        exchange: 交易所（SHFE/DCE/CZCE/CFFEX）
        delivery_month: 交割月份
        price/change/change_pct: 最新价/涨跌/涨跌幅
        open/high/low/prev_settlement: 今开/最高/最低/昨结
        open_interest/volume/oi_change/turnover: 持仓量/成交量/日增仓/成交额
        spot_price/basis/basis_pct: 现货价/基差/基差率
        spread_near_far: 近月-远月价差
        roll_yield: 展期收益年化
        top5_long/top_short: 前 5 多/空持仓
        oi_concentration/long_short_ratio: 净持仓集中度/多空比
        inventory/inventory_chg/spot_premium: 库存/库存环比/现货升贴水
        atr/vol_20d/vol_60d: ATR/20日波动率/60日波动率
        forecast_5d/forecast_20d: 5日/20日预测置信区间
    """
    engine = ai_analysis_engine["get_engine"]()
    if engine is None:
        return _module_error("ai_analysis_engine")

    context = {
        "contract": contract, "symbol": symbol, "exchange": exchange,
        "delivery_month": delivery_month or "主力",
        "price": price, "change": change, "change_pct": change_pct,
        "open": open, "high": high, "low": low,
        "prev_settlement": prev_settlement or "N/A",
        "open_interest": open_interest, "volume": volume,
        "oi_change": oi_change or "N/A", "turnover": turnover or "N/A",
        "spot_price": spot_price or "N/A",
        "basis": basis or "N/A", "basis_pct": basis_pct or "N/A",
        "spread_near_far": spread_near_far or "N/A",
        "roll_yield": roll_yield or "N/A",
        "top5_long": top5_long or "N/A", "top5_short": top5_short or "N/A",
        "oi_concentration": oi_concentration or "N/A",
        "long_short_ratio": long_short_ratio or "N/A",
        "inventory": inventory or "N/A", "inventory_chg": inventory_chg or "N/A",
        "spot_premium": spot_premium or "N/A",
        "atr": atr or "N/A", "vol_20d": vol_20d or "N/A", "vol_60d": vol_60d or "N/A",
        "forecast_5d": forecast_5d or "N/A",
        "forecast_20d": forecast_20d or "N/A",
    }
    try:
        result = await asyncio.to_thread(engine.analyze, "futures_analysis", context)
        output = {
            "success": result.success,
            "is_fallback": result.is_fallback,
            "model": result.model,
            "contract": contract,
        }
        if result.error:
            output["error"] = result.error
        output["analysis"] = result.content[:8000]
        return json.dumps(output, ensure_ascii=False, indent=2)[:10000]
    except Exception as e:
        return f"❌ 期货分析异常: {str(e)}"


@server.tool()
async def ai_analyze_money_flow(
    code: str = "", name: str = "",
    main_net_inflow: str = "", super_large_net: str = "",
    large_net: str = "", medium_net: str = "",
    small_net: str = "", main_pct: str = "",
    north_1d: str = "", north_5d: str = "", north_20d: str = "",
    north_holding_pct: str = "",
    margin_balance: str = "", margin_1d: str = "", margin_5d: str = "",
    short_balance: str = "", margin_buy_pct: str = "",
    etf_name: str = "", etf_flow_1d: str = "", etf_flow_5d: str = "",
    etf_premium: str = "",
    smart_money_score: str = "", abnormal_orders: str = "",
    smart_money_direction: str = "",
    limit_up_count: str = "", limit_down_count: str = "",
    abnormal_amplitude_count: str = "", abnormal_volume_count: str = "",
) -> str:
    """v11.0 AI 资金流分析（主力+北向+融资+ETF+聪明钱）。

    Args:
        code/name: 标的代码/名称
        main_net_inflow/super_large_net/large_net/medium_net/small_net: 各级资金净流入
        main_pct: 主力净流入占比
        north_1d/5d/20d: 北向持股 1/5/20日变化
        north_holding_pct: 北向持股比例
        margin_balance/1d/5d: 融资余额及变化
        short_balance: 融券余额
        margin_buy_pct: 融资买入额占比
        etf_name/flow_1d/flow_5d: 对应 ETF 名称及净申赎
        etf_premium: ETF 折溢价率
        smart_money_score: 聪明钱评分 0-100
        abnormal_orders: 异常订单笔数
        smart_money_direction: 大单净买入方向（买入/卖出/中性）
        limit_up_count/limit_down_count: 5日涨停/跌停次数
        abnormal_amplitude_count: 振幅异常次数
        abnormal_volume_count: 成交量异动次数
    """
    engine = ai_analysis_engine["get_engine"]()
    if engine is None:
        return _module_error("ai_analysis_engine")

    context = {
        "code": code, "name": name or code,
        "main_net_inflow": main_net_inflow, "super_large_net": super_large_net,
        "large_net": large_net, "medium_net": medium_net,
        "small_net": small_net, "main_pct": main_pct,
        "north_1d": north_1d or "N/A", "north_5d": north_5d or "N/A",
        "north_20d": north_20d or "N/A",
        "north_holding_pct": north_holding_pct or "N/A",
        "margin_balance": margin_balance or "N/A",
        "margin_1d": margin_1d or "N/A", "margin_5d": margin_5d or "N/A",
        "short_balance": short_balance or "N/A",
        "margin_buy_pct": margin_buy_pct or "N/A",
        "etf_name": etf_name or "N/A", "etf_flow_1d": etf_flow_1d or "N/A",
        "etf_flow_5d": etf_flow_5d or "N/A",
        "etf_premium": etf_premium or "N/A",
        "smart_money_score": smart_money_score or "N/A",
        "abnormal_orders": abnormal_orders or "N/A",
        "smart_money_direction": smart_money_direction or "中性",
        "limit_up_count": limit_up_count or "0",
        "limit_down_count": limit_down_count or "0",
        "abnormal_amplitude_count": abnormal_amplitude_count or "0",
        "abnormal_volume_count": abnormal_volume_count or "0",
    }
    try:
        result = await asyncio.to_thread(engine.analyze, "money_flow_analysis", context)
        output = {
            "success": result.success,
            "is_fallback": result.is_fallback,
            "model": result.model,
            "code": code, "name": name,
        }
        if result.error:
            output["error"] = result.error
        output["analysis"] = result.content[:8000]
        return json.dumps(output, ensure_ascii=False, indent=2)[:10000]
    except Exception as e:
        return f"❌ 资金流分析异常: {str(e)}"


@server.tool()
async def ai_analyze_index_forecast(
    code: str = "", name: str = "",
    price: str = "", change_pct: str = "",
    pe_ttm: str = "", pe_pct_10y: str = "", pe_pct_5y: str = "",
    pb_pct_10y: str = "", div_yield: str = "",
    ma20: str = "", ma60: str = "", ma120: str = "",
    ma_position: str = "", rsi: str = "", macd: str = "",
    rs_20d_vs_hs300: str = "", rs_60d_vs_hs300: str = "", rps_pct: str = "",
    adx: str = "", trend_score: str = "", momentum_score: str = "",
    tsf_yoy: str = "", bond_10y: str = "",
    industrial_yoy: str = "", dxy: str = "",
    forecast_1m_direction: str = "", forecast_1m_prob: str = "",
    forecast_3m_direction: str = "", forecast_3m_prob: str = "",
    forecast_6m_direction: str = "", forecast_6m_prob: str = "",
) -> str:
    """v11.0 AI 指数预测（PE分位+RS评分+多周期方向）。

    Args:
        code/name: 指数代码/名称
        price/change_pct: 最新点位/涨跌幅
        pe_ttm: PE-TTM
        pe_pct_10y/pe_pct_5y: 10年/5年 PE 分位
        pb_pct_10y: PB 分位
        div_yield: 股息率
        ma20/60/120: 20/60/120 日均线
        ma_position: 当前相对位置
        rsi/macd: 技术指标
        rs_20d_vs_hs300/rs_60d_vs_hs300: 相对沪深 300 强度
        rps_pct: RPS 百分位
        adx: 趋势强度
        trend_score/momentum_score: 趋势/动量评分 0-100
        tsf_yoy: 社融存量同比
        bond_10y: 10 年期国债收益率
        industrial_yoy: 工业增加值同比
        dxy: 美元指数
        forecast_1m/3m/6m_direction/prob: 多周期方向预测
    """
    engine = ai_analysis_engine["get_engine"]()
    if engine is None:
        return _module_error("ai_analysis_engine")

    context = {
        "code": code, "name": name or code,
        "price": price, "change_pct": change_pct,
        "pe_ttm": pe_ttm, "pe_pct_10y": pe_pct_10y, "pe_pct_5y": pe_pct_5y,
        "pb_pct_10y": pb_pct_10y, "div_yield": div_yield,
        "ma20": ma20, "ma60": ma60, "ma120": ma120,
        "ma_position": ma_position or "N/A",
        "rsi": rsi or "N/A", "macd": macd or "N/A",
        "rs_20d_vs_hs300": rs_20d_vs_hs300 or "N/A",
        "rs_60d_vs_hs300": rs_60d_vs_hs300 or "N/A",
        "rps_pct": rps_pct or "N/A",
        "adx": adx or "N/A", "trend_score": trend_score or "N/A",
        "momentum_score": momentum_score or "N/A",
        "tsf_yoy": tsf_yoy or "N/A", "bond_10y": bond_10y or "N/A",
        "industrial_yoy": industrial_yoy or "N/A", "dxy": dxy or "N/A",
        "forecast_1m_direction": forecast_1m_direction or "中性",
        "forecast_1m_prob": forecast_1m_prob or "50",
        "forecast_3m_direction": forecast_3m_direction or "中性",
        "forecast_3m_prob": forecast_3m_prob or "50",
        "forecast_6m_direction": forecast_6m_direction or "中性",
        "forecast_6m_prob": forecast_6m_prob or "50",
    }
    try:
        result = await asyncio.to_thread(engine.analyze, "index_forecast", context)
        output = {
            "success": result.success,
            "is_fallback": result.is_fallback,
            "model": result.model,
            "code": code,
        }
        if result.error:
            output["error"] = result.error
        output["analysis"] = result.content[:8000]
        return json.dumps(output, ensure_ascii=False, indent=2)[:10000]
    except Exception as e:
        return f"❌ 指数预测异常: {str(e)}"


@server.tool()
async def ai_analyze_portfolio(
    total_value: str = "", holdings_count: str = "", cash_pct: str = "",
    annual_return: str = "", benchmark_return: str = "", alpha: str = "",
    allocation_contribution: str = "", selection_contribution: str = "",
    interaction_contribution: str = "",
    holdings_detail: str = "",
    industry_hhi: str = "", max_weight_pct: str = "", top3_pct: str = "",
    size_exposure: str = "", value_growth_exposure: str = "",
    quality_score: str = "", momentum_score: str = "",
    last_rebalance_days: str = "", target_drift: str = "",
    suggested_turnover: str = "", rebalance_method: str = "",
    current_dd: str = "", max_dd_1y: str = "", dd_recovery_days: str = "",
) -> str:
    """v11.0 AI 组合诊断（业绩归因+再平衡+风格漂移+集中度）。

    Args:
        total_value/holdings_count/cash_pct: 组合规模/数量/现金比例
        annual_return/benchmark_return/alpha: 收益/基准/alpha
        allocation_contribution: 行业配置贡献
        selection_contribution: 个股选择贡献
        interaction_contribution: 交互作用贡献
        holdings_detail: 持仓明细（前 10）
        industry_hhi/max_weight_pct/top3_pct: 集中度
        size_exposure/value_growth_exposure: 风格暴露
        quality_score/momentum_score: 质量/动量得分 0-10
        last_rebalance_days: 上次调仓天数
        target_drift: 目标偏离度
        suggested_turnover: 建议调仓幅度
        rebalance_method: 再平衡方式（定期/阈值/智能）
        current_dd/max_dd_1y: 当前/最大回撤
        dd_recovery_days: 回撤恢复天数
    """
    engine = ai_analysis_engine["get_engine"]()
    if engine is None:
        return _module_error("ai_analysis_engine")

    ctx = {
        "total_value": total_value, "holdings_count": holdings_count, "cash_pct": cash_pct,
        "annual_return": annual_return or "N/A",
        "benchmark_return": benchmark_return or "N/A",
        "alpha": alpha or "N/A",
        "allocation_contribution": allocation_contribution or "N/A",
        "selection_contribution": selection_contribution or "N/A",
        "interaction_contribution": interaction_contribution or "N/A",
        "holdings_detail": holdings_detail or "无明细",
        "industry_hhi": industry_hhi, "max_weight_pct": max_weight_pct,
        "top3_pct": top3_pct or "N/A",
        "size_exposure": size_exposure or "0.5",
        "value_growth_exposure": value_growth_exposure or "0.5",
        "quality_score": quality_score or "N/A", "momentum_score": momentum_score or "N/A",
        "last_rebalance_days": last_rebalance_days or "N/A",
        "target_drift": target_drift or "N/A",
        "suggested_turnover": suggested_turnover or "N/A",
        "rebalance_method": rebalance_method or "N/A",
        "current_dd": current_dd or "N/A", "max_dd_1y": max_dd_1y or "N/A",
        "dd_recovery_days": dd_recovery_days or "N/A",
    }
    try:
        result = await asyncio.to_thread(engine.analyze, "portfolio_diagnosis", ctx)
        output = {
            "success": result.success,
            "is_fallback": result.is_fallback,
            "model": result.model,
        }
        if result.error:
            output["error"] = result.error
        output["analysis"] = result.content[:8000]
        return json.dumps(output, ensure_ascii=False, indent=2)[:10000]
    except Exception as e:
        return f"❌ 组合诊断异常: {str(e)}"


# ============================================================================
# 3. 量化分析类工具
# ============================================================================

@server.tool()
async def run_master_council(code: str = "") -> str:
    """v9.5 大师圆桌共识评分（6位投资大师加权共识）。

    Args:
        code: 股票代码（A股 6位数字）
    """
    quick = agents_master_council["quick_master_council"]
    if quick is None:
        return _module_error("agents_master_council")

    try:
        report = await asyncio.to_thread(quick, code)
        if report is None:
            return f"❌ 无法获取 {code} 数据（数据源可能不可用）"

        # 格式化输出
        output = {
            "code": report.code,
            "name": report.name,
            "price": report.price,
            "consensus_score": getattr(report, "consensus_score", None),
            "consensus_signal": getattr(report, "consensus_signal", None),
            "agreement_ratio": getattr(report, "agreement_ratio", None),
            "bull_count": sum(1 for r in report.results if getattr(r, "score", 0) > 20),
            "bear_count": sum(1 for r in report.results if getattr(r, "score", 0) < -20),
            "neutral_count": sum(1 for r in report.results if -20 <= getattr(r, "score", 0) <= 20),
            "master_views": [
                {
                    "master": r.master,
                    "score": getattr(r, "score", None),
                    "signal": getattr(r, "signal", None),
                    "key_points": getattr(r, "key_points", [])[:3],
                } for r in report.results
            ],
        }
        return json.dumps(output, ensure_ascii=False, indent=2)[:6000]
    except Exception as e:
        return f"❌ 圆桌评分异常: {str(e)}"


@server.tool()
async def quick_predict(code: str = "") -> str:
    """v7.0 量化预测评分（七维评分 + 多周期预测）。

    Args:
        code: 股票代码
    """
    try:
        Researcher = core_analyzer["StockResearcher"]
        if Researcher is None:
            return _module_error("core_analyzer")
        researcher = await asyncio.to_thread(Researcher, code)
        result = await asyncio.to_thread(researcher.full_analysis)
        return json.dumps(result if isinstance(result, dict) else str(result),
                          ensure_ascii=False, indent=2)[:6000]
    except Exception as e:
        return f"❌ 预测异常: {str(e)}"


@server.tool()
async def predict_multi_horizon(code: str = "", prices: str = "",
                                 regime: str = "", horizons: str = "") -> str:
    """v11.0 多周期预测（1d/5d/1M/3M/6M，股票/基金/期货/指数通用）。

    Args:
        code: 资产代码（如 600519、000001、AU2502、idx:000300）
        prices: 可选历史价格序列（逗号分隔，如 "100,101,102,...，留空自动拉取）
        regime: 当前市场体制（bullish/bearish/neutral，可选）
        horizons: 周期列表（逗号分隔，如 "1d,5d,1M"，留空用全部）
    """
    predict_fn = prediction_v1100["predict_multi_horizon"]
    if predict_fn is None:
        return _module_error("prediction_v1100")

    try:
        # 解析价格序列
        price_list: Optional[List[float]] = None
        if prices:
            try:
                price_list = [float(x.strip()) for x in prices.split(",") if x.strip()]
            except ValueError:
                return f"❌ prices 参数格式错误，应为逗号分隔的数字"

        # 解析周期
        h_list: Optional[List[str]] = None
        if horizons:
            h_list = [h.strip() for h in horizons.split(",") if h.strip()]

        result = await asyncio.to_thread(
            predict_fn, code=code,
            prices=price_list,
            regime=regime or None,
            horizons=h_list,
        )
        output = {
            "code": result.code,
            "name": result.name,
            "asset_type": result.asset_type,
            "horizons": {k: v.to_dict() for k, v in result.horizons.items()},
            "overall_signal": result.overall_signal,
            "overall_confidence": result.overall_confidence,
            "timestamp": result.timestamp,
            "latency_ms": result.latency_ms,
            "disclaimer": result.disclaimer,
        }
        return json.dumps(output, ensure_ascii=False, indent=2)[:10000]
    except Exception as e:
        return f"❌ 多周期预测异常: {str(e)}"


# ============================================================================
# 4. 系统类工具
# ============================================================================

@server.tool()
async def get_skill_status() -> str:
    """v11.0 获取 stock-researcher 技能状态（版本/能力/数据源/AI引擎）。"""
    output = {
        "version": VERSION,
        "skill_name": "stock-researcher",
        "display_name": "全球智能投研",
        "disclaimer": constants.get("DISCLAIMER", "仅供学习参考，不构成投资建议"),
        "domestic_direct_required": constants.get("DOMESTIC_DIRECT_REQUIRED", ""),
        "v11_changelog": [
            "新增 4 数据源适配器: 新浪/雪球/期货所/同花顺",
            "新增 DataCategory: FUTURES_HISTORY/MONEY_FLOW/SENTIMENT",
            "AI 模板扩充: 7 → 11 类 (新增期货/资金流/指数预测/组合诊断)",
            "AI 模板增强: market_regime/macro_outlook/risk_report/sector_rotation 加入多维证据",
            "新增多周期预测器 prediction_v1100.py (1d/5d/1M/3M/6M)",
            "ETag/If-Modified-Since 缓存 + 时效分级 + 多源交叉验证 + 3σ 异常检测",
            "新增 ExternalMCPAdapter (金融六日外部 MCP 桥接占位)",
            "MCP 工具: 14 → 20 (新增 futures/money_flow/index_forecast/portfolio AI + get_futures_quote + predict_multi_horizon)",
        ],
    }

    # 数据源状态
    try:
        router = data_multi_source["get_router"]()
        if router:
            sources = router.list_available_sources()
            output["data_sources"] = {
                "available": [k for k, v in sources.items() if v],
                "unavailable": [k for k, v in sources.items() if not v],
            }
    except Exception:
        output["data_sources"] = {"error": "data_multi_source 未加载"}

    # AI 引擎状态
    try:
        engine = ai_analysis_engine["get_engine"]()
        if engine:
            output["ai_engine"] = engine.status()
            output["ai_engine"]["v11_template_count"] = 11
    except Exception:
        output["ai_engine"] = {"error": "ai_analysis_engine 未加载"}

    # 工具列表（v11.0 完整 20 个）
    output["mcp_tools"] = [
        # 数据查询（5）
        "get_stock_quote", "get_fund_nav", "get_macro_data",
        "get_futures_quote", "list_data_sources",
        # AI 分析（11）
        "ai_analyze_stock", "ai_analyze_fund", "ai_analyze_market_regime",
        "ai_analyze_master_council", "ai_analyze_macro_outlook",
        "ai_analyze_risk_report", "ai_analyze_sector_rotation",
        "ai_analyze_futures", "ai_analyze_money_flow",
        "ai_analyze_index_forecast", "ai_analyze_portfolio",
        # 量化分析（3）
        "run_master_council", "quick_predict", "predict_multi_horizon",
        # 系统（1）
        "get_skill_status",
    ]
    output["total_tools"] = len(output["mcp_tools"])

    return json.dumps(output, ensure_ascii=False, indent=2)[:8000]


# ============================================================================
# 主入口
# ============================================================================

def main():
    """MCP Server 入口 — 走 stdio 协议。"""
    log.info(f"stock-researcher MCP Server v{VERSION} 启动")
    server.run(transport="stdio")


if __name__ == "__main__":
    main()
