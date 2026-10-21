#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""publish_gate.py — keeper 发版门禁：一道门拦住「带病发布」。

把本技能的三道质量闸门串成一条链，**任一红灯即非零退出**：

  1. 文档/代码一致性 —— gen_cookbook.py --strict
     COOKBOOK.md 若与代码参数漂移，使用者照文档就会踩空。
  2. 随包集成测试   —— run_gate.py
     scripts/tests/ 下全量用例（模块间 env 隔离，防顺序依赖型 flaky）。
  3. 文档声称校验   —— verify_claims.py
     文档里每一条「强制 / 自动 / 绝不」声称都要在代码里坐实，含三道防复发闸门：
     红线单一真源、同步硬拦截、符号死引用。

设计原则（与 keeper 其余闸门同一套）：
- **默认安全**：闸门脚本缺失按 FAIL 处理，不静默跳过——宁可卡住发版，也不放过带病包。
- **显式逃生**：确有需要可用 --skip-tests / --only 收窄范围，但会在输出里留痕。
- **全跑再汇总**：不遇到第一个红灯就退出，一次看全所有问题，省得修一轮跑一轮。

用法：
  python scripts/publish_gate.py                 # 三道全跑
  python scripts/publish_gate.py --skip-tests    # 跳过集成测试（逃生：环境不可用时）
  python scripts/publish_gate.py --only claims   # 只跑 claim 校验（cookbook|tests|claims）
  python scripts/publish_gate.py --timeout 5400  # 统一覆盖所有闸门的超时（默认按闸门分档）

退出码：0 全绿 ｜ 1 有闸门红灯 ｜ 2 门禁自身异常（脚本缺失等）。

关于「自动发现」：SkillHub 发布器不会自动发现本文件。发版前请显式运行本脚本，
或由 publish_skill.py 的 gate 钩子在 dry-run 前调用（取决于发布器版本是否接入）。
"""
import argparse
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent

# (step_id, 脚本名, 额外参数, 默认超时秒)：脚本名相对 HERE。
# 超时**按闸门分档**而非一刀切（P7 修复，4.9.25）：三道闸门的耗时量级差两个数量级——
# 文档一致性约 0.3s、静态断言约 20s，而全量集成测试在慢环境要十几分钟。原先统一
# 1800s，对前两道是巨大浪费余量、对 tests 却只剩 1.7 倍，实测跑满 1800s 被强杀
# （rc=124，见 _gate_timeout_4.9.24.md 存证）。显式 --timeout 仍可统一覆盖。
STEPS = [
    ("cookbook", "gen_cookbook.py", ["--strict"], 300),
    ("tests", "run_gate.py", [], 3600),
    ("claims", "verify_claims.py", [], 900),
]


def _run(script, extra, timeout=None):
    """跑单道闸门，返回 (rc, 耗时秒, 说明)。脚本缺失按 FAIL（rc=2），不静默跳过。"""
    target = HERE / script
    if not target.exists():
        return 2, 0.0, "闸门脚本缺失：%s" % target
    t0 = time.time()
    try:
        r = subprocess.run(
            [sys.executable, str(target)] + list(extra),
            cwd=str(HERE),
            timeout=timeout,
        )
        rc = r.returncode
        note = "" if rc == 0 else "（详见该脚本输出）"
    except subprocess.TimeoutExpired:
        rc, note = 124, "超时（%s 秒）" % timeout
    except Exception as ex:
        rc, note = 2, "执行异常：%s: %s" % (type(ex).__name__, ex)
    return rc, time.time() - t0, note


def main(argv=None):
    ap = argparse.ArgumentParser(description="keeper 发版门禁（cookbook + tests + claims）")
    ap.add_argument("--skip-tests", action="store_true",
                    help="跳过集成测试（逃生口：测试环境不可用时；会留痕）")
    ap.add_argument("--only", choices=[s[0] for s in STEPS], default=None,
                    help="只跑指定的一道闸门")
    ap.add_argument("--timeout", type=int, default=None,
                    help="统一覆盖所有闸门的超时秒数（默认按闸门分档："
                         "cookbook 300 / tests 3600 / claims 900）")
    args = ap.parse_args(argv)

    if args.only:
        plan = [s for s in STEPS if s[0] == args.only]
    elif args.skip_tests:
        plan = [s for s in STEPS if s[0] != "tests"]
        print("[publish-gate] 已按 --skip-tests 跳过集成测试（此轮未被完整校验）")
    else:
        plan = list(STEPS)

    print("=" * 60)
    print("[publish-gate] keeper 发版门禁 · 共 %d 道闸门" % len(plan))
    print("=" * 60)

    results = []
    for step_id, script, extra, tier_timeout in plan:
        # 显式 --timeout 统一覆盖；未给则用该闸门的分档值
        eff_timeout = args.timeout if args.timeout else tier_timeout
        head = "[%s] %s %s" % (step_id, script, " ".join(extra))
        print("")
        print("▶ %s  [超时 %ss]" % (head.rstrip(), eff_timeout))
        rc, dt, note = _run(script, extra, eff_timeout)
        flag = "PASS" if rc == 0 else "FAIL(rc=%d)" % rc
        print("◀ [%s] %s · %.1fs %s" % (step_id, flag, dt, note))
        results.append((step_id, rc))

    failed = [s for s, rc in results if rc != 0]
    print("")
    print("=" * 60)
    print("[publish-gate] 跑完 %d 道 · 通过 %d · 红灯 %d"
          % (len(results), len(results) - len(failed), len(failed)))
    if failed:
        print("[publish-gate] 红灯闸门: %s" % ", ".join(failed))
    print("[publish-gate] 结论: %s"
          % ("PASS 可发版" if not failed else "BLOCKED 已拦截发版"))
    print("=" * 60)
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
