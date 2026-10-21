#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
demo_walkthrough.py — Agent 本地记忆系统「端到端上手演示」

模拟一个新手从零使用本系统的完整流程，并打印每一步引擎真实返回的结果，
让你直接看到「调用长什么样、返回长什么样」。无任何外部依赖，store 落在临时目录，
跑完即弃（不污染你的真实记忆库）。

用法：
python demo_walkthrough.py
也可复制到 skill 包内（scripts/demo_walkthrough.py）供他人一键体验。
"""
import os
import sys
import tempfile
import json

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import memory_ops as M


def show(title, value):
    print("\n" + "=" * 64)
    print(title)
    print("-" * 64)
    if isinstance(value, (dict, list)):
        print(json.dumps(value, ensure_ascii=False, indent=2)[:1400])
    else:
        print(value)


def main():
    root = tempfile.mkdtemp(prefix="mem_demo_")
    print("演示 store 根目录：", root)

    # 1) 记一条「最佳实践」
    show("① 记一条经验（deposit best_practice）",
         M.deposit(root, "best_practice",
                   "用 pandas 读大 CSV 要加 chunksize 避免爆内存",
                   ["pandas", "csv", "性能"],
                   "pd.read_csv(path, chunksize=50000) 分块迭代处理。"))

    # 2) 调出来看看（recall 返回的 JSON 长什么样）
    res = M.recall(root, tag="pandas")
    show("② 用标签调出（recall --tag pandas）返回的 entries", res)

    # 3) 发现记错了 → 用 correction 纠正，自动把旧版标 superseded
    cid = M.deposit(root, "correction",
                    "上条不对：pandas 读大 CSV 应用 iterator=True + chunksize",
                    ["pandas", "csv"],
                    "read_csv 的 chunksize 本身就返回迭代器，无需额外 iterator=True。",
                    corrects=res[0]["id"])
    show("③ 纠正旧记忆（deposit --corrects 旧id）", cid)

    # 4) 再召回：纠正记忆浮现，旧版被标 superseded 不再主推
    res2 = M.recall(root, tag="pandas")
    show("④ 纠正后召回（recall --tag pandas）", [
        {"id": e["id"], "category": e.get("category"),
         "status": e.get("status"), "summary": e.get("summary")}
        for e in res2
    ])

    # 5) 让系统自我巩固（reflect --auto：去重/矛盾/分类复评/过期归档/晋升候选）
    f = M.reflect(root, auto=True)
    show("⑤ 自我巩固（reflect --auto）findings 摘要", {
        "duplicates": f["duplicates"],
        "contradictions": f["contradictions"],
        "promote_candidates": f["promote_candidates"],
        "scope_review": f["scope_review"],
    })

    # 6) 危险操作先预览（--dry-run 不执行）
    show("⑥ 删除前先预览（delete --dry-run）",
         M.delete(root, res2[0]["id"], dry_run=True))

    # 7) 确认删除（加 --yes 关闭警告）
    show("⑦ 确认删除（delete --yes）",
         M.delete(root, res2[0]["id"], yes=True))

    # 8) 健康自检
    show("⑧ 健康自检（doctor）", M.doctor(root))

    print("\n" + "=" * 64)
    print("演示结束。store 在临时目录：", root)
    print("真实使用时把 store 指向你的长期目录（环境变量 AI_MEMORY_STORE 或 --root）。")


if __name__ == "__main__":
    main()
