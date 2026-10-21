# -*- coding: utf-8 -*-
"""keeper_benchmark.py —— 性能基准。

在（建议隔离的）记忆库上：
1. 批量 deposit N 条合成记忆（defer_index 批量落盘），测写入吞吐；
2. 随机抽 query 跑 M 次 recall，测 p50/p95/avg 时延与空召回率；
输出 JSON 报告，可选 --out 落盘。

默认 ann=False（全量扫描基线时延，结果与语义后端无关、确定可复现）；
--ann 则走 ANN 优化路径（库≥ann_min 时），用于测大库加速比。

用法：
python scripts/keeper_benchmark.py --root <store> --n 200 --recall-times 50
python scripts/keeper_benchmark.py --root <store> --n 500 --ann --out bench.json
"""
import os
import sys
import json
import time
import random
import argparse
import datetime

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)

import memory_ops as mo  # noqa: E402


def _pctl(xs, p):
    if not xs:
        return 0.0
    xs = sorted(xs)
    if len(xs) == 1:
        return float(xs[0])
    k = (len(xs) - 1) * p / 100.0
    f = int(k)
    c = min(f + 1, len(xs) - 1)
    return xs[f] + (xs[c] - xs[f]) * (k - f)


def run_benchmark(root, n=200, recall_times=50, top_n=10, ann=False,
                  out=None, seed=1234, topic_space=20):
    # 🔴 护栏：benchmark 会向 root 写入 N 条合成记忆，禁止对默认真实记忆库跑，否则污染真实召回。
    # 独立脚本直跑 / 引擎 op 均经此入口；引擎 op 已先拦，此处为双保险。
    # ⚠️ 比较必须走 mo._root_key 规范化：曾因 `root == mo.DEFAULT_ROOT` 字符串比较，
    # 让 `--root "D:/<库路径>"`（正斜杠）绕过护栏并把 200 条合成记忆写进真库（2026-09-16 实锤）。
    if root and mo._root_key(root) == mo._root_key(mo.DEFAULT_ROOT):
        return {"ok": False, "error": "refuse_default_root",
                "msg": "benchmark 会写入合成记忆，禁止对默认真实记忆库跑。"
                       "请显式传 --root <隔离目录>（如 --root /tmp/keeper_bench）"}
    random.seed(seed)
    mo.init_store(root)

    # ── 写入阶段 ──
    t0 = time.time()
    for i in range(n):
        topic = i % topic_space
        mo.deposit(
            root,
            category="benchmark",
            summary="bench item %d about topic %d keyword" % (i, topic),
            tags="bench,t%d" % topic,
            body="synthetic memory %d for performance testing topic %d" % (i, topic),
            defer_index=True,
            auto_link=False,
            recorded_by="benchmark",
        )
    mo.flush_memory_index(root, auto_link=False)
    dep_s = time.time() - t0

    # ── 召回阶段 ──
    queries = ["topic %d keyword" % random.randint(0, topic_space - 1)
               for _ in range(recall_times)]
    rts = []
    empty = 0
    matched_total = 0
    for q in queries:
        t = time.time()
        res = mo.recall(root, query=q, ann=ann)
        rts.append(time.time() - t)
        res = (res or [])[:top_n]
        if not res:
            empty += 1
        else:
            matched_total += len(res)

    rep = {
        "ok": True,
        "root": root,
        "backend": mo._emb_backend(),
        "ann": ann,
        "n_memories": n,
        "recall_times": recall_times,
        "top_n": top_n,
        "deposit_total_s": round(dep_s, 4),
        "deposit_per_s": round(n / dep_s, 1) if dep_s > 0 else None,
        "recall_p50_ms": round(_pctl(rts, 50) * 1000, 2),
        "recall_p95_ms": round(_pctl(rts, 95) * 1000, 2),
        "recall_avg_ms": round((sum(rts) / len(rts)) * 1000, 2) if rts else 0.0,
        "recall_empty_rate": round(empty / recall_times, 3) if recall_times else 0.0,
        "recall_avg_matched": round(matched_total / recall_times, 2) if recall_times else 0.0,
        "timestamp": datetime.datetime.now().isoformat(timespec="seconds"),
    }
    if out:
        with open(out, "w", encoding="utf-8") as f:
            json.dump(rep, f, ensure_ascii=False, indent=2)
        rep["report"] = out
    return rep


def main(argv=None):
    ap = argparse.ArgumentParser(description="keeper 性能基准（写入吞吐 + 召回时延）")
    ap.add_argument("--root", required=True,
                    help="记忆根目录（必须显式指向隔离目录，如 --root /tmp/keeper_bench；"
                         "禁止指向默认真实记忆库，否则写入的合成记忆会污染真实召回）")
    ap.add_argument("--n", type=int, default=200, help="合成记忆条数（默认 200）")
    ap.add_argument("--recall-times", type=int, default=50, help="recall 次数（默认 50）")
    ap.add_argument("--top-n", type=int, default=10, help="每次 recall 返回条数（默认 10）")
    ap.add_argument("--ann", action="store_true",
                    help="走 ANN 优化路径（默认全量扫描基线）")
    ap.add_argument("--topics", type=int, default=20, help="topic 数量空间（默认 20）")
    ap.add_argument("--out", default=None, help="JSON 报告输出路径")
    args = ap.parse_args(argv)
    rep = run_benchmark(args.root, n=args.n, recall_times=args.recall_times,
                        top_n=args.top_n, ann=args.ann, out=args.out,
                        topic_space=args.topics)
    print(json.dumps(rep, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
