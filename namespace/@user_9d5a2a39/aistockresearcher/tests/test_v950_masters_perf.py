#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v9.5 升级回归测试 — 大佬策略参考面板 + 分析性能优化（离线，不联网）。

覆盖：
  1. MasterInput：快照构建与派生特征（动量/波动/回撤/52周位置）
  2. 六位大佬策略：索罗斯/费雪/达利欧/马克斯/格林布拉特/利弗莫尔 方向性 + 降级
  3. MasterCouncil：圆桌加权共识/一致度/中文报告
  4. 性能优化：行情+K线并行拉取 / predict 并行链路冒烟
  5. 接线：语音意图 masters + 顶层懒加载导出 + 版本一致性
"""
import json
import math
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from stock_researcher.agents_master_input import MasterInput, MasterResult, score_to_signal
from stock_researcher.agents_master_council import MasterCouncil, CouncilReport, quick_master_council
from stock_researcher.agents_soros import SorosAnalyzer
from stock_researcher.agents_fisher import FisherAnalyzer
from stock_researcher.agents_dalio import DalioAnalyzer
from stock_researcher.agents_marks import MarksAnalyzer
from stock_researcher.agents_greenblatt import GreenblattAnalyzer
from stock_researcher.agents_livermore import LivermoreAnalyzer


# ── 确定性样本 ──────────────────────────────────────────────

def _up_series(n=300, daily=0.002):
    """平滑上行序列（低波动牛市代理）"""
    p, out = 100.0, []
    for _ in range(n):
        p *= 1 + daily
        out.append(p)
    return out


def _down_series(n=300, daily=-0.003):
    """平滑下行序列（熊市代理）"""
    p, out = 100.0, []
    for _ in range(n):
        p *= 1 + daily
        out.append(p)
    return out


def _bull_snapshot(**kw):
    defaults = dict(code="600519", name="测试牛", price=0, pe=25,
                    roe=20, revenue_growth=25, net_margin=22,
                    closes=_up_series())
    defaults.update(kw)
    return MasterInput.from_market(**defaults)


def _bear_snapshot(**kw):
    defaults = dict(code="600519", name="测试熊", price=0, pe=60,
                    roe=-3, revenue_growth=-12, net_margin=-5,
                    closes=_down_series())
    defaults.update(kw)
    return MasterInput.from_market(**defaults)


# ══════════════ 1. MasterInput 快照与派生特征 ══════════════

def test_master_input_derived_features():
    inp = MasterInput.from_market(code="600519", closes=_up_series())
    assert inp.has_prices
    assert inp.ret_20 > 0 and inp.ret_60 > inp.ret_20
    assert inp.ann_vol >= 0
    assert inp.max_dd_250 <= 0
    assert 0.99 <= inp.pos_52w <= 1.0          # 平滑上行 → 顶部
    assert inp.price == pytest.approx(inp.closes[-1])


def test_master_input_bear_position_at_bottom():
    inp = MasterInput.from_market(closes=_down_series())
    assert 0.0 <= inp.pos_52w <= 0.02
    assert inp.ret_250 < -30


def test_master_input_insufficient_data():
    inp = MasterInput.from_market(closes=[100.0] * 5)
    assert not inp.has_prices
    assert inp.ret_20 == 0 and inp.ann_vol == 0


def test_master_input_filters_bad_prices():
    inp = MasterInput.from_market(closes=[0, -1, None, 100, 101] + [102] * 30)
    assert all(c > 0 for c in inp.closes)


def test_score_to_signal_mapping():
    assert score_to_signal(60) == "强烈买入"
    assert score_to_signal(30) == "买入"
    assert score_to_signal(0) == "中性"
    assert score_to_signal(-30) == "卖出"
    assert score_to_signal(-60) == "强烈卖出"
    assert score_to_signal(90, confidence=0.1) == "数据不足"


# ══════════════ 2. 六位大佬策略 ══════════════

def test_soros_bull_positive_bear_negative():
    az = SorosAnalyzer()
    bull, bear = az.analyze(_bull_snapshot()), az.analyze(_bear_snapshot())
    assert bull.score > 0 and bull.signal in ("买入", "强烈买入")
    assert bear.score < 0
    assert any("盛衰" in p or "反身" in p for p in bull.key_points)


def test_soros_no_prices_degrades():
    r = SorosAnalyzer().analyze(MasterInput())
    assert r.signal == "数据不足" and r.confidence == 0


def test_fisher_growth_scoring():
    az = FisherAnalyzer()
    bull = az.analyze(_bull_snapshot(pe=30))
    assert bull.score > 0                       # 高成长+高利润率+合理PEG
    bear = az.analyze(_bear_snapshot(pe=90))
    assert bear.score < 0                       # 负增长+亏损+高估值


def test_fisher_no_data_degrades():
    r = FisherAnalyzer().analyze(MasterInput())
    assert r.signal == "数据不足"


def test_dalio_quadrant_direction():
    az = DalioAnalyzer()
    bull, bear = az.analyze(_bull_snapshot()), az.analyze(_bear_snapshot())
    assert bull.score > 0
    assert bear.score < 0
    assert abs(bull.score) <= 60 and abs(bear.score) <= 60   # 宏观视角保守上限
    assert any("分散" in p for p in bull.key_points)


def test_marks_contrarian_temperature():
    az = MarksAnalyzer()
    hot = az.analyze(_bull_snapshot(pe=60))     # 高位+高估值+强动量 → 高温低分
    cold = az.analyze(_bear_snapshot(pe=8))     # 低位+低估值 → 低温高分
    assert hot.score < 0 < cold.score
    assert any("风险温度" in p for p in hot.key_points)
    assert any("钟摆" in p for p in cold.key_points)


def test_greenblatt_magic_formula():
    az = GreenblattAnalyzer()
    good = az.analyze(MasterInput.from_market(pe=12, roe=22, closes=_up_series()))
    bad = az.analyze(MasterInput.from_market(pe=90, roe=-3, closes=_up_series()))
    assert good.score > 0 and bad.score < 0
    r = az.analyze(MasterInput())
    assert r.signal == "数据不足"


def test_livermore_trend_structure():
    az = LivermoreAnalyzer()
    bull, bear = az.analyze(_bull_snapshot()), az.analyze(_bear_snapshot())
    assert bull.score > 0 and bull.signal in ("买入", "强烈买入")
    assert bear.score < 0
    assert any("关键点" in p or "多头排列" in p for p in bull.key_points)


def test_livermore_no_prices_degrades():
    r = LivermoreAnalyzer().analyze(MasterInput())
    assert r.signal == "数据不足"


# ══════════════ 3. MasterCouncil 圆桌共识 ══════════════

def test_council_full_snapshot_consensus():
    rep = MasterCouncil().analyze(_bull_snapshot(pe=25))
    assert rep.valid_count == 6
    assert -100 <= rep.consensus_score <= 100
    assert rep.consensus_signal != "数据不足"
    assert 0 <= rep.agreement <= 1
    assert rep.most_bullish and rep.most_bearish
    assert len(rep.results) == 6


def test_council_empty_snapshot_all_degrade():
    rep = MasterCouncil().analyze(MasterInput())
    assert rep.valid_count == 0
    assert rep.consensus_signal == "数据不足"


def test_council_format_report():
    rep = MasterCouncil().analyze(_bull_snapshot())
    txt = MasterCouncil.format(rep)
    assert "大佬圆桌" in txt
    for name in ("索罗斯", "费雪", "达利欧", "马克斯", "格林布拉特", "利弗莫尔"):
        assert name in txt
    assert "圆桌共识" in txt
    assert "不构成投资建议" in txt


def test_council_custom_weights():
    w = {"livermore": 1.0}  # 仅趋势大佬有权重，其余按默认小权重
    rep = MasterCouncil(weights=w).analyze(_bull_snapshot())
    assert rep.weights["livermore"] == 1.0
    assert rep.consensus_score != 0


def test_quick_master_council_helper():
    rep = quick_master_council(_bear_snapshot())
    assert isinstance(rep, CouncilReport)
    assert rep.valid_count >= 1


# ══════════════ 4. 性能优化 ══════════════

def test_fetch_quote_kline_parallel(monkeypatch):
    """行情+K线并行拉取：两个独立请求都返回结果"""
    import stock_predict as sp
    calls = []

    def fake_quote(code, silent=False, max_retries=3):
        calls.append("quote")
        return {"price": 10.0, "name": code}

    def fake_kline(code, days=120, silent=False):
        calls.append("kline")
        return [{"close": 10.0}]

    monkeypatch.setattr(sp, "fetch_quote", fake_quote)
    monkeypatch.setattr(sp, "fetch_kline", fake_kline)
    q, kl = sp.fetch_quote_kline("600519")
    assert q["price"] == 10.0 and kl
    assert calls.count("quote") == 1 and calls.count("kline") == 1


def test_predict_parallel_pipeline_smoke(monkeypatch):
    """predict 并行链路冒烟：假行情+假K线 → 完整评分输出"""
    import stock_predict as sp
    kl = [{"date": f"d{i}", "open": 10.0, "close": 10.0 + i * 0.01,
           "high": 11.0, "low": 9.5, "vol": 10000.0} for i in range(130)]

    monkeypatch.setattr(sp, "fetch_quote", lambda code, silent=False, max_retries=3: {
        "name": "测试股", "code": code, "market": "cn", "price": 11.3,
        "prev_close": 11.2, "open": 11.2, "vol": 1e6, "high": 11.4,
        "low": 11.1, "amount": 1e8, "change": 0.1, "chg_pct": 0.9,
        "pe": 15.0, "turnover": 1.2, "currency": "CNY"})
    monkeypatch.setattr(sp, "fetch_kline", lambda code, days=120, silent=False: kl)
    monkeypatch.setattr(sp, "_get_cached_risk_appetite", lambda: None)
    monkeypatch.setattr(sp, "_get_cached_gold_factors", lambda: None)

    r = sp.predict("600519", silent=True)
    assert "error" not in r
    assert r["technical"]["atr"] >= 0
    assert r["technical"]["atr_pct"] >= 0
    assert 0 <= r["score"]["total"] <= 100
    assert r["monte_carlo"]["5d"]["up"] >= 0


def test_predict_quote_error_short_circuit(monkeypatch):
    """行情失败时并行链路仍正确短路返回错误"""
    import stock_predict as sp
    monkeypatch.setattr(sp, "fetch_quote", lambda *a, **k: {"error": "网络失败"})
    monkeypatch.setattr(sp, "fetch_kline", lambda *a, **k: [])
    r = sp.predict("600519", silent=True)
    assert "error" in r and r["code"] == "600519"


# ══════════════ 5. 接线：语音意图 + 导出 + 版本 ══════════════

def test_voice_intent_masters():
    from stock_researcher.voice_interface import parse_voice_command
    cmd = parse_voice_command("大佬们怎么看茅台")
    assert cmd["intent"] == "masters" and cmd["code"] == "600519"
    cmd2 = parse_voice_command("圆桌讨论600519")
    assert cmd2["intent"] == "masters" and cmd2["code"] == "600519"
    cmd3 = parse_voice_command("大师们怎么看")
    assert cmd3["intent"] == "masters" and cmd3["code"] is None
    cmd4 = parse_voice_command("帮助")
    assert "大佬圆桌" in cmd4["echo"]


def test_agents_package_exports():
    # 平铺后 agents 命名空间由 agents_* 平铺模块聚合
    import types
    import stock_researcher.agents_master_input as _mi
    import stock_researcher.agents_master_council as _mc
    import stock_researcher.agents_buffett as _bu
    import stock_researcher.agents_graham as _gr
    import stock_researcher.agents_lynch as _ly
    ag = types.SimpleNamespace()
    for _m in (_mi, _mc, _bu, _gr, _ly):
        for _k in dir(_m):
            if not _k.startswith("_"):
                setattr(ag, _k, getattr(_m, _k))
    for name in ("MasterInput", "MasterResult", "score_to_signal",
                 "SorosAnalyzer", "FisherAnalyzer", "DalioAnalyzer",
                 "MarksAnalyzer", "GreenblattAnalyzer", "LivermoreAnalyzer",
                 "MasterCouncil", "CouncilReport", "quick_master_council",
                 "BuffettAnalyzer", "GrahamAnalyzer", "LynchAnalyzer"):
        assert hasattr(ag, name), name


def test_top_level_lazy_exports():
    import stock_researcher as sr
    # 双重导入路径下不做 identity 断言，校验懒加载导出存在且类名正确（同 test_v940 写法）
    for name in ("MasterInput", "MasterResult", "score_to_signal",
                 "SorosAnalyzer", "FisherAnalyzer", "DalioAnalyzer",
                 "MarksAnalyzer", "GreenblattAnalyzer", "LivermoreAnalyzer",
                 "MasterCouncil", "CouncilReport", "quick_master_council"):
        obj = getattr(sr, name)
        assert obj is not None, f"顶层缺少导出 {name}"
    assert sr.MasterCouncil.__name__ == "MasterCouncil"
    assert sr.MasterInput.__name__ == "MasterInput"
    assert callable(sr.quick_master_council)
    assert sr.__version__ == "11.0.0"


def test_version_sync_all_files():
    """v9.5 版本同步：7 处来源一致"""
    root = Path(__file__).resolve().parents[1]
    import re as _re
    import stock_researcher
    assert stock_researcher.__version__ == "11.0.0"

    init = (root / "stock_researcher" / "__init__.py").read_text(encoding="utf-8")
    const = (root / "stock_researcher" / "constants.py").read_text(encoding="utf-8")
    m_init = _re.search(r"__version__\s*=\s*[\"']([^\"']+)[\"']", init)
    m_const = _re.search(r"VERSION\s*=\s*[\"']([^\"']+)[\"']", const)
    assert m_init and m_init.group(1) == "11.0.0"
    assert m_const and m_const.group(1) == "11.0.0"

    meta = json.loads((root / "_meta.json").read_text(encoding="utf-8"))
    assert meta["version"] == "11.0.0"
    assert meta["maintenance"]["changelog"][0]["version"] == "11.0.0"
    settings = json.loads((root / "config" / "settings.json").read_text(encoding="utf-8"))
    assert settings["version"] == "11.0.0"
    assert settings["_version_info"]["version"] == "11.0.0"
    skill = (root / "SKILL.md").read_text(encoding="utf-8")
    assert "version: 11.0.0" in skill
