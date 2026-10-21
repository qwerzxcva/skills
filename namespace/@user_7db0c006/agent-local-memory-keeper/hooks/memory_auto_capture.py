# -*- coding: utf-8 -*-
"""
memory_auto_capture.py — WorkBuddy Stop / PreCompact 钩子（端口化版）
从会话 transcript 提取「显式保存意图」句（记一下/踩坑/教训…），沉淀为 learning 经验。

为何需要：
- Stop：会话结束自动落盘本会话要点，不再依赖 AI 临场想起。
- PreCompact：WB 压缩上下文前保全，避免「会话中学到的东西随压缩消失」。

判重逻辑修正（旧版是真 bug）：
- 旧 _dup 直接用 recall(count)>0 判重；但本机任意 token 重叠 query 都返回 ~6 条，
导致**任何**新句子都判为「已重复」→ 自动蒸馏永远存不进（核心价值是死的）。
- 新版改用本地 2-gram 对称 containment 对比候选与条目 summary，阈值 0.5，
仅在确实语义相近时才跳过（已用真实库验证：重复/近义→True，全新/半新/新技术→False）。

护栏（防膨胀 + 防 WB<->keeper 回路）：
- 每日上限 5 条；同会话 Stop 只处理一次；冷却去重（指纹 10 分钟）。
- 跳过「注入文本」（含 🧠 / hookSpecificOutput），避免回写。
- 失败/无 transcript/异常 → 静默跳过（fail-open）。所有动作写 hook_audit.log。
- 端口化（v4.5.2）：PY/SCR/WB_HOME 由 keeper_hook_common 推导，不再硬编码具体 Windows 用户名主目录。

v4.5.50 加固：
- 落盘异步化：实际 deposit（embed 冷加载）改由 DETACHED 子进程（_async_deposit.py）执行，
钩子内仅同步记账（每日上限/冷却指纹），Stop/PreCompact 钩子延迟归零。
- 去重兜底：daemon 离线/返空时回退 inprocess recall，避免离线时 _dup 恒 False 导致重复 deposit。
- 状态文件原子写：_auto_cap.json 改 temp+os.replace 原子写 + 建议锁，消除并发 race/半截写入。
"""
import sys, os, json, time, re, hashlib, subprocess, tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import keeper_hook_common as C

PY = C.PY
SCR = C.SCR
STATE = os.path.join(C.WB_HOME, "hooks", "_auto_cap.json")
DAILY_CAP = 5
COOLDOWN_S = 600
DUP_COVER = 0.5       # 候选覆盖条目 summary 的比例阈值
INTENT = re.compile(r"(记一下|记一条|记住|别忘了|踩坑|教训|这个坑|经验是|沉淀|总结一下今天|存一下|存档)")
SKIP = re.compile(r"(当前生效的 AI 经验|🧠|hookSpecificOutput|additionalContext)")


def _load():
    try:
        return json.load(open(STATE, encoding="utf-8"))
    except Exception:
        return {"date": "", "count": 0, "sessions": {}, "fp": {}}


def _save(s):
    with C.locked(STATE):
        C.atomic_write_json(STATE, s)


def _today():
    return time.strftime("%Y-%m-%d")


def _extract(text):
    out = []
    seen = set()
    for m in INTENT.finditer(text):
        seg = text[max(0, m.start() - 80): min(len(text), m.end() + 200)].replace("\n", " ").strip()
        if len(seg) < 12:
            continue
        if SKIP.search(seg):
            continue
        h = hashlib.md5(seg[:200].encode("utf-8")).hexdigest()
        if h in seen:
            continue
        seen.add(h)
        out.append(seg[:400])
    return out


def _dup(summary):
    """本地重叠判重：候选与召回条目 summary 的 containment >= 阈值才视为重复。
    优先 daemon（毫秒级）；daemon 离线/返空时回退 inprocess recall 兜底，
    避免离线时 _dup 恒 False 导致跨会话重复 deposit（仅冷却指纹防完全相同）。"""
    st = C.tokenize(summary)
    raw = None
    try:
        raw = C.recall_via_daemon(query=summary, top_n=5, semantic_gate=0)
    except Exception:
        raw = None
    entries = []
    if raw:
        try:
            entries = json.loads(raw).get("entries", [])
        except Exception:
            entries = []
    if not entries:
        # daemon 离线/返空 → inprocess 兜底（不依赖 daemon 进程）
        try:
            raw2 = C.recall_inprocess(query=summary, top_n=5, semantic_gate=0)
            if raw2:
                entries = json.loads(raw2).get("entries", [])
        except Exception:
            entries = []
    for e in entries:
        es = C.tokenize(e.get("summary") or "")
        ratio, _ = C.containment(st, es)
        if ratio >= DUP_COVER:
            return True
    return False


def _deposit_async(root, summary, body):
    """异步落盘：写临时 JSON → DETACHED 子进程调 _async_deposit.py，绝不阻塞 Stop/PreCompact 钩子。
    返回 True 表示子进程已成功 spawn（任务已提交），False 表示 spawn 失败。
    记账（每日上限/冷却指纹）仅在 spawn 成功后进行，避免 spawn 失败仍白扣配额（假记账）。"""
    try:
        fd, tmp = tempfile.mkstemp(dir=C.HOOKS_DIR, prefix="._dep_", suffix=".json")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump({"root": root, "summary": summary, "body": body}, f)
        env = C.prepare_env()
        helper = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_async_deposit.py")
        cmd = [C.PY, helper, tmp]
        kwargs = dict(env=env, stdin=subprocess.DEVNULL,
                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if os.name == "nt":
            kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW：静默后台，不弹控制台窗口
        else:
            kwargs["start_new_session"] = True
        subprocess.Popen(cmd, **kwargs)
        C.audit("autocap_deposit", "spawn_async", summary[:60])
        return True
    except Exception as e:
        C.audit("autocap_deposit", "error", str(e)[:60])
        return False


def _auto_capture_enabled(root):
    """开箱自动捕获是否开启（用户没设 KEEPER_AUTO_CAPTURE=0 即开启）。"""
    try:
        if os.environ.get("KEEPER_AUTO_CAPTURE") == "0":
            return False
        sys.path.insert(0, SCR)
        import memory_ops as M
        cfg = M._load_keeper_config(root)
        return bool(cfg.get("auto_capture", True))
    except Exception:
        return True


def _converse_flush_async():
    """走法2：会话边界由 harness 保证跑一次 converse 整理闭环
    （flush 累积 buffer + harvest --self-learn 跨记忆自学习 + reflect --auto 整理），
    **不依赖 AI 每轮自调 converse**——即便 AI 漏调用也不会漏掉收尾整理。
    后台 detached 子进程执行，绝不阻塞 Stop/PreCompact 钩子。fail-open。
    """
    try:
        root = C.store_root()
        if not _auto_capture_enabled(root):
            C.audit("converse_flush", "skip", "auto_capture disabled")
            return
        env = C.prepare_env()
        cmd = [C.PY, os.path.join(SCR, "memory_ops", "__init__.py"), "converse",
               "--root", root, "--end", "--with-workbuddy", "--no-llm",
               "--max-items", "10"]
        kwargs = dict(env=env, stdin=subprocess.DEVNULL,
                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if os.name == "nt":
            kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW：静默后台，不弹控制台窗口
        else:
            kwargs["start_new_session"] = True
        subprocess.Popen(cmd, **kwargs)
        C.audit("converse_flush", "spawn", "async converse --end")
    except Exception as e:
        C.audit("converse_flush", "error", str(e)[:60])


def main():
    try:
        # 消毒：stdin 在 UTF-8 模式下会把非法字节解成半代理码点，导致后续写盘编码失败
        evt = C.read_event()
    except Exception:
        evt = {}
    if not isinstance(evt, dict):
        evt = {}
    event = evt.get("hook_event_name") or (sys.argv[1] if len(sys.argv) > 1 else "Stop")
    session = evt.get("session_id") or "na"
    transcript = evt.get("transcript_path") or ""
    st = _load()
    if st.get("date") != _today():
        st = {"date": _today(), "count": 0, "sessions": {}, "fp": {}}
    now = time.time()
    # 走法2：会话边界 harness 保证整理闭环（每会话至多一次，异步不阻塞）
    cfs = st.setdefault("converse_flushed_sessions", {})
    if not cfs.get(session):
        _converse_flush_async()
        cfs[session] = True
        if len(cfs) > 50:
            st["converse_flushed_sessions"] = dict(list(cfs.items())[-50:])
    if event == "Stop" and st.get("sessions", {}).get(session):
        print(json.dumps({"continue": True}))
        return
    if st.get("count", 0) >= DAILY_CAP:
        C.audit(event, "skip", "daily_cap reached")
        print(json.dumps({"continue": True}))
        return
    text = ""
    if transcript and os.path.exists(transcript):
        try:
            with open(transcript, encoding="utf-8", errors="ignore") as f:
                text = f.read()[-20000:]
        except Exception:
            pass
    segs = _extract(text)
    deposited = 0
    for seg in segs:
        if st.get("count", 0) >= DAILY_CAP:
            break
        fp = hashlib.md5(seg[:200].encode("utf-8")).hexdigest()
        if st.get("fp", {}).get(fp) and now - st["fp"][fp] < COOLDOWN_S:
            continue
        summary = seg[:120]
        if _dup(summary):
            C.audit(event, "dup_skip", summary[:60])
            continue
            # 同步记账（每日上限/冷却指纹）仅在异步子进程成功 spawn 后进行，
            # 避免 spawn 失败仍白扣每日配额（假记账）；落库失败由 _async_deposit 保留到 failed/ 不丢记忆。
        ok = _deposit_async(C.store_root(), "自动蒸馏: " + summary, seg)
        if not ok:
            C.audit(event, "deposit_skip", "spawn failed, quota preserved")
            continue
        st["count"] = st.get("count", 0) + 1
        st.setdefault("fp", {})[fp] = now
        deposited += 1
        C.audit(event, "deposit_async", summary[:60])
    if event == "Stop":
        st.setdefault("sessions", {})[session] = True
    _save(st)
    sys.stderr.write("[autocap] %s 提取 %d 句 沉淀 %d 条\n" % (event, len(segs), deposited))
    print(json.dumps({"continue": True}))


if __name__ == "__main__":
    main()
