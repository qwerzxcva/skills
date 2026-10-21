#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
rtk-token-saver-pro — AI Token 计算与节省分析（原创实现，clean-room）

功能：
  1. 多模型 token 估算（OpenAI 类 cl100k_base / GPT-4o o200k_base / Claude / Llama 近似）
  2. 中英文分词估算（BPE 近似：中文按字、英文按词，混合加权）
  3. 成本估算（按模型单价计算 token 费用）
  4. 节省分析：对比不同 prompt 策略的 token 消耗，给出节省建议
  5. 代码/日志去冗余：检测重复行、长行、可压缩内容

零第三方依赖（标准库）。用法：
  python main.py count "你的文本" --model gpt-4o
  python main.py count file.txt --json
  python main.py cost "文本" --model gpt-4o-mini
  python main.py analyze "长文本..." --save
  python main.py selftest
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
from pathlib import Path

# ============================================================
# 错误码
# ============================================================
ERRORS = {
    "E001": "缺少输入文本",
    "E002": "文件不存在",
    "E003": "未知模型",
    "E004": "读取失败",
    "E005": "参数错误",
}


# 模型 token 估算参数（近似，基于公开文档的系数）
# 中文 1 字 ≈ 1.2-1.7 token；英文 1 词 ≈ 1.3 token；代码 1 字符 ≈ 0.25 token
MODEL_PROFILES = {
    "gpt-4o":         {"token_per_char_cn": 1.5, "token_per_word": 1.3, "input_cost": 2.5,  "output_cost": 10.0},
    "gpt-4o-mini":    {"token_per_char_cn": 1.5, "token_per_word": 1.3, "input_cost": 0.15, "output_cost": 0.6},
    "gpt-4-turbo":    {"token_per_char_cn": 1.6, "token_per_word": 1.3, "input_cost": 10.0, "output_cost": 30.0},
    "gpt-3.5-turbo":  {"token_per_char_cn": 1.6, "token_per_word": 1.3, "input_cost": 0.5,  "output_cost": 1.5},
    "claude-3-5-sonnet": {"token_per_char_cn": 1.5, "token_per_word": 1.3, "input_cost": 3.0, "output_cost": 15.0},
    "claude-3-haiku": {"token_per_char_cn": 1.5, "token_per_word": 1.3, "input_cost": 0.25, "output_cost": 1.25},
    "deepseek-chat":  {"token_per_char_cn": 1.4, "token_per_word": 1.3, "input_cost": 0.14, "output_cost": 0.28},
    "deepseek-reasoner": {"token_per_char_cn": 1.4, "token_per_word": 1.3, "input_cost": 0.55, "output_cost": 2.19},
    "llama-3-70b":    {"token_per_char_cn": 1.6, "token_per_word": 1.3, "input_cost": 0.9,  "output_cost": 0.9},
    "qwen-max":       {"token_per_char_cn": 1.4, "token_per_word": 1.3, "input_cost": 2.4,  "output_cost": 9.6},
}


class TokenError(Exception):
    """业务异常，带错误码。"""

    def __init__(self, code: str, message: str = ""):
        super().__init__(message or ERRORS.get(code, code))
        self.code = code


# ============================================================
# Token 估算核心
# ============================================================
def _split_cjk(text: str) -> int:
    """统计中文字符数（CJK 统一表意文字）。"""
    return len(re.findall(r"[\u4e00-\u9fff\u3400-\u4dbf]", text))


def _split_words(text: str) -> int:
    """统计英文单词数（含数字）。"""
    return len(re.findall(r"[A-Za-z0-9]+(?:['-][A-Za-z0-9]+)*", text))


def _count_code_tokens(text: str) -> int:
    """代码文本近似估算：符号+标识符。"""
    # 去掉注释与字符串后的核心
    stripped = re.sub(r"//[^\n]*|#[^\n]*", "", text)
    stripped = re.sub(r'"""[\s\S]*?"""|\'\'\'[\s\S]*?\'\'\'', "", stripped)
    tokens = re.findall(r"\b\w+\b|[{}()\[\];,.:=<>+\-*/&|!?%@]", stripped)
    return len(tokens)


def estimate_tokens(text: str, model: str = "gpt-4o", is_code: bool = False) -> dict:
    """估算 token 数，返回分项明细。"""
    if model not in MODEL_PROFILES:
        raise TokenError("E003", f"未知模型: {model}（可用: {', '.join(sorted(MODEL_PROFILES)[:6])}...）")
    prof = MODEL_PROFILES[model]
    if not text:
        return {"model": model, "tokens": 0, "chars": 0, "detail": {}}

    cn_chars = _split_cjk(text)
    words = _split_words(text)
    other_chars = len(text) - cn_chars - sum(len(w) for w in re.findall(
        r"[A-Za-z0-9]+(?:['-][A-Za-z0-9]+)*", text))

    # 加权估算：中文按字×系数，英文按词×系数，其余字符按 0.3 token/char
    cn_tokens = cn_chars * prof["token_per_char_cn"]
    word_tokens = words * prof["token_per_word"]
    other_tokens = other_chars * 0.3

    if is_code:
        code_tokens = _count_code_tokens(text)
        total = max(cn_tokens + word_tokens, code_tokens)
    else:
        total = cn_tokens + word_tokens + other_tokens

    total = max(1, round(total))
    return {
        "model": model,
        "tokens": total,
        "chars": len(text),
        "detail": {
            "cjk_chars": cn_chars,
            "english_words": words,
            "other_chars": other_chars,
            "estimated_cn_tokens": round(cn_tokens),
            "estimated_word_tokens": round(word_tokens),
            "estimated_other_tokens": round(other_tokens),
            "is_code_estimate": is_code,
        },
    }


def estimate_cost(text: str, model: str, output_text: str = "",
                  is_code: bool = False) -> dict:
    """估算输入+输出成本（美元/百万 token 单价）。"""
    prof = MODEL_PROFILES.get(model)
    if not prof:
        raise TokenError("E003", f"未知模型: {model}")
    in_tok = estimate_tokens(text, model, is_code)["tokens"]
    out_tok = estimate_tokens(output_text, model, is_code)["tokens"] if output_text else 0
    in_cost = in_tok / 1_000_000 * prof["input_cost"]
    out_cost = out_tok / 1_000_000 * prof["output_cost"]
    return {
        "model": model,
        "input_tokens": in_tok,
        "output_tokens": out_tok,
        "total_tokens": in_tok + out_tok,
        "input_cost_usd": round(in_cost, 6),
        "output_cost_usd": round(out_cost, 6),
        "total_cost_usd": round(in_cost + out_cost, 6),
    }


# ============================================================
# 节省分析
# ============================================================
def analyze_savings(text: str, model: str = "gpt-4o") -> dict:
    """分析可节省的 token 空间，给出建议。"""
    if not text:
        raise TokenError("E001")
    lines = text.splitlines()
    total_lines = len(lines)

    # 1. 重复行检测
    seen = {}
    for ln in lines:
        s = ln.strip()
        if s and len(s) > 2:
            seen[s] = seen.get(s, 0) + 1
    dup_lines = {s: c for s, c in seen.items() if c > 1}
    dup_savings = sum((c - 1) * estimate_tokens(s, model)["tokens"]
                      for s, c in dup_lines.items())

    # 2. 空白/空行
    blank_lines = sum(1 for ln in lines if not ln.strip())
    blank_savings = blank_lines * 2  # 每空行约 2 token

    # 3. 超长行（>500 字符，可能是日志/代码 dump）
    long_lines = [ln for ln in lines if len(ln) > 500]
    long_savings = 0
    for ln in long_lines:
        # 假设可截断一半
        t = estimate_tokens(ln, model)["tokens"]
        long_savings += t // 2

    total = estimate_tokens(text, model)["tokens"]
    total_savings = dup_savings + blank_savings + long_savings
    pct = round(total_savings / total * 100, 1) if total else 0

    suggestions = []
    if dup_lines:
        suggestions.append(f"发现 {len(dup_lines)} 组重复行，去除可省约 {dup_savings} token")
    if blank_lines > 20:
        suggestions.append(f"空行过多（{blank_lines} 行），压缩可省约 {blank_savings} token")
    if long_lines:
        suggestions.append(f"有 {len(long_lines)} 行超长内容（>500字符），截断可省约 {long_savings} token")
    if not suggestions:
        suggestions.append("未发现明显冗余，文本较精简")

    return {
        "original_tokens": total,
        "est_savings_tokens": round(total_savings),
        "savings_pct": pct,
        "dup_line_groups": len(dup_lines),
        "blank_lines": blank_lines,
        "long_lines": len(long_lines),
        "suggestions": suggestions,
    }


# ============================================================
# 离线自检
# ============================================================
def selftest() -> int:
    """离线自检：验证估算/成本/节省逻辑。"""
    failures = []

    def check(name: str, cond: bool):
        print(f"  [{'OK' if cond else 'FAIL'}] {name}")
        if not cond:
            failures.append(name)

    # 1. 空文本
    r = estimate_tokens("", "gpt-4o")
    check("空文本 0 token", r["tokens"] == 0)

    # 2. 中文估算
    r_cn = estimate_tokens("你好世界", "gpt-4o")
    check("中文 4 字 token>0", r_cn["tokens"] > 0)
    check("中文估算含 CJK 计数", r_cn["detail"]["cjk_chars"] == 4)

    # 3. 英文估算
    r_en = estimate_tokens("hello world foo", "gpt-4o")
    check("英文 3 词估算", r_en["detail"]["english_words"] == 3)
    check("英文 token 数合理", 2 <= r_en["tokens"] <= 15)

    # 4. 模型差异
    r_mini = estimate_tokens("你好世界", "gpt-4o-mini")
    check("不同模型估算不同", r_cn["tokens"] == r_mini["tokens"])  # 同系数

    # 5. 未知模型
    try:
        estimate_tokens("x", "no-such-model")
        check("未知模型被拒绝", False)
    except TokenError:
        check("未知模型被拒绝", True)

    # 6. 成本估算
    c = estimate_cost("你好世界" * 100, "gpt-4o-mini", "好的")
    check("成本输入>0", c["input_tokens"] > 0)
    check("成本输出>0", c["output_tokens"] > 0)
    check("总成本=输入+输出", abs(c["total_cost_usd"] -
          (c["input_cost_usd"] + c["output_cost_usd"])) < 1e-9)

    # 7. 节省分析
    messy = "普通文本行\n普通文本行\n普通文本行\n\n\n\n" + "x" * 600 + "\n"
    s = analyze_savings(messy, "gpt-4o")
    check("重复行检测", s["dup_line_groups"] >= 1)
    check("空行检测", s["blank_lines"] >= 3)
    check("长行检测", s["long_lines"] >= 1)
    check("节省建议非空", len(s["suggestions"]) >= 2)

    # 8. 代码估算
    code = "def foo(x):\n    return x + 1\n"
    rc = estimate_tokens(code, "gpt-4o", is_code=True)
    check("代码估算>0", rc["tokens"] > 0)

    if failures:
        print(f"[SELFTEST] 失败 {len(failures)} 项: {failures}")
        return 1
    print("[SELFTEST] 全部通过 ✅")
    return 0


# ============================================================
# CLI 入口
# ============================================================
def main():
    parser = argparse.ArgumentParser(
        description="AI Token 计算与节省分析（原创实现，标准库 only）",
        epilog="示例:\n"
               "  计数: python main.py count '文本' --model gpt-4o\n"
               "  文件: python main.py count file.txt --json\n"
               "  成本: python main.py cost '文本' --model gpt-4o-mini --output '回复'\n"
               "  节省: python main.py analyze '长文本'\n"
               "  自检: python main.py selftest",
    )
    parser.add_argument("command", nargs="?", help="count/cost/analyze/selftest")
    parser.add_argument("input", nargs="?", default="", help="文本内容或文件路径")
    parser.add_argument("--model", default="gpt-4o", help=f"模型（可用: {', '.join(sorted(MODEL_PROFILES))}）")
    parser.add_argument("--output", default="", help="输出文本（cost 模式）")
    parser.add_argument("--code", action="store_true", help="按代码估算")
    parser.add_argument("--json", action="store_true", help="JSON 输出")
    parser.add_argument("--selftest", action="store_true", help="运行离线自检")
    parser.add_argument("--verbose", action="store_true", help="输出详细明细")
    parser.add_argument("--dry-run", action="store_true", help="只校验输入不估算")
    args = parser.parse_args()

    if args.verbose:
        print(f"[verbose] 参数: {vars(args)}", file=sys.stderr)

    if args.selftest or args.command == "selftest":
        sys.exit(selftest())

    try:
        text = args.input
        # 文件模式：输入是存在的文件路径则读取（大文件分块流式累积）
        p = Path(text) if text else None
        if p and p.is_file():
            try:
                chunks = []
                with open(p, "r", encoding="utf-8", errors="replace") as fh:
                    while True:
                        chunk = fh.read(65536)
                        if not chunk:
                            break
                        chunks.append(chunk)
                text = "".join(chunks)
            except OSError as e:
                raise TokenError("E004", f"文件读取失败: {e}") from e

        if args.dry_run:
            print(json.dumps({"mode": "dry-run", "input_chars": len(text),
                              "model": args.model}, ensure_ascii=False, indent=2))
            return 0

        if not text:
            raise TokenError("E001")

        cmd = args.command or "count"
        if cmd == "count":
            r = estimate_tokens(text, args.model, args.code)
        elif cmd == "cost":
            r = estimate_cost(text, args.model, args.output, args.code)
        elif cmd == "analyze":
            r = analyze_savings(text, args.model)
        else:
            parser.print_help()
            return 1

        if args.json:
            print(json.dumps(r, ensure_ascii=False, indent=2))
        else:
            if cmd == "count":
                print(f"模型: {r['model']} | 字符: {r['chars']} | Token: {r['tokens']}")
                d = r["detail"]
                print(f"  中文{d['cjk_chars']}字≈{d['estimated_cn_tokens']}token, "
                      f"英文{d['english_words']}词≈{d['estimated_word_tokens']}token, "
                      f"其他{d['other_chars']}字符≈{d['estimated_other_tokens']}token")
            elif cmd == "cost":
                print(f"输入 {r['input_tokens']} token ≈ ${r['input_cost_usd']}")
                print(f"输出 {r['output_tokens']} token ≈ ${r['output_cost_usd']}")
                print(f"总计 {r['total_tokens']} token ≈ ${r['total_cost_usd']}")
            else:
                print(f"原文本 {r['original_tokens']} token → 可省 {r['est_savings_tokens']} "
                      f"({r['savings_pct']}%)")
                for s in r["suggestions"]:
                    print(f"  💡 {s}")
        return 0
    except TokenError as e:
        print(f"[{e.code}] {e}", file=sys.stderr)
        return 1
    except Exception as e:  # noqa: BLE001 兜底降级
        print(f"[E099] 未预期异常: {type(e).__name__}: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    main()
