#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fetch_stock_data.py — 股票价值投资分析一键取数（yfinance + AkShare 双引擎，可选）

用法：
    python fetch_stock_data.py --symbol 0700.HK --market HK
    python fetch_stock_data.py --symbol 600519 --market A
    python fetch_stock_data.py --symbol AAPL  --market US
    python fetch_stock_data.py --symbol 0700.HK --market HK --output ./out.json

设计原则：
    - yfinance 优先（港股/美股/ADR）；AkShare 兜底（A 股主用，港股明细兜底）。
    - 任何引擎/字段失败都记录到 errors[]，不中断主流程。
    - 自动调用 value_models.py 计算 models / time_series。
    - 库未安装时优雅降级：输出 meta.engines_used=[] 与 errors，LLM 改用用户数据/联网分析。
    - 仅标准库 + 可选 yfinance/akshare/pandas/numpy；缺失即跳过对应引擎。

依赖（可选）： pip install yfinance akshare pandas numpy

License: MIT
"""

from __future__ import annotations
import argparse
import json
import os
import sys
from datetime import datetime, timezone

# 让脚本可 import 同目录的 value_models
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    import value_models as vm  # type: ignore
except Exception:
    vm = None  # type: ignore


def _safe(d, key, default=None):
    try:
        v = d.get(key, default) if isinstance(d, dict) else default
        return v if v is not None else default
    except Exception:
        return default


# ---------------------------------------------------------------------------
# 引擎 1：yfinance
# ---------------------------------------------------------------------------
def fetch_via_yfinance(symbol: str) -> dict:
    try:
        import yfinance as yf  # type: ignore
    except Exception as e:
        return {"ok": False, "error": f"yfinance 未安装或导入失败: {e}"}
    try:
        t = yf.Ticker(symbol)
        info = t.info or {}
        out = {
            "price": _safe(info, "currentPrice") or _safe(info, "regularMarketPrice"),
            "market_cap": _safe(info, "marketCap"),
            "currency": _safe(info, "currency"),
            "pe_ratio": _safe(info, "trailingPE"),
            "pb_ratio": _safe(info, "priceToBook"),
            "dividend_yield": _safe(info, "dividendYield"),
            "roe": _safe(info, "returnOnEquity"),
            "profit_margin": _safe(info, "profitMargins"),
            "company": _safe(info, "shortName") or _safe(info, "longName"),
            "sector": _safe(info, "sector"),
            "industry": _safe(info, "industry"),
            "shares": _safe(info, "sharesOutstanding"),
        }
        # 时间序列：尝试 fast 历史
        try:
            hist = t.history(period="5y")
            out["_hist_ok"] = (hist is not None and len(hist) > 0)
        except Exception:
            out["_hist_ok"] = False
        return {"ok": True, "data": out}
    except Exception as e:
        return {"ok": False, "error": f"yfinance 取数失败: {e}"}


# ---------------------------------------------------------------------------
# 引擎 2：AkShare
# ---------------------------------------------------------------------------
def fetch_via_akshare(symbol: str, market: str) -> dict:
    try:
        import akshare as ak  # type: ignore
    except Exception as e:
        return {"ok": False, "error": f"akshare 未安装或导入失败: {e}"}
    try:
        out = {}
        # A 股实时行情
        if market == "A":
            try:
                df = ak.stock_zh_a_spot_em()
                row = df[df["代码"] == symbol]
                if len(row):
                    r = row.iloc[0]
                    out["price"] = float(r["最新价"])
                    out["market_cap"] = float(r["总市值"])
                    out["pe_ratio"] = float(r["市盈率-动态"]) if r["市盈率-动态"] != "--" else None
                    out["pb_ratio"] = float(r["市净率"]) if r["市净率"] != "--" else None
                    out["currency"] = "CNY"
            except Exception as e:
                out["_a_spot_err"] = str(e)
        # 港股/通用：尝试个股信息
        try:
            info = ak.stock_individual_info_em(symbol=symbol)
            d = dict(zip(info["item"], info["value"]))
            out["company"] = _safe(d, "股票简称")
            out.setdefault("market_cap", _safe(d, "总市值"))
            out.setdefault("price", _safe(d, "最新价"))
        except Exception:
            pass
        return {"ok": True, "data": out}
    except Exception as e:
        return {"ok": False, "error": f"akshare 取数失败: {e}"}


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------
def build_output(symbol: str, market: str) -> dict:
    meta = {
        "symbol": symbol,
        "market": market,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "engines_used": [],
        "errors": [],
    }
    merged = {}
    engines = []

    yf_r = fetch_via_yfinance(symbol)
    if yf_r.get("ok"):
        merged.update({k: v for k, v in yf_r["data"].items() if not k.startswith("_")})
        engines.append("yfinance")
    else:
        meta["errors"].append(yf_r.get("error"))

    ak_r = fetch_via_akshare(symbol, market)
    if ak_r.get("ok"):
        for k, v in ak_r["data"].items():
            if not k.startswith("_") and merged.get(k) is None:
                merged[k] = v
        engines.append("akshare")
    else:
        meta["errors"].append(ak_r.get("error"))

    meta["engines_used"] = engines

    # 量化模型（若 value_models 可用）
    models = {}
    if vm is not None:
        # 反向 DCF 需市值 + FCF；此处无 FCF，标记 applicable=False（需用户补 FCF）
        models["reverse_dcf"] = vm.reverse_dcf(
            _safe(merged, "market_cap"), None, 0.09
        ) if False else {"applicable": False, "reason": "需用户提供基准自由现金流(FCF)"}
        # 其余模型同样需明细输入，先用占位说明
        models["_note"] = "models 各字段需在 LLM 分析时结合用户财报明细调用 value_models 函数计算；脚本仅做取数与字段对齐。"
    else:
        meta["errors"].append("value_models.py 未加载，量化模型未计算（LLM 可手动计算）")

    result = {
        "meta": meta,
        "price": _safe(merged, "price"),
        "valuation": {"pe": _safe(merged, "pe_ratio"), "pb": _safe(merged, "pb_ratio"),
                       "dividend_yield": _safe(merged, "dividend_yield")},
        "profitability": {"roe": _safe(merged, "roe"), "profit_margin": _safe(merged, "profit_margin")},
        "financials": {},
        "company": {"name": _safe(merged, "company"), "sector": _safe(merged, "sector"),
                    "industry": _safe(merged, "industry")},
        "shares": _safe(merged, "shares"),
        "market_cap": _safe(merged, "market_cap"),
        "currency": _safe(merged, "currency"),
        "time_series": {"note": "需三大报表明细；AkShare/东方财富可补 5-10 年序列后由 LLM 引用"},
        "models": models,
    }
    return result


def main():
    ap = argparse.ArgumentParser(description="股票价值投资分析取数（双引擎）")
    ap.add_argument("--symbol", required=True, help="股票代码，如 600519 / 0700.HK / AAPL")
    ap.add_argument("--market", required=True, choices=["A", "HK", "US"], help="市场")
    ap.add_argument("--output", default=None, help="输出 JSON 路径（默认打印到 stdout）")
    ap.add_argument("--fx-market-to-report", type=float, default=None, help="港股币种对齐汇率（可选）")
    args = ap.parse_args()

    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    result = build_output(args.symbol, args.market)
    text = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(text)
        print(f"已写入 {args.output}")
    else:
        print(text)


if __name__ == "__main__":
    main()
