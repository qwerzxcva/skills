# -*- coding: utf-8 -*-
"""
keeper_setup.py — 记忆系统「一键配置向导 + 就绪自检」（v4.5.13）

为什么需要：
keeper 绝大多数能力已开箱即用（存储路径/中文语义/钩子/反馈校准默认即开，无需任何配置），
仅「IMA 云端同步 / 本地 LLM」几项因涉及外部账号、重资源，需用户按需开启。
本脚本把「装后步骤」收口成一条命令（init / all），并把「装好没」变成一眼绿红的自检（doctor）；
默认即 silent 钩子（无弹窗）+ fastembed 中文语义（自动安装），真正零配置上手。

设计原则（全 additive，不重写架构）：
- store：默认零配置；换路径时用 setx（Windows）/ profile（POSIX）持久化。
- embed：默认 fastembed（轻量本地 ONNX，CPU 推理）；首次用到中文语义时自动 pip 安装 + 下载模型，
之后完全离线；无网络/无 pip 优雅降级词法级。
- hooks：默认 silent（复制+合并 settings+启动 daemon+可选调度，关掉会弹窗的 2 个钩子）；
想全开用 --mode full。封装 install_hooks。
- ima（Phase 2）：预检 KB id 是否被占位符污染，setx 持久化；引导跑 ima_sync --push。默认不配置。
- doctor：查 store / embed / hooks / daemon / ima / recall 六项，绿红表。

用法：
python scripts/keeper_setup.py init            # 引导式全配
python scripts/keeper_setup.py all             # 一条命令全配
python scripts/keeper_setup.py store [--path X]
python scripts/keeper_setup.py embed [--backend auto|fastembed|lexical|online]
python scripts/keeper_setup.py hooks [--scheduler]
python scripts/keeper_setup.py ima [--kb-id X]
python scripts/keeper_setup.py archive [--apply | --review]   # 180天归档+IMA镜像（取代删除）
python scripts/keeper_setup.py doctor          # 就绪自检
python scripts/keeper_setup.py uninstall [--yes]   # 卸载（程序侧；默认只预览，不碰数据）
"""
import os
import sys
import json
import argparse
import subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL = os.path.dirname(HERE)
HOME = os.path.expanduser("~")
WB_HOME = os.path.join(HOME, ".workbuddy")
SETTINGS = os.path.join(WB_HOME, "settings.json")

sys.path.insert(0, HERE)
import memory_ops as M  # 复用配置入口 / 归档 / 召回等公共入口，避免重复实现


# ── 通用工具 ────────────────────────────────────────────────
def _resolve_python():
    venv = os.path.join(WB_HOME, "binaries", "python", "envs", "default",
                        "Scripts", "python.exe").replace("\\", "/")
    if os.path.exists(venv):
        return venv
    base = os.path.join(WB_HOME, "binaries", "python", "versions")
    if os.path.isdir(base):
        for v in sorted(os.listdir(base), reverse=True):
            cand = os.path.join(base, v, "python.exe").replace("\\", "/")
            if os.path.exists(cand):
                return cand
    return os.path.join(WB_HOME, "binaries", "python", "versions",
                        "3.13.12", "python.exe").replace("\\", "/")


PY = _resolve_python()


def _root():
    return os.environ.get("AI_MEMORY_STORE") or M._default_root()


def _read_cfg_kb():
    """从 store/config.json 的 keeper.ima_kb_id 读已配置的 IMA 知识库 ID（跨 shell 立即可见）。
    注意：直接读原始 config.json，不走 M._load_keeper_config（后者只返回白名单键，会丢 ima_kb_id）。"""
    try:
        root = _root()
        p = os.path.join(root, "config.json")
        if os.path.exists(p):
            with open(p, encoding="utf-8") as f:
                cfg = json.load(f)
            return cfg.get("keeper", {}).get("ima_kb_id") or ""
    except Exception:
        return ""
    return ""


def _set_env_persist(name, value):
    """跨平台持久化环境变量：Windows=setx(HKCU\\Environment, mem_bridge 读得到)；POSIX=追加 profile。"""
    os.environ[name] = value
    if os.name == "nt":
        try:
            subprocess.run(["setx", name, value], capture_output=True, timeout=30)
            return True
        except Exception:
            return False
            # POSIX：按 $SHELL 智能选 profile，避免写错文件导致 env 在 zsh/fish 下不生效（用户曾踩坑）
    shell = os.environ.get("SHELL", "")
    if "fish" in shell:
        rc = os.path.join(HOME, ".config", "fish", "config.fish")
        line = "set -gx %s %s" % (name, value)
        marker = "set -gx %s " % name
    elif "zsh" in shell:
        rc = os.path.join(HOME, ".zshrc")
        line = "export %s=%s" % (name, value)
        marker = "export %s=" % name
    elif "bash" in shell:
        rc = os.path.join(HOME, ".bashrc")
        line = "export %s=%s" % (name, value)
        marker = "export %s=" % name
    else:
        rc = os.path.join(HOME, ".profile")
        line = "export %s=%s" % (name, value)
        marker = "export %s=" % name
    try:
        os.makedirs(os.path.dirname(rc), exist_ok=True)
        cur = "" if not os.path.exists(rc) else open(rc, encoding="utf-8").read()
        if marker in cur:
            return True
        with open(rc, "a", encoding="utf-8") as f:
            f.write("\n# keeper 持久化（自动化生成）\n%s\n" % line)
        print("  ✅ 已写入 %s（%s 下次登录生效）" % (rc, shell or "登录 shell"))
    except Exception as e:
        print("  ⚠️ 写 %s 失败：%s（可手动加：%s）" % (rc, e, line))
    return True


        # ── 各配置动作 ──────────────────────────────────────────────
def action_store(args):
    print("=== [store] 存储路径 ===")
    if args.path:
        p = os.path.abspath(args.path)
        try:
            os.makedirs(p, exist_ok=True)
        except Exception as e:
            print("  ❌ 无法创建目录 %s：%s" % (p, e))
            return 1
        ok = _set_env_persist("AI_MEMORY_STORE", p)
        print("  ✅ 存储路径已设为 %s（%s持久化）" % (p, "已" if ok else "未"))
        print("  📌 重启 WorkBuddy 后该路径对钩子/守护进程生效。")
    else:
        r = _root()
        print("  ℹ️  当前存储根：%s" % r)
        print("  ℹ️  默认零配置：Windows 落到 ~/AI记忆，mac/Linux ~/.ai-memory；"
              "改位置写 ~/.keeper/store_root 或设 AI_MEMORY_STORE。")
        print("  ℹ️  想换路径：python scripts/keeper_setup.py store --path <绝对路径>")
    return 0


def action_embed(args):
    print("=== [embed] 语义后端 ===")
    cfg = M._load_keeper_config()
    cur = cfg.get("embed_backend", "auto")
    print("  ℹ️  当前后端（config.json）：%s" % cur)
    backend = args.backend or cur
    if backend == "auto":
        # ：auto 不再直接降级 lexical——保留 auto，交给 embed.py 的惰性安装路径
        # （首次用到中文语义时自动 pip 装 fastembed + 下载模型；失败才回退词法级）。
        # 这样“auto”用户也能享受开箱中文语义，只是不强制锁定 fastembed。
        try:
            import fastembed  # noqa
            backend = "fastembed"
        except Exception:
            backend = "auto"
    if backend not in ("auto", "fastembed", "neural", "sentence_transformers",
                       "lexical", "online"):
        print("  ❌ 未知后端：%s" % backend)
        return 1
        # 写 config.json 的 keeper.embed_backend（与 env 二选一，config 优先收口）
    _set_config("embed_backend", backend)
    print("  ✅ 语义后端已设为 %s（写入 store/config.json 的 keeper 块）" % backend)
    if backend in ("fastembed", "neural"):
        try:
            import fastembed  # noqa
            print("  ✅ fastembed 已安装，可中文改写召回。")
        except Exception:
            print("  ℹ️  fastembed 未安装——首次用到中文语义检索时 keeper 会自动安装（需联网一次）。")
            print("     手动预装：%s -m pip install fastembed" % PY)
    elif backend == "lexical":
        print("  ℹ️  纯词法模式：零安装、零下载；召回质量略降（字面不完全重叠的改写弱）。")
    elif backend == "online":
        print("  ℹ️  线上 embeddings：请确保 AI_MEM_EMBED_ONLINE_URL / *_KEY_ENV 已配置。")
    return 0


def action_hooks(args):
    print("=== [hooks] 钩子 + 守护进程 ===")
    installer = os.path.join(SKILL, "install_hooks.py")
    if not os.path.exists(installer):
        print("  ❌ 找不到 install_hooks.py：%s" % installer)
        return 1
    if args.status:
        r = subprocess.run([PY, installer, "--status"])
        return r.returncode
    cmdl = [PY, installer]
    if args.mode:
        cmdl += ["--set-mode", args.mode]
    if args.scheduler:
        cmdl += ["--setup-scheduler"]
    cmdl += ["--start-daemon"]
    print("  $ %s" % " ".join(cmdl))
    r = subprocess.run(cmdl)
    if r.returncode != 0:
        print("  ❌ install_hooks 返回码 %s" % r.returncode)
        return 1
    _m = args.mode or "（按持久模式）"
    print("  ✅ 钩子已按模式 %s 应用 + daemon 已尝试启动。" % _m)
    print("  📌 请重启 WorkBuddy，使 settings.json 的钩子对新会话生效。")
    return 0


def action_ima(args):
    print("=== [ima] IMA 云端同步 ===")
    if args.kb_id:
        if args.kb_id == "YOUR_IMA_KB_ID":
            print("  ❌ 不能把占位符 YOUR_IMA_KB_ID 作为 KB id。请填真实知识库 ID。")
            return 1
        _set_env_persist("IMA_KB_ID", args.kb_id)
        _set_config("ima_kb_id", args.kb_id)
        print("  ✅ IMA 同步目标已配置：%s" % args.kb_id)
        print("  📌 已写入注册表(env) + store/config.json，跨会话/跨 shell 立即可见。")
    kb = os.environ.get("IMA_KB_ID") or _read_cfg_kb() or "YOUR_IMA_KB_ID"
    if kb == "YOUR_IMA_KB_ID":
        print("  ❌ 未配置 IMA 知识库 ID。两种方式：")
        print("    ① 让 AI 在已连接 IMA MCP 的会话里直接帮你选（推荐，不用找 ID）")
        print("    ② 手动：python scripts/keeper_setup.py ima --kb-id <你的知识库ID>")
        return 1
    if args.push:
        # Phase 2：导出+脱敏复检+KB预检+推送指令（含占位符预检）
        sync = os.path.join(HERE, "ima_sync.py")
        r = subprocess.run([PY, sync, "--push"])
        return r.returncode
    print("  ℹ️ 配置就绪。要真正推送到云端：说『同步到 IMA』或 "
          "python scripts/keeper_setup.py ima --push")
    return 0


def action_archive(args):
    print("=== [archive] 180天归档 + IMA 镜像（取代删除）===")
    root = _root()
    if args.review:
        r = M.archive_review(root)
        print("  复查 %d 条归档/被取代记忆：%d 条需关注，%d 条状态正常。" % (
            r["reviewed"], r["n_flagged"], r["n_ok"]))
        if r["flagged"]:
            print("  — 需关注（按严重度）—")
            for e in r["flagged"]:
                print("   • [%s] %s（归档%d天 / 闲置%d天）" % (
                    e["status"], e["summary"], e["archived_days"] or -1, e["idle_days"] or -1))
                for rs in e["reasons"]:
                    print("       - %s" % rs)
        else:
            print("  ✅ 没有需关注的归档项。")
        return 0
    res = M.archive_sweep(root, ttl_days=180, dry_run=not args.apply,
                          mirror_ima=not args.no_mirror)
    print("  模式：%s" % res["mode"])
    print("  候选 %d · 冷却待确认 %d · 受保护 %d" % (
        res["n_candidates"], res["n_cooldown_pending"], res["n_protected"]))
    if args.apply:
        print("  本次新归档 %d · 已软保留(无需动作) %d · IMA 镜像%s" % (
            res["n_archived_now"], res["n_already_soft"],
            "已重新生成" if res.get("mirrored_to_ima") else "跳过"))
        if res["n_archived_now"]:
            print("  👉 把归档镜像推到 IMA：python scripts/ima_sync.py --push（或由每周自动化执行）")
    else:
        print("  ℹ️ 这是只读预览。确认无误后加 --apply 真正归档（绝不删除任何记忆）。")
        print("  ℹ️ 首次 --apply 只落冷却基准，第二次 --apply 才执行（防手滑）。")
    return 0


def action_doctor(args):
    print("=== [doctor] 记忆系统就绪自检 ===\n")
    checks = []

    # 1) store
    try:
        root = _root()
        ok_dir = os.path.isdir(root)
        idx = os.path.join(root, "index.json")
        readable = os.path.exists(idx)
        checks.append(("存储根", ok_dir and readable,
                       "%s（index%s）" % (root, "可读" if readable else "未建，首次 deposit 会自动建")))
    except Exception as e:
        checks.append(("存储根", False, "解析失败: %s" % e))

        # 2) embed
    try:
        cfg = M._load_keeper_config()
        be = cfg.get("embed_backend", "auto")
        neural = be in ("fastembed", "neural")
        avail = False
        if neural:
            try:
                import fastembed  # noqa
                avail = True
            except Exception:
                avail = False
        detail = "后端=%s" % be
        if neural:
            detail += "，fastembed %s" % ("已装" if avail else "缺失(首次用会自装)")
        checks.append(("语义召回", True, detail))
    except Exception as e:
        checks.append(("语义召回", False, "读配置失败: %s" % e))

        # 3) hooks 注册数（识别指向 ~/.workbuddy/hooks/ 的命令，比"keeper"子串更准）
    try:
        n = 0
        if os.path.exists(SETTINGS):
            with open(SETTINGS, encoding="utf-8") as f:
                s = json.load(f)
            hooks = s.get("hooks", {})
            for ev, groups in hooks.items():
                for g in groups:
                    for h in g.get("hooks", []):
                        cmd = h.get("command", "")
                        if (".workbuddy/hooks/" in cmd) or (".workbuddy\\hooks\\" in cmd):
                            n += 1
        checks.append(("钩子注册", n > 0, "%d 个 keeper 钩子已注册（重启 WorkBuddy 生效）" % n))
    except Exception as e:
        checks.append(("钩子注册", False, "读 settings 失败: %s" % e))

        # 5) daemon（仅 daemon 模式需常驻；inprocess 模式钩子进程内召回，守护进程可关）
    try:
        _mode = "daemon"
        try:
            _cfgp = os.path.join(_root(), "store", "config.json")
            if os.path.exists(_cfgp):
                _cfg = json.load(open(_cfgp, encoding="utf-8"))
                _mode = (_cfg.get("keeper") or {}).get("recall_mode") or "daemon"
        except Exception:
            pass
        if _mode == "inprocess":
            checks.append(("守护进程", True,
                           "未启用（recall_mode=inprocess，钩子进程内召回，无需常驻进程）"))
        elif os.path.exists(os.path.join(WB_HOME, "keeper_daemon", "keeper_recall_client.py")):
            client = os.path.join(WB_HOME, "keeper_daemon", "keeper_recall_client.py")
            try:
                r = subprocess.run([PY, client, "--query", "", "--top-n", "1"],
                                   capture_output=True, timeout=120)
                alive = r.returncode == 0
                detail = "存活" if alive else "未运行（可 python install_hooks.py --start-daemon）"
            except subprocess.TimeoutExpired:
                # 守护进程冷加载中文语义模型需 10–120s，超时属假阴性而非真故障
                alive = False
                detail = "冷加载中（首次启动模型需 10–120s，稍后重跑 doctor 即可确认存活）"
            checks.append(("守护进程", alive, detail))
        else:
            checks.append(("守护进程", False, "未安装（先跑 hooks）"))
    except Exception:
        checks.append(("守护进程", False, "状态未知（subprocess 失败）"))

        # 6) ima
    kb = os.environ.get("IMA_KB_ID") or _read_cfg_kb() or "YOUR_IMA_KB_ID"
    ok = kb != "YOUR_IMA_KB_ID"
    checks.append(("IMA 同步", ok, "KB=%s" % (kb if ok else "未配置（占位符）")))

    # 7) recall 冒烟
    try:
        root = _root()
        res = M.recall(root, query="自检冒烟查询", include_auto=False, semantic_gate=0)
        ent = res if isinstance(res, list) else res.get("entries", [])
        checks.append(("召回冒烟", True, "recall 返回 %d 条（无崩溃）" % len(ent)))
    except Exception as e:
        checks.append(("召回冒烟", False, "recall 异常: %s" % e))

        # 打印
    width = 18
    for name, ok, detail in checks:
        mark = "✅" if ok else "❌"
        print("  %s %s%s %s" % (mark, name.ljust(width), "· ", detail))
    bad = [c for c in checks if not c[1]]
    print()
    if bad:
        print("⚠️ 有 %d 项需关注（非全失败即不可用，按提示处理）：" % len(bad))
        for name, ok, detail in bad:
            print("   - %s：%s" % (name, detail))
        print("\n👉 一键修复：python scripts/keeper_setup.py all")
    else:
        print("🎉 全部就绪。")
    return 0


def _prewarm_embed():
    """开箱即用：一次性触发中文语义组件的惰性安装+模型下载（best-effort，失败不影响）。
    让首次 recall 不必现场等下载；无网络/无 pip 时 embed.py 已优雅降级词法级。"""
    print("=== [embed] 预热中文语义模型（首次需联网下载 ~50MB，可能 1-2min） ===")
    try:
        import embed as E  # 同目录导入，复用惰性安装与国内镜像逻辑
        import memory_ops as M
        be = M._load_keeper_config()["embed_backend"].lower()
        if be in ("lexical", "online"):
            print("  ℹ️  后端=%s，无需本地模型，跳过预热。" % be)
            return
        info = E.backend_info()
        if info != "lexical":
            print("  ✅ 中文语义已就绪（%s），无需下载。" % info)
            return
            # 触发一次编码 → 走 _probe_neural 自动安装+下载
        E.embed("预热中文语义模型")
        print("  ✅ 中文语义模型已就绪（%s）。" % E.backend_info())
    except Exception as e:
        print("  ℹ️  预热未成功（%s）—— 不影响使用：首次 recall 用到中文语义时会自动重试下载，" % e)
        print("     若长期离线，系统自动降级词法级（字面召回略弱）。")


def action_all(args):
    print("# keeper 一键配置（init / all）— 开箱即用，零配置\n")
    print("  默认即开：存储路径(默认) · 中文语义(fastembed, 自动安装) · 钩子(silent 无弹窗) · 反馈校准")
    print("  按需手动：IMA 云端同步(需外部知识库) · 本地LLM(~5GB,重)\n")
    action_store(argparse.Namespace(path=None))
    print()
    action_embed(argparse.Namespace(backend="fastembed"))
    print()
    _prewarm_embed()
    print()
    action_hooks(argparse.Namespace(scheduler=args.scheduler, mode="silent"))
    print()
    action_ima(argparse.Namespace(kb_id=None))
    print()
    print("# 配置完成，下面是就绪自检：\n")
    action_doctor(argparse.Namespace())
    return 0


def _set_config(key, value):
    """写 store/config.json 的 keeper 块（与 env 二选一，config 优先收口）。"""
    root = _root()
    cfg_path = os.path.join(root, "config.json")
    cfg = {}
    if os.path.exists(cfg_path):
        try:
            with open(cfg_path, encoding="utf-8") as f:
                cfg = json.load(f)
        except Exception:
            cfg = {}
    keeper = cfg.setdefault("keeper", {})
    keeper[key] = value
    os.makedirs(root, exist_ok=True)
    with open(cfg_path, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


_KEEPER_ENV_NAMES = ("AI_MEMORY_STORE", "IMA_KB_ID")


def _ts():
    import datetime as _dt
    return _dt.datetime.now().strftime("%Y%m%d-%H%M%S")


def _daemon_quit_all(dry):
    """请退本机所有 keeper daemon（按 STATE 自报的 port+token）。只请退，不删文件。"""
    import glob as _g
    import urllib.request
    dirs = [os.path.join(WB_HOME, "keeper_daemon"), os.path.join(SKILL, "keeper_daemon")]
    seen, lines = set(), []
    for dd in dirs:
        for p in sorted(_g.glob(os.path.join(dd, ".daemon*.json"))):
            try:
                with open(p, encoding="utf-8") as f:
                    st = json.load(f)
            except Exception as e:
                lines.append("跳过 %s（读不了：%s）" % (os.path.basename(p), type(e).__name__))
                continue
            port, tok = st.get("port"), st.get("token", "")
            if not port or port in seen:
                continue
            seen.add(port)
            if dry:
                lines.append("[dry] 将请退 daemon(port=%s, root=%s)"
                             % (port, st.get("root") or "?"))
                continue
            try:
                req = urllib.request.Request("http://127.0.0.1:%d/quit" % port,
                                             headers={"X-Token": tok})
                urllib.request.urlopen(req, timeout=3)
                lines.append("已请退 daemon(port=%s)" % port)
            except Exception as e:
                lines.append("该 daemon 已不在或不可达（port=%s，%s）" % (port, type(e).__name__))
    if not lines:
        lines.append("未发现运行中的 keeper daemon")
    return lines


def _retire_dir(src, retire_root, dry):
    """把目录搬到归档区（同卷 rename，只搬不删——红线 A2）。返回结果字符串。"""
    if not os.path.isdir(src):
        return "ℹ️  不存在，跳过：%s" % src
    if dry:
        return "[dry] 将搬离部署副本 %s → %s" % (
            src, os.path.join(retire_root, os.path.basename(src)))
    try:
        os.makedirs(retire_root, exist_ok=True)
        dst = os.path.join(retire_root, os.path.basename(src))
        if os.path.exists(dst):
            dst = dst + "." + _ts()
        os.rename(src, dst)
        return "✅ 已搬离 %s → %s" % (src, dst)
    except Exception as e:
        return "⚠️ 搬离失败（可能被进程占用）：%s（%s）" % (src, e)


def _env_persisted(name):
    """该 env 是否已持久化（Windows 查注册表 HKCU 的 Environment 键，POSIX 查 profile）。"""
    if os.name == "nt":
        try:
            r = subprocess.run(["reg", "query", r"HKCU\Environment", "/v", name],
                               capture_output=True, timeout=10)
            return r.returncode == 0
        except Exception:
            return False
    rc = os.path.join(HOME, ".profile")
    try:
        return (os.path.exists(rc)
                and ("export %s=" % name) in open(rc, encoding="utf-8").read())
    except Exception:
        return False


def _unset_env_persist(name, dry):
    if dry:
        return "[dry] 将移除持久化 env：%s" % name
    if os.name == "nt":
        try:
            subprocess.run(["reg", "delete", r"HKCU\Environment", "/v", name, "/f"],
                           capture_output=True, timeout=30)
            return "已移除持久化 env：%s" % name
        except Exception as e:
            return "移除 %s 失败：%s" % (name, e)
    rc = os.path.join(HOME, ".profile")
    try:
        if not os.path.exists(rc):
            return "ℹ️  无 profile，跳过：%s" % name
        cur = open(rc, encoding="utf-8").read()
        lines = cur.splitlines()
        kept = [ln for ln in lines
                if ("export %s=" % name) not in ln and ("set -gx %s " % name) not in ln]
        if len(kept) == len(lines):
            return "ℹ️  %s 未在 profile 中" % name
        with open(rc, "w", encoding="utf-8") as f:
            f.write("\n".join(kept) + "\n")
        return "已从 profile 移除：%s" % name
    except Exception as e:
        return "移除 %s 失败：%s" % (name, e)


def action_uninstall(args):
    """一条收口的卸载：清钩子注册 / 守护进程 / 部署副本 / 计划任务 /（可选）持久化 env。

    🔴 **绝不触碰记忆库数据**——数据与程序分离。你的记忆、备份
    都留在原处；要处理数据请按 SKILL.md §九 红线流程单独来（唯一真删是 delete --yes）。
    """
    print("=== [uninstall] 卸载 keeper（程序侧）===")
    dry = bool(args.dry_run) or not args.yes
    print("  模式：%s" % ("只读预览（加 --yes 才执行）" if dry else "**执行**"))
    print("  🔴 本命令不碰记忆库数据：条目 / 备份 一律留在原处。\n")
    rc = 0

    print("  [1/5] 钩子反注册", flush=True)
    installer = os.path.join(SKILL, "install_hooks.py")
    if os.path.exists(installer):
        cmd = [PY, installer, "--set-mode", "off"] + (["--dry-run"] if dry else [])
        try:
            r = subprocess.run(cmd)
            if r.returncode != 0:
                print("        ⚠️ 安装器返回码 %s" % r.returncode)
                rc = 1
        except Exception as e:
            print("        ⚠️ 失败：%s" % e)
            rc = 1
    else:
        print("        ℹ️  找不到 install_hooks.py，跳过")

    print("\n  [2/5] 计划任务", flush=True)
    sched = os.path.join(SKILL, "setup_scheduler.py")
    if os.path.exists(sched):
        cmd = [PY, sched, "--uninstall"] + (["--dry-run"] if dry else [])
        try:
            subprocess.run(cmd)
        except Exception as e:
            print("        ⚠️ 失败：%s" % e)
    else:
        print("        ℹ️  找不到 setup_scheduler.py，跳过")

    print("\n  [3/5] 守护进程", flush=True)
    for ln in _daemon_quit_all(dry):
        print("        %s" % ln)

    print("\n  [4/5] 部署副本", flush=True)
    retire_root = os.path.join(WB_HOME, "_retired_keeper_uninstall_%s" % _ts())
    for d in (os.path.join(WB_HOME, "keeper_daemon"), os.path.join(WB_HOME, "hooks")):
        print("        %s" % _retire_dir(d, retire_root, dry))
    if not dry and os.path.isdir(retire_root):
        print("        📦 归档在：%s（keeper 不硬删；想彻底清理请自行处理）" % retire_root)

    print("\n  [5/5] 持久化环境变量", flush=True)
    if args.purge_env:
        for n in _KEEPER_ENV_NAMES:
            print("        %s" % _unset_env_persist(n, dry))
    else:
        for n in _KEEPER_ENV_NAMES:
            if _env_persisted(n):
                print("        ℹ️  %s 仍持久化着（想一并清：加 --purge-env --yes）" % n)

    print()
    if dry:
        print("👉 以上为预览。确认无误后执行：python scripts/keeper_setup.py uninstall --yes")
    else:
        print("✅ 程序侧已卸载。记忆数据未动；要恢复重跑 python scripts/keeper_setup.py all。")
    return rc


def main():
    ap = argparse.ArgumentParser(description="keeper 一键配置向导 + 就绪自检")
    sub = ap.add_subparsers(dest="cmd")

    p_init = sub.add_parser("init", help="引导式全配")
    p_init.add_argument("--scheduler", action="store_true")

    p_all = sub.add_parser("all", help="一条命令全配")
    p_all.add_argument("--scheduler", action="store_true")

    p_store = sub.add_parser("store", help="存储路径")
    p_store.add_argument("--path", default=None)

    p_embed = sub.add_parser("embed", help="语义后端")
    p_embed.add_argument("--backend", default=None)

    p_hooks = sub.add_parser("hooks", help="钩子+守护进程（可加 --mode full/silent/off 切换）")
    p_hooks.add_argument("--scheduler", action="store_true")
    p_hooks.add_argument("--mode", choices=["full", "silent", "off"], default=None,
                         help="钩子模式：full=全部(含弹窗源); silent=仅功能钩子+MEMORY.md自提醒; off=无钩子")
    p_hooks.add_argument("--status", action="store_true", help="查看当前钩子模式与注册状态")

    p_ima = sub.add_parser("ima", help="IMA 同步配置（MCP 驱动：AI 在已连 IMA MCP 的会话里直接选库）")
    p_ima.add_argument("--kb-id", default=None, help="知识库 ID；不填则由 AI 经 IMA MCP 发现")
    p_ima.add_argument("--push", action="store_true", help="配置后立即导出并生成推送指令")

    p_arc = sub.add_parser("archive", help="180天归档+IMA镜像（取代删除；--apply 才执行）")
    p_arc.add_argument("--apply", action="store_true", help="真正归档（默认只读预览）")
    p_arc.add_argument("--review", action="store_true", help="生成归档复查报告（过时/更优方法）")
    p_arc.add_argument("--no-mirror", action="store_true", help="归档后不重新生成 IMA 导出")

    sub.add_parser("doctor", help="就绪自检")

    p_un = sub.add_parser("uninstall", help="卸载 keeper（程序侧；默认只预览，--yes 才执行）")
    p_un.add_argument("--dry-run", action="store_true", help="只打印将清理的对象（等同默认）")
    p_un.add_argument("--yes", action="store_true", help="真正执行（默认只预览）")
    p_un.add_argument("--purge-env", action="store_true",
                      help="同时移除持久化环境变量（AI_MEMORY_STORE / IMA_KB_ID）")

    args = ap.parse_args()
    cmd = args.cmd or "doctor"
    if cmd == "init":
        return action_all(args)
    if cmd == "all":
        return action_all(args)
    if cmd == "store":
        return action_store(args)
    if cmd == "embed":
        return action_embed(args)
    if cmd == "hooks":
        return action_hooks(args)
    if cmd == "ima":
        return action_ima(args)
    if cmd == "archive":
        return action_archive(args)
    if cmd == "doctor":
        return action_doctor(args)
    if cmd == "uninstall":
        return action_uninstall(args)
    ap.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
