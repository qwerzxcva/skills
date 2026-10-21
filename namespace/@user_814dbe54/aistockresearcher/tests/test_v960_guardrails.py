#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v9.6 回归测试 — 两条标红限制固化 + 潜伏 bug 修复（全离线，不联网）。

覆盖：
  1. 代理防护（限制1）：proxy_guard 检测/直连安装/幂等/中文告警/排障提示
  2. 评分免责声明（限制2）：constants 固化文案 + predict 输出 disclaimer 字段 +
     pp() 完整输出携带声明
  3. 接线：stock_researcher 包导入自动安装直连 opener；stock_predict --test 自检
  4. bug 修复：source_manager.fetch 缓存键对 list 参数不再抛 unhashable TypeError
"""
import sys
import urllib.request
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from stock_researcher.data import proxy_guard
from stock_researcher import constants
from stock_researcher.data.source_manager import DataSourceManager, DataSource


PROXY_KEYS = ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY",
              "http_proxy", "https_proxy", "all_proxy")


@pytest.fixture
def clean_proxy_env(monkeypatch):
    """清空全部代理环境变量，保证测试确定性。"""
    for k in PROXY_KEYS:
        monkeypatch.delenv(k, raising=False)
    return monkeypatch


# ── 1. 代理防护（限制1：国内直连，开代理反而失败）─────────────

class TestProxyGuard:
    def test_detect_no_proxy(self, clean_proxy_env):
        assert proxy_guard.detect_proxy_env() == {}

    def test_detect_uppercase_proxy(self, clean_proxy_env):
        clean_proxy_env.setenv("HTTP_PROXY", "http://127.0.0.1:7890")
        found = proxy_guard.detect_proxy_env()
        assert found.get("HTTP_PROXY") == "http://127.0.0.1:7890"

    def test_detect_lowercase_proxy(self, clean_proxy_env):
        clean_proxy_env.setenv("https_proxy", "http://10.0.0.1:8080")
        assert "https_proxy" in proxy_guard.detect_proxy_env()

    def test_ignore_blank_proxy(self, clean_proxy_env):
        clean_proxy_env.setenv("ALL_PROXY", "   ")
        assert proxy_guard.detect_proxy_env() == {}

    def test_ensure_direct_connection_idempotent(self):
        first = proxy_guard.ensure_direct_connection()
        second = proxy_guard.ensure_direct_connection()
        assert second is False            # 幂等：第二次不再安装
        assert proxy_guard.is_direct_opener_active() is True

    def test_direct_opener_has_empty_proxy_handler(self):
        """直连状态：opener 中不存在任何有效代理表。
        注：Py3.11 下 ProxyHandler({}) 空代理表不会被 opener 保留，
        无 ProxyHandler 即意味着不走任何代理（直连）。"""
        proxy_guard.ensure_direct_connection()
        opener = urllib.request._opener
        proxy_handlers = [h for h in opener.handlers
                          if isinstance(h, urllib.request.ProxyHandler)]
        assert all(not h.proxies for h in proxy_handlers)

    def test_proxy_warning_when_detected(self, clean_proxy_env):
        assert proxy_guard.proxy_warning() == ""
        clean_proxy_env.setenv("HTTPS_PROXY", "http://127.0.0.1:1080")
        msg = proxy_guard.proxy_warning()
        assert "国内直连" in msg and "代理" in msg and "反而会失败" in msg

    def test_diagnose_proxy_error(self, clean_proxy_env):
        msg = proxy_guard.diagnose_network_error(
            "Tunnel connection failed: 403")
        assert "代理" in msg and "国内直连" in msg

    def test_diagnose_env_proxy_even_generic_error(self, clean_proxy_env):
        clean_proxy_env.setenv("HTTP_PROXY", "http://127.0.0.1:7890")
        msg = proxy_guard.diagnose_network_error("timed out")
        assert "代理" in msg

    def test_diagnose_plain_network_error(self, clean_proxy_env):
        msg = proxy_guard.diagnose_network_error("Name resolution failed")
        assert "代理" not in msg and "网络" in msg


class TestProxyGuardWiring:
    def test_package_import_installs_direct_opener(self):
        import stock_researcher  # noqa: F401  导入即装直连 opener
        assert proxy_guard.is_direct_opener_active()

    def test_stock_predict_has_guard_functions(self):
        sp = __import__("stock_predict")
        assert hasattr(sp, "_ensure_domestic_direct")
        assert hasattr(sp, "_proxy_env_detected")
        sp._ensure_domestic_direct()
        assert proxy_guard.is_direct_opener_active()

    def test_stock_predict_proxy_env_detected(self, clean_proxy_env):
        sp = __import__("stock_predict")
        assert sp._proxy_env_detected() is False
        clean_proxy_env.setenv("ALL_PROXY", "socks5://127.0.0.1:1080")
        assert sp._proxy_env_detected() is True


# ── 2. 评分免责声明（限制2：评分≠盈利保证）─────────────────────

class TestScoreDisclaimer:
    def test_constants_score_meaning(self):
        assert "盈利保证" in constants.SCORE_MEANING
        assert "历史相似条件" in constants.SCORE_MEANING
        assert "上涨概率" in constants.SCORE_MEANING

    def test_constants_disclaimer_and_direct(self):
        assert "不构成投资建议" in constants.DISCLAIMER
        assert "国内直连" in constants.DOMESTIC_DIRECT_REQUIRED
        assert "代理" in constants.DOMESTIC_DIRECT_REQUIRED

    def test_stock_predict_score_meaning_text(self):
        sp = __import__("stock_predict")
        assert "盈利保证" in sp._SCORE_MEANING
        assert "不构成投资建议" in sp._SCORE_MEANING

    def test_predict_result_carries_disclaimer(self):
        """predict() 返回结构必须携带 disclaimer 字段（用离线构造验证字段注入点）。"""
        import inspect
        sp = __import__("stock_predict")
        src = inspect.getsource(sp.predict)
        assert '"disclaimer"' in src and "_SCORE_MEANING" in src

    def test_pp_output_contains_disclaimer(self, capsys):
        """完整输出必须打印评分含义声明。"""
        sp = __import__("stock_predict")
        r = {
            "code": "600519", "name": "贵州茅台", "market": "cn",
            "currency": "CNY",
            "price": {"price": 1500.0, "chg_pct": 1.2, "open": 1490.0,
                      "high": 1510.0, "low": 1485.0, "pe": 25.0,
                      "turnover": 0.3},
            "technical": {
                "ma5": 1495, "ma10": 1490, "ma20": 1480, "ma60": 1460,
                "rsi": 55.0, "macd": {"dif": 1.2, "dea": 1.0, "hist": 0.4},
                "kdj": {"k": 60, "d": 55, "j": 70}, "vol_ratio": 1.3,
                "boll": {"up": 1520, "mid": 1490, "lo": 1460, "pos": 65},
                "adx": {"adx": 28, "pdi": 30, "ndi": 18},
                "wr": -40.0, "cci": 50.0, "mfi": 58.0, "atr_pct": 1.8,
                "obv": 12345.0,
            },
            "monte_carlo": {
                "5d": {"avg": 0.8, "up": 0.58, "p50": 1512.0,
                       "lo": 1430.0, "hi": 1590.0},
                "10d": {"avg": 1.5, "up": 0.60, "p50": 1522.0,
                        "lo": 1400.0, "hi": 1640.0},
            },
            "score": {"total": 62.0, "trend": 18.0, "momentum": 12.0,
                      "vol": 8.0, "volatility": 6.0, "prob": 11.0,
                      "env": 7.0, "gold_factor": 0.0, "ma": "多头排列"},
            "signal": "📈 看涨", "confidence": 0.68,
            "summary": "贵州茅台(600519) [CN] 评分62/100",
            "disclaimer": sp._SCORE_MEANING,
        }
        sp.pp(r)
        out = capsys.readouterr().out
        assert "盈利保证" in out
        assert "不构成投资建议" in out


# ── 3. 版本一致性 ─────────────────────────────────────────────

class TestVersion:
    def test_version_96(self):
        assert constants.VERSION == "9.8.0"
        assert constants.VERSION_DATE == "2026-09-01"

    def test_meta_json_in_sync(self):
        import json
        meta = json.loads(
            (Path(__file__).resolve().parents[1] / "_meta.json")
            .read_text(encoding="utf-8"))
        assert meta["version"] == constants.VERSION


# ── 4. bug 修复：source_manager 缓存键兼容 list 参数 ──────────

class TestSourceManagerCacheKey:
    def test_fetch_with_list_kwargs_no_typeerror(self):
        mgr = DataSourceManager()
        mgr.register_source("realtime", DataSource(
            name="mock_src", fetch_func=lambda codes: {"ok": True, "n": len(codes)},
            priority=1, cache_ttl=60))
        # list 参数（文档示例用法）不应再抛 unhashable TypeError
        result = mgr.fetch("realtime", codes=["600519", "000858"])
        assert result == {"ok": True, "n": 2}

    def test_cache_hit_with_list_kwargs(self):
        calls = {"n": 0}

        def fetcher(codes):
            calls["n"] += 1
            return {"data": codes}

        mgr = DataSourceManager()
        mgr.register_source("history", DataSource(
            name="mock_hist", fetch_func=lambda code, days=120: fetcher(code),
            priority=1, cache_ttl=60))
        r1 = mgr.fetch("history", code=["600519"], days=5)
        r2 = mgr.fetch("history", code=["600519"], days=5)
        assert r1 == r2 and calls["n"] == 1   # 第二次命中缓存


# ── 5. 交付守卫：仓库零二进制缓存残留 ──────────────────

class TestNoBinaryResidue:
    """上传平台禁二进制：仓库内不得存在 .pyc/.pyo/__pycache__/.pytest_cache。

    防护链路（缺一会复发）：
      - stock_predict.py / run_voice.py / market_overview.py 导入前设
        sys.dont_write_bytecode（堵 CLI 直跑盲区）
      - tests/conftest.py 启动时清理历史残留 + pytest.ini 禁 cacheprovider
    """

    ROOT = Path(__file__).resolve().parents[1]

    def test_no_pyc_files(self):
        residue = [str(p.relative_to(self.ROOT))
                   for p in self.ROOT.rglob("*.py*")
                   if p.suffix in (".pyc", ".pyo")]
        assert residue == [], f"发现字节码残留: {residue}"

    def test_no_pycache_dirs(self):
        dirs = [str(p.relative_to(self.ROOT))
                for p in self.ROOT.rglob("__pycache__")]
        assert dirs == [], f"发现 __pycache__ 残留: {dirs}"

    def test_no_pytest_cache(self):
        assert not (self.ROOT / ".pytest_cache").exists()

    def test_cli_entries_set_bytecode_guard(self):
        """三个 CLI 入口必须在导入本地模块前设 dont_write_bytecode。"""
        for rel in ("scripts/stock_predict.py", "run_voice.py",
                    "scripts/market_overview.py"):
            txt = (self.ROOT / rel).read_text(encoding="utf-8")
            assert "sys.dont_write_bytecode = True" in txt, f"{rel} 缺字节码防护"
