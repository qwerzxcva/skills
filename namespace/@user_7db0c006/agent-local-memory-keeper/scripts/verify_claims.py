#!/usr/bin/env python3
"""verify_claims.py · 一次性批量断言所有「文档里宣传的命令/参数」

解决「连环 verify」陷阱：把分散的 10+ 次「T4 succeeded but I must verify...」
压成一次「跑+断言+出 verdict」。逻辑只有一个：每条 claim 一次跑+一次断言，
要么 PASS 要么 FAIL，绝不级联。

用法：
# 1) 跑自带的 claims.json（覆盖所有 P5 虚标变真能力 + 关键 API）
python scripts/verify_claims.py

# 2) 跑外部自定义 claim 列表（适合发版前回归）
python scripts/verify_claims.py --claims /path/to/custom.json

# 3) 自带 JSON 里选几条跑（--filter 支持 id 包含）
python scripts/verify_claims.py --filter "max-age|review|key-hint"

输出：JSON {"ok": bool, "n_pass": int, "n_fail": int, "claims": [{id, ok, ...}]}
退出码：全部 PASS=0；有 FAIL=1；JSON 解析错误=2。

设计原则（= 这个脚本存在的根因）：
- L1 防 JSON 误读：用 python -c 一次性 json.load + 断言 + 抽取字段；
永远不在 shell 层做 grep -o 之类的脆弱操作。
- L2 防连环 verify：每条 claim 一旦断言完，立刻打印 verdict，下一条。
没有「再跑一次」「再 grep 一下」的余地。
- L3 防工具粒度过细：一次 tool call 跑完所有断言，结构化输出，
调用方只需读一次 verdict。
- L4 防元思考膨胀：脚本不输出任何 "I should..." 元话语，只输出结构化 PASS/FAIL。
- L5 防 skill 没约束：本脚本作为本 skill 自带组件，强制执行 one-shot 验证。
"""
import argparse
import ast
import glob
import io
import json
import os
import re
import secrets
import subprocess
import sys
import tempfile
import tokenize
from typing import Any, Callable, Dict, List

# 动态生成测试用伪凭证，避免分发包中携带硬编码敏感字符串触发供应链卫生告警。
# 这些值仅在测试运行时存在，符合 keeper 的 secrets 扫描模式，保证断言仍有效。
_TEST_SECRET_TOKEN = "sk-" + secrets.token_hex(16)  # 匹配 openai_sk_key 模式 sk-.*{20,}


def _run(cmd: str, env: dict, timeout: int = 30) -> Dict[str, Any]:
    """Run a CLI command, return {ok, stdout, stderr, code}."""
    try:
        p = subprocess.run(
            cmd, shell=True, capture_output=True, text=True,
            env=env, timeout=timeout,
        )
        return {"ok": p.returncode == 0, "code": p.returncode,
                "stdout": p.stdout.strip(), "stderr": p.stderr.strip()}
    except subprocess.TimeoutExpired:
        return {"ok": False, "code": -1, "stdout": "", "stderr": "TIMEOUT"}
    except Exception as ex:
        return {"ok": False, "code": -1, "stdout": "", "stderr": str(ex)}


def _parse_json_output(run_result: Dict[str, Any]) -> Any:
    """把 CLI 输出解析为 JSON dict；失败抛 ValueError（带原输出便于调试）。"""
    if not run_result["ok"] and not run_result["stdout"]:
        raise ValueError(f"CLI failed: code={run_result['code']} stderr={run_result['stderr'][:200]}")
    try:
        return json.loads(run_result["stdout"])
    except json.JSONDecodeError as e:
        raise ValueError(f"stdout not JSON: {run_result['stdout'][:200]}... (err: {e})")


        # ── 断言原语（每个都是一次性消费，没有"再 verify"余地）──

def assert_in(needle: str, haystack: str, ctx: str = "") -> bool:
    return needle in haystack


def assert_json_has(payload: Any, path: str, expected: Any = None) -> bool:
    """assert_json_has(d, "entries.0.summary", "foo") — 一行断言 JSON 字段值。
    path 用 '.' 分段访问 list 索引或 dict 键；expected 不传则只断言存在。"""
    cur = payload
    for seg in path.split("."):
        if isinstance(cur, list):
            cur = cur[int(seg)]
        elif isinstance(cur, dict):
            cur = cur.get(seg)
        else:
            return False
        if cur is None:
            return False
    if expected is not None and cur != expected:
        return False
    return True


def assert_json_count(payload: Any, path: str, op: str, n: int) -> bool:
    """assert_json_count(d, "entries", "==", 3) — 断言集合长度。"""
    cur = payload
    for seg in path.split("."):
        if isinstance(cur, list):
            cur = cur[int(seg)]
        else:
            cur = cur.get(seg) if isinstance(cur, dict) else None
        if cur is None:
            return False
    actual = len(cur) if hasattr(cur, "__len__") else -1
    if op == "==":
        return actual == n
    if op == ">=":
        return actual >= n
    if op == "<=":
        return actual <= n
    if op == ">":
        return actual > n
    if op == "<":
        return actual < n
    return False


    # ── 静态自检（离线、不依赖测试库）：文档宣称 ↔ 代码现实 的一致性 ──
    # 这是「结论先取证（verify-before-conclude）」原则在 keeper 自身上的可执行化身：
    # 文档（SKILL.md）宣称的配置键，必须能被代码（KEEPER_DEFAULTS）grep 到，且完全对称；
    # 杜绝「报告/SKILL.md 说配置集中在 X，实际 grep 在 Y」这类反复踩过的漂移坑。

def _extract_dict_keys(src: str, dict_name: str) -> set:
    """抽取 `dict_name = { "k": ..., }` 块内的顶层键名集合（不求值，纯正则）。"""
    m = re.search(r"%s\s*=\s*\{(.*?)\n\}" % re.escape(dict_name), src, re.S)
    if not m:
        return set()
    return set(re.findall(r'"([A-Za-z_][A-Za-z0-9_]*)"\s*:', m.group(1)))


def _extract_dict_literal(src: str, dict_name: str) -> Dict[str, Any]:
    """用 ast 解析 `dict_name = { "k": <字面量>, }`，返回 {键: 值}。

    与 `_extract_dict_keys`（纯正则、只取键名）互补：这里拿**真实默认值**，
    用于「文档写的默认值是否与代码一致」的值级比对。非字面量（如函数调用）
    记为 None——视为「无法静态判定」，不参与比对。
    解析失败返回空 dict（由调用方判为无法校验）。
    """
    out: Dict[str, Any] = {}
    try:
        tree = ast.parse(src)
    except Exception:
        return out
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        for t in node.targets:
            if isinstance(t, ast.Name) and t.id == dict_name and isinstance(node.value, ast.Dict):
                for k, v in zip(node.value.keys, node.value.values):
                    if not isinstance(k, ast.Constant):
                        continue
                    try:
                        out[k.value] = ast.literal_eval(v)
                    except Exception:
                        out[k.value] = None
                return out
    return out


def _static_config_doc_matches_code(skill_root: str) -> Dict[str, Any]:
    """离线静态检查：SKILL.md 的 keeper 配置段列举的键，必须与 memory_ops.py 的
    KEEPER_DEFAULTS 完全对称（防止『文档宣称 X 键 / 代码实际 Y 键』漂移）。
    这是『结论先取证』原则在 keeper 自身配置上的可执行化身：文档声称的开关必须能被代码 grep 到。"""
    verdict: Dict[str, Any] = {
        "id": "config_doc_matches_code",
        "desc": "配置收口：SKILL.md keeper 段列举的键 ↔ memory_ops.KEEPER_DEFAULTS 完全对称（含 _KEEPER_ENV_MAP 存在）",
        "ok": False, "error": None, "actual": None,
    }
    skill_md = os.path.join(skill_root, "SKILL.md")
    # v4.9.1：memory_ops 已重构为包，KEEPER_DEFAULTS 实际定义在
    # scripts/memory_ops/__init__.py；scripts/memory_ops.py 只是 runpy 转发垫片。
    # 原先只查垫片 → 恒 not found（假失败）。改为按优先级依次查找，取首个命中。
    mo_candidates = [
        os.path.join(skill_root, "scripts", "memory_ops", "__init__.py"),
        os.path.join(skill_root, "scripts", "memory_ops.py"),
    ]
    mo = next((p for p in mo_candidates if os.path.isfile(p)), "")
    if not (os.path.isfile(skill_md) and mo):
        verdict["error"] = f"missing file: SKILL.md={os.path.isfile(skill_md)} memory_ops={'found' if mo else 'missing'}"
        return verdict
    md = ""
    try:
        with open(skill_md, encoding="utf-8-sig") as f:
            md = f.read()
        with open(mo, encoding="utf-8") as f:
            mosrc = f.read()
    except Exception as ex:
        verdict["error"] = f"read failed: {ex}"
        return verdict

        # 1) 代码侧键集合（KEEPER_DEFAULTS）
    code_keys = _extract_dict_keys(mosrc, "KEEPER_DEFAULTS")
    if not code_keys:
        verdict["error"] = "KEEPER_DEFAULTS not found / empty in %s" % os.path.relpath(mo, skill_root)
        return verdict

        # 2) 文档侧：SKILL.md 中含 "keeper" 的 ```json 块（同时取键与值）
    doc_block = ""
    for block in re.findall(r"```json\s*(.*?)```", md, re.S):
        if '"keeper"' in block:
            doc_block = block
            break
    doc_keys = set()
    if doc_block:
        doc_keys = set(re.findall(r'"([A-Za-z_][A-Za-z0-9_]*)"\s*:', doc_block))
        doc_keys.discard("keeper")  # "keeper" 是容器键，不是配置开关
    if not doc_keys:
        verdict["error"] = "SKILL.md keeper JSON block not found / no keys extracted"
        return verdict

        # 3) 对称比对 + env 映射存在性（证明 env 覆盖已接线）
    missing_in_doc = sorted(code_keys - doc_keys)
    missing_in_code = sorted(doc_keys - code_keys)
    env_map_ok = "_KEEPER_ENV_MAP" in mosrc
    if missing_in_doc or missing_in_code or not env_map_ok:
        verdict["error"] = (
            f"code↔doc key mismatch: in_code_not_doc={missing_in_doc} "
            f"in_doc_not_code={missing_in_code} env_map={env_map_ok}"
        )
        verdict["actual"] = f"code={sorted(code_keys)} doc={sorted(doc_keys)}"
        return verdict

        # 4) 值比对：文档 JSON 块里的默认值必须与代码 KEEPER_DEFAULTS 逐键相等。
        #    只比键名会漏掉「键都在、但值写错」——那正是默认值漂移最常见也最隐蔽的形态
        #    （例如文档写 "auto_capture": false，代码是 True，旧断言照样放行）。
    code_vals = _extract_dict_literal(mosrc, "KEEPER_DEFAULTS")
    if not code_vals:
        verdict["error"] = "无法用 ast 解析 KEEPER_DEFAULTS 字面量，值级比对回退失败（拒判，不静默放行）"
        return verdict
    try:
        _obj = json.loads(doc_block)
    except Exception as _ex:
        verdict["error"] = "SKILL.md keeper JSON block 不是合法 JSON，无法比值: %s" % _ex
        return verdict
    _doc_keeper = _obj.get("keeper") if isinstance(_obj, dict) else None
    if not isinstance(_doc_keeper, dict):
        verdict["error"] = "SKILL.md keeper JSON block 缺少可解析的 keeper 对象"
        return verdict

    val_mismatch = []
    for k in sorted(set(code_vals.keys()) & set(_doc_keeper.keys())):
        cv = code_vals.get(k)
        if cv is None:          # 代码侧非字面量 → 无法静态判定，跳过
            continue
        dv = _doc_keeper.get(k)
        if str(cv) != str(dv):
            val_mismatch.append("%s: code=%r doc=%r" % (k, cv, dv))
    if val_mismatch:
        verdict["error"] = "code↔doc 默认值不一致: " + "; ".join(val_mismatch[:6])
        verdict["actual"] = "; ".join(val_mismatch)
        return verdict

    verdict["ok"] = True
    verdict["actual"] = (f"{len(code_keys)} keys symmetric + values equal; _KEEPER_ENV_MAP present")
    return verdict


def _static_claimed_scripts_exist(skill_root: str) -> Dict[str, Any]:
    """离线静态检查：SKILL.md / references/*.md 提及的 `scripts/*.py` 必须真实存在，
    除非同上下文明确标注「规划中 / 未发布」等豁免词（如 mem_bridge）。
    拦截『文档声称有、代码没有』的虚标（双写漂移的变种：文档侧单方面造事实）。

    典型捕获：SKILL.md 写「mem_bridge.py 已随本包发布」，但 scripts/ 下无此文件——
    读者按文档去找会扑空。降级为「规划中」并配豁免词后，本检查放行；若日后有人
    把文档改回「已发布」却忘了补脚本，本检查会 FAIL 拦下，防回归。
    """
    import glob
    verdict: Dict[str, Any] = {
        "id": "claimed_scripts_exist",
        "desc": "文档提及的 scripts/*.py 必须真实存在（豁免：同上下文标注规划中/未发布）",
        "ok": False, "error": None, "actual": None,
    }
    _EXEMPT_WORDS = ("规划中", "未发布", "尚未", "待发布", "未随包", "暂未", "尚未随包发布")
    md_files = [os.path.join(skill_root, "SKILL.md")]
    md_files += sorted(glob.glob(os.path.join(skill_root, "references", "*.md")))
    text = ""
    try:
        for fp in md_files:
            if os.path.isfile(fp):
                with open(fp, encoding="utf-8-sig") as f:
                    text += "\n" + f.read()
    except Exception as ex:
        verdict["error"] = f"read failed: {ex}"
        return verdict

    mentioned = set(re.findall(r"scripts/([A-Za-z0-9_]+\.py)", text))
    missing = []
    for name in sorted(mentioned):
        fpath = os.path.join(skill_root, "scripts", name)
        if os.path.isfile(fpath):
            continue
            # 豁免判断：提及处前后上下文含豁免词 → 视为「已知未发布」，放行
        idx = text.find("scripts/" + name)
        ctx = text[max(0, idx - 120): idx + 160] if idx >= 0 else ""
        if any(w in ctx for w in _EXEMPT_WORDS):
            continue
        missing.append(name)
    if missing:
        verdict["error"] = f"claimed scripts missing (not exempted): {missing}"
        verdict["actual"] = f"mentioned={sorted(mentioned)}"
        return verdict
    verdict["ok"] = True
    verdict["actual"] = f"{len(mentioned)} mentioned scripts all exist (or exempted)"
    return verdict


def _static_redline_single_source(skill_root: str) -> Dict[str, Any]:
    """红线/边界收敛闸门：防止「警示分散 + 表述失真/矛盾」复发。

    背景：删除的警示曾散落在 9+ 份文档里，并造成一类真实危害——
      **事实矛盾**：`delete --yes`（真删、不可逆）被标成「可找回」，与红线直接冲突。
    现已收敛为 SKILL.md §九「红线与边界」单一真源。本断言把结论固化：
      1. SKILL.md 必须存在含「红线与边界」的章节（真源不能被删/改名而指针不回扫）；
      2. `delete --yes` / 「真删」后 16 字符内不得出现**肯定**的「可找回 / 可恢复」。
    """
    verdict: Dict[str, Any] = {
        "id": "redline_single_source",
        "desc": "红线收敛：SKILL.md 存在「红线与边界」真源章节；全库无『真删可找回』矛盾表述",
        "ok": False, "error": None, "actual": None,
    }
    skill_md = os.path.join(skill_root, "SKILL.md")
    if not os.path.isfile(skill_md):
        verdict["error"] = "missing SKILL.md"
        return verdict

    targets = [("SKILL.md", skill_md),
               ("QUICKSTART.md", os.path.join(skill_root, "QUICKSTART.md"))]
    ref_dir = os.path.join(skill_root, "references")
    if os.path.isdir(ref_dir):
        for fn in sorted(os.listdir(ref_dir)):
            if fn.endswith(".md"):
                targets.append(("references/" + fn, os.path.join(ref_dir, fn)))

    # ① 真源章节必须存在
    has_source = False
    try:
        with open(skill_md, encoding="utf-8-sig") as f:
            for line in f:
                if line.startswith("#") and "红线与边界" in line:
                    has_source = True
                    break
    except Exception as ex:
        verdict["error"] = "read SKILL.md failed: %s" % ex
        return verdict
    if not has_source:
        verdict["error"] = "SKILL.md 缺少含「红线与边界」的真源章节标题（指针会全部断链）"
        return verdict

    # 矛盾表述闸门
    _NEG2 = ("不可", "无法", "不能", "难以", "没法")
    _NEG1 = "不无未没难"

    bad_contradiction: List[str] = []
    scanned = 0
    for rel, path in targets:
        if not os.path.isfile(path):
            continue
        try:
            with open(path, encoding="utf-8-sig") as f:
                lines = f.read().splitlines()
        except Exception:
            continue
        scanned += 1
        for i, line in enumerate(lines, 1):
            for m in re.finditer(r"(?:delete\s+--yes|真删)", line):
                seg = line[m.end():m.end() + 16]
                for mm in re.finditer(r"可(找回|恢复)", seg):
                    pre = seg[max(0, mm.start() - 2):mm.start()]
                    if pre in _NEG2 or (pre and pre[-1] in _NEG1):
                        continue  # 否定表述（不可找回）是正确写法
                    bad_contradiction.append("%s:%d" % (rel, i))
                    break

    if bad_contradiction:
        verdict["error"] = "矛盾表述=%s" % (bad_contradiction[:5],)
        verdict["actual"] = {"contradiction": bad_contradiction}
        return verdict

    verdict["ok"] = True
    verdict["actual"] = {"scanned_files": scanned}
    return verdict


def _code_body(src: str) -> str:
    """返回去掉注释与字符串字面量的代码骨架（只留 NAME/OP/NUMBER 等真实代码 token）。

    用途：判断某标识符是否「真的在代码里」。若直接搜全文，字符串常量
    （如 SQL 语句、事件名 "PostToolUse"）会被误当成定义，掩盖死引用。
    """
    out = []
    try:
        for tok in tokenize.generate_tokens(io.StringIO(src).readline):
            if tok.type in (tokenize.COMMENT, tokenize.STRING, tokenize.NL,
                            tokenize.NEWLINE, tokenize.INDENT, tokenize.DEDENT):
                continue
            out.append(tok.string)
    except Exception:
        return src
    return " ".join(out)


# 标准库 / 内置 / 非本项目符号：文档提到它们不是死引用
_STDLIB_NAMES = set("""os sys json re glob shutil tempfile subprocess argparse time datetime hashlib
base64 hmac getpass urllib socket threading sqlite3 pathlib pickle copy collections itertools
functools math random string textwrap traceback logging unittest importlib ast types typing
dataclasses enum abc io csv platform locale signal struct uuid warnings contextlib operator
secrets stat codecs errno print len range dict list set str int float bool open super isinstance
getattr setattr hasattr enumerate zip map filter sorted sum min max abs round type id dir vars
repr format input""".split())

# 反引号里的两种候选形态
_RE_CALL = re.compile(r"`([A-Za-z_][A-Za-z0-9_]*)\s*\(")   # `foo(` 调用形态
_RE_PRIV = re.compile(r"`(_[A-Za-z0-9_]{3,})`")             # `_foo` 私有名


def _string_body(src: str) -> str:
    """返回所有**非 docstring** 的字符串常量。

    SQL 命令（wal_checkpoint）、事件名（PostToolUse）、配置键这类「确实存在但不在代码
    符号表里」的名字应豁免——它们通常作为字符串常量出现。

    ⚠️ 必须剔除 docstring：tokenize 把 docstring 也归为 STRING，若不排除，
    写在 docstring 里的历史错误名会被当成字符串常量永久豁免，闸门形同虚设。
    """
    tree = ast.parse(src)          # 解析失败直接抛出：绝不静默返回空（那等于静默放宽闸门）
    doc_ids = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            b = getattr(node, "body", None)
            if b and isinstance(b[0], ast.Expr) and isinstance(b[0].value, ast.Constant) \
                    and isinstance(b[0].value.value, str):
                doc_ids.add(id(b[0].value))
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) \
                and id(node) not in doc_ids:
            out.append(node.value)
    return " ".join(out)


def _collect_py_comment_lines(code_files, skip_tests=True):
    """提取 .py 中的注释行与 docstring 行（tests/ 目录默认跳过：那里常写「故意拼错的名字」做负向用例）"""
    out = []
    for p in code_files:
        if skip_tests and (os.sep + "tests" + os.sep) in (os.sep + p):
            continue
        try:
            lines = io.open(p, encoding="utf-8", errors="ignore").read().split("\n")
        except Exception:
            continue
        q3, q3s = chr(34) * 3, chr(39) * 3      # 避免三引号字面量嵌套
        in_doc = False
        for i, line in enumerate(lines, 1):
            s = line.strip()
            n3 = s.count(q3) + s.count(q3s)
            if in_doc:
                out.append((p, i, line))
                if n3:
                    in_doc = False
                continue
            if s.startswith("#"):
                out.append((p, i, line))
            elif n3 == 1 and (s.startswith(q3) or s.startswith(q3s)):
                in_doc = True
                out.append((p, i, line))
            elif s.startswith(q3) or s.startswith(q3s):
                out.append((p, i, line))
    return out


def _static_no_dead_symbol_refs(skill_root: str) -> Dict[str, Any]:
    """死引用闸门：文档/注释里点名的符号，代码里必须真存在。

    背景：模块头注释曾写「某 secrets 扫描函数（写前一票否决）」——而那个函数
    **根本不存在**，真名是 `_scan_sensitive()`。此类「注释声称的机制」比删除警示更隐蔽：
    读者（含 AI）会以为有一道保障，实际是空的，于是放心做危险操作。

    判定：候选符号需满足「本文件代码骨架 / 其他文件骨架+全文」都搜不到。
    - 排除本文件注释但保留本文件代码：否则同文件定义的函数会被误杀（踩过：_is_substantive）。
    - 其他文件搜「代码骨架 + 字符串字面量」：SQL 命令 / 事件名 / 配置键正确豁免；
      **注释不算存在**——否则不存在的名字只要在注释里被提过一次就永久放过了。
    - 确有理由引用不存在的名字（如描述重构前的旧名）时，在该行写 `deadref-ok` 显式豁免。
    """
    verdict: Dict[str, Any] = {
        "id": "no_dead_symbol_refs",
        "desc": "文档/注释点名的符号必须在代码里存在（防「注释声称的机制实际不存在」式死引用）",
        "ok": False, "error": None, "actual": None,
    }

    code_files = []
    for pat in ("scripts/**/*.py", "*.py", "hooks/*.py"):
        for p in glob.glob(os.path.join(skill_root, pat), recursive=True):
            if "__pycache__" not in p and os.path.isfile(p):
                # 前缀 _retired_ / _bak_ 是退休件与改造期快照（装的是旧版源码），
                # 不是生产代码：纳入扫描会让本闸门对着历史副本报「死引用」。
                # 实测 2026-09-15 加密下线：2 处命中全部来自
                # scripts/memory_ops/_retired_tmp_20260915/_crypto.py。
                _rel = os.path.relpath(p, skill_root)
                if any(seg.startswith(("_retired", "_bak")) for seg in _rel.split(os.sep)):
                    continue
                code_files.append(p)
    if not code_files:
        verdict["error"] = "no python files found"
        return verdict

    body, strs, parse_failed = {}, {}, []
    for p in code_files:
        try:
            src = io.open(p, encoding="utf-8", errors="ignore").read()
        except Exception:
            continue
        body[p] = _code_body(src)
        try:
            strs[p] = _string_body(src)
        except SyntaxError:
            # 语法无法解析的文件不提供「字符串豁免」来源，但也不因此判死引用失败；
            # 记名以便观测（宁可少豁免，不可静默放宽）
            strs[p] = ""
            parse_failed.append(os.path.relpath(p, skill_root))

    # 磁盘上的文件名/目录名：文档提到它们不是死引用（如 `_core` → _core.py）
    names_on_disk = set()
    for dirpath, dirnames, filenames in os.walk(skill_root):
        if "__pycache__" in dirpath or ".workbuddy" in dirpath:
            continue
        for d in dirnames:
            names_on_disk.add(d)
        for f in filenames:
            names_on_disk.add(f)
            names_on_disk.add(os.path.splitext(f)[0])

    def _skip(name: str) -> bool:
        if name in _STDLIB_NAMES or name.isupper() or len(name) < 4:
            return True
        if re.fullmatch(r"_+[A-Za-z0-9]+_+", name):      # `_review_` 这类前后缀说明
            return True
        if name in names_on_disk:
            return True
        for n in names_on_disk:
            if len(name) >= 6 and len(n) < 60 and name in n:
                return True
        return False

    def _exists(name: str, self_file=None) -> bool:
        """存在 = 代码骨架 或 非 docstring 字符串中找到。**注释不算**。

        私有名额外允许**前缀匹配**：文档常写符号族名（如 `_recall_cache`），
        而代码里是 `_recall_cache_key/_get/_set`。
        """
        pat = r"(?<![A-Za-z0-9_])%s(?![A-Za-z0-9_])" % re.escape(name)
        pre = r"(?<![A-Za-z0-9_])%s" % re.escape(name) if name.startswith("_") else None
        for p in code_files:
            if self_file and os.path.abspath(p) == os.path.abspath(self_file):
                continue
            if pre and re.search(pre, body.get(p, "")):
                return True
            if re.search(pat, body.get(p, "")) or re.search(pat, strs.get(p, "")):
                return True
        if self_file and (re.search(pat, body.get(self_file, ""))
                          or (pre and re.search(pre, body.get(self_file, "")))):
            return True
        return False

    dead = []
    scanned = 0
    md_targets = [("SKILL.md", os.path.join(skill_root, "SKILL.md")),
                  ("QUICKSTART.md", os.path.join(skill_root, "QUICKSTART.md"))]
    ref_dir = os.path.join(skill_root, "references")
    if os.path.isdir(ref_dir):
        for fn in sorted(os.listdir(ref_dir)):
            if fn.endswith(".md"):
                md_targets.append(("references/" + fn, os.path.join(ref_dir, fn)))

    for rel, path in md_targets:
        if not os.path.isfile(path):
            continue
        scanned += 1
        for i, line in enumerate(io.open(path, encoding="utf-8-sig").read().split("\n"), 1):
            if "deadref-ok" in line:
                continue
            for rx in (_RE_CALL, _RE_PRIV):
                for m in rx.finditer(line):
                    nm = m.group(1)
                    if _skip(nm) or _exists(nm):
                        continue
                    dead.append("SKILL: %s:%d `%s`" % (rel, i, nm))

    for p, i, line in _collect_py_comment_lines(code_files):
        if "deadref-ok" in line:
            continue
        for rx in (_RE_CALL, _RE_PRIV):
            for m in rx.finditer(line):
                nm = m.group(1)
                if _skip(nm) or _exists(nm, self_file=p):
                    continue
                dead.append("CODE: %s:%d `%s`" % (os.path.relpath(p, skill_root), i, nm))

    if dead:
        verdict["error"] = "dead symbol refs (%d): %s" % (len(dead), "; ".join(dead[:8]))
        verdict["actual"] = {"scanned_md": scanned, "dead": dead}
        return verdict

    verdict["ok"] = True
    verdict["actual"] = {"scanned_md": scanned, "scanned_py": len(code_files), "dead": 0,
                         "parse_failed": parse_failed}
    return verdict


# 「高危默认值声明」事实表。
# 每条自带 code_check 正则：只有代码里确实存在该默认值时，对应禁令才生效——
# 代码默认值一旦翻转，禁令自动失效，不会退化成过时的死规则（避免"闸门比文档还旧"）。
# ⚠️ 禁令正则需**窄而精确**，只禁「明确的相反声明」，不许禁「澄清误解」的句子
#    （反例：正确写法「默认不是『不自动记』」不得被禁）。
_DEFAULT_FACTS: List[Dict[str, Any]] = [
    {
        "fact": "auto_capture 默认开（对话内自动沉淀 converse，每 20 轮一次）",
        "code_file": ("scripts", "memory_ops", "__init__.py"),
        "code_pat": r'"auto_capture"\s*:\s*True',
        "code_env_pat": r'"auto_capture"\s*:\s*"KEEPER_AUTO_CAPTURE"',
        "forbid": [r"默认\s*\*{0,2}不自动"],
        "hint": "代码 auto_capture=True → 文档不得声称「默认不自动运行 / 默认不自动记」",
    },
    {
        "fact": "会话钩子默认自动注册（KEEPER_AUTO_INSTALL_HOOKS 默认开）",
        "code_file": ("scripts", "memory_ops", "_hooks.py"),
        "code_pat": r'"KEEPER_AUTO_INSTALL_HOOKS"\s*,\s*"1"',
        "code_env_pat": None,
        "forbid": [r"(钩子|自动记忆)[^\n]{0,40}需(要)?跑一次[^\n]{0,40}才(激活|生效)"],
        "hint": "代码钩子默认自动注册 → 文档不得声称「钩子需跑一次 setup 才激活」",
    },
]


def _static_default_claims_consistent(skill_root: str) -> Dict[str, Any]:
    """静态检查：文档对**高危默认值**的说法必须与代码一致（正反短语闸门）。

    动机（实锤，非假想）：文档曾同时存在三组与代码相反的默认值声明，且长期无人发现——
      · LIMITS §7 写「默认不自动运行，须显式说『记一下』才触发」，而代码 auto_capture=True；
      · SKILL.md / CAPABILITY_MAP 把「自动记忆（钩子）」标成需手动开启，而代码默认自动注册。
    既有断言 `config_doc_matches_code` **只比键名、不比值，且只看一个 JSON 块**，
    完全管不到散落 prose——本断言正是补这个盲区。

    做法：把「代码默认值 → 禁止的相反说法」成对固化在 `_DEFAULT_FACTS`，双向把关：
      ① 先确认代码里**确实**是该默认值（否则该条不适用，避免死规则）；
      ② 再扫用户文档，命中禁令正则即 FAIL，并给出归因（哪条事实、为什么禁）。
    与 `no_dead_symbol_refs` 同理：desc 里不复述禁令原文，避免自我豁免歧义。
    """
    verdict: Dict[str, Any] = {
        "id": "default_claims_consistent",
        "desc": "默认值声明：文档对高危默认值（自动捕获 / 钩子自动注册）的说法必须与代码一致",
        "ok": False, "error": None, "actual": None,
    }

    # 收集用户文档（与 redline 闸门同范围；刻意排除 CHANGELOG 与 _design 内部稿）
    targets = [("SKILL.md", os.path.join(skill_root, "SKILL.md")),
               ("QUICKSTART.md", os.path.join(skill_root, "QUICKSTART.md"))]
    ref_dir = os.path.join(skill_root, "references")
    if os.path.isdir(ref_dir):
        for fn in sorted(os.listdir(ref_dir)):
            if fn.endswith(".md"):
                targets.append(("references/" + fn, os.path.join(ref_dir, fn)))

    corpus = []  # [(rel, lineno, line)]
    for rel, path in targets:
        if not os.path.isfile(path):
            continue
        try:
            with open(path, encoding="utf-8-sig") as f:
                for i, line in enumerate(f.read().splitlines(), 1):
                    corpus.append((rel, i, line))
        except Exception:
            continue
    if not corpus:
        verdict["error"] = "未读到任何用户文档（扫描集为空）"
        return verdict

    active_facts = 0
    violations: List[str] = []
    for fact in _DEFAULT_FACTS:
        cf = os.path.join(skill_root, *fact["code_file"])
        try:
            with open(cf, encoding="utf-8") as f:
                csrc = f.read()
        except Exception as ex:
            verdict["error"] = "读取代码文件失败 %s: %s" % (os.path.relpath(cf, skill_root), ex)
            return verdict
        # ① 代码默认值是否存在（不存在 → 本条不适用）
        if not re.search(fact["code_pat"], csrc):
            continue
        if fact.get("code_env_pat") and not re.search(fact["code_env_pat"], csrc):
            # 有默认值但缺少 env 映射 → 说明代码本身不完整，记为明确失败而非跳过
            verdict["error"] = ("代码有默认值但缺 env 映射：%s（%s）"
                                % (fact["fact"], fact["code_env_pat"]))
            return verdict
        active_facts += 1
        # ② 扫文档禁令
        for rel, i, line in corpus:
            for pat in fact["forbid"]:
                if re.search(pat, line):
                    violations.append("%s:%d [%s] %s" % (rel, i, fact["fact"], line.strip()[:90]))

    if not active_facts:
        verdict["error"] = ("_DEFAULT_FACTS 全部未在代码中匹配到默认值——"
                            "要么事实表过时，要么代码路径变更（拒判，不静默放行）")
        return verdict
    if violations:
        verdict["error"] = "默认值相反声明（%d）：%s" % (len(violations), " | ".join(violations[:6]))
        verdict["actual"] = violations
        return verdict

    verdict["ok"] = True
    verdict["actual"] = "%d 条高危默认值事实：代码默认值存在，且文档无相反声明" % active_facts
    return verdict


# ── 第 6 条 · 发布包洁净度：运行态产物不得进包 ──
# 背景：hooks/ 与 keeper_daemon/ 里的 .json 状态文件是「跑起来才有」的东西——注入钩子记
# 已注入 id（_session_inject.json）、自动捕获记轮次（_auto_cap.json）、错误捕获记状态、
# 守护进程记端口/token/pid（STATE 名按记忆库带指纹：`.daemon-<库指纹>.json`）。
# 发布器只按 .log/.lock/.pid/.jsonl 等**后缀**
# 排除，不覆盖 .json 状态；而测试在源码树里跑钩子/守护进程时会把它们写回源码目录 →
# 这些文件曾真的躺进待发布清单（那份状态里还带着上一台机器的端口与本地 token）。
#
# 为什么不直接扫「源码树里有没有这些文件」：钩子一跑就会重新生成，而 publish_gate 是
# 先跑 tests 再跑 claims，扫描必然 flaky 红。故改为检查**技能级 .skillhubignore 是否
# 声明了这些排除项、且声明语法确实能命中**——静态、确定、可负向自测。
# 匹配语义与发布器（另一个技能 skillhub-cli-publish 的 publish_skill.py）里那套
# glob→正则 与 ignored 判定对齐（`*` 跨层级、`(?:/.*)?` 覆盖子树、`!` 为负模式）。
# 注：此处**不反引号点名**对方技能的函数名——它们不在本技能代码里，会被
# no_dead_symbol_refs 判为死引用（本闸门就是这么自己抓到自己第一版的）。
_PACK_IGNORE_PROBES: List[Dict[str, str]] = [
    {"path": "hooks/_session_inject.json", "why": "注入钩子运行态（已注入过的 id 记录）"},
    {"path": "hooks/_auto_cap.json", "why": "自动捕获钩子运行态（轮次计数）"},
    {"path": "hooks/_errcap_state.json", "why": "错误捕获钩子运行态（去重/冷却状态）"},
    {"path": "keeper_daemon/.daemon-0f1e2d3c4b5a.json",
     "why": "守护进程运行态（端口/token/pid）；STATE 名带**库指纹**，故这条同时校验通配写法"},
    {"path": "hooks/_retired_20260101_probe.py", "why": "已退休件（rename 搬离后仍在磁盘）"},
    {"path": "_retired_tmp_probe/any.py", "why": "清理暂存目录（同卷 rename 的落脚点）"},
    {"path": "mem_bridge.py.bak_20260913",
     "why": "改动前整文件快照（开发期回滚基线）。发布器只按 .log/.lock/.pid/.jsonl 后缀排除，"
            "不覆盖 .bak_* → 必须显式声明，否则旧版源码会随包外泄"},
]
# 防「排除写太宽」：这些是真源码，必须仍进包，被误排 = 漏发。
_PACK_IGNORE_MUST_KEEP: List[str] = [
    "SKILL.md",
    "install_hooks.py",
    "hooks/keeper_hook_common.py",
    "hooks/_async_deposit.py",
    "scripts/memory_ops/_hooks.py",
    "scripts/memory_ops/_doctor.py",
]


def _ignore_pat_to_regex(pat: str):
    """`.skillhubignore` 模式 → 正则（镜像发布器语义，保证本闸门判据与真实打包一致）。"""
    if pat.startswith("./"):
        pat = pat[2:]
    if pat.endswith("/"):
        pat = pat[:-1]
    esc = "".join(".*" if c == "*" else ("." if c == "?" else re.escape(c)) for c in pat)
    return re.compile("(?:^|/)" + esc + "(?:/.*)?$")


def _is_pack_ignored(ignore_rx, unignore_rx, rel_posix: str) -> bool:
    parts = rel_posix.split("/")
    cands = [rel_posix] + ["/".join(parts[:i]) for i in range(1, len(parts))]
    for rx in unignore_rx:
        if any(rx.search(c) for c in cands):
            return False
    return any(any(rx.search(c) for c in cands) for rx in ignore_rx)


def _static_pack_excludes_runtime_state(skill_root: str) -> Dict[str, Any]:
    verdict = {"id": "pack_excludes_runtime_state", "ok": False, "error": None, "actual": None}
    ig = os.path.join(skill_root, ".skillhubignore")
    if not os.path.isfile(ig):
        # 「没有 .skillhubignore」有两种正经来路，都**不该判红**：
        #   · 发布器的「干净副本」——上传载荷必须排除 .skillhubignore（SkillHub 拒收该文件类型），
        #     而发布器恰恰是在干净副本里跑本门禁 → 副本里永远看不到它。
        #   · 用户手上的**下载/安装副本**——平台会往包里注入 `_meta.json`，但**不带**仓库级的
        #     `.skillhubignore`（它不随包分发）。
        # 🔴 曾用「目录里有 `_meta.json`」判「这是源码树、缺文件必 FAIL」——错：`_meta.json` 恰恰是
        #    平台注入下载产物的（对照实测：本技能与另两个技能的下发包里都含它），于是**自家发布
        #    产物上恒报假红**。`_meta.json` 因此**不能再当"源码树"标志**。
        # ⇒ 改为：没有声明文件就**无从校验**，本项跳过（ok=True + 显式说明，不静默）。
        #    源码树侧"该文件必须存在"由发布器构建时读取保证（读不到就没有任何排除规则）。
        has_meta = os.path.isfile(os.path.join(skill_root, "_meta.json"))
        verdict["ok"] = True
        verdict["actual"] = (
            "跳过：本目录无 .skillhubignore → 无从校验排除声明，本项不适用"
            "（发布干净副本、或平台下发的安装副本都会缺它%s）。"
            "本项只在**含该声明文件的源码目录**上生效。"
            % ("（含平台注入的 _meta.json，判定为下载/安装副本）" if has_meta else "")
        )
        return verdict
    ignore_rx, unignore_rx = [], []
    with io.open(ig, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            neg = line.startswith("!")
            (unignore_rx if neg else ignore_rx).append(
                _ignore_pat_to_regex(line[1:] if neg else line)
            )
    missing = [
        "%s（%s）" % (pr["path"], pr["why"])
        for pr in _PACK_IGNORE_PROBES
        if not _is_pack_ignored(ignore_rx, unignore_rx, pr["path"])
    ]
    over = [
        f for f in _PACK_IGNORE_MUST_KEEP
        if _is_pack_ignored(ignore_rx, unignore_rx, f)
    ]
    if missing or over:
        msgs = []
        if missing:
            msgs.append("运行态产物未被排除（会进发布包）：" + " | ".join(missing))
        if over:
            msgs.append("正常源码被误排除（会漏发）：" + " | ".join(over))
        verdict["error"] = "；".join(msgs)
        verdict["actual"] = {"missing": missing, "over_excluded": over}
        return verdict
    verdict["ok"] = True
    verdict["actual"] = "%d 项运行态产物已声明排除，%d 项正常源码未被误排除" % (
        len(_PACK_IGNORE_PROBES),
        len(_PACK_IGNORE_MUST_KEEP),
    )
    return verdict


# ── 第 8 条 · 源码树不得残留运行态产物（测试隔离的可验证判据）──
# 4.9.13 前：测试直接 import 源码树里的 hooks 模块、或 spawn 源码树的钩子脚本，
# 而 `keeper_hook_common.HOOKS_DIR` 取自 `__file__`（与 HOME 无关，环境隔离救不了）
# → `hook_audit.log` / `_session_inject.json` 必然写回源码树，只能靠 .skillhubignore
# 事后兜底。4.9.13 起 HOOKS_DIR 可被 env `KEEPER_HOOKS_DIR` 重定向、run_gate 统一注入，
# 于是「扫源码树」从 flaky 变成**确定可判**——本条即那次修复的可验证判据。
# （这也是为什么第 6 条只能查声明、不能查实际：修复到位前查了必假红。）
_RUNTIME_STATE_IN_TREE: List[str] = [
    "hooks/hook_audit.log",
    "hooks/_session_inject.json",
    "hooks/_async_deposit.failed.log",
    "hooks/_auto_cap.json",
    "hooks/_errcap_state.json",
]
# 守护进程 STATE 的名字带**库指纹**（`.daemon-<指纹>.json`），写死单个文件名会漏检；
# 用通配同时覆盖新名与 ≤4.9.12 的旧名 `.daemon.json`（旧名也仍属运行态产物）。
_RUNTIME_STATE_IN_TREE_GLOBS: List[str] = [
    "keeper_daemon/.daemon*.json",
]


def _runtime_state_residue(skill_root: str) -> List[str]:
    """源码树里残留的运行态产物（相对路径，posix 分隔）。精确名 + 通配名两类都查。"""
    found = [
        rel for rel in _RUNTIME_STATE_IN_TREE
        if os.path.exists(os.path.join(skill_root, rel.replace("/", os.sep)))
    ]
    for pat in _RUNTIME_STATE_IN_TREE_GLOBS:
        for p in sorted(glob.glob(os.path.join(skill_root, pat.replace("/", os.sep)))):
            if os.path.isfile(p):
                found.append(os.path.relpath(p, skill_root).replace(os.sep, "/"))
    return found


def _static_no_runtime_state_in_tree(skill_root: str) -> Dict[str, Any]:
    verdict = {"id": "no_runtime_state_in_tree", "ok": False, "error": None, "actual": None}
    found = _runtime_state_residue(skill_root)
    if found:
        verdict["error"] = (
            "源码树残留运行态产物 %d 个：%s。测试/门禁本应把它们重定向到临时目录"
            "（env KEEPER_HOOKS_DIR / KEEPER_DAEMON_DIR，run_gate.py 已统一注入；"
            "手动单跑请自设）。"
            "发版前先搬离：这些文件可能带本机端口/token，且会被打进发布包。"
            % (len(found), " | ".join(found))
        )
        verdict["actual"] = found
        return verdict
    verdict["ok"] = True
    verdict["actual"] = "%d 个已知运行态产物名（含 %d 条通配）均不在源码树（隔离生效）" % (
        len(_RUNTIME_STATE_IN_TREE), len(_RUNTIME_STATE_IN_TREE_GLOBS))
    return verdict


# ── 第 7 条 · 后台子进程不得弹窗 ──
# 背景：4.9.11 已实测「DETACHED_PROCESS 不等于静默」，并把钩子里的 spawn 改成 CREATE_NO_WINDOW；
# 但同一个坑**修了一处漏一处**——install_hooks.py 后台拉起 daemon 仍在用 CREATE_NEW_PROCESS_GROUP
# (0x200)，等于每次安装/后台刷新都弹一个黑窗。2026-09-11 受控实验（父 pythonw + 子 python.exe +
# DEVNULL 重定向，即真实形态）复现：
#     不设 flags → hwnd=722416 可见 ｜ 0x200 → hwnd=984144 可见
#     0x08000000 / DETACHED_PROCESS / 0x8|0x200 → hwnd=0 不可见
# 适用面：只在**钩子/守护进程执行路径**里扫（hooks/、scripts/memory_ops/、keeper_daemon/）——
# 这些模块的父进程常是无控制台的 pythonw；其余脚本跑在用户终端里（已有控制台，不会新开窗）。
# 局限（诚实说明）：本断言只看**调用点附近是否出现静默旗标**，无法证明"旗标真的生效"，
# 也不能覆盖"完全不传 creationflags 且确实会弹窗"的极端写法（POSIX 分支本就无需旗标）。
_POPUP_SPAWN_RE = re.compile(r"(?:subprocess|_sp|_subprocess|sp)\.(?:Popen|run|call)\s*\(")
_SILENT_FLAG_TOKENS = ("0x08000000", "CREATE_NO_WINDOW", "DETACHED_PROCESS",
                       "0x00000008", "start_new_session")
# 根目录里**由钩子路径派发**的脚本只有 install_hooks.py（_hooks.py 的自动注册 + 自愈刷新）；
# 其余根脚本（mem_bridge / setup_scheduler 等）跑在 Agent 或用户终端里，本就有控制台，不会新开窗。
_ROOT_HOOK_REACHABLE = ("install_hooks.py",)


def _static_no_popup_spawn(skill_root: str) -> Dict[str, Any]:
    verdict = {"id": "no_popup_spawn", "ok": False, "error": None, "actual": None}
    targets = []
    for rel in _ROOT_HOOK_REACHABLE:
        p = os.path.join(skill_root, rel)
        if os.path.isfile(p):
            targets.append(p)
    for sub in (("hooks",), ("scripts", "memory_ops"), ("keeper_daemon",)):
        d = os.path.join(skill_root, *sub)
        if not os.path.isdir(d):
            continue
        for fn in sorted(os.listdir(d)):
            if not fn.endswith(".py") or fn.startswith("_retired"):
                continue
            targets.append(os.path.join(d, fn))
    violations = []
    scanned_sites = 0
    for path in targets:
        try:
            with io.open(path, "r", encoding="utf-8", errors="replace") as f:
                lines = f.read().splitlines()
        except Exception:
            continue
        rel = os.path.relpath(path, skill_root).replace("\\", "/")
        for i, line in enumerate(lines):
            if not _POPUP_SPAWN_RE.search(line):
                continue
            scanned_sites += 1
            win = "\n".join(lines[max(0, i - 5):i + 13])
            if not any(tok in win for tok in _SILENT_FLAG_TOKENS):
                violations.append("%s:%d" % (rel, i + 1))
    if violations:
        verdict["error"] = (
            "后台子进程未指定静默旗标（父进程是 pythonw 时会新开可见控制台=弹窗）：%s。"
            "Windows 请用 creationflags=0x08000000（CREATE_NO_WINDOW），POSIX 用 start_new_session。"
            % " | ".join(violations[:8])
        )
        verdict["actual"] = {"violations": violations, "scanned_files": len(targets),
                             "scanned_sites": scanned_sites}
        return verdict
    verdict["ok"] = True
    verdict["actual"] = "%d 个文件 / %d 处 spawn 点均带静默旗标" % (len(targets), scanned_sites)
    return verdict


# ── 静态检查 9 · 用户向文档不得残留版本号 ──
# 判据来源 = CHANGELOG「例外收窄」段：版本号只是「时间戳式的叙事前缀」，
# 去掉后原意一字未损（「v3.0 已发货」→「现已发货」），反而不再让读者去猜「v3.0 是多久以前」。
# 规则文字以本注释块为单一真源（用户向文档一律不得残留版本号，无整文件例外）。
#
# 为什么不用「形态正则」：先试过「三段式 + v 前缀双段式 + `N.M 起/新增`」的口径，
# 实测 12 处命中里混着 `127.0.0.1`（IP）与 `versions/3.13.12`（Python 版本）两类误报，
# 又漏掉「（双时序，5.0）」这种不带「起 / 新增」的写法（漏 2 处）。
# 改用「本仓真实版本号集合」判定：
#   ① 从 CHANGELOG.md 的 ##/### 标题收集全部历史版本号；
#   ② 每个版本登记其前缀形式（5.0.0 → 5.0），因为文档惯用两段式简称；
#   ③ 再补上 SKILL.md frontmatter 的当前版本。
# 收益：`127.0.0.1` / `3.13.12` / `2.92s` 天然不在集合里（零误报），
#      而全部真实写法（4.9.26 / 4.9.27 / 5.0 / 5.0.0）命中（零漏报）。实测抓 10 处、零误报。
_VERSION_TOKEN_RE = re.compile(
    r"(?<![A-Za-z0-9._-])([vV]?\d+\.\d+(?:\.\d+)?)(?![A-Za-z0-9._-])")
_VERSION_HEADING_RE = re.compile(r"^#{2,3}\s+.*?([vV]?\d+\.\d+(?:\.\d+)?)")
# 整文件豁免：已被 .skillhubignore 排除的历史归档（当前无，保留扩展点）
_VERSION_DOC_EXEMPT = frozenset()
# 本体豁免：CHANGELOG.md 是版本记账本，满篇版本号正是它的职责
_VERSION_DOC_SKIP = frozenset({"CHANGELOG.md"})
# 行级豁免：SKILL.md frontmatter 的 version: 是「版本单一真源」，必须保留
_VERSION_FRONTMATTER_RE = re.compile(r"^\s*version\s*:")


def _repo_version_set(skill_root: str):
    """本仓真实版本号集合（含前缀形式）。取不到则返回空集 = 判定基线缺失。"""
    vs = set()
    cp = os.path.join(skill_root, "CHANGELOG.md")
    if os.path.isfile(cp):
        try:
            with io.open(cp, encoding="utf-8", errors="replace") as f:
                for line in f:
                    m = _VERSION_HEADING_RE.match(line.strip())
                    if not m:
                        continue
                    parts = m.group(1).lstrip("vV").split(".")
                    vs.add(".".join(parts))
                    for k in range(2, len(parts)):
                        vs.add(".".join(parts[:k]))
        except Exception:
            pass
    sp = os.path.join(skill_root, "SKILL.md")
    if os.path.isfile(sp):
        try:
            with io.open(sp, encoding="utf-8-sig", errors="replace") as f:
                for line in f:
                    if line.strip().startswith("version:"):
                        vs.add(line.split(":", 1)[1].strip().strip('"').strip("'"))
                        break
        except Exception:
            pass
    return vs


def _iter_user_docs(skill_root: str):
    """会随包分发的 .md（排除版本记账本与豁免件）。"""
    for dp, dn, fns in os.walk(skill_root):
        dn[:] = [d for d in dn if d not in ("__pycache__", ".workbuddy")]
        for fn in fns:
            if not fn.lower().endswith(".md"):
                continue
            p = os.path.join(dp, fn)
            rel = os.path.relpath(p, skill_root).replace(os.sep, "/")
            if rel in _VERSION_DOC_SKIP or rel in _VERSION_DOC_EXEMPT:
                continue
            yield p, rel


def _static_no_version_claims_in_user_docs(skill_root: str) -> Dict[str, Any]:
    verdict = {"id": "no_version_claims_in_user_docs", "ok": False,
               "error": None, "actual": None}
    vs = _repo_version_set(skill_root)
    if not vs:
        verdict["error"] = "判定基线缺失：未能从 CHANGELOG.md / SKILL.md 收集到任何版本号"
        return verdict
    hits = []
    n_docs = 0
    for p, rel in sorted(_iter_user_docs(skill_root)):
        n_docs += 1
        try:
            with io.open(p, encoding="utf-8", errors="replace") as f:
                lines = f.read().split("\n")
        except Exception as e:
            hits.append("%s: 读取失败 %s" % (rel, e))
            continue
        for i, line in enumerate(lines, 1):
            if rel == "SKILL.md" and _VERSION_FRONTMATTER_RE.match(line):
                continue
            for m in _VERSION_TOKEN_RE.finditer(line):
                if m.group(1).lstrip("vV") in vs:
                    hits.append("%s:%d -> %s" % (rel, i, m.group(1)))
    if hits:
        verdict["error"] = (
            "用户向文档残留 %d 处版本号：版本号是我们自己的修复史，对使用者无意义，"
            "去掉后原意不损。版本史唯一权威源 = CHANGELOG.md。"
            % len(hits))
        verdict["actual"] = hits[:20]
        return verdict
    verdict["ok"] = True
    verdict["actual"] = "扫 %d 个用户向文档 / 0 处版本号（判定集合 %d 个版本号）" % (
        n_docs, len(vs))
    return verdict


def _static_self_checks(skill_root: str) -> List[Dict[str, Any]]:
    """离线静态自检集合（扩展点：未来可加更多「文档↔代码」一致性断言）。"""
    return [
        _static_config_doc_matches_code(skill_root),
        _static_claimed_scripts_exist(skill_root),
        _static_redline_single_source(skill_root),
        _static_no_dead_symbol_refs(skill_root),
        _static_default_claims_consistent(skill_root),
        _static_pack_excludes_runtime_state(skill_root),
        _static_no_runtime_state_in_tree(skill_root),
        _static_no_popup_spawn(skill_root),
        _static_no_version_claims_in_user_docs(skill_root),
    ]


    # ── 内置 claims（P5 虚标变真能力 + 关键 API）──

DEFAULT_CLAIMS: List[Dict[str, Any]] = [
    {
        "id": "freshness_max_age_days_zero_no_filter",
        "desc": "P5.1: --max-age-days=0 不应过滤 created_at=今天的条目",
        "setup_run": 'deposit --category best_practice --summary "vtest-fresh0" --body "x"',
        "run": 'recall --max-age-days 0',
        "assert": lambda out: assert_json_count(out, "entries", ">=", 1),
    },
    {
        "id": "freshness_until_expired_tag_hidden",
        "desc": "P5.1: until: 过期标签的记忆应被 --max-age-days=30 隐藏（其他保留）",
        "setup_run": 'deposit --category best_practice --tags "until:2020-01-01" --summary "vtest-expired" --body "x"',
        "run": 'recall --max-age-days 30',
        "assert": lambda out: not any(
            e.get("summary") == "vtest-expired" for e in (out.get("entries") or [])
        ),
    },
    {
        "id": "promote_review_lists_candidates",
        "desc": "P5.2: promote --review 返回结构化 candidates 列表（不修改任何记忆）",
        "setup": "init",
        "run": "promote --review",
        "assert": lambda out: (
            isinstance(out, dict) and "mode" in out and out.get("mode") == "review"
            and "candidates" in out and "count" in out
        ),
    },
    {
        "id": "promote_review_no_modify_no_apply",
        "desc": "P5.2: promote --review 不带 --apply 时只读不写（无 applied 字段）",
        "setup": "init",
        "run": "promote --review",
        "assert": lambda out: "applied" not in out and out.get("mode") == "review",
    },
    {
        "id": "promote_review_with_apply_is_review_apply",
        "desc": "P5.2: promote --review --apply 返回 mode=review+apply",
        "setup": "init",
        "run": "promote --review --apply --tier curated",
        "assert": lambda out: out.get("mode") == "review+apply" and "applied" in out,
    },
    {
        "id": "deposit_secret_quarantined",
        "desc": "隔离：deposit 命中 secrets 返回 ok=False + quarantined=True + qid（捕获 dispatch 误报 ok=True bug）",
        "run": f'deposit --category best_practice --summary "vtest-sec" --body "api_key={_TEST_SECRET_TOKEN}"',
        "assert": lambda out: (out.get("ok") is False and out.get("quarantined") is True and bool(out.get("qid"))),
    },
    {
        "id": "list_quarantine_after_secret",
        "desc": "隔离：deposit 命中 secrets 后 list_quarantine 能列出候选",
        "setup_run": f'deposit --category best_practice --summary "vtest-sec2" --body "api_key={_TEST_SECRET_TOKEN}"',
        "run": "list_quarantine",
        "assert": lambda out: isinstance(out, dict) and out.get("count", 0) >= 1,
    },
# ── 关键 API 烟雾测试 ──
    {
        "id": "init_returns_ok",
        "desc": "init 创建记忆目录",
        "run": "init",
        "assert": lambda out: isinstance(out, dict) and out.get("ok") is True,
    },
    {
        "id": "deposit_returns_id",
        "desc": "deposit 返回 ok=true + id",
        "run": 'deposit --category best_practice --summary "vtest-A" --body "x"',
        "assert": lambda out: out.get("ok") is True and out.get("id", "").startswith("LRN-"),
    },
    {
        "id": "recall_returns_entries_list",
        "desc": "recall 返回 ok=true + entries 列表",
        "run": "recall",
        "assert": lambda out: out.get("ok") is True and isinstance(out.get("entries"), list),
    },
    {
        "id": "include_auto_filter_works",
        "desc": "recall --include-auto 不报参数错（参数真实存在）",
        "run": 'recall --include-auto',
        "assert": lambda out: out.get("ok") is True,
    },
    {
        "id": "auto_candidate_flag_works",
        "desc": "recurrence --auto-candidate 不报参数错（参数真实存在）",
        "run": "recurrence --auto-candidate",
        "assert": lambda out: isinstance(out, dict),  # 接受任意 dict 输出
    },
    {
        "id": "reclaim_dry_run_safe",
        "desc": "归档清理：reclaim 默认 dry-run 不归档任何文件（mode=DRY-RUN 且 n_archived_now=0），仅报告候选",
        "setup_run": 'deposit --category best_practice --summary "vtest-reclaim-a" --body "x"',
        "run": "reclaim",
        "assert": lambda out: isinstance(out, dict) and out.get("mode") == "DRY-RUN"
                              and out.get("n_archived_now", 0) == 0,
    },
    {
        "id": "reclaim_param_real_exists",
        "desc": "回收：reclaim 接受 --ttl-days/--min-importance/--apply 等参数且不报参数错",
        "run": "reclaim --ttl-days 180 --min-importance 0.4 --max-purge 200",
        "assert": lambda out: isinstance(out, dict) and "mode" in out,
    },
]


def main():
    ap = argparse.ArgumentParser(description="一次性批量断言文档宣传的命令/参数")
    ap.add_argument("--claims", default=None, help="自定义 claims.json 路径")
    ap.add_argument("--filter", default=None, help="只跑 id 包含子串的 claim（正则）")
    ap.add_argument("--root", default=None,
                    help="测试记忆库根目录（默认每次新建唯一临时目录，避免误删既有大库触发安全拦截）")
    ap.add_argument("--keep", action="store_true", help="保留测试库（默认完事后删）")
    args = ap.parse_args()

    # 默认每次跑新建唯一临时目录：既隔离并行运行，又避免对「既有的大测试库」做
    # 批量 rmtree 触发环境的安全删除拦截（阈值 50 文件）导致脚本被阻断、零输出。
    import shutil
    test_root = args.root or tempfile.mkdtemp(prefix="keeper_verify_")
    if os.path.isdir(test_root):
        shutil.rmtree(test_root, ignore_errors=True)
    os.makedirs(test_root, exist_ok=True)

    # 加载 claims
    if args.claims and os.path.isfile(args.claims):
        with open(args.claims, encoding="utf-8") as f:
            claims = json.load(f)
    else:
        claims = DEFAULT_CLAIMS

        # 可选过滤
    if args.filter:
        import re as _re
        claims = [c for c in claims if _re.search(args.filter, c.get("id", ""))]
    if not claims:
        print(json.dumps({"ok": False, "error": "no claims to verify"}, ensure_ascii=False))
        return 2

    env = os.environ.copy()
    env["AI_MEMORY_STORE"] = test_root

    # 计算脚本相对路径
    script_dir = os.path.dirname(os.path.abspath(__file__))
    mo = os.path.join(script_dir, "memory_ops.py")

    results = []
    n_pass = 0
    n_fail = 0

    for c in claims:
        cid = c.get("id", "?")
        cdesc = c.get("desc", "")
        crun = c.get("run", "")
        csetup = c.get("setup", "")
        cassert = c.get("assert")

        env_local = env.copy()

        verdict = {"id": cid, "desc": cdesc, "run": crun, "ok": False,
                   "error": None, "actual": None}

        try:
            # 1) init（每次都跑，保险）
            init_r = _run(f'python "{mo}" init', env_local)
            if not init_r["ok"]:
                verdict["error"] = f"init failed: {init_r['stderr'][:100]}"
                results.append(verdict); n_fail += 1; continue

                # 2) 可选 setup_run：在跑主命令前额外跑一次（用于需要预置数据的 claim）
            if c.get("setup_run"):
                sr = _run(f'python "{mo}" {c["setup_run"]}', env_local)
                if not sr["ok"] and not sr["stdout"]:
                    verdict["error"] = f"setup_run failed code={sr['code']}: {sr['stderr'][:200]}"
                    results.append(verdict); n_fail += 1; continue

                    # 3) 跑目标命令
            r = _run(f'python "{mo}" {crun}', env_local)
            if not r["ok"] and not r["stdout"]:
                verdict["error"] = f"CLI failed code={r['code']}: {r['stderr'][:200]}"
                results.append(verdict); n_fail += 1; continue

                # 3) 一次性解析 + 断言（核心：防止 L1 误读）
            try:
                parsed = _parse_json_output(r)
            except ValueError as ve:
                verdict["error"] = f"json parse fail: {ve}"
                verdict["actual"] = r["stdout"][:200]
                results.append(verdict); n_fail += 1; continue

            verdict["actual"] = (str(parsed)[:150] + "...") if len(str(parsed)) > 150 else str(parsed)

            # 4) 断言
            if cassert(parsed):
                verdict["ok"] = True
                n_pass += 1
            else:
                verdict["ok"] = False
                verdict["error"] = "assertion failed (actual payload shown)"
                n_fail += 1

        except Exception as ex:
            verdict["error"] = f"unexpected: {ex}"
            n_fail += 1

        results.append(verdict)

        # ── 离线静态自检（不依赖测试库）：文档宣称 ↔ 代码现实 一致性 ──
        # 「结论先取证」原则的可执行化身：SKILL.md 配置段键必须与 KEEPER_DEFAULTS 对称。
    skill_root = os.path.dirname(script_dir)
    for sc in _static_self_checks(skill_root):
        results.append(sc)
        if sc["ok"]:
            n_pass += 1
        else:
            n_fail += 1

            # 清理测试库
    if not args.keep:
        shutil.rmtree(test_root, ignore_errors=True)

        # 一次性输出完整 verdict（结构化、不允许"再 verify"）
    out = {"ok": n_fail == 0, "n_pass": n_pass, "n_fail": n_fail,
           "total": len(results), "claims": results}
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0 if n_fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())