# -*- coding: utf-8 -*-
"""
ima_sync.py — IMA 云端镜像「一键导出 + 脱敏复检 + 推送指令生成」（v4.5.4）

为什么需要：
原先 IMA 同步要自己拼「导出 → create_media → COS 上传 → add_knowledge → search」五步，
且 create_media / add_knowledge 是 **IMA MCP 工具**，脚本调不到（必须由 Agent 经 MCP 执行）。
本脚本把「能脚本化的部分」一条命令做完，并直接产出一份**可贴给 Agent 的推送指令**，
把用户侧的流程从「从零拼流程」压成「跑一条命令 → 贴一段指令」。

做什么：
1) 调用 _keeper_ima_push.py 导出：全量记忆 → 脱敏 → 按域拆分 → 写 ~/.workbuddy/ima_push/keeper-镜像-<domain>.md
2) 对每份文档跑 verify_desensitization 复检（任何残留敏感信息直接失败，绝不交付明文）
3) 打印文件清单 + 知识库 ID + 一份**复制即用**的 Agent 推送指令（含每文件三步 MCP 调用）

用法：
python scripts/ima_sync.py              # 导出 + 复检 + 打印推送指令
python scripts/ima_sync.py --open       # 额外尽力打开 IMA 知识库网页
python scripts/ima_sync.py --kb-id XXX  # 指定知识库 ID（默认读 IMA_KB_ID 或内置已知库）

注意：脚本只负责「导出侧一键化」；真正的入库（create_media/add_knowledge）由 Agent 经 IMA MCP 完成，
这是设计使然（MCP 工具不走 REST，脚本无法代调）。本脚本已把该步所需的参数全部填好，Agent 照做即可。
"""
import os
import sys
import json
import subprocess

SKILL = os.path.dirname(os.path.abspath(__file__))
HOME = os.path.expanduser("~")
WB_HOME = os.path.join(HOME, ".workbuddy")
PUSH_DIR = os.path.join(WB_HOME, "ima_push")
# 内置默认知识库占位符：发布版不含作者私有 KB id；用 IMA_KB_ID 环境变量 / store config / --kb-id 覆盖。
KB_NAME = "AI记忆"

sys.path.insert(0, SKILL)
import memory_ops as M  # 复用配置入口，从 config.json 的 keeper.ima_kb_id 兜底读 KB id


def _config_kb_id():
    """从 store/config.json 的 keeper.ima_kb_id 读 KB id（跨 shell 立即可见）。
    直接读原始 config.json，不走 M._load_keeper_config（后者只返回白名单键，会丢 ima_kb_id）。"""
    try:
        root = os.environ.get("AI_MEMORY_STORE") or M._default_root()
        p = os.path.join(root, "config.json")
        if os.path.exists(p):
            with open(p, encoding="utf-8") as f:
                cfg = json.load(f)
            return cfg.get("keeper", {}).get("ima_kb_id") or ""
    except Exception:
        return ""
    return ""


DEFAULT_KB_ID = os.environ.get("IMA_KB_ID") or _config_kb_id() or "YOUR_IMA_KB_ID"


def _run_export():
    py = sys.executable
    installer = os.path.join(SKILL, "_keeper_ima_push.py")
    if not os.path.exists(installer):
        print("❌ 找不到 _keeper_ima_push.py（%s）" % installer)
        sys.exit(2)
    print("=== [1/3] 导出 + 脱敏（_keeper_ima_push.py）===")
    # v4.9.1：原为 shell=True + 字符串拼接（'"%s" "%s"'），当 sys.executable 或
    # SKILL 路径含空格（如 C:\Program Files\...）时命令行会被拆断 → 导出静默失败。
    # 改为 list 传参（subprocess 自动加引号），同时去掉不必要的 shell=True。
    r = subprocess.run([py, installer])
    if r.returncode != 0:
        print("❌ 导出失败（返回码 %s），未生成可推送文件。" % r.returncode)
        sys.exit(2)


def _verify():
    from _keeper_ima_push import verify_desensitization
    docs = []
    if not os.path.isdir(PUSH_DIR):
        return docs
    for fn in sorted(os.listdir(PUSH_DIR)):
        if fn.startswith("keeper-镜像-") and fn.endswith(".md"):
            p = os.path.join(PUSH_DIR, fn)
            with open(p, encoding="utf-8") as f:
                text = f.read()
            leaks = verify_desensitization(text)
            if leaks:
                print("❌ [脱敏复检失败] %s 仍残留敏感信息，已拒绝交付：" % p)
                for name, snip in leaks[:10]:
                    print("   - %s: %s" % (name, snip))
                sys.exit(2)
            docs.append(p)
    return docs


def _verify_reconcile():
    """D2：IMA 同步对账（关闭回路），解决『导出≠入库』（跑完≠同步）的误解。

    导出侧脚本只能生成文件+指令，真正入库由 Agent 经 MCP 完成。本函数提供可验证完成态：
    - 读本地导出清单（PUSH_DIR 下的 keeper-镜像-*.md 文件名/域）；
    - 若 Agent 已把 KB 内文档列表落盘到 store/ima_kb_listing.json（由 search_knowledge 取得），
    则比对『导出集 vs KB 集』，报告 N 已推送 / M 缺失；
    - 否则打印对账指令，请 Agent 跑 search_knowledge 并落盘后重跑本命令。
    纯只读、fail-open。"""
    _exported = []
    if os.path.isdir(PUSH_DIR):
        for fn in sorted(os.listdir(PUSH_DIR)):
            if fn.startswith("keeper-镜像-") and fn.endswith(".md"):
                _exported.append(fn)
    print("=== [D2] IMA 同步对账 ===")
    print("本地已导出文档：%d 个" % len(_exported))
    for fn in _exported:
        print("   - %s" % fn)
    _root = os.environ.get("AI_MEMORY_STORE") or M._default_root()
    _listing = os.path.join(_root, "store", "ima_kb_listing.json")
    if not os.path.exists(_listing):
        print("")
        print("⚠️ 未找到 KB 内文档清单（%s）。" % _listing)
        print("   请让 Agent 执行以下步骤后再跑 `python scripts/ima_sync.py --verify`：")
        print("   ① 在 IMA MCP 会话调用 `search_knowledge(knowledge_base_id=\"%s\", query=\"\")` 列出 KB 文档；" % DEFAULT_KB_ID)
        print("   ② 把返回的文档列表（标题列表）写入 %s（JSON 数组，元素含 title 字段）。" % _listing)
        print("   即可自动比对『导出集 vs KB 集』，确认哪些已推送、哪些缺失。")
        return
    try:
        with open(_listing, encoding="utf-8") as f:
            _kb_docs = json.load(f)
    except Exception as e:
        print("❌ 读取 KB 清单失败：%s" % e)
        return
    _kb_titles = set()
    for d in _kb_docs:
        if isinstance(d, dict):
            _kb_titles.add((d.get("title") or "").strip())
        elif isinstance(d, str):
            _kb_titles.add(d.strip())
    _exported_titles = set(fn[len("keeper-镜像-"):-len(".md")] for fn in _exported)
    _matched = _exported_titles & _kb_titles
    _missing = _exported_titles - _kb_titles
    print("KB 内文档：%d 个；已对账匹配：%d / %d" % (len(_kb_titles), len(_matched), len(_exported_titles)))
    if _missing:
        print("❌ 以下导出域在 KB 中未找到（可能未推送或标题不一致）：")
        for m in sorted(_missing):
            print("   - %s" % m)
    else:
        print("✅ 所有导出文档均在 KB 中存在（已推送）。")


def _open_ima():
    url = "https://ima.qq.com"
    try:
        if sys.platform.startswith("win"):
            os.startfile(url)
        elif sys.platform.startswith("darwin"):
            subprocess.Popen(["open", url])
        else:
            subprocess.Popen(["xdg-open", url])
        print("🌐 已尝试打开 IMA 网页：%s" % url)
    except Exception as e:
        print("⚠️ 无法自动打开浏览器（可手动访问 %s）：%s" % (url, e))


def _build_prompt(docs, kb_id):
    lines = []
    lines.append("请把以下记忆镜像文件推送到 IMA 知识库（知识库ID：%s，名称「%s」）。" % (kb_id, KB_NAME))
    lines.append("这些文件已由 `python scripts/ima_sync.py` 自动**脱敏 + 复检通过**，可放心推送。")
    lines.append("每个文件走三步（务必带 REPLACE 防堆积）：")
    lines.append("")
    lines.append("1) `create_media(content_type=\"text/markdown\", file_name=\"<文件名>\", file_size=<字节数>, knowledge_base_id=\"%s\")` → 拿到 `media_id` + `cos_credential`" % kb_id)
    lines.append("2) 用 `python scripts/ima_cos_upload.py <cos_credential.json> <文件绝对路径> text/markdown` 上传（官方 cos-python-sdk-v5）")
    lines.append("3) `add_knowledge(knowledge_base_id=\"%s\", media_id=<第1步>, duplicate_name_strategy=DUPLICATE_NAME_STRATEGY_REPLACE)`" % kb_id)
    lines.append("")
    lines.append("文件清单（共 %d 个）：" % len(docs))
    for p in docs:
        try:
            size = os.path.getsize(p)
        except OSError:
            size = 0
        lines.append("- %s  （%d 字节）" % (p, size))
    return "\n".join(lines)


def _precheck_kb(kb_id):
    """Phase 2：KB id 占位符预检——杜绝「前半段成功、Agent 那步才失败」的静默坑。"""
    if not kb_id or kb_id == "YOUR_IMA_KB_ID":
        print("❌ [预检失败] 未配置有效的 IMA 知识库 ID（当前=%s）。" % kb_id)
        print("   请先在 IMA 网页复制你的知识库 ID，然后二选一：")
        print("   ① python scripts/keeper_setup.py ima --kb-id <你的知识库ID>")
        print("   ② 设置环境变量 IMA_KB_ID=<你的知识库ID>（Windows: setx IMA_KB_ID <id>）")
        print("   配置后再跑：python scripts/ima_sync.py --push")
        sys.exit(2)
    print("=== [0/3] 预检：目标知识库 ID = %s ✅ ===" % kb_id)


def main():
    import argparse
    ap = argparse.ArgumentParser(description="IMA 云端镜像一键导出 + 脱敏复检 + 推送指令生成")
    ap.add_argument("--open", action="store_true", help="额外尽力打开 IMA 知识库网页")
    ap.add_argument("--kb-id", default=DEFAULT_KB_ID, help="目标知识库 ID（默认 IMA_KB_ID 或内置已知库）")
    ap.add_argument("--push", action="store_true",
                    help="一键推送流程（导出+脱敏复检+KB预检+推送指令，等于默认行为但意图更明确）")
    ap.add_argument("--verify", action="store_true",
                    help="D2 同步对账（只读）：比对本地导出集 vs KB 内文档清单，确认哪些已推送、哪些缺失")
    args = ap.parse_args()

    # D2：对账是只读操作，不需要 KB 预检/导出，单独分支返回
    if args.verify:
        _verify_reconcile()
        return

        # Phase 2：任何路径都先做 KB id 预检，避免占位符假成功
    _precheck_kb(args.kb_id)

    _run_export()
    print("=== [2/3] 脱敏后复检（verify_desensitization）===")
    docs = _verify()
    if not docs:
        print("⚠️ 没有可导出的记忆文档（库可能为空，或导出未产出文件）。")
        sys.exit(0)
    print("✅ 脱敏复检通过：%d 个域文档无敏感信息残留。" % len(docs))

    print("=== [3/3] 生成 Agent 推送指令 ===")
    prompt = _build_prompt(docs, args.kb_id)
    print("-" * 60)
    print(prompt)
    print("-" * 60)
    print("👉 把上面这段指令直接发给 Agent 即可完成入库（create_media/add_knowledge 走 IMA MCP，由 Agent 执行）。")
    print("   也可直接对 Agent 说：「把 ima_push 下的记忆镜像推到 IMA 知识库 %s」。" % args.kb_id)

    if args.open:
        _open_ima()

        # 同时把指令落盘，方便随时取用
    try:
        out = os.path.join(PUSH_DIR, "IMA推送指令.md")
        with open(out, "w", encoding="utf-8") as f:
            f.write("# IMA 记忆镜像 · 推送指令\n\n")
            f.write("知识库 ID：`%s`（名称「%s」）\n\n" % (args.kb_id, KB_NAME))
            f.write(prompt)
            f.write("\n\n---\n由 `python scripts/ima_sync.py` 生成。\n")
        print("📄 推送指令已落盘：%s" % out)
    except Exception:
        pass


if __name__ == "__main__":
    main()
