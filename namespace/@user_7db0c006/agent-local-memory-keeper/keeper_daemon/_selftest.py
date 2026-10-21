# -*- coding: utf-8 -*-
"""
keeper_daemon 回归自测：验证 daemon 启动、神经后端、冷/热延迟、回退安全网。
用法：python _selftest.py
"""
import sys, os, time, json, subprocess

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import keeper_recall_client as C

ok = True


def check(name, cond, detail=""):
    global ok
    print(("PASS " if cond else "FAIL "), name, detail)
    if not cond:
        ok = False


        # 清理旧 STATE 后冷启动
try:
    os.remove(C.STATE)
except Exception:
    pass

    # 1) 冷启动召回（含 daemon 首启 + 模型/recall 冷成本）
t0 = time.time()
raw = C.recall_proxy(query="沙箱 ctypes 硬删文件怎么绕过 safe-delete", top_n=8)
c1 = time.time() - t0
obj = json.loads(raw)
check("cold recall ok", obj.get("ok") is True, "%.0fms count=%s" % (c1 * 1000, obj.get("count")))

# 2) 神经后端强制生效
st = json.load(open(C.STATE, encoding="utf-8"))
import urllib.request
bi = json.loads(urllib.request.urlopen("http://127.0.0.1:%d/ping" % st["port"], timeout=2).read()).get("backend", "")
check("neural backend forced", bi.startswith("fastembed"), bi)

# 3) 热召回毫秒级（daemon 常驻）
t0 = time.time()
C.recall_proxy(query="skillhub 升级被 sandbox safe-delete 拦截怎么办", top_n=8)
c2 = time.time() - t0
check("warm recall fast (<500ms)", c2 < 0.5, "%.0fms" % (c2 * 1000))

# 4) 回退安全网：返回空（毫秒级，绝不阻塞）
raw2 = C._fallback_skip()
check("fallback empty (skip)", json.loads(raw2).get("count") == 0)

# 5) 自愈：杀掉 daemon 后下一次调用应 resurrect（<=30s）
try:
    urllib.request.urlopen("http://127.0.0.1:%d/quit" % st["port"], timeout=2).read()
except Exception:
    pass
time.sleep(0.5)
t0 = time.time()
C.recall_proxy(query="路径脱敏替换真实目录占位符", top_n=8)
c3 = time.time() - t0
check("self-heal resurrect (<=30s)", c3 < 30.0, "%.0fms" % (c3 * 1000))

# 关闭（留下干净状态）
try:
    st2 = json.load(open(C.STATE, encoding="utf-8"))
    urllib.request.urlopen("http://127.0.0.1:%d/quit" % st2["port"], timeout=2).read()
except Exception:
    pass

print("\nRESULT:", "ALL PASS" if ok else "HAS FAILURES")
sys.exit(0 if ok else 1)
