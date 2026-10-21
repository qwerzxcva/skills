#!/usr/bin/env python3
"""agent-local-memory-keeper · 随包集成测试门禁。

发现并运行 `scripts/tests/` 下所有 `test_*.py`，输出通过/失败统计与退出码。

设计目标（稳固优先）：
- 随技能包发布，任何改动都能 `python scripts/run_gate.py` 一键回归；
- 不依赖开发实验室的脚本（verify_claims/regression/deep_sim 等只活在实验室）；
- 失败即非零退出，可作为发版门禁（publish_gate.py 后续可调用）。

## 模块间 env 隔离（4.9.8 引入，修顺序依赖型 flaky）

多个测试模块会在 **import 期**直接改 `os.environ`（如 test_embed_cache_poison 钉
fastembed、test_import_mcp_fixes 等钉 lexical），这类副作用**无法在模块内安全撤销**：
- tearDown 若还原到「用例前」，那份快照本身就含模块级污染 → 污染照样泄漏；
- 若还原到「模块注入前」，又会连带清掉别的模块 import 期设的 lexical 基线 →
  后续测试改走默认后端去拉 90MB 模型，换一批测试失败。

实测症状：全量跑**随机**有 1 个测试失败，且每次受害者不同（一会儿
test_inject_gate、一会儿 test_md_roundtrip），单跑该模块却全过——典型顺序依赖。

故在门禁层统一兜底：**逐个模块运行，每个模块前后快照/还原 os.environ，并在模块
开跑前套用统一安全基线**（不拉模型）。这样模块间互不影响，且与执行顺序无关。

历史：4.6.4 引入，替代此前「测试只在开发实验室、发布包无门禁」的缺口。
"""
import fnmatch
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
import argparse


HERE = os.path.dirname(os.path.abspath(__file__))
TEST_DIR = os.path.join(HERE, "tests")

# 运行态产物的统一落点（hooks 侧 / daemon 侧各一个）。做成**模块级常量**（而非
# main() 里临时算）：任何入口（本文件 main / 别的门禁转发 / IDE 直跑）只要用了
# _SAFE_ENV_BASELINE，隔离就生效——避免「换个入口跑测试就又开始污染源码树」。
_HOOKS_SANDBOX = os.path.join(tempfile.gettempdir(), "keeper_gate_hooks")
_DAEMON_SANDBOX = os.path.join(tempfile.gettempdir(), "keeper_gate_daemon")

# 每个模块开跑前套用的安全基线：门禁不联网、不拉 90MB 模型。
# 需要神经后端的模块（如 test_embed_cache_poison）会在自己的 setUp 里覆盖，不受影响。
# `KEEPER_DAEMON_IDLE_SECONDS`：STATE 按库分隔后，测试各自拉起的沙箱 daemon 不再互相
# 复用（这正是修复目标），若默认「永不离线」就会一路攒在门禁机器上占端口与内存。
# 设个空闲上限让它们自己退场；生产默认值不受影响（此 env 只在本门禁进程树里）。
#
# 🔴 这里**不**统一钉库相关环境变量：各用例的运行前提由它自己声明，不是门禁的资源约束。
# 若在此统一钉死，会连带把"复制真实记忆库做同步验证"的用例判成空库而**整类跳过**——
# 那是静默的覆盖损失，比红灯更糟。
_SAFE_ENV_BASELINE = {
    "AI_MEM_EMBED_BACKEND": "lexical",
    "KEEPER_HOOKS_DIR": _HOOKS_SANDBOX,
    "KEEPER_DAEMON_DIR": _DAEMON_SANDBOX,
    "KEEPER_DAEMON_IDLE_SECONDS": "45",
}

# 2026-09-15 审计补：门禁默认走**进程内召回**，不再依赖调用方"记得声明"。
# 背景（本库既有铁律）：凡 spawn 钩子或走 recall 的测试，若落到**共享 daemon** 上，
# 会因 daemon 生命周期/状态残留产生「顺序依赖型间歇假红」——受害者每次不同、单跑必过。
# 该前提原先只存在于文档与经验里靠人记 → 现固化为代码默认值。
# 用 setdefault 而非写进 _SAFE_ENV_BASELINE：**尊重调用方的显式选择**（需要真实
# daemon 路径的用例/CI 可自行 export 覆盖），只在无人声明时才兜底，不改变既有行为。
os.environ.setdefault("KEEPER_RECALL_MODE", "inprocess")

# 子进程 runner：先 sys.path 锚定 scripts 并**预 import memory_ops 包**（命中
# scripts/memory_ops/__init__.py，而非技能根的 memory_ops.py 转发垫片），再 discover。
# 不预 import 的话，测试模块的 `if _p not in sys.path` 会把技能根插到 scripts 前面，
# `import memory_ops` 命中转发垫片（无 init_store 等顶层名）→ 大量 AttributeError。
# 预 import 让测试模块的 `import memory_ops` 直接命中 sys.modules 缓存，顺序无关。
_GATE_RUNNER = (
    "import sys, os, unittest\n"
    "HERE = os.path.abspath(os.environ['KEEPER_GATE_HERE'])\n"
    "sys.path.insert(0, HERE)\n"
    "import memory_ops  # 预 import：命中 scripts/memory_ops 包\n"
    "loader = unittest.TestLoader()\n"
    "_td = os.path.join(HERE, 'tests')\n"
    "_suite = loader.discover(_td, pattern=sys.argv[1], top_level_dir=_td)\n"
    # 🔴 必须 stream=sys.stdout：TextTestRunner 默认写 stderr，而父进程从 stdout\n"
    # 解析「Ran N tests / failures= / errors= / skipped=」。若不改，父进程统计恒为 0，\n"
    # 门禁「结论 PASS ✅」实为假绿（2026-09-17 实测：运行 0 测试却 PASS）。\n"
    "_res = unittest.TextTestRunner(verbosity=2, stream=sys.stdout).run(_suite)\n"
    "sys.exit(0 if _res.wasSuccessful() else 1)\n"
)

# 只对「必须保持」的键做越权检测。KEEPER_HOOKS_DIR 允许被模块临时改写
# （test_hook_mode_and_deploy 就故意把它指到自己的临时区），故不列入。
_LEAK_CHECKED = ("AI_MEM_EMBED_BACKEND",)

# ---------------------------------------------------------------------------
# %TEMP% 临时目录回收
# 背景：scripts/tests 下 50+ 个用例各自 tempfile.mkdtemp() 建沙箱、**从不回收**，
# 每跑一轮门禁就多留一批且无人察觉。本机实测累积 1459 MB（keeper_sync_* 的整库
# copytree 是大头）。两档判定、任一命中即回收：
#   ① 本次运行期间新建（mtime >= 门禁启动时刻）；
#   ② 超龄陈旧残留（mtime 早于 now - stale_age）——兜历史存量与上次崩溃留下的。
# ---------------------------------------------------------------------------
_TEMP_RESIDUE_PREFIXES = ("keeper_", "plain_", "mem_demo_")
# 固定共享沙箱不是 mkdtemp 随机名，且 daemon 可能仍活着，永不参与回收。
_TEMP_PINNED = frozenset({
    os.path.basename(_HOOKS_SANDBOX),
    os.path.basename(_DAEMON_SANDBOX),
})
_STALE_AGE_SECONDS = 6 * 3600


def _release_db_handles():
    """回收前主动释放本进程持有的 sqlite 句柄。

    🔴 **为什么必须做（2026-09-16 实测，不是推测）**：memory_ops 的 per-root 连接池
    （`_persistence._DB_CACHE`）**只在 atexit 关闭**，而回收发生在 atexit **之前**
    ⇒ 沙箱里的 `store/index.db` 仍被本进程持有 ⇒ Windows 抛共享冲突拒绝删除
    ⇒ 原实现 `shutil.rmtree(ignore_errors=True)` **静默吞掉**，回收数虚低。
    证据链：
      · 三轮全量门禁（399 / 409 / 415 用例）回收数**恒为 99 个 / 0.7 MB** ——
        用例数变了、"99" 不动 ⇒ 不是回收量正常，而是**大批删除失败没被计数**；
      · 单跑 `test_md_roundtrip.py`：新建 1 个含 `index.db` 的沙箱，
        跑完日志**连「回收本轮临时目录」这行都没有**（该行仅 `_n>0` 时打印）⇒ 回收 0 个；
      · 该目录在进程退出 14.7s 后 `shutil.rmtree`（不加 ignore_errors）**一次成功**
        ⇒ 占用者是**本进程的 sqlite 连接**，不是权限问题。
    教训：`ignore_errors=True` 让「删不掉」和「没东西可删」看起来一模一样。

    全程 fail-open：句柄释放失败绝不能让门禁判红。
    """
    try:
        import gc
        _close = None
        for key in ("memory_ops._persistence",):
            _mod = sys.modules.get(key)
            if _mod is not None:
                _close = getattr(_mod, "_db_close_all", None)
                if callable(_close):
                    break
        if callable(_close):
            try:
                _close()
            except Exception:
                pass
        # 游标/临时对象持有的剩余句柄靠 GC 回收（sqlite3 的 C 层释放要等引用归零）
        gc.collect()
    except Exception:
        pass


def _rmtree_retry(path, attempts=3, delay=0.2):
    """删除目录，失败则短暂等待后重试，返回是否删净。

    句柄释放由调用方在批量删除**前**做一次（见 `_release_db_handles`）；
    这里只兜底「刚释放、底层还没落定」的时间窗。仍失败则如实上报
    （见 `with_stats`），由下一轮门禁的「超龄档」兜底，绝不静默。
    ⚠️ **不要在这里调 `_release_db_handles`**：每个目录一次 `gc.collect()` 在
    900 个残留的场景下会把回收拖成几十秒（回收是卫生动作，不该反过来拖慢门禁）。
    """
    for i in range(attempts):
        shutil.rmtree(path, ignore_errors=True)
        if not os.path.exists(path):
            return True
        if i < attempts - 1:
            time.sleep(delay)
    return not os.path.exists(path)


def _cleanup_temp_residue(since_ts, stale_age=_STALE_AGE_SECONDS, base=None,
                          with_stats=False):
    """回收本技能测试在 %TEMP% 留下的临时目录。

    返回 `(回收目录数, 释放字节数)`；`with_stats=True` 时返回
    `(回收目录数, 释放字节数, 未能回收数)`——**失败数必须能拿到**，
    否则「删不掉」与「没东西可删」无法区分（这正是 5.0 前每轮漏约 2/3 的原因）。

    安全边界（三条都不能省）：
      - **白名单前缀**：只认本技能建的目录，绝不扫别人的；
      - **固定沙箱排除**：_HOOKS_SANDBOX / _DAEMON_SANDBOX 始终不动；
      - **跑前那档传 now**：判据「mtime >= since_ts」天然不命中，只清超龄的，
        因此绝不会误伤**并发进程刚建的**沙箱。
    **任何异常都 fail-open**：回收是磁盘卫生动作，不能反过来把门禁判红。
    """
    base = base or tempfile.gettempdir()
    now = time.time()
    try:
        names = os.listdir(base)
    except OSError:
        return (0, 0, 0) if with_stats else (0, 0)
    removed = freed = failed = 0
    pending = []          # (path, size)：首轮删失败的，第二轮重试
    # 🔴 批量删除前**只放一次**句柄：占用者通常是本进程 memory_ops 的连接池
    #    （只在 atexit 关闭），放掉之后首轮就能删掉绝大多数。见 _release_db_handles。
    _release_db_handles()
    for name in names:
        if name in _TEMP_PINNED or not name.startswith(_TEMP_RESIDUE_PREFIXES):
            continue
        path = os.path.join(base, name)
        if not os.path.isdir(path):
            continue
        try:
            mtime = os.path.getmtime(path)
        except OSError:
            continue
        if not (mtime >= since_ts or (now - mtime) > stale_age):
            continue
        size = 0
        for dirpath, _dirnames, filenames in os.walk(path):
            for fn in filenames:
                try:
                    size += os.path.getsize(os.path.join(dirpath, fn))
                except OSError:
                    pass
        # 删不掉不再静默吞掉：进 pending 重试，仍失败则计入 failed 并上报。
        shutil.rmtree(path, ignore_errors=True)
        if os.path.exists(path):
            pending.append((path, size))
        else:
            removed += 1
            freed += size
    # 第二轮：兜「句柄刚释放、底层还没落定」的时间窗（一次等待 + 重试）。
    if pending:
        time.sleep(0.3)
        _release_db_handles()
        for path, size in pending:
            if _rmtree_retry(path):
                removed += 1
                freed += size
            else:
                failed += 1
    if with_stats:
        return removed, freed, failed
    return removed, freed


def _sandbox_hooks_dir():
    """确保两个运行态沙箱目录存在，返回 hooks 侧那个。

    测试若直接 import 源码树里的 hooks 模块，或 spawn 源码树的钩子脚本 / 守护进程，
    状态文件（注入去重、审计日志、守护进程 STATE 里的端口与 token 等）会写回源码树，
    进而可能随发布包外泄——daemon 的状态文件曾因同类路径把 token 带进包。
    在门禁层统一重定向 = 一处收口，且与「逐模块隔离」的设计一致。
    """
    for _d in (_HOOKS_SANDBOX, _DAEMON_SANDBOX):
        try:
            os.makedirs(_d, exist_ok=True)
        except OSError:
            pass
    return _HOOKS_SANDBOX


def _restore_env(saved):
    """把 os.environ 还原到 saved 快照。

    逐个赋值而非 update：某些沙箱会注入 >32767 字符的环境变量（如
    ACC_PRODUCT_CONFIG_V3），Windows 下重新 set 会抛 ValueError，直接 update 会
    让 os.environ 停在「部分清除」的损坏状态。超限变量属环境产物，跳过。
    """
    os.environ.clear()
    for k, v in saved.items():
        try:
            os.environ[k] = v
        except ValueError:
            pass


def main(argv=None):
    parser = argparse.ArgumentParser(description="keeper 随包集成测试门禁")
    parser.add_argument(
        "--pattern", default="test_*.py",
        help="测试文件匹配模式（默认 test_*.py）",
    )
    parser.add_argument(
        "--keep-temp", action="store_true",
        help="保留 %%TEMP%% 下的测试临时目录（默认跑完回收；复现残留问题时用）",
    )
    args = parser.parse_args(argv)
    gate_start = time.time()  # 跑后回收「本轮新建」的判据

    # 让测试能 import 包内模块（memory_ops / mem_bridge / contract）
    if HERE not in sys.path:
        sys.path.insert(0, HERE)

    if not os.path.isdir(TEST_DIR):
        print(f"[gate] 测试目录不存在: {TEST_DIR}")
        return 2

    # 确保钩子运行态沙箱就绪（env 值已由 _SAFE_ENV_BASELINE 提供）
    _sandbox_hooks_dir()

    # 先扫一遍超龄残留（历史存量 / 上次崩溃留下的）。此处传「当前时刻」，
    # 「本轮新建」那档天然不命中，故不会误伤并发进程刚建的沙箱。
    if not args.keep_temp:
        _n, _freed, _failed = _cleanup_temp_residue(time.time(), with_stats=True)
        if _n:
            print("[gate] 回收陈旧临时目录 %d 个（释放 %.1f MB）" % (_n, _freed / 1048576.0))
        if _failed:
            print("[gate] ⚠️ 有 %d 个陈旧沙箱未能回收（句柄未释放），下次跑门禁再试" % _failed)

    # 逐个模块在**独立子进程**运行（进程级隔离，根治顺序依赖型 flaky）。
    # 5.0.x：原实现 loader.discover + runner.run 在同一进程内跑所有模块，仅做
    # os.environ 快照/还原，无法隔离 `_emb` 等模块的**进程内全局状态** →
    # 「声明 lexical 却触发模型探测」的模块会把 backend 状态污染给后续模块，
    # 造成顺序依赖型 flaky（同一批用例全量跑失败、单跑必过、受害者每次不同）。
    # 改每模块独立子进程：import 副作用与全局状态天然隔离，与执行顺序无关。
    files = sorted(f for f in os.listdir(TEST_DIR) if fnmatch.fnmatch(f, args.pattern))
    if not files:
        print(f"[gate] 没有匹配 {args.pattern} 的测试文件")
        return 2

    total = failures = errors = skipped = 0
    failed_modules = []
    for fn in files:
        env = dict(os.environ)
        env.update(_SAFE_ENV_BASELINE)
        try:
            _env = dict(env)
            _env["KEEPER_GATE_HERE"] = HERE
            p = subprocess.run(
                [sys.executable, "-c", _GATE_RUNNER, fn],
                capture_output=True, text=True, encoding="utf-8",
                errors="replace", env=_env, cwd=HERE, timeout=900,
            )
        except Exception as _e:
            print("[gate] ⚠️ 模块 %s 子进程启动失败：%s" % (fn, _e))
            errors += 1
            failed_modules.append(fn)
            continue
        out = p.stdout or ""
        # 透传子进程输出（保留 -v 逐用例详情），便于定位失败
        sys.stdout.write(out)
        if p.stderr:
            sys.stderr.write(p.stderr)
        m_ran = re.search(r"Ran (\d+) tests?", out)
        m_fail = re.search(r"failures=(\d+)", out)
        m_err = re.search(r"errors=(\d+)", out)
        m_skip = re.search(r"skipped=(\d+)", out)
        ran = int(m_ran.group(1)) if m_ran else 0
        f = int(m_fail.group(1)) if m_fail else 0
        e = int(m_err.group(1)) if m_err else 0
        s = int(m_skip.group(1)) if m_skip else 0
        total += ran; failures += f; errors += e; skipped += s
        # 🔴 失败判据以子进程退出码为准（子进程已 sys.exit(0 if wasSuccessful else 1)）。
        # 2026-09-17 实测：早期版本仅从 stdout 解析 failures=/errors=，但 TextTestRunner
        # 默认写 stderr → 解析恒 0，导致「测试真失败也报 PASS」的假绿。退出码是权威信号。
        if p.returncode != 0:
            failed_modules.append(fn)
            if f == 0 and e == 0:
                # 退出码非零但 stdout 没解析到失败数（如崩溃/超时/导入错误），计入 error
                errors += 1
        # 🔴 「匹配到 test_*.py 却 0 测试」= 覆盖损失，必须判错。
        # 实测（2026-09-17）：test_v4613_evolution_synergy.py 曾以 pytest 风格
        # 顶层函数书写，unittest.discover 只认 TestCase 子类 → 该文件被判 0 测试，
        # 5 个回归用例（evolve/belief/forget/provenance 幂等/反回声/investment
        # failopen）被静默跳过，且空 suite 仍被判为成功 →
        # 门禁绿得不明不白。宁可红，不可静默少跑。
        if ran == 0:
            print(f"[gate] ❌ 模块 {fn} 发现 0 个测试（覆盖损失：文件未以 TestCase 风格书写或被误清空），判错")
            errors += 1
            failed_modules.append(fn)

    print("\n" + "=" * 56)
    print(f"[gate] 运行 {total} 个测试 · 失败 {failures} · 错误 {errors} · 跳过 {skipped}")
    if failed_modules:
        print(f"[gate] 失败模块：{', '.join(failed_modules)}")
    if skipped:
        # 跳过不判 FAIL，但要**说出来**：曾出现「宿主环境一变，某个用例整类静默跳过」——
        # 用例数从 251 掉到 248 却仍报 PASS。绿得不明不白比红灯更危险。
        print(f"[gate] ⚠️ 有 {skipped} 个用例被跳过（不参与判定），确认不是环境导致的覆盖损失")
    # 再收掉本轮跑出来的（含刚分配的沙箱），让 %%TEMP%% 不留残渣。
    if not args.keep_temp:
        _n, _freed, _failed = _cleanup_temp_residue(gate_start, with_stats=True)
        if _n:
            print("[gate] 回收本轮临时目录 %d 个（释放 %.1f MB）" % (_n, _freed / 1048576.0))
        if _failed:
            print("[gate] ⚠️ 本轮有 %d 个沙箱未能回收（句柄占用未释放），"
                  "下次跑门禁会按超龄档清掉" % _failed)

    ok = (failures == 0 and errors == 0)
    print("[gate] 结论:", "PASS ✅" if ok else "FAIL ❌")
    print("=" * 56)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
