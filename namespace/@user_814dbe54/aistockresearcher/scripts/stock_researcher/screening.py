# -*- coding: utf-8 -*-
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from typing import Dict, List

# ==============================================================


# <<< screening/screening_engine.py >>>


# 统一筛选引擎 (v6.0.0)


# =====================


# 多市场股票/基金/板块投资价值筛选，含评分排序与分析理由。


# 纯 Python 标准库，零依赖。


# ==============================================================











SKILL_DIR = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(SKILL_DIR / "scripts"))

from stock_researcher.data.market_classifier import MarketClassifier
from stock_researcher.data.errors import safe_float


# ── 预设筛选策略 ──
PRESETS = {
    "graham_value": {
        "name": "格雷厄姆深度价值",
        "description": "低PE、低PB、低负债、高股息的价值股筛选",
        "criteria": {"pe_max": 15, "pb_max": 1.5, "debt_ratio_max": 50,
                     "roe_min": 10, "dividend_yield_min": 3},
    },
    "growth_reasonable": {
        "name": "合理成长 (GARP)",
        "description": "PE合理、盈利增长强劲的成长股",
        "criteria": {"pe_max": 40, "pe_min": 10, "revenue_growth_min": 15,
                     "roe_min": 15},
    },
    "dividend_aristocrats": {
        "name": "股息贵族",
        "description": "高股息、高派息率的稳定现金流企业",
        "criteria": {"dividend_yield_min": 3, "roe_min": 8,
                     "debt_ratio_max": 60},
    },
    "momentum_leaders": {
        "name": "动量领先",
        "description": "技术面强势、资金流入的动量股",
        "criteria": {"rsi_min": 40, "rsi_max": 75, "ma_status": "多头排列",
                     "avg_volume_min": 50000},
    },
    "quality_compounders": {
        "name": "质量复利",
        "description": "高ROE、低负债、稳定增长的优质企业",
        "criteria": {"roe_min": 15, "debt_ratio_max": 40,
                     "revenue_growth_min": 8},
    },
    "turnaround": {
        "name": "困境反转",
        "description": "低PB、ROE改善的潜在反转标的",
        "criteria": {"pb_max": 1.0, "roe_min": 0},
    },
}


@dataclass
class ScreeningCriteria:
    """筛选条件"""
    market: str = "cn"
    filters: Dict = field(default_factory=dict)
    ranking_key: str = "score"
    top_n: int = 20

    def to_dict(self) -> Dict:
        return {
            "market": self.market,
            "filters": self.filters,
            "ranking_key": self.ranking_key,
            "top_n": self.top_n,
        }


class UnifiedScreener:
    """
    统一筛选器

    支持股票、基金、板块三类资产的多条件筛选。
    每个结果附带评分和理由。

    用法:
        screener = UnifiedScreener()
        results = screener.screen_stocks({"pe_max": 20, "roe_min": 15}, market="hk", top_n=10)
        for r in results:
            print(f"{r['code']} {r['name']}: {r['score']}分")
            for reason in r['reasons']:
                print(f"  - {reason}")
    """

    def __init__(self):
        self._data = {}

    def screen_stocks(self, criteria: dict, market: str = "cn",
                      codes: List[str] = None, top_n: int = 20) -> List[dict]:
        """
        筛选股票。

        Args:
            criteria: 筛选条件字典。支持:
                pe_max, pe_min, pb_max, pb_min, roe_min, roe_max,
                debt_ratio_max, revenue_growth_min, dividend_yield_min,
                market_cap_min, market_cap_max, industry, sector,
                rsi_min, rsi_max, ma_status (多头排列/空头排列),
                avg_volume_min
            market: 市场 (cn/hk/us)
            codes: 可选指定代码列表，不传则自动加载
            top_n: 返回前N条

        Returns:
            List[dict]: 排序后的筛选结果，每个含 code/name/score/reasons
        """
        import math

        stock_pool = codes or self._load_stock_pool(market)
        results = []

        for stock in stock_pool[:200]:  # 限制扫描数量
            code = stock.get("code", "")
            name = stock.get("name", "")
            try:
                score, reasons, failed = self._score_stock(code, name, market, criteria, stock)
                if score > 0:
                    results.append({
                        "code": code, "name": name, "score": round(score, 1),
                        "reasons": reasons, "failed_criteria": failed,
                        "market": market,
                    })
            except Exception:
                continue

        results.sort(key=lambda x: x["score"], reverse=True)
        return results[:top_n]

    def screen_funds(self, criteria: dict, top_n: int = 20) -> List[dict]:
        """
        筛选基金。

        Args:
            criteria: 筛选条件。支持 min_score, max_drawdown_limit, min_sharpe,
                      max_expense_ratio, fund_type
            top_n: 返回前N条
        """
        try:
            from pkg.fund_analyzer import screen_funds as _screen_funds
            return _screen_funds(criteria, top_n=top_n)
        except ImportError:
            return [{"code": "", "name": "基金筛选需要 fund_analyzer 模块", "score": 0, "reasons": []}]

    def screen_sectors(self, market: str = "cn", top_n: int = 5) -> List[dict]:
        """
        筛选板块。

        按真实成分股行情（平均涨跌幅 + 主力净流入）综合排序。
        v9.1 修复：此前 avg_chg = len(codes) * 0.1 是编造的占位值，
        导致评分只与成分股数量正相关（大板块恒靠前），与真实行情无关。
        """
        try:
            from stock_researcher.sector_analysis.sectors import SectorAnalyzer
            analyzer = SectorAnalyzer()
            sector_map = analyzer.get_sector_map(market)
            results = []
            for sector_name, codes in sector_map.items():
                try:
                    sector = analyzer.analyze_sector(sector_name, market=market)
                    # 复用 SectorResult.score（真实涨跌幅 + 资金流），映射到 0~100
                    score = min(100, max(0, 50 + sector.score * 1.5))
                    results.append({
                        "name": sector_name, "code": sector_name,
                        "score": round(score, 1), "market": market,
                        "representatives": codes[:4],
                        "avg_change_pct": sector.avg_change_pct,
                        "net_flow": sector.total_net_flow,
                        "signal": sector.signal,
                        "reasons": [
                            f"平均涨跌幅 {sector.avg_change_pct:+.2f}%",
                            f"主力净流入 {sector.total_net_flow:+.0f} 万",
                            f"上涨 {sector.up_count} / 下跌 {sector.down_count}",
                            f"代表股: {', '.join(codes[:3])}",
                        ],
                    })
                except Exception:
                    continue
            results.sort(key=lambda x: x["score"], reverse=True)
            return results[:top_n]
        except Exception:
            return []

    def _score_stock(self, code: str, name: str, market: str,
                     criteria: dict, stock_data: dict = None) -> Tuple[float, List[str], List[str]]:
        """
        对单只股票评分。

        Returns:
            (score, reasons, failed_criteria)
        """
        stock_data = stock_data or {}
        score = 50.0
        reasons = []
        failed = []

        pe = safe_float(stock_data.get("pe", 0), 0)
        pb = safe_float(stock_data.get("pb", 0), 0)
        roe = safe_float(stock_data.get("roe", 0), 0)
        debt_ratio = safe_float(stock_data.get("debt_ratio", 0), 0)
        dividend_yield = safe_float(stock_data.get("dividend_yield", 0), 0)
        revenue_growth = safe_float(stock_data.get("revenue_growth", 0), 0)

        # PE 筛选
        if "pe_max" in criteria and pe > 0:
            if pe <= criteria["pe_max"]:
                score += 10
                reasons.append(f"PE={pe:.1f}，低于上限{criteria['pe_max']}，估值合理")
            else:
                score -= 5
                failed.append(f"PE={pe:.1f} > {criteria['pe_max']}")
        if "pe_min" in criteria and pe > 0:
            if pe >= criteria["pe_min"]:
                score += 3
            else:
                failed.append(f"PE={pe:.1f} < {criteria['pe_min']}")

        # PB 筛选
        if "pb_max" in criteria and pb > 0:
            if pb <= criteria["pb_max"]:
                score += 8
                reasons.append(f"PB={pb:.2f}，低于上限{criteria['pb_max']}")
            else:
                score -= 5
                failed.append(f"PB={pb:.2f} > {criteria['pb_max']}")

        # ROE 筛选
        if "roe_min" in criteria and roe > 0:
            if roe >= criteria["roe_min"]:
                score += 12
                reasons.append(f"ROE={roe:.1f}%，高于{criteria['roe_min']}%，盈利质量好")
            else:
                score -= 8
                failed.append(f"ROE={roe:.1f}% < {criteria['roe_min']}%")

        # 负债率筛选
        if "debt_ratio_max" in criteria:
            if debt_ratio <= criteria["debt_ratio_max"]:
                score += 6
                reasons.append(f"资产负债率={debt_ratio:.1f}%，财务稳健")
            else:
                score -= 4
                failed.append(f"资产负债率={debt_ratio:.1f}% > {criteria['debt_ratio_max']}%")

        # 股息率筛选
        if "dividend_yield_min" in criteria:
            if dividend_yield >= criteria["dividend_yield_min"]:
                score += 8
                reasons.append(f"股息率={dividend_yield:.1f}%，高于{criteria['dividend_yield_min']}%")
            else:
                failed.append(f"股息率={dividend_yield:.1f}% < {criteria['dividend_yield_min']}%")

        # 营收增长
        if "revenue_growth_min" in criteria:
            if revenue_growth >= criteria["revenue_growth_min"]:
                score += 8
                reasons.append(f"营收增长={revenue_growth:.1f}%，高于{criteria['revenue_growth_min']}%")
            else:
                score -= 3
                failed.append(f"营收增长={revenue_growth:.1f}% < {criteria['revenue_growth_min']}%")

        # 行业匹配
        if "industry" in criteria and stock_data.get("industry"):
            if criteria["industry"] in str(stock_data.get("industry", "")):
                score += 5
                reasons.append(f"行业匹配: {criteria['industry']}")

        # 如果没有匹配到任何条件
        if not reasons:
            reasons.append("基础评分")

        # 归一化到 0-100
        score = max(0, min(100, score))
        return (score, reasons, failed)

    def _load_stock_pool(self, market: str) -> List[dict]:
        """加载股票池"""
        if market == "cn":
            try:
                from stock_researcher.data.market_all_stocks_crawler import MarketAllStocksCrawler
                crawler = MarketAllStocksCrawler()
                return crawler.fetch_all_stocks()
            except Exception:
                pass
        elif market == "hk":
            try:
                from stock_researcher.data.hk_market import HkMarketData
                return HkMarketData.fetch_all_hk_stocks()
            except Exception:
                pass
        elif market == "us":
            try:
                from stock_researcher.data.us_market import UsMarketData
                return UsMarketData.fetch_all_us_stocks()
            except Exception:
                pass

        # 回退：返回可用板块的代表股
        try:
            from stock_researcher.sector_analysis.sectors import SectorAnalyzer
            analyzer = SectorAnalyzer()
            sector_map = analyzer.get_sector_map(market)
            stocks = []
            for sector, codes in sector_map.items():
                for c in codes:
                    stocks.append({"code": c, "name": "", "industry": sector})
            return stocks
        except Exception:
            return []


def get_preset(name: str) -> dict:
    """获取预设筛选策略"""
    return PRESETS.get(name, PRESETS.get("graham_value", {}))


# ==============================================================


# <<< screening/reasoning.py >>>


# 筛选理由生成器 (v6.0.0)


# =======================


# 为筛选结果生成自然语言分析理由，引用具体数据源。


# ==============================================================














class ReasoningGenerator:
    """筛选理由生成器

    为每只通过筛选的股票/基金/板块生成结构化理由，
    每条理由引用具体数据来源和阈值。
    """

    REASON_TEMPLATES_CN = {
        "pe_low": "市盈率 {pe:.1f}，低于行业平均水平，估值具有安全边际",
        "pe_high": "市盈率 {pe:.1f} 偏高，需关注盈利增长能否支撑估值",
        "pb_low": "市净率 {pb:.2f}，低于净资产，可能存在低估机会",
        "roe_high": "ROE {roe:.1f}%，连续保持高盈利能力，盈利质量扎实",
        "roe_improving": "ROE 呈上升趋势（从 {roe_prev:.1f}% → {roe:.1f}%），盈利改善明显",
        "debt_low": "资产负债率 {debt:.1f}%，财务杠杆较低，抗风险能力强",
        "debt_high": "资产负债率 {debt:.1f}% 偏高，需注意债务风险",
        "dividend_high": "股息率 {div_yield:.1f}%，持续为股东创造现金回报",
        "dividend_growth": "股息连续 {consecutive_years} 年增长，分红记录优秀",
        "growth_strong": "营收同比增长 {growth:.1f}%，增长动力强劲",
        "momentum_strong": "技术面多头排列，RSI={rsi:.0f}，短期动能充足",
        "money_inflow": "主力资金净流入 {flow:.0f}万，机构关注度提升",
        "sentiment_positive": "舆情偏正面（{sentiment_score:.0f}分），市场情绪乐观",
        "sentiment_negative": "舆情偏负面（{sentiment_score:.0f}分），短期需谨慎",
        "sector_leading": "所属 {industry} 板块资金持续流入，板块轮动有利",
        "sector_lagging": "所属 {industry} 板块资金流出，板块承压",
        "market_cap_large": "市值 {cap:.0f}亿，大盘蓝筹，流动性充足",
        "market_cap_small": "市值 {cap:.0f}亿，中小盘，成长弹性大",
        "margin_of_safety": "当前价格低于内在价值 {margin:.1f}%，安全边际充足",
        "risk_warning_volatility": "近期波动率偏高（ATR%={atr:.1f}%），短期波动风险较大",
    }

    def generate_stock_reasons(self, code: str, name: str, score: float,
                                matched: List[str], data: Dict = None) -> List[str]:
        """为筛选通过的股票生成理由"""
        data = data or {}
        reasons = []

        # 添加得分概况
        reasons.append(f"综合评分 {score:.1f}/100")

        # 添加已匹配的理由
        for reason in matched:
            reasons.append(reason)

        # 如果没有匹配到具体理由，生成基础理由
        if not matched:
            name_str = name or code
            reasons.append(f"{name_str} ({code}) 满足基本筛选条件")
            if score > 70:
                reasons.append("得分较高，多项条件表现优秀")
            elif score > 50:
                reasons.append("得分中等，部分条件达标")
            else:
                reasons.append("得分偏低，仅部分条件满足")

        return reasons

    def generate_fund_reasons(self, fund_code: str, fund_name: str,
                               score: float, dimensions: Dict = None) -> List[str]:
        """为筛选通过的基金生成理由"""
        dimensions = dimensions or {}
        reasons = [f"综合评分 {score:.1f}/100"]

        if dimensions.get("alpha", 0) > 2:
            reasons.append(f"Alpha={dimensions['alpha']:.1f}%，超额收益显著")
        if dimensions.get("sharpe", 0) > 0.8:
            reasons.append(f"Sharpe={dimensions['sharpe']:.2f}，风险调整收益优秀")
        if dimensions.get("sortino", 0) > 1.0:
            reasons.append(f"Sortino={dimensions['sortino']:.2f}，下行风险控制好")
        if dimensions.get("max_drawdown", 100) > -15:
            reasons.append(f"最大回撤 {dimensions['max_drawdown']:.1f}%，回撤控制良好")
        if dimensions.get("expense_ratio", 10) < 1.0:
            reasons.append(f"费率 {dimensions['expense_ratio']:.2f}%，成本较低")

        return reasons

    def generate_sector_reasons(self, sector_name: str, score: float,
                                 market: str = "cn", data: Dict = None) -> List[str]:
        """为板块生成理由"""
        data = data or {}
        return [
            f"板块 {sector_name} 综合评分 {score:.1f}/100",
            f"市场: {market}",
            f"代表股: {', '.join(data.get('representatives', [])[:4])}",
        ]


# ==============================================================


# <<< screening/__init__.py (exports) >>>


# Screening module v6.0.0 — 投资价值筛选引擎


# ==============================================================






