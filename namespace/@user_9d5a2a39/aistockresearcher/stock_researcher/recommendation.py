# -*- coding: utf-8 -*-
from __future__ import annotations
import sys
from pathlib import Path
from typing import Dict, List, Optional
from dataclasses import dataclass, field
from datetime import datetime

# ==============================================================


# <<< recommendation/recommendation_engine.py >>>


# 投资推荐引擎 (v4.0.0 新增)


# 


# 基于融合多周期预测，输出 短(1-5日)/中(1月)/长(1季) 三档


# 板块 + 个股推荐，每项带排名分、方向、具体理由(引用信号来源)、风险提示。


# ==============================================================











SKILL_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SKILL_DIR / "scripts"))

from stock_researcher.fusion_multi_horizon_forecaster import MultiHorizonForecaster, ForecastResult, MultiHorizonForecast

# 申万板块 → 代表股列表（与 sector_forecast 一致）
SECTOR_CODES = {
    "银行": ["600036","601318","600016","601166"],
    "非银金融": ["601601","600837","601628","601688"],
    "食品饮料": ["600519","000858","600887","603288"],
    "医药生物": ["000538","600276","603259","000661"],
    "电子": ["002475","603986","000725","600183"],
    "计算机": ["000977","002410","300033","600570"],
    "通信": ["000063","600050","601728","002281"],
    "传媒": ["300059","002027","603444","300413"],
    "军工": ["600893","002013","000733","601985"],
    "新能源": ["300750","002594","600900","601012"],
    "汽车": ["002594","000625","601127","600741"],
    "房地产": ["000002","600048","600383","001979"],
    "有色金属": ["601899","600111","000630","002460"],
    "基础化工": ["600309","002601","600486","000301"],
    "电力设备": ["600900","601012","002459","601615"],
}

# 各周期桶映射
HORIZON_BUCKETS = {
    "short": {"horizons": ["1d", "3d", "5d"], "label": "短期(1-5日)", "merge_key": "5d"},
    "mid":   {"horizons": ["1M"], "label": "中期(1个月)", "merge_key": "1M"},
    "long":  {"horizons": ["1Q"], "label": "长期(1个季度)", "merge_key": "1Q"},
}


@dataclass
class Recommendation:
    target_type: str       # "sector"|"stock"
    code: str              # 板块名或股票代码
    name: str
    horizon_bucket: str    # "short"/"mid"/"long"
    direction: str
    predicted_pct: float
    score: float           # 排名分(-100~+100,越高越推荐)
    confidence: float
    top_reasons: List[str] # 具体理由列表
    risk_notes: List[str]


class RecommendationEngine:
    """投资推荐引擎"""

    def __init__(self, seed: int = None):
        self._forecaster = MultiHorizonForecaster(seed=seed)
        self._sector_cache: Dict[str, MultiHorizonForecast] = {}
        self._stock_cache: Dict[str, MultiHorizonForecast] = {}

    def recommend_sectors(
        self, sectors: List[str] = None, bucket: str = "short",
        top_n: int = 5
    ) -> List[Recommendation]:
        """推荐板块"""
        sectors = sectors or list(SECTOR_CODES.keys())
        bucket_cfg = HORIZON_BUCKETS.get(bucket, HORIZON_BUCKETS["short"])
        merge_key = bucket_cfg["merge_key"]
        recs = []

        for s in sectors[:15]:
            codes = SECTOR_CODES.get(s, [])
            if not codes:
                continue
            if s not in self._sector_cache:
                try:
                    self._sector_cache[s] = self._forecaster.forecast_sector(s, codes,
                                                                              horizons=[merge_key])
                except Exception:
                    continue
            fc = self._sector_cache[s]
            fr = fc.horizons.get(merge_key)
            if not fr:
                continue
            reasons = [f"{dr['dimension']}面{dr['contribution']:+.0f}分: {dr['reason'][:35]}"
                       for dr in fr.top_drivers[:3]]

            recs.append(Recommendation(
                target_type="sector", code=s, name=s,
                horizon_bucket=bucket, direction=fr.direction,
                predicted_pct=fr.predicted_pct, score=fr.composite_score,
                confidence=fr.confidence,
                top_reasons=reasons, risk_notes=fr.risk_factors[:2],
            ))
        # 按得分排序
        recs.sort(key=lambda r: r.score, reverse=True)
        return recs[:top_n]

    def recommend_stocks(
        self, codes: List[str] = None, sector: str = None,
        bucket: str = "short", top_n: int = 5
    ) -> List[Recommendation]:
        """推荐个股"""
        if codes is None:
            parts = []
            if sector and sector in SECTOR_CODES:
                parts = SECTOR_CODES[sector]
            else:
                # 取所有板块 Top1 代表股
                for c_list in SECTOR_CODES.values():
                    parts.append(c_list[0])
            codes = list(dict.fromkeys(parts))
        bucket_cfg = HORIZON_BUCKETS.get(bucket, HORIZON_BUCKETS["short"])
        merge_key = bucket_cfg["merge_key"]
        recs = []
        for code in codes[:20]:
            c = str(code).zfill(6)
            if c not in self._stock_cache:
                try:
                    self._stock_cache[c] = self._forecaster.forecast_stock(
                        c, horizons=[merge_key])
                except Exception:
                    continue
            fc = self._stock_cache[c]
            fr = fc.horizons.get(merge_key)
            if not fr:
                continue
            reasons = [f"{dr['dimension']}面{dr['contribution']:+.0f}分: {dr['reason'][:35]}"
                       for dr in fr.top_drivers[:3]]
            recs.append(Recommendation(
                target_type="stock", code=c, name="",
                horizon_bucket=bucket, direction=fr.direction,
                predicted_pct=fr.predicted_pct, score=fr.composite_score,
                confidence=fr.confidence,
                top_reasons=reasons, risk_notes=fr.risk_factors[:2],
            ))
        recs.sort(key=lambda r: r.score, reverse=True)
        return recs[:top_n]

    def recommend_all(
        self, sectors: List[str] = None, top_n: int = 5
    ) -> Dict[str, Dict[str, List[Recommendation]]]:
        """三档全推：shortsector + mid + long，含板块和个股"""
        result = {}
        for bucket in ["short", "mid", "long"]:
            sectors_rec = self.recommend_sectors(sectors, bucket, top_n)
            # 从推荐板块中提取代表股做个股推荐
            stock_codes = []
            for sr in sectors_rec[:3]:
                stock_codes.extend(SECTOR_CODES.get(sr.code, [])[:2])
            stocks_rec = self.recommend_stocks(
                list(dict.fromkeys(stock_codes)), bucket=bucket, top_n=top_n)
            result[bucket] = {"sectors": sectors_rec, "stocks": stocks_rec}
        return result


def get_recommendations(
    horizon: str = "short", asset_type: str = "sector", top_n: int = 5
) -> List[Recommendation]:
    """便捷入口"""
    eng = RecommendationEngine()
    if asset_type == "stock":
        return eng.recommend_stocks(bucket=horizon, top_n=top_n)
    return eng.recommend_sectors(bucket=horizon, top_n=top_n)


def format_recommendations(recos: Dict[str, Dict[str, List[Recommendation]]]) -> str:
    lines = ["⭐ 投资推荐  |  " + datetime.now().strftime("%Y-%m-%d %H:%M"),
             "=" * 70]
    for bucket in ["short", "mid", "long"]:
        data = recos.get(bucket, {})
        hlabel = HORIZON_BUCKETS[bucket]["label"]
        sr = data.get("sectors", [])
        lines.append(f"")
        lines.append(f"【{hlabel} - 板块推荐】")
        if not sr:
            lines.append("  (暂无明确推荐板块)")
            continue
        for i, r in enumerate(sr, 1):
            lines.append(f"  #{i} [{r.code}] {r.direction} | 涨跌幅度{r.predicted_pct:+.2f}% "
                         f"| 得分{r.score:+.0f} | 置信{r.confidence:.0%}")
            for re in r.top_reasons[:2]:
                lines.append(f"       → {re}")
            if r.risk_notes:
                lines.append(f"       ⚠️ {r.risk_notes[0]}")
        st = data.get("stocks", [])
        if st:
            lines.append(f"  ── 代表个股 ──")
            for i, r in enumerate(st[:3], 1):
                lines.append(f"  #{i} [{r.code}] {r.direction} "
                             f"涨跌幅{r.predicted_pct:+.2f}% 得分{r.score:+.0f}")
    lines.append("=" * 70)
    return "\n".join(lines)


# ==============================================================


# <<< recommendation/fund_recommender.py >>>


# 基金推荐引擎 (v4.0.0 新增)


# 


# 基于 pkg/fund_analyzer 评分+风格漂移检测+超额收益归因，


# 对国内主流基金池进行短/中/长期推荐，每项附带评分依据。


# 


# 基金池覆盖股票型、混合型、指数型主流标的。


# ==============================================================











SKILL_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SKILL_DIR / "pkg"))
from fund_analyzer import score_fund, score_fund_v2, score_fund_v3  # noqa: E402

FUND_POOL = {
    "股票型": ["110022", "000083", "519069", "001410", "001717",
               "050001", "160626", "512800"],
    "混合型": ["163406", "519736", "001875", "001112", "005827",
               "162102", "000390", "001590"],
    "指数型": ["510050", "510300", "510500", "159915", "588000",
               "159949", "512880", "513050"],
}

CATEGORY_NAMES = {"股票型": "股票型基金", "混合型": "混合型基金", "指数型": "指数/ETF"}


@dataclass
class FundRecommendation:
    code: str
    name: str
    category: str
    score: int          # 0~100
    grade: str          # A/B/C/D
    style: str
    alpha: Optional[float]     # 超额收益
    sharpe: Optional[float]    # 夏普比率
    reasons: List[str]


class FundRecommender:
    """基金推荐器"""

    def recommend(
        self, category: str = "all", top_n: int = 8,
        scoring_version: str = "v2"
    ) -> List[FundRecommendation]:
        """
        基金推荐（v5.0 升级：支持 v2/v3 评分版本）。

        Args:
            category: all/股票型/混合型/指数型
            top_n: 返回数量
            scoring_version: v1/v2/v3 评分版本（默认 v2）
        """
        cats = list(FUND_POOL.keys()) if category == "all" else [category]
        recs = []
        for cat in cats:
            for code in FUND_POOL.get(cat, [])[:10]:
                try:
                    # v5.0: 根据 scoring_version 选择评分函数
                    if scoring_version == "v3":
                        r = score_fund_v3(code)
                    elif scoring_version == "v2":
                        r = score_fund_v2(code)
                    else:
                        r = score_fund(code)
                    recs.append(FundRecommendation(
                        code=code, name=r.get("name", code),
                        category=cat, score=r.get("score", 50),
                        grade=r.get("grade", "C"),
                        style=r.get("style", {}).get("current_style", ""),
                        alpha=r.get("attribution", {}).get("alpha"),
                        sharpe=r.get("attribution", {}).get("sharpe_ratio"),
                        reasons=r.get("details", []),
                    ))
                except Exception:
                    pass
        recs.sort(key=lambda r: r.score, reverse=True)
        return recs[:top_n]

    def recommend_by_horizon(
        self, top_n: int = 5,
        scoring_version: str = "v2"
    ) -> Dict[str, List[FundRecommendation]]:
        """短/中/长期分别推荐（v5.0: 支持 v2/v3 评分版本）
        短期: 偏指数型(流动性好)
        中期: 偏混合型(风格均衡)
        长期: 偏股票型(超额收益潜力)
        """
        all_recs = self.recommend("all", top_n=20, scoring_version=scoring_version)
        result = {}
        # 短期：取指数型 Top + 高分混合
        idx = [r for r in all_recs if r.category == "指数型"][:top_n]
        mix = [r for r in all_recs if r.category == "混合型"][:2]
        result["short"] = (idx + mix)[:top_n]
        # 中期：混合型为主
        result["mid"] = [r for r in all_recs if r.category in ("混合型", "股票型")][:top_n]
        # 长期：股票型为主
        result["long"] = [r for r in all_recs if r.category in ("股票型", "混合型")][:top_n]
        return result


def get_fund_recommendations(category: str = "all", top_n: int = 8) -> List[Dict]:
    recs = FundRecommender().recommend(category, top_n)
    return [
        {
            "code": r.code, "name": r.name, "category": r.category,
            "score": r.score, "grade": r.grade, "style": r.style,
            "alpha": f"{r.alpha:+.1f}%" if r.alpha else "N/A",
            "sharpe": r.sharpe,
            "reasons": r.reasons,
        }
        for r in recs
    ]


def format_fund_recommendations(recs: List[FundRecommendation]) -> str:
    lines = [f"💰 基金推荐  |  {datetime.now().strftime('%Y-%m-%d %H:%M')}",
             "=" * 65]
    for i, r in enumerate(recs, 1):
        alpha_str = f"{r.alpha:+.1f}%" if r.alpha else "N/A"
        shrp_str = f"{r.sharpe:.2f}" if r.sharpe else "N/A"
        lines.append(
            f"  #{i} [{r.code}] {r.name}  {r.grade}({r.score})  "
            f"α={alpha_str}  Sharpe={shrp_str}  {r.style}"
        )
        for re in r.reasons[:2]:
            lines.append(f"       → {re}")
        lines.append("")
    lines.append("=" * 65)
    return "\n".join(lines)


# ==============================================================


# <<< recommendation/__init__.py (exports) >>>


# recommendation 包 — 投资推荐引擎 (v4.0.0 新增)


# 


# - recommendation_engine: 基于融合预测的短/中/长期板块+个股推荐(带具体理由)


# - fund_recommender: 基金推荐(复用 fund_analyzer 评分+归因)


# ==============================================================








__all__ = [
    "RecommendationEngine", "get_recommendations",
    "FundRecommender", "get_fund_recommendations",
]
