# -*- coding: utf-8 -*-
"""
_async_deposit.py — 由 memory_auto_capture.py 异步调用的落库助手（DETACHED 子进程）。

读取临时 JSON 文件中的 root/summary/body，执行 memory_ops.deposit 沉淀为 learning 经验，
随后自删临时文件。把「embed 冷加载」从 Stop/PreCompact 钩子关键路径挪到后台，钩子延迟归零。

fail-open：绝不反向上报或阻塞主流程。
但**绝不静默丢记忆**——落库失败时把临时载荷移入 failed/ 重试队列并写诊断日志，
（而非删除），保证记忆可重试 / 可审计；仅落库成功才删除临时载荷。
"""
import os
import sys
import json
import time


def _fail_keep_payload(p, e, hooks_dir=None):
    """落库失败时不删载荷：移入 failed/ 重试队列并写诊断，避免静默丢记忆。

    failed/ 下保留原始载荷（可人工 / 定时重试），记忆永不丢失。
    任何异常都不删原始载荷（兜底）。

    hooks_dir 默认取本钩子所在目录；测试可传入临时目录以隔离产物，
    避免污染线上 hooks/failed/ 与诊断日志（否则 run_gate 会把测试噪声写进真实失败队列）。"""
    try:
        if not hooks_dir:
            # 与 keeper_hook_common.HOOKS_DIR 共用同一开关（env `KEEPER_HOOKS_DIR`）：
            # 测试/门禁隔离时不把 failed/ 载荷与诊断日志写回源码树。
            hooks_dir = (os.environ.get("KEEPER_HOOKS_DIR")
                         or os.path.dirname(os.path.abspath(__file__)))
        failed_dir = os.path.join(hooks_dir, "failed")
        os.makedirs(failed_dir, exist_ok=True)
        ts = time.strftime("%Y%m%d_%H%M%S")
        base = os.path.basename(p)
        dst = os.path.join(failed_dir, "%s_%s" % (ts, base))
        if os.path.exists(dst):
            dst += ".%d" % int(time.time() * 1000)
        try:
            os.replace(p, dst)
        except Exception:
            pass  # 移动失败则保留原位（绝不删）
        log = os.path.join(hooks_dir, "_async_deposit.failed.log")
        try:
            with open(log, "a", encoding="utf-8") as lf:
                lf.write("%s payload=%s err=%s\n" % (ts, base, repr(e)[:200]))
        except Exception:
            pass
    except Exception:
        pass  # 兜底：任何异常都不删原始载荷


def main():
    if len(sys.argv) < 2:
        return
    p = sys.argv[1]
    try:
        with open(p, encoding="utf-8") as f:
            d = json.load(f)
        root = d.get("root")
        summary = d.get("summary")
        body = d.get("body")
        if not (root and summary is not None):
            return
        sk = os.path.dirname(os.path.abspath(__file__))
        if sk not in sys.path:
            sys.path.insert(0, sk)
        import keeper_hook_common as C
        sys.path.insert(0, C.SCR)
        import memory_ops as M
        M.init_store(root)
        M.deposit(root, "learning", summary, "auto_distill", body,
                  area="learning", priority="normal", recorded_by="agent", auto_sourced=True)
    except Exception as e:
        # 失败保留载荷（移入 failed/），不静默删 → 记忆不丢 + 可审计
        _fail_keep_payload(p, e)
        return
        # 仅落库成功才删临时载荷
    try:
        os.remove(p)
    except Exception:
        pass


if __name__ == "__main__":
    main()
