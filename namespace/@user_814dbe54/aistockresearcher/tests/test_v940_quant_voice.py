#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v9.4 升级回归测试 — 高级量化统计计算 + 语音交互（离线，不联网）。

覆盖：
  1. advanced_stats：滚动指标/稳定性/回撤剖析/仓位计算/统计检验/自相关/业绩归因/相关矩阵/一站式体检
  2. voice_interface：播报压缩 / 口语指令解析 / VoiceResearchChat 假回调闭环
  3. 接线：quantitative 包导出 + 顶层懒加载导出 + 版本一致性
"""
import math
import random
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from stock_researcher.quantitative.advanced_stats import (
    rolling_metrics, rolling_stability, drawdown_report,
    kelly_fraction, fixed_fractional_size, vol_target_weight,
    skewness, kurtosis, jarque_bera, autocorrelation, ljung_box,
    tracking_error, information_ratio, up_down_capture,
    correlation_matrix, quick_advanced_stats,
)
from stock_researcher.voice_interface import (
    summarize_for_speech, parse_voice_command, VoiceResearchChat,
)


# ── 确定性样本 ──────────────────────────────────────────────

def _trend_prices(n=200, drift=0.001, vol=0.01, seed=42):
    random.seed(seed)
    p, out = 100.0, []
    for _ in range(n):
        p *= 1 + drift + random.gauss(0, vol)
        out.append(p)
    return out


def _returns(prices):
    return [prices[i] / prices[i - 1] - 1 for i in range(1, len(prices))]


# ══════════════ 1. 滚动指标与稳定性 ══════════════

def test_rolling_metrics_shape_and_fields():
    prices = _trend_prices(120)
    rm = rolling_metrics(prices, window=60)
    assert len(rm) == len(prices) - 60
    row = rm[-1]
    for k in ("index", "ann_return", "ann_vol", "sharpe", "max_drawdown"):
        assert k in row
    assert row["ann_vol"] >= 0 and row["max_drawdown"] <= 0


def test_rolling_metrics_insufficient_returns_empty():
    assert rolling_metrics([100, 101, 102], window=60) == []
    assert rolling_metrics(_trend_prices(30), window=4) == []   # window < 5


def test_rolling_stability():
    prices = _trend_prices(150)
    roll = rolling_metrics(prices, window=60)
    st = rolling_stability(roll, "sharpe")
    assert st["available"] and st["n"] == len(roll)
    assert 0.0 <= st["positive_ratio"] <= 1.0
    assert isinstance(st["stable"], bool)
    assert rolling_stability([{"sharpe": 0.1}], "sharpe")["available"] is False


# ══════════════ 2. 回撤剖析 ══════════════

def test_drawdown_report_known_sequence():
    prices = [100, 90, 80, 85, 110, 99]
    rep = drawdown_report(prices)
    assert rep["max_drawdown"] == pytest.approx(-0.2, abs=1e-9)
    assert rep["n_drawdowns"] >= 2
    first = rep["drawdowns"][0]
    assert first["recovered"] is True and first["recovery_days"] is not None


def test_drawdown_report_ongoing_unrecovered():
    prices = [100, 110, 90, 85]          # 110 → 85 未恢复
    rep = drawdown_report(prices)
    assert rep["drawdowns"][0]["recovered"] is False
    assert rep["max_drawdown"] == pytest.approx(85 / 110 - 1, abs=1e-9)


def test_drawdown_report_empty():
    rep = drawdown_report([100])
    assert rep["n_drawdowns"] == 0 and rep["max_drawdown"] == 0.0


# ══════════════ 3. 仓位计算 ══════════════

def test_kelly_fraction_math():
    k = kelly_fraction(0.6, 2.0, fraction=0.5, cap=0.25)
    assert k["full_kelly"] == pytest.approx(0.6 - 0.4 / 2)      # 0.4
    assert k["suggested"] == pytest.approx(0.2)                 # 半凯利
    assert k["edge"] > 0 and k["capped"] is False


def test_kelly_fraction_cap_and_negative_edge():
    k = kelly_fraction(0.9, 5.0, fraction=1.0, cap=0.25)
    assert k["suggested"] == pytest.approx(0.25) and k["capped"] is True
    k2 = kelly_fraction(0.3, 1.0)          # 期望为负 → 不应下注
    assert k2["edge"] < 0 and k2["suggested"] == 0.0


def test_fixed_fractional_size():
    r = fixed_fractional_size(100000, 0.02, entry=100.0, stop=95.0)
    assert r["risk_amount"] == pytest.approx(2000)
    assert r["shares"] == pytest.approx(400)
    assert r["lots_a_share"] == 4
    assert r["position_value"] == pytest.approx(40000)
    bad = fixed_fractional_size(100000, 0.02, entry=100, stop=100)
    assert bad["shares"] == 0


def test_vol_target_weight():
    rets = _returns(_trend_prices(120))
    w = vol_target_weight(rets, target_vol=0.15)
    assert 0.0 <= w["weight"] <= 1.0 and w["ann_vol"] > 0
    # 零波动 → 满仓（封顶）
    w0 = vol_target_weight([0.0] * 60, target_vol=0.15)
    assert w0["weight"] == 1.0
    # 样本不足 → 0
    assert vol_target_weight([0.01, 0.02])["weight"] == 0.0


# ══════════════ 4. 统计检验 ══════════════

def test_skewness_kurtosis_edge_cases():
    assert skewness([1.0, 2.0]) is None
    assert kurtosis([1.0, 2.0, 3.0]) is None
    assert skewness([5.0] * 10) == 0.0     # 零方差
    assert kurtosis([5.0] * 10) == 0.0


def test_skewness_direction():
    random.seed(3)
    base = [random.gauss(0, 1) for _ in range(500)]
    left_tail = base + [-8.0, -9.0, -10.0]
    assert skewness(left_tail) < -0.5      # 左尾肥 → 负偏度


def test_jarque_bera():
    rets = _returns(_trend_prices(200))
    jb = jarque_bera(rets)
    assert jb["available"] and jb["statistic"] >= 0
    assert 0.0 <= jb["p_value"] <= 1.0
    assert jb["verdict"]
    assert jarque_bera([0.01] * 5)["available"] is False


def test_autocorrelation_directions():
    momentum = [0.01] * 50 + [0.02] * 50        # 持续 → 正自相关
    assert autocorrelation(momentum, 1) > 0
    alternating = [(-1) ** i * 0.01 for i in range(60)]
    assert autocorrelation(alternating, 1) < -0.5
    assert autocorrelation([0.01, 0.02], 1) is None


def test_ljung_box():
    rets = _returns(_trend_prices(250))
    lb = ljung_box(rets, lags=10)
    assert lb["available"] and lb["lags"] == 10
    assert lb["statistic"] >= 0 and 0.0 <= lb["p_value"] <= 1.0
    assert len(lb["acf"]) == 10
    assert ljung_box(rets[:10])["available"] is False


# ══════════════ 5. 业绩归因 ══════════════

def test_tracking_error_and_ir_identical():
    rets = _returns(_trend_prices(100))
    assert tracking_error(rets, rets) == pytest.approx(0.0, abs=1e-12)
    assert information_ratio(rets, rets) is None   # TE=0 → 无定义


def test_information_ratio_positive_for_outperformer():
    random.seed(5)
    bench = [random.gauss(0.0005, 0.01) for _ in range(200)]
    active = [b + 0.001 + random.gauss(0, 0.002) for b in bench]
    ir = information_ratio(active, bench)
    assert ir is not None and ir > 0
    assert tracking_error(active, bench) > 0


def test_up_down_capture_verdicts():
    random.seed(6)
    bench = [random.gauss(0, 0.01) for _ in range(200)]
    # 进攻型：跟涨 1.2 倍，回撤也 1.2 倍
    aggressive = [b * 1.2 for b in bench]
    cap = up_down_capture(aggressive, bench)
    assert cap["up_capture"] == pytest.approx(1.2, abs=1e-9)
    assert cap["verdict"] == "进攻型（跟涨强，回撤也大）"
    # 防御型：涨时弱、跌时抗跌
    defensive = [b * 0.8 if b > 0 else b * 0.5 for b in bench]
    cap2 = up_down_capture(defensive, bench)
    assert cap2["verdict"] == "防御型（抗跌但跟涨弱）"
    assert cap2["capture_ratio"] == pytest.approx(
        cap2["up_capture"] / cap2["down_capture"])


def test_up_down_capture_insufficient():
    assert up_down_capture([0.01] * 3, [0.01] * 3)["verdict"] == "样本不足"


# ══════════════ 6. 相关矩阵与一站式体检 ══════════════

def test_correlation_matrix():
    a = [float(i) for i in range(30)]
    b = [2 * x + 5 for x in a]
    c = [-x for x in a]
    out = correlation_matrix({"A": a, "B": b, "C": c})
    assert out["n_series"] == 3
    assert out["pairs"][("A", "B")] == pytest.approx(1.0, abs=1e-9)
    assert out["pairs"][("A", "C")] == pytest.approx(-1.0, abs=1e-9)
    short = correlation_matrix({"X": [1, 2], "Y": [2, 3]})
    assert short["pairs"][("X", "Y")] is None


def test_quick_advanced_stats_short_and_full():
    assert quick_advanced_stats([100, 101])["available"] is False
    prices = _trend_prices(200)
    r = quick_advanced_stats(prices, window=60)
    assert r["available"]
    assert r["rolling"]["n_windows"] == len(prices) - 60
    assert r["drawdown"]["max_drawdown"] <= 0
    assert 0.0 <= r["kelly"]["suggested"] <= 0.25
    assert r["stats_tests"]["jarque_bera"]["available"]
    assert 0.0 <= r["position"]["weight"] <= 1.0
    assert "attribution" not in r          # 未给基准


def test_quick_advanced_stats_with_benchmark():
    prices = _trend_prices(160)
    bench = _trend_prices(160, drift=0.0005, seed=7)
    r = quick_advanced_stats(prices, benchmark=bench)
    attr = r["attribution"]
    assert attr["tracking_error"] is not None
    assert "up_down_capture" in attr


# ══════════════ 7. 语音：播报压缩 ══════════════

def test_summarize_for_speech_strips_markdown_and_url():
    reply = "## 预测结果\n**评分 78/100**\n- 5日上涨概率 62%，详见：https://x.com/a"
    out = summarize_for_speech(reply)
    assert "http" not in out and "#" not in out and "**" not in out
    assert "评分" in out and "62" in out


def test_summarize_for_speech_truncates():
    reply = "。".join(f"第{i}条预测结论内容比较长" for i in range(80))
    out = summarize_for_speech(reply, max_chars=100)
    assert len(out) <= 120
    assert out.endswith("（更多内容见终端输出）")


def test_summarize_for_speech_empty():
    assert summarize_for_speech("") == ""


# ══════════════ 8. 语音：口语指令解析 ══════════════

def test_parse_predict_with_alias():
    cmd = parse_voice_command("预测茅台")
    assert cmd["intent"] == "predict" and cmd["code"] == "600519"
    assert cmd["echo"]
    cmd2 = parse_voice_command("帮我分析一下腾讯")
    assert cmd2["code"] == "hk:00700"


def test_parse_predict_numeric_and_us_code():
    assert parse_voice_command("分析600519")["code"] == "600519"
    assert parse_voice_command("看看 300750")["code"] == "300750"
    assert parse_voice_command("分析美股AAPL")["code"] == "us:AAPL"


def test_parse_v90_intents():
    assert parse_voice_command("A股板块排名")["intent"] == "sector_ranking"
    hk = parse_voice_command("港股板块强度对比")
    assert hk["intent"] == "sector_ranking" and hk["params"]["market"] == "hk"
    reg = parse_voice_command("上证指数体制怎么样")
    assert reg["intent"] == "index_regime" and reg["code"] == "idx:SSE"
    assert parse_voice_command("上证指数体制")["code"] == "idx:SSE"
    assert parse_voice_command("情景分析")["intent"] == "scenario"
    td = parse_voice_command("自上而下美股全景")
    assert td["intent"] == "topdown" and td["params"]["market"] == "us"


def test_parse_quant_check_help_exit_unknown():
    qc = parse_voice_command("量化体检招商银行")
    assert qc["intent"] == "quant_check" and qc["code"] == "600036"
    assert parse_voice_command("量化体检")["code"] is None     # 需追问标的
    assert parse_voice_command("帮助")["intent"] == "help"
    assert parse_voice_command("退出")["intent"] == "exit"
    assert parse_voice_command("你好啊谢谢")['intent'] == "unknown"
    assert parse_voice_command("")["intent"] == "unknown"


# ══════════════ 9. 语音：会话闭环（假回调） ══════════════

def test_voice_chat_handle_text_with_fake_executor():
    spoken = []
    vc = VoiceResearchChat(
        executor=lambda cmd: f"已执行:{cmd['intent']}:{cmd.get('code')}",
        speak_fn=lambda t: spoken.append(t) or True,
        tts=True)
    reply = vc.handle_text("预测茅台")
    assert reply == "已执行:predict:600519"
    assert vc.history[-1]["user"] == "预测茅台"
    assert spoken, "TTS 未被调用"


def test_voice_chat_no_tts_and_history():
    vc = VoiceResearchChat(executor=lambda cmd: "ok", tts=False)
    assert vc.handle_text("你好") == "ok"
    assert len(vc.history) == 1


def test_voice_chat_default_executor_help_offline():
    """默认执行器处理 help/exit 不触网。"""
    vc = VoiceResearchChat(tts=False)
    assert "支持指令" in vc._default_execute({"intent": "help"})
    assert "退出" in vc._default_execute({"intent": "exit"})
    assert "没听懂" in vc._default_execute({"intent": "unknown"})


def test_voice_chat_run_text_mode(monkeypatch):
    """非默认 listen → 文本输入循环，max_turns 与 exit 均可终止。"""
    lines = iter(["预测茅台", "退出"])
    monkeypatch.setattr("builtins.input", lambda *_: next(lines))
    executed = []
    vc = VoiceResearchChat(
        listen=lambda timeout=8: None,      # 非 listen_once → 文本路径
        executor=lambda cmd: executed.append(cmd["intent"]) or "ok",
        tts=False)
    vc.run(max_turns=5)
    assert executed[:2] == ["predict", "exit"]
    assert len(vc.history) == 2


# ══════════════ 10. 接线与版本 ══════════════

def test_quantitative_package_exports():
    from stock_researcher import quantitative as q
    for name in ("rolling_metrics", "drawdown_report", "kelly_fraction",
                 "jarque_bera", "ljung_box", "up_down_capture",
                 "correlation_matrix", "quick_advanced_stats"):
        assert hasattr(q, name), f"quantitative 缺少导出 {name}"


def test_top_level_lazy_exports():
    import stock_researcher as sr
    assert sr.__version__ == "9.8.0"
    for name in ("rolling_metrics", "rolling_stability", "drawdown_report",
                 "kelly_fraction", "fixed_fractional_size", "vol_target_weight",
                 "skewness", "kurtosis", "jarque_bera", "autocorrelation",
                 "ljung_box", "tracking_error", "information_ratio",
                 "up_down_capture", "correlation_matrix", "quick_advanced_stats",
                 "VoiceResearchChat", "parse_voice_command",
                 "summarize_for_speech"):
        assert getattr(sr, name) is not None, f"顶层缺少导出 {name}"


def test_version_files_consistent_940():
    import json
    root = Path(__file__).resolve().parents[1]
    meta = json.loads((root / "_meta.json").read_text(encoding="utf-8"))
    assert meta["version"] == "9.8.0"
    assert meta["maintenance"]["changelog"][0]["version"] == "9.8.0"
    settings = json.loads((root / "config" / "settings.json").read_text(encoding="utf-8"))
    assert settings["version"] == "9.8.0"
    assert settings["_version_info"]["version"] == "9.8.0"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
