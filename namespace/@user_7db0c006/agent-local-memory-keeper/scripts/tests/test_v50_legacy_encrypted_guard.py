# -*- coding: utf-8 -*-
"""回归（5.0.0）：4.9.25 的「at-rest 加密库」必须 **fail-closed 拒绝**，不得静默返回密文。

背景（问题链）
  线上 4.9.25 内置加密：启用后 summary / body / provenance_key / src_origin /
  verified_source / review_by 六个字段以 Fernet 密文落盘，并写下 store/salt.bin 与
  store/enc_key.txt。5.0.0 整体下线加解密能力后，**存量加密库升级不会报错**：
  密文仍是合法 JSON，json.load 正常返回 → 密文当明文用 → 召回出乱码、无异常、无日志。
  更危险的是写入：明文写进密文库 = 混库；此后降级回 4.9.25 会因「明文写 fail-closed」
  导致整库读不出。4.9.25 自己是有这道门的（`_decrypt_fields` 字段像密文即拒绝返回），
  5.0.0 把保护与功能一起删了 —— 本守卫把门补回来。

判据来源（忠实取自 4.9.25 `_crypto.py`，非自创）
  · 标志层：`_store_was_encrypted` = store/salt.bin 存在；另加 store/enc_key.txt
  · 内容层：`_looks_like_fernet_token` = str 且 startswith("gAAAAA") 且 len > 50

四道锁
  A. 标志层：命中 ⇒ 各读写原语全部抛 LegacyEncryptedStoreError
  B. 内容层：标志被剥离但字段仍是密文 ⇒ 同样抛错（含**缓存快路径**这条实测漏点）
  C. 覆盖率：**真实 CLI** 在旧加密库上必须 rc=13 + error=legacy_encrypted_store
     （G1 覆盖面矩阵固化 —— 只靠读代码无法证明「所有入口都被挡」）
  D. 零回归：明文库一切照旧；且「恰好以 gAAAAA 开头但长度 ≤50」不误报
"""
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))     # scripts/
if HERE not in sys.path:
    sys.path.insert(0, HERE)
os.environ.setdefault("KEEPER_RECALL_MODE", "inprocess")

import memory_ops as M  # noqa: E402

MEM_OPS = os.path.join(HERE, "memory_ops.py")
MOD_DIR = os.path.join(HERE, "memory_ops")
SKILL_ROOT = os.path.dirname(HERE)

# 形状合规的假 Fernet 密文（本守卫只做前缀+长度判据，不解密，故内容无关）
FERNET_FAKE = "gAAAAA" + ("Zk9x" * 20)


def _clear_caches(root):
    """清进程内记忆/路径缓存 —— 模拟「另一个进程刚改过盘上的库」。"""
    for k in list(getattr(M, "_MEM_CACHE", {})):
        if k[0] == os.path.abspath(root):
            M._MEM_CACHE.pop(k, None)
    for k in list(getattr(M, "_MTIME_CACHE", {})):
        if k[0] == root or k[0] == os.path.abspath(root):
            M._MTIME_CACHE.pop(k, None)
    for k in list(getattr(M, "_RESOLVE_PATH_CACHE", {})):
        if k[0] == root or k[0] == os.path.abspath(root):
            M._RESOLVE_PATH_CACHE.pop(k, None)


def _make_store(ciphertext=False, salt=False, keyfile=False, text="zzleg guard probe"):
    """造一个库；再按需改造成 4.9.25 加密库的形状。返回 (root, mid)。"""
    root = tempfile.mkdtemp(prefix="keeper_leg_guard_")
    M.init_store(root)
    mid = M.deposit(root, "pitfall", text, ["leg"], "body " + text)
    if ciphertext:
        fp = os.path.join(root, "memories", mid + ".json")
        with io.open(fp, encoding="utf-8") as f:
            mem = json.load(f)
        for fld in ("summary", "body"):
            mem[fld] = FERNET_FAKE
        mem["_encrypted"] = True
        with io.open(fp, "w", encoding="utf-8") as f:
            json.dump(mem, f, ensure_ascii=False, indent=2)
    sd = os.path.join(root, "store")
    os.makedirs(sd, exist_ok=True)
    if salt:
        with open(os.path.join(sd, "salt.bin"), "wb") as f:
            f.write(os.urandom(16))
    if keyfile:
        with io.open(os.path.join(sd, "enc_key.txt"), "w", encoding="utf-8") as f:
            f.write("probe-key-not-real\n")
    _clear_caches(root)
    return root, mid


# ── 「必须设防」的读写原语登记表（(文件, 函数名)）──────────────────────────────
# 新增任何直接读/写用户记忆或索引的入口，都要登记到这里并在实现里加守卫；
# test_all_registered_readers_are_guarded 会静态核对，防止「新读原语忘设防」复发。
GUARDED_READERS = [
    ("_core.py", "_load_mem"),
    ("_core.py", "_all_mems"),
    ("_core.py", "_save_mem"),
    ("__init__.py", "_write_mem"),
    ("__init__.py", "_iter_all_mems"),
    ("_persistence.py", "load_index"),
    ("_versions.py", "_list_versions"),
    ("_versions.py", "rollback"),
    ("_versions.py", "delete"),
    ("_api.py", "stats"),
]

GUARD_CALLS = ("assert_not_legacy_encrypted(", "raise_if_legacy_ciphertext(")


class _Base(unittest.TestCase):
    def setUp(self):
        self.roots = []

    def tearDown(self):
        for r in self.roots:
            shutil.rmtree(r, ignore_errors=True)
        # 释放 sqlite 连接池：否则用例结束时报 ResourceWarning: unclosed database
        try:
            M._db_close_all()
        except Exception:
            pass

    def _store(self, **kw):
        r, mid = _make_store(**kw)
        self.roots.append(r)
        return r, mid


# ── A 标志层 ──────────────────────────────────────────────────────────────
class MarkerLayerTest(_Base):

    def test_salt_bin_blocks_every_reader_and_writer(self):
        root, mid = self._store(salt=True)
        cases = [
            ("_all_mems", lambda: M._all_mems(root)),
            ("_load_mem", lambda: M._load_mem(root, mid)),
            ("_iter_all_mems", lambda: list(M._iter_all_mems(root))),
            ("_save_mem", lambda: M._save_mem(root, mid, {"id": mid, "summary": "x"})),
            ("_write_mem", lambda: M._write_mem(root, "LRN-GUARD", {"id": "LRN-GUARD"})),
            ("load_index", lambda: M.load_index(root)),
            ("versions", lambda: M.versions(root, mid)),
            ("recall(列表)", lambda: M.recall(root)),
            ("recall(--query)", lambda: M.recall(root, query="zzleg guard probe")),
            ("recall(--id)", lambda: M.recall(root, mid=mid)),
            ("stats", lambda: M.stats(root)),
            ("deposit", lambda: M.deposit(root, "pitfall", "zzleg new", ["leg"], "b")),
            ("export_memories", lambda: M.export_memories(root, fmt="jsonl")),
        ]
        leaked = []
        for name, fn in cases:
            try:
                fn()
                leaked.append(name)
            except M.LegacyEncryptedStoreError:
                pass
            except Exception as e:                       # 别的异常也算未按契约拒绝
                leaked.append("%s(%s: %s)" % (name, type(e).__name__, e))
        self.assertFalse(
            leaked,
            "这些入口在旧加密库上没有 fail-closed（静默返回密文/静默写入明文）：%r" % leaked)

    def test_enc_keyfile_alone_is_also_a_marker(self):
        """4.9.25 `_enc_key_resolve` 的本地 keyfile 只在加密路径落盘，单独出现也应拒绝。"""
        root, _mid = self._store(keyfile=True)
        self.assertIn("store/enc_key.txt".replace("/", os.sep), M.legacy_store_markers(root))
        self.assertRaises(M.LegacyEncryptedStoreError, M._all_mems, root)

    def test_blocked_write_leaves_library_untouched(self):
        """被拒绝的写入**不得**留下任何新记忆文件（fail-closed 必须无副作用）。"""
        root, mid = self._store(salt=True)
        before = sorted(os.listdir(os.path.join(root, "memories")))
        with self.assertRaises(M.LegacyEncryptedStoreError):
            M.deposit(root, "pitfall", "zzleg should not land", ["leg"], "b")
        after = sorted(os.listdir(os.path.join(root, "memories")))
        self.assertEqual(before, after,
                         "被拒绝的 deposit 仍在密文库落盘 → 明文/密文混库风险")


# ── B 内容层（标志被剥离）──────────────────────────────────────────────────
class CiphertextLayerTest(_Base):

    def test_stripped_marker_still_refused(self):
        """salt.bin 被手工删掉、但字段仍是密文 —— 4.9.25 也防了这一手，5.0.0 不能漏。"""
        root, mid = self._store(ciphertext=True, salt=False)
        self.assertEqual(M.legacy_store_markers(root), [], "前置条件：本例不设库级标志")
        for name, fn in (("_all_mems", lambda: M._all_mems(root)),
                         ("_load_mem", lambda: M._load_mem(root, mid))):
            with self.assertRaises(M.LegacyEncryptedStoreError, msg=name):
                fn()

    def test_cache_hit_path_is_guarded(self):
        """**实测漏点固化**：命中进程内缓存时 `_load_mem` 会提前 return，
        守卫若只放在「读盘之后」，则同一个库「第一次读被挡、第二次读漏过」。"""
        root, mid = self._store(ciphertext=True, salt=False)
        self.assertRaises(M.LegacyEncryptedStoreError, M._load_mem, root, mid)
        # 第二次调用：此时 mem 已在 _MEM_CACHE 里，走的是缓存快路径
        self.assertRaises(M.LegacyEncryptedStoreError, M._load_mem, root, mid)

    def test_fernet_judgement_fidelity(self):
        """旧判据忠实：前缀 gAAAAA + 长度 >50；短串/其它前缀/非字符串都不算。"""
        f = M.looks_like_fernet_token
        self.assertTrue(f("gAAAAA" + "x" * 45))
        self.assertTrue(f(FERNET_FAKE))
        self.assertFalse(f("gAAAAA"), "太短不算（旧判据 len>50）")
        self.assertFalse(f("gAAAAA" + "x" * 44), "恰好 ≤50 不算")
        self.assertFalse(f("hello world " + "x" * 60), "前缀不对不算")
        self.assertFalse(f(""), "空串不算")
        self.assertFalse(f(None), "非字符串不算")
        self.assertFalse(f(12345), "非字符串不算")

    def test_guard_flags_only_the_six_encrypted_fields(self):
        """只在 4.9.25 的加密域字段上判定 —— 避免对普通长 base64 正文误报。"""
        self.assertIsNone(M.looks_like_legacy_ciphertext({"note": FERNET_FAKE}))
        self.assertEqual(M.looks_like_legacy_ciphertext({"body": FERNET_FAKE}), "body")
        self.assertEqual(M.looks_like_legacy_ciphertext({"provenance_key": FERNET_FAKE}),
                         "provenance_key")
        self.assertIsNone(M.looks_like_legacy_ciphertext(None))


# ── C 真实 CLI 覆盖率（G1 矩阵固化）────────────────────────────────────────
class CliCoverageTest(_Base):

    # 覆盖：读（含只读索引的列表模式）/ 写 / 派生维护 / 导出备份
    KEY_CMDS = [
        ("recall(列表)", ["recall"]),
        ("recall(--query)", ["recall", "--query", "zzleg guard probe"]),
        ("recall(--id)", ["recall", "--id", "__MID__"]),
        ("recall(--as-of)", ["recall", "--query", "zzleg", "--as-of", "2026-01-01"]),
        ("stats", ["stats"]),
        ("explain(--id)", ["explain", "--id", "__MID__"]),
        ("versions(--id)", ["versions", "--id", "__MID__"]),
        ("doctor", ["doctor"]),
        ("report", ["report"]),
        ("audit", ["audit"]),
        ("dashboard", ["dashboard"]),
        ("deposit", ["deposit", "--category", "pitfall", "--summary", "zzleg cli write",
                     "--body", "body zzleg"]),
        ("overwrite", ["overwrite", "--id", "__MID__", "--summary", "zzleg cli ovw"]),
        ("archive", ["archive", "--id", "__MID__"]),
        ("unarchive", ["unarchive", "--id", "__MID__"]),
        ("delete", ["delete", "--id", "__MID__", "--yes"]),
        ("rollback", ["rollback", "--id", "__MID__", "--to-version", "1", "--yes"]),
        ("promote", ["promote", "--id", "__MID__", "--tier", "core"]),
        ("invalidate", ["invalidate", "--id", "__MID__", "--reason", "zzleg"]),
        ("reclassify", ["reclassify", "--id", "__MID__", "--scope", "project"]),
        ("reflect(--auto)", ["reflect", "--auto", "--dry-run"]),
        ("decay", ["decay", "--dry-run"]),
        ("reclaim", ["reclaim", "--dry-run"]),
        ("cluster", ["cluster", "--apply", "--min-size", "2"]),
        ("rebuild", ["rebuild"]),
        ("export(jsonl)", ["export", "--format", "jsonl"]),
        ("graph(--build)", ["graph", "--build"]),
        ("distill", ["distill", "--review"]),
        # 批处理型：内部会把逐条异常吞成 ok:false，故必须由 dispatch 层拦下（rc=13）
        ("evolve(--apply)", ["evolve", "--apply"]),
        ("import(--execute)", ["import", "--file", "__IMP__", "--execute"]),
    ]

    def _run(self, root, args):
        env = dict(os.environ)
        env["KEEPER_RECALL_MODE"] = "inprocess"
        env["AI_MEM_EMBED_BACKEND"] = "lexical"      # 免去模型加载，保持用例快
        return subprocess.run([sys.executable, MEM_OPS, "--root", root] + list(args),
                              capture_output=True, text=True, encoding="utf-8",
                              errors="replace", timeout=300, env=env)

    def _last_json(self, out):
        try:
            j = json.loads((out or "").strip().splitlines()[-1])
        except Exception:
            return {}
        return j if isinstance(j, dict) else {}

    def test_real_cli_refuses_with_exit_code_13(self):
        """真跑 CLI：旧加密库上必须 rc=13 且 error=legacy_encrypted_store。

        为什么必须真跑：只读代码无法证明「所有入口都被挡」—— G1 矩阵就是这样才发现
        `deposit`（走 `_write_mem` 而非 `_save_mem`）与 `recall` 列表模式（走 `load_index`）
        两条真漏网，以及 `stats` 用 `except Exception: pass` 把守卫错误吞成「静默 0 条」。"""
        root, mid = self._store(salt=True, ciphertext=True)
        imp = os.path.join(root, "_probe_import.jsonl")
        with io.open(imp, "w", encoding="utf-8") as f:
            f.write(json.dumps({"category": "pitfall", "summary": "zzleg imported",
                                "body": "b", "tags": ["leg"]}, ensure_ascii=False) + "\n")
        bad = []
        for name, args in self.KEY_CMDS:
            a = [x.replace("__MID__", mid).replace("__IMP__", imp) for x in args]
            p = self._run(root, a)
            j = self._last_json(p.stdout)
            if p.returncode != 13 or j.get("error") != "legacy_encrypted_store":
                blob = ((p.stdout or "") + (p.stderr or "")).replace("\n", " | ")[-200:]
                bad.append("%s rc=%s error=%s :: %s" % (name, p.returncode, j.get("error"), blob))
        self.assertFalse(
            bad,
            "以下 CLI 命令在旧加密库上没有 fail-closed（G1 覆盖面矩阵漏网）：\n  " +
            "\n  ".join(bad))

    def test_cli_error_payload_is_actionable(self):
        root, _mid = self._store(salt=True, ciphertext=True)
        p = self._run(root, ["recall", "--query", "zzleg"])
        j = self._last_json(p.stdout)
        self.assertEqual(j.get("error_code"), "LEG-001")
        steps = " ".join(j.get("next_steps") or [])
        self.assertIn("4.9.25", steps, "next_steps 必须指出唯一可用版本")
        self.assertIn("salt.bin", j.get("msg", ""), "报错须指出检测到的标志文件名")
        self.assertIn("混库", j.get("msg", ""), "报错须说明继续写入的危害")


# ── D 零回归 + 静态锁 ─────────────────────────────────────────────────────
class PlaintextUnaffectedTest(_Base):

    def test_plaintext_store_works_normally(self):
        root, mid = self._store()
        self.assertEqual(M.legacy_store_markers(root), [])
        self.assertEqual(len(M._all_mems(root)), 1)
        self.assertEqual(M._load_mem(root, mid)[0]["id"], mid)
        self.assertEqual(len(list(M._iter_all_mems(root))), 1)
        self.assertTrue(M.recall(root, query="zzleg guard probe"))
        self.assertTrue(M.stats(root).get("ok"))
        mid2 = M.deposit(root, "pitfall", "zzleg second", ["leg"], "b")
        self.assertTrue(mid2)

    def test_guard_is_noop_without_marker_or_ciphertext(self):
        root, mid = self._store()
        mem, _ = M._load_mem(root, mid)
        self.assertIsNone(M.assert_not_legacy_encrypted(root, mem=mem))
        self.assertIsNone(M.raise_if_legacy_ciphertext(root, mem))


class StaticGuardRegistryTest(unittest.TestCase):

    def test_all_registered_readers_are_guarded(self):
        """静态锁：登记表里的每个读写原语，函数体内必须出现守卫调用。

        用 AST 取函数体行区间（项目铁律：代码度量走 ast，不用文本切片），
        避免「守卫被误删/新读原语忘设防」静默复发。"""
        import ast
        missing = []
        for fname, fn in GUARDED_READERS:
            path = os.path.join(MOD_DIR, fname)
            with io.open(path, encoding="utf-8") as _f:
                src = _f.read()
            tree = ast.parse(src)
            lines = src.split("\n")
            node = None
            for n in tree.body:
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == fn:
                    node = n
                    break
            if node is None:
                missing.append("%s::%s 未找到（登记表已过期？）" % (fname, fn))
                continue
            body = "\n".join(lines[node.lineno - 1:node.end_lineno])
            if not any(c in body for c in GUARD_CALLS):
                missing.append("%s::%s 函数体内无守卫调用" % (fname, fn))
        self.assertFalse(
            missing,
            "以下读写原语缺少旧加密库守卫（密文会被当明文返回/明文会被写进密文库）：\n  " +
            "\n  ".join(missing))

    def test_guard_module_carries_no_decryption_ability(self):
        """守卫**不得**夹带加解密能力 —— 5.0.0 已整体下线加密，只能拒绝不能解密。

        用 AST 查「import / 调用」，**不查字符串**：文件头注释里必然写着「删 cryptography
        依赖」「不解密」这类说明，纯文本包含检查会把注释误判成代码（首版就踩了这个坑）。
        """
        import ast
        with io.open(os.path.join(MOD_DIR, "_legacy.py"), encoding="utf-8") as _f:
            src = _f.read()
        tree = ast.parse(src)

        imported = set()
        for n in ast.walk(tree):
            if isinstance(n, ast.Import):
                imported.update(a.name.split(".")[0] for a in n.names)
            elif isinstance(n, ast.ImportFrom) and n.module:
                imported.add(n.module.split(".")[0])
        self.assertNotIn("cryptography", imported, "守卫模块不得 import 加解密库")

        called = set()
        for n in ast.walk(tree):
            if isinstance(n, ast.Call):
                f = n.func
                if isinstance(f, ast.Name):
                    called.add(f.id)
                elif isinstance(f, ast.Attribute):
                    called.add(f.attr)
        for bad in ("Fernet", "encrypt", "decrypt", "pbkdf2_hmac", "urlsafe_b64encode"):
            self.assertNotIn(bad, called,
                             "守卫模块出现加解密调用 %s —— 5.0.0 只能拒绝、不能解密" % bad)


if __name__ == "__main__":
    unittest.main()
