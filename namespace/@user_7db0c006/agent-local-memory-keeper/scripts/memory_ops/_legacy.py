# memory_ops/_legacy.py
# 5.0.0 新增：旧版本「at-rest 加密库」的 fail-closed 兼容守卫。
# 本模块**不提供任何加解密能力**，只负责把「静默乱码」换成「响亮拒绝 + 可操作指引」。
#
# ── 为什么需要它（问题链）────────────────────────────────────────────────
# 线上 4.9.25 内置 at-rest 加密：启用后 summary / body / provenance_key / src_origin /
# verified_source / review_by 六个字段以 Fernet 密文落盘，并在 store/ 下落
# store/salt.bin（PBKDF2 salt）+ store/enc_key.txt（本地密钥兜底）。
# 5.0.0 决定整体下线加解密（删 _crypto.py、删命令面、删 cryptography 依赖）——
# 但**存量加密库升级上来后不会报错**：密文本身仍是合法 JSON，json.load 正常返回，
# 于是密文被当明文用，表现为「召回出乱码、无异常、无日志、无自救命令」。
#
# 4.9.25 自己是有这道门的：`_decrypt_fields` 在「字段像密文但无密钥」时**拒绝返回**  deadref-ok
# （注释原文：即便 _encrypted 标志被剥离，字段像密文而当前无密钥，也拒绝返回）。
# 5.0.0 把保护与功能一起删掉了 —— 本模块把这道门以「兼容守卫」形式补回来。
#
# 💡 本文件刻意引用若干 **4.9.25 已删除的历史函数名**（下文每处行尾标 `deadref-ok`）：
#    目的是让判据可回溯到线上包源码逐字对照，属**史料引用**而非死引用。
#    死引用闸门（verify_claims.no_dead_symbol_refs）对该类引用须显式豁免，故逐行标注。
#
# 还有一个更危险的次生伤害：5.0.0 在 salt.bin 尚存的库上写入的是**明文**，会与既有
# 密文**混库**；此后一旦降级回 4.9.25，4.9.25 的「明文写 fail-closed」会让整库读不出。
# 所以守卫必须同时挡在读路径与写路径上。
#
# ── 判据（两层，均忠实取自 4.9.25 _crypto.py 的真实实现，非自创）──────────
#   ① 标志层：store/salt.bin 存在（4.9.25 `_store_was_encrypted` 的原判据，明文库永不生成）  deadref-ok
#             或 store/enc_key.txt 存在（4.9.25 `_enc_key_resolve` 的本地 keyfile，仅加密路径落盘）  deadref-ok
#   ② 内容层：六个加密域字段中任一「像 Fernet 密文」
#             （4.9.25 `_looks_like_fernet_token`：str 且 startswith("gAAAAA") 且 len>50）  deadref-ok
# 为什么两层都要：① 便宜且高置信，但可被手工删掉 salt.bin 绕过（旧版明确设想过该攻击面）；
# ② 不需要任何额外 IO —— 读路径本来就要把 JSON 读进内存，嗅探是顺手的事。
#
# ── 性能 ────────────────────────────────────────────────────────────────
# ① 是 1~2 次 os.path.exists（微秒级；相对 _all_mems 内部 N 次 stat 可忽略）；
# ② 只嗅探**已经在内存里**的字段，零额外 IO。因此**刻意不做进程内 memo 缓存**：
# 缓存只会引入「库状态在进程内改变后不生效」的陈旧窗口，而这里根本不需要缓存。
import os

# 相对库根的标志文件（与 4.9.25 落盘位置逐字一致）
LEGACY_SALT_REL = os.path.join("store", "salt.bin")
LEGACY_KEYFILE_REL = os.path.join("store", "enc_key.txt")

# 4.9.25 `_encrypt_fields` / `_decrypt_fields` 的加密域字段（逐字取自旧实现，勿自行增删）  deadref-ok
LEGACY_ENCRYPTED_FIELDS = ("summary", "body", "provenance_key",
                           "src_origin", "verified_source", "review_by")

_LEGACY_MARKER_HINTS = {
    LEGACY_SALT_REL: "PBKDF2 salt，加密库的唯一标志（明文库永不生成）",
    LEGACY_KEYFILE_REL: "本地加密密钥兜底文件（仅加密路径落盘）",
}

_LEGACY_MSG = """本记忆库曾启用「at-rest 加密」，5.0.0 已移除加解密能力，故拒绝按明文%(op)s（fail-closed）。

  库路径：%(root)s
  检测到：%(seen)s

  为什么拒绝：4.9.25（SkillHub 线上版）的加密把 summary / body / provenance_key /
  src_origin / verified_source / review_by 六个字段存成 Fernet 密文。密文**仍是合法
  JSON**，5.0.0 读出来既不报错、也不留日志，只会把密文当明文用 —— 表现就是「召回出乱码」。
  继续写入更危险：5.0.0 写的是明文，会与既有密文混库；此后一旦降级回 4.9.25，
  4.9.25 的「明文写 fail-closed」会让**整库读不出来**。
  这道门 4.9.25 自己就有（字段像密文而当前无密钥 ⇒ 拒绝返回），5.0.0 把保护与功能一起
  删掉了。本守卫把它补回来：**不恢复解密能力**，只把静默乱码换成明确拒绝。

  出路（三选一）：
   ① 继续用本库 ⇒ 换回 4.9.25 并恢复密钥
      重装 4.9.25，设置 AI_MEM_ENCRYPTION_KEY（或放好 store/enc_key.txt /
      ~/.ai-memory-keys/<库路径哈希>.key）。本库只在 4.9.25 下可用。
   ② 把数据搬进明文库 ⇒ 需要 4.9.25 + 原密钥做一次性迁移
      在 4.9.25 环境下用原密钥逐条读（读出来即明文）并导出，写入一个**全新目录**；
      确认新库没有 store/salt.bin、且内容可正常读出后，再让 5.0.0 用 --root <新目录>。
      注意：4.9.25 的 rekey **不支持轮换成明文库**（其 --new-key 帮助原文即如此），
      所以只能走「导出 → 新建」，没有一键通道。
   ③ 用新库 ⇒ 现在就能用，旧库原样留档
      用 --root <一个全新空目录>（或设 AI_MEMORY_STORE）。旧库不动，随时可回到 ①。

  ⚠️ 不要在本库上执行 5.0.0 的写入命令（deposit / overwrite / import / merge 等）。"""


class LegacyEncryptedStoreError(RuntimeError):
    """本库曾启用 at-rest 加密，而当前版本已移除加解密能力（fail-closed，拒绝按明文处理）。"""


# 判据逐字取自 4.9.25 同名私有函数 `_looks_like_fernet_token`（前缀 + 长度）  deadref-ok
def looks_like_fernet_token(s):
    """4.9.25 同语义判据的等价实现（str 且 startswith("gAAAAA") 且 len>50）。"""
    return isinstance(s, str) and s.startswith("gAAAAA") and len(s) > 50


def legacy_store_markers(root):
    """库级标志：返回命中的相对路径列表（空列表 = 无标志）。"""
    if not root:
        return []
    try:
        base = os.path.abspath(root)
    except (TypeError, ValueError):
        return []
    return [rel for rel in (LEGACY_SALT_REL, LEGACY_KEYFILE_REL)
            if os.path.exists(os.path.join(base, rel))]


def looks_like_legacy_ciphertext(mem):
    """内容层判据：返回首个「像 Fernet 密文」的加密域字段名，否则 None。"""
    if not isinstance(mem, dict):
        return None
    for fld in LEGACY_ENCRYPTED_FIELDS:
        if looks_like_fernet_token(mem.get(fld)):
            return fld
    return None


def _scan_ciphertext(mem=None, mems=None):
    """在**已在内存中**的对象里找密文字段：单条优先，其次集合（dict / iterable）。

    返回字段名或 None。全部为内存内字符串前缀比较，无额外 IO。"""
    if isinstance(mem, dict):
        fld = looks_like_legacy_ciphertext(mem)
        if fld:
            return fld
    if mems:
        it = mems.values() if isinstance(mems, dict) else mems
        for _m in it:
            fld = looks_like_legacy_ciphertext(_m)
            if fld:
                return fld
    return None


def _describe(markers, cipher_field):
    seen = ["%s（%s）" % (rel, _LEGACY_MARKER_HINTS.get(rel, "旧加密库标志")) for rel in markers]
    if cipher_field:
        seen.append("字段 %s 形如 Fernet 密文（以 gAAAAA 开头且长度 >50）" % cipher_field)
    return "\n          ".join(seen) if seen else "（无）"


def raise_if_legacy_ciphertext(root, mem, op="读取"):
    """**仅内容层**入口（零额外 IO）：标志层已另行查过时用，避免重复 stat。

    典型场景：`_core._load_mem` 在函数入口先查一次库级标志（覆盖「命中进程内缓存、
    根本不读盘」的快路径），随后对**即将返回的那条记忆**调本函数做内容层判定。
    命中即抛与 `assert_not_legacy_encrypted` 完全相同的异常与文案。
    """
    if looks_like_legacy_ciphertext(mem):
        assert_not_legacy_encrypted(root, op=op, mem=mem)
    return None


def assert_not_legacy_encrypted(root, op="读取", mem=None, mems=None):
    """旧加密库 fail-closed 守卫：命中即抛 LegacyEncryptedStoreError，未命中静默返回 None。

    调用约定（四个读写原语各调一次，恰好增加 1~2 次 os.path.exists）：
      · `_core._load_mem`    —— 读盘后传 `mem=<刚读到的记忆>`
      · `_core._all_mems`    —— 全量加载后传 `mems=<id->mem 字典>`
      · `_iter_all_mems`     —— 逐条产出时传 `mem=<当前记忆>`
      · `_core._save_mem`    —— 写盘前传 `mem=<即将写入的记忆>`

    标记命中时**短路**，不再扫内容（省一次全量嗅探）；标记缺失时才依赖内容判据，
    覆盖「salt.bin 被手工删掉但数据仍是密文」的场景。
    """
    markers = legacy_store_markers(root)
    field = _scan_ciphertext(mem, None if markers else mems)
    if not markers and not field:
        return None
    try:
        _abs = os.path.abspath(root)
    except (TypeError, ValueError):
        _abs = str(root)
    raise LegacyEncryptedStoreError(
        _LEGACY_MSG % {"op": op, "root": _abs, "seen": _describe(markers, field)})
