# Auto-extracted submodule: _cli
# Source: agent-local-memory-keeper scripts/memory_ops/__init__.py
# Loaded via dependency-injection (globals injected by __init__ loader block).
# Shared helpers (_audit_log, _with_deposit_lock, _save_mem, caches, etc.) resolve
# through the injected namespace; do NOT re-define them here.

def list_commands():
    """返回人/机都可读的命令清单，降低"高级功能触发方式多"的认知门槛。"""
    lines = ["=== Agent 记忆系统 · 命令清单 ==="]
    for group, cmd, desc in _COMMAND_CATALOG:
        lines.append("  %-6s %-42s %s" % (group, cmd, desc))
    lines.append("\n常用组合：")
    for name, combo in _COMMAND_COMBOS:
        lines.append("  %-12s %s" % (name, combo))
    lines.append("\n完整文档：SKILL.md（AI 规则单） + references/TUTORIAL.md（人读教程） + references/QA.md（避坑）")
    readable = "\n".join(lines)
    return {
        "ok": True,
        "commands": [
            {"group": g, "command": c, "description": d} for g, c, d in _COMMAND_CATALOG
        ],
        "combos": [{"name": n, "flow": f} for n, f in _COMMAND_COMBOS],
        "readable": readable,
    }

def quickstart_text():
    """极简上手指引（2 分钟）：三句话触发 + 新能力一句话触发，缓解 over-engineering 劝退。"""
    lines = [
        "=== 极简上手 · agent-local-memory-keeper ===",
        "",
        "你只用说人话，AI 在后台替你跑命令（不用记命令、不用看输出）：",
        "  1. 「记一下…」            → deposit（存一条经验）",
        "  2. 「找一下之前那个…」    → recall（语义召回，换说法也能找回）",
        "  3. 「帮我整理今天记的」    → reflect --auto（去重/纠错/归档，永远 0 删除）",
        "",
        "新能力（一句话触发，AI 路由到对应命令）：",
        "  · 导出成跨工具可分享的 learnings 文件：export --format learnings",
        "  · 把高频经验萃取成可复用 skill 脚手架：extract-skill",
        "  · 把行为规则固化给 GitHub Copilot / Claude（平台自动加载）：export-rules --rules-target copilot|claude",
        "  · 把规则写到任意自定义路径（零平台耦合）：export-rules --rules-target text --out <路径>",
        "  · 看全部命令与组合：commands",
        "",
        "完整文档：SKILL.md（AI 规则单）+ references/TUTORIAL.md（教程）+ references/COMMANDS.md（命令参数表）",
    ]
    return "\n".join(lines)


# 5.0.0：旧加密库守卫在 CLI dispatch 层的**放行白名单**（详见 main() 内的注释）。
# 只列「不读写本库记忆数据」的命令，故在旧加密库上放行是正确行为而非漏网：
#   quickstart / commands —— 纯帮助文本；
#   release-audit         —— 只对账 CHANGELOG 与平台发布版本；
#   backup                —— 把整库原样打成 ZIP 存到库外（迁移/留档前正需要它）；
#   init                  —— 幂等建目录，不动既有数据；
#   mcp                   —— 长驻服务，在 dispatch 之前已 return。
_LEGACY_GUARD_EXEMPT_OPS = frozenset({
    "quickstart", "commands", "release-audit", "backup", "init", "mcp",
})


def main():
    ap = argparse.ArgumentParser(description="Agent 本地记忆系统：本地文件存储与语义召回的命令行操作入口")
    # R2 修复（工程改进方案阶段2.1）：op 名单一源。choices 由 OP_NAMES 派生，
    # 新增 op 只需在 OP_NAMES 与对应 elif 分支各加一处；test_op_consistency.py
    # 强制「OP_NAMES ↔ dispatch 分支 ↔ 文档」三处对齐，杜绝 recall_v30/taxonomy 式幽灵。
    ap.add_argument("op", choices=OP_NAMES)
    # F5 修复：delete/touch/archive/overwrite/unarchive/link/promote/reclassify 等命令
    # 都接受一个位置参数 id（`delete LRN-001 --yes`），作为 --id 的兼容回退。
    ap.add_argument("op_id", nargs="?", default=None, help=argparse.SUPPRESS)
    ap.add_argument("--root", default=DEFAULT_ROOT,
                    help="记忆根目录（默认跨平台零配置路径，设 AI_MEMORY_STORE 可改；首次自动创建）")
    ap.add_argument("--roots", default=None,
                    help="4.5.58 多库交叉召回：逗号分隔多个记忆根目录（如 --roots D:/A,D:/B），recall 时跨库合并按 score 排序，每条带 source_root；与 --root 互斥（--roots 优先）")
    ap.add_argument("--top", type=int, default=20,
                    help="stats/audit-log：条数（audit-log 默认 20，仅展示尾部）")
    ap.add_argument("--days", type=int, default=None,
                    help="timeline --query：只返回最近 N 天的事件")
    ap.add_argument("--limit", type=int, default=20,
                    help="timeline：最多返回事件条数（默认 20）")
    ap.add_argument("--filter-op", default=None,
                    help="audit-log：按 op 过滤（如 deposit/delete/confirm）")
    ap.add_argument("--top-keep", type=int, default=5,
                    help="stats：Top 高频记忆条数（默认 5，仅展示召回频次最高的若干条）")
    ap.add_argument("--id")
    ap.add_argument("--to-version", type=int, default=None,
                    help="rollback 目标历史版本号（用 `versions --id <mid>` 查看可用版本）")
    ap.add_argument("--category", default="")
    ap.add_argument("--summary", default="")
    ap.add_argument("--tags", default="")
    ap.add_argument("--body", default="")
    ap.add_argument("--body-file", default="", help="从文件读取 body（避免超长 CLI 参数触发 Windows 命令行长度限制）")
    ap.add_argument("--tier", default="")
    ap.add_argument("--confidence", type=float, default=None,
                    help="显式置信度 0-1（默认不传则按来源判定：显式经验=1.0，推断经验=0.5）")
    ap.add_argument("--inferred", action="store_true",
                    help="标记为推断来源（AI 推断而非用户明说）→ confidence=0.5")
    ap.add_argument("--importance", type=float, default=None,
                    help="重要性评分 0-1（默认按类别/范围推断：correction 0.9 / project 0.7 / universal 0.6 / ephemeral 0.4）")
    ap.add_argument("--no-auto-link", action="store_true",
                    help="关闭 deposit 时的自动相似连边（默认开启）")
    ap.add_argument("--corrects", default="", help="新记忆推翻的旧记忆 id（自动纠错）")
    # P0 升级：deposit --why 记录决策理由（复盘可回溯）
    ap.add_argument("--why", default="", help="deposit 时记录「为什么这么定」的决策理由（存 reason 字段，复盘可回溯推理链）")
    ap.add_argument("--scope", default="", help="记忆分类 universal/project/ephemeral（留空自动初判）")
    ap.add_argument("--project", default="", help="工作专属记忆归属的项目 id（scope=project 时生效）")
    ap.add_argument("--recorded-by", default="agent", choices=["user", "agent"],
                    help="deposit：记录触发来源（默认 agent=AI 代记；user=用户原话直记），落盘 recorded_by 字段，区分主动/被动触发供审计")
    ap.add_argument("--reason", default="", help="reclassify 的理由（记录进 accessed_from）")
    ap.add_argument("--pending", action="store_true",
                    help="reclassify --pending：数据质量队列——列出缺 scene/about_axis/domain 标注的活跃记忆（只读，配 --suggest 给保守建议）")
    ap.add_argument("--type", default="",
                    help="记忆类型 BP/WF/PF/PREF/FACT/DOC：deposit 时显式指定（覆盖由 category 推导的默认类型，置 type_confidence=1.0）；reclassify 时纠正类型（留空不改）")
    ap.add_argument("--rel", default="")
    ap.add_argument("--target", default="")
    ap.add_argument("--tag")
    ap.add_argument("--domain", default="",
                    help="域过滤（investment/work/personal/project）：只召回匹配域的记忆（同域优先，互不污染热位）")
    ap.add_argument("--scene", default="",
                    help="多轴 taxonomy：场景过滤（onboarding/setup/release/incident/debugging/research/maintenance/learning/conversation/general/backtest/rebalance/premarket/intraday/postmarket），与 --domain 正交")
    ap.add_argument("--subdomain", default="",
                    help="子域过滤（如 估值/技术/资金/宏观/仓位/数据源/回测/调仓）；deposit 时设定、recall 时硬过滤，与 --domain/--scene 正交")
    ap.add_argument("--attr", action="append", default=[], metavar="K=V",
                    help="P0 deposit 时显式写入结构化指标（如 --attr pe=28.5 --attr momentum=0.82）；"
                         "与自动抽取合并，显式优先。仅 deposit 生效。")
    ap.add_argument("--filter", default="",
                    help="P0 recall 时数值/字符串过滤 DSL，如 'pe>=20 AND pe<=30 AND domain=investment'；"
                         "字段白名单、禁用 eval，安全。仅 recall 生效。")
    # ：状态机 / 优先级 / 领域（纯加性，留空则触发词典预填 → 默认值）
    ap.add_argument("--state", default="",
                    help="状态机：pending/confirmed/resolved/wont_fix（留空则触发词典/默认 pending）")
    ap.add_argument("--priority", default="",
                    help="优先级：low/normal/high/critical（留空则触发词典/默认 normal）")
    ap.add_argument("--area", default="",
                    help="领域：bugfix/feature/learning/decision（留空则触发词典/默认 learning）")
    ap.add_argument("--about-axis", default="", dest="about_axis",
                    help="四轴：user/self/relationship/world（关于谁）。与 category/area 正交；"
                         "留空则触发词典/默认 None（纯经验）。仅 deposit 生效。")
    ap.add_argument("--include-auto", action="store_true",
                    help="（向后兼容，默认已包含）召回时包含 auto_sourced(被动捕获暂存) 的记忆")
    ap.add_argument("--exclude-auto", action="store_true",
                    help="召回时显式排除 auto_sourced(被动捕获暂存) 的记忆——默认已包含，"
                         "仅当确需严格 staging 隔离（如人工 review 流程）时传此参数")
    ap.add_argument("--max-tokens", type=int, default=None,
                    help="recall：注入预算——按 token 估算裁剪结果（保留最高分直到预算用尽），AI 消费不爆上下文")
    ap.add_argument("--with-meta", action="store_true",
                    help="recall：返回随带 meta（实际后端 / 是否降级 / 空结果诊断），供 AI 感知语义降级，不必手动跑 doctor")
    ap.add_argument("--max-age-days", type=int, default=None,
                    help="freshness 过滤：只返回 created_at ≤ N 天的记忆；同时尊重 until: 标签（过期即隐藏）。"
                         "等价 filter DSL 的 fresh_within=N（仅 recall 生效）")
    ap.add_argument("--query")
    ap.add_argument("--min-tier", default="")
    ap.add_argument("--include-superseded", action="store_true",
                    help="recall：一并检索被取代记忆；export：一并导出被取代记忆"
                         "（v4.9.1 起对 export 生效，此前传了也无效——静默少导）")
    ap.add_argument("--deep", action="store_true", help="recall 时一并搜索更深子记忆（archive）")
    # 5.0/A3：双时序回溯查询——按 valid_at/invalid_at 判定「该时点上这条是否为真」，
    # 绕过 status（否则现在已 superseded 的记忆在过去时点永远查不到）。日期格式 YYYY-MM-DD。
    ap.add_argument("--as-of", dest="as_of", default=None, metavar="YYYY-MM-DD",
                    help="recall：回溯到指定日期，只返回该时点仍有效的记忆（双时序）")
    # 5.0/A3：invalidate 的双时序入参。
    # 🔴 本 parser 是【扁平单 parser】，选项名全局唯一 —— 曾在此重复定义 `--reason`
    #    （已存在于 deposit/reclassify 段）与 `--at`（已属于 schedule_reflect，且默认
    #    "03:00"）→ argparse._check_conflict 抛 ArgumentError，**整个 CLI 起不来**，
    #    所有子进程型测试级联失败（门禁 20 失败 / 1 错误）。故：
    #      · 原因复用既有 `--reason`（默认 ""，语义一致）
    #      · 时点用独立名字 `--invalid-at`，避免与 schedule_reflect 的 `--at` 撞车
    ap.add_argument("--by", default=None, metavar="ID",
                    help="invalidate：取代本条的记忆 id（写入 invalidated_by + superseded_by 边）")
    ap.add_argument("--invalid-at", dest="invalid_at", default=None, metavar="YYYY-MM-DD",
                    help="invalidate：失效时点（缺省=今天）")
    ap.add_argument("--touch", action="store_true", help="recall 命中条目时刷新其 accessed（显式记录被使用；默认不写盘）")
    ap.add_argument("--auto", action="store_true", help="reflect/promote 等自动执行安全动作（不删除；过期记忆归档 / 自主晋升合并，默认 dry-run 预览）")
    ap.add_argument("--no-auto-archive", action="store_true", help="reflect --auto 时只标记过期、不归档")
    ap.add_argument("--undo", action="store_true", help="reflect --undo：撤销 reflect --auto 的自动重分类（category/type 回滚到原值），只读安全动作")
    ap.add_argument("--at", default="03:00", help="schedule_reflect：每日运行时刻 HH:MM（默认 03:00）")
    ap.add_argument("--freq", choices=["daily", "weekly"], default="daily",
                    help="schedule_reflect：调度频率 daily/weekly（默认 daily）")
    ap.add_argument("--with-rebuild", action="store_true",
                    help="schedule_self_heal：额外排入 graph --rebuild 月度索引重建（默认不排，按需）")
    ap.add_argument("--cron", action="store_true",
                    help="schedule_self_heal --cron：改产出 systemd/cron 片段（非 WorkBuddy 环境低频自愈），替代 WB 自动化清单")
    ap.add_argument("--stale-days", type=int, default=90)
    ap.add_argument("--context-budget", type=int, default=None,
                    help="reflect/doctor 的 token 预算预警阈值（默认不检查）；total 超过则标记 context_full 并建议 reflect --auto")
    ap.add_argument("--llm", action="store_true",
                    help="reflect 时启用可选 LLM 自进化（安全版：内容冻结，仅产出合并/纠正/晋升/关联建议落盘 store/llm_suggestions.json，绝不改写记忆）；需先 reflect --llm-setup 配置端点，未配置则本开关无效并静默回退规则 reflect")
    ap.add_argument("--backend", default=None, help="llm-setup：LLM 后端 ollama|openai")
    ap.add_argument("--base-url", default=None, help="llm-setup：OpenAI 兼容端点（ollama 默认 http://localhost:11434/v1）")
    ap.add_argument("--model", default=None, help="llm-setup：模型名（ollama 默认 qwen2.5:7b；openai 默认 gpt-4o-mini）")
    ap.add_argument("--api-key-env", default=None, help="llm-setup：外部 API key 所在环境变量名（本地 ollama 留空）")
    ap.add_argument("--enable-llm", action="store_true", help="llm-setup：写入 config 启用 LLM 自进化")
    ap.add_argument("--disable-llm", action="store_true", help="llm-setup：写入 config 关闭 LLM 自进化")
    ap.add_argument("--llm-dry", action="store_true", help="llm-setup：只检测并打印推荐硬件配置要求，不写 config")
    ap.add_argument("--max-suggestions", type=int, default=None, help="llm-setup：单次 reflect --llm 最大建议条数（默认 30）")
    ap.add_argument("--batch-size", type=int, default=None, help="llm-setup：LLM 批量发送记忆元信息条数（默认 20）")
    ap.add_argument("--temperature", type=float, default=None, help="llm-setup：LLM 采样温度（默认 0.2，低温度更确定）")
    ap.add_argument("--zip", default="", help="restore 的备份 ZIP 路径")
    ap.add_argument("--max-k", type=int, default=12,
                    help="cluster 的最大簇数（默认 12，实际 k=min(max_k, √n/2) 自适应）")
    ap.add_argument("--min-size", type=int, default=8,
                    help="cluster 的最小聚类样本数（默认 8；小库可降到 2 以换取主题标签，但可靠性下降）")
    ap.add_argument("--decay-lambda", type=float, default=0.03,
                    help="decay --apply 的衰减系数 λ（默认 0.03，越大过期越快）")
    ap.add_argument("--incremental", action="store_true",
                    help="decay --apply --incremental：仅重算自上次 decay 以来被访问/改动过的记忆（大库提速）；"
                         "首次运行无基线时退化为全量。默认全量（零风险路径）")
    ap.add_argument("--min-count", type=int, default=3,
                    help="recurrence 报告 / promote --auto 的最小重复阈值（默认 3）")
    ap.add_argument("--auto-candidate", action="store_true",
                    help="recurrence：额外判定「跨≥2 任务且 30 天内」的组为晋升候选(promotion_candidate=True)")
    ap.add_argument("--review", action="store_true",
                    help="promote：列出待晋升候选（高频但低 tier/低置信）不修改任何记忆；"
                         "配合 --apply 才真晋升到 --tier 指定的目标")
    # 自主晋升/合并参数（promote --auto 复用上面的 --auto；--apply 复用 cluster 的 dry-run 反义）
    ap.add_argument("--merge", action="store_true", default=True,
                    help="promote --auto 时对重复簇自动合并（保留最佳、其余 archive；可 unarchive 找回）")
    ap.add_argument("--no-merge", dest="merge", action="store_false",
                    help="promote --auto 时只晋升不合并")
    ap.add_argument("--min-relevance", type=float, default=0.6,
                    help="promote --auto 晋升相关性阈值（relevance_score 或 importance≥此值）")
    ap.add_argument("--min-access", type=int, default=5,
                    help="promote --auto 晋升最小访问次数")
    ap.add_argument("--min-age-days", type=int, default=30,
                    help="promote --auto 晋升最小龄期（天），避免刚记的就固化")
    ap.add_argument("--apply", action="store_true",
                    help="reclaim（归档清理）时把上一轮已报告过的候选**归档**（软保留，绝不删除文件；"
                         "默认 dry-run 只报告候选，不归档任何文件；须显式 --apply，"
                         "任何自动化脚本不得自动带此参数）")
    ap.add_argument("--ann", action="store_true",
                    help="recall --query 时启用可选 ANN 近邻加速（索引**持久化**到磁盘，数据变更自动重建；"
                         "需 numpy，装 hnswlib 则用 store/ann.idx 加速、未装回退 numpy 落盘索引；结果不变）")
    ap.add_argument("--no-ann", dest="no_ann", action="store_true",
                    help="显式关闭 ANN 近邻加速（覆盖默认的『库≥AI_MEM_ANN_MIN_MEMORIES 自动启用』），"
                         "退回全量线性扫描——用于需要 100%% 穷举候选的场景")
    # 归档清理（reclaim）参数：对归档/被取代记忆做受控**归档**（软保留，绝不删除）
    ap.add_argument("--ttl-days", type=int, default=180,
                    help="reclaim：归档/被取代记忆的沉淀存活期（天），默认 180；超龄且未豁免才候选归档")
    ap.add_argument("--min-importance", type=float, default=0.4,
                    help="reclaim：重要性低于此值的软删记忆才候选归档（core 层/保护标签/未过期 until 仍豁免）")
    ap.add_argument("--quota-archived", type=int, default=300,
                    help="reclaim：归档记忆容量配额，超出后最老的被归档（环形覆盖），默认 300")
    ap.add_argument("--quota-superseded", type=int, default=300,
                    help="reclaim：被取代记忆容量配额，超出后最老的被归档，默认 300")
    ap.add_argument("--max-purge", type=int, default=200,
                    help="reclaim：单次最多归档条数，防止一次归档太多（默认 200；注意：归档≠删除）")
    ap.add_argument("--no-staging", action="store_true",
                    help="reclaim：不清理超时未晋级的 auto_sourced 暂存记忆（默认清理，满 365 天）")
    ap.add_argument("--staging-ttl-days", type=int, default=365,
                    help="reclaim：auto_sourced 暂存记忆超此天数未晋级则候选清理（默认 365）")
    ap.add_argument("--include-quarantine", action="store_true",
                    help="reclaim：把超时未复审的隔离候选**列入报告的保护项**（默认【关】；"
                         "隔离属安全缓冲，绝不自动归档，需手动 review_quarantine 决议）")
    ap.add_argument("--quarantine-ttl-days", type=int, default=365,
                    help="reclaim：隔离候选超此天数未复审则列入报告保护项（默认 365，需 --include-quarantine 开启）")
    ap.add_argument("--no-mirror", action="store_true",
                    help="reclaim：归档后不刷新 IMA 知识库导出（默认会生成带【归档】标记的镜像，供跨设备检索）")
    ap.add_argument("--cluster-boost", action="store_true",
                    help="recall --query 时启用聚类召回增强（#6→recall）：query 找最近主题簇，该簇成员增持分+放宽阈值；未跑过 cluster 则自动无效")
    # P0 升级：关系图谱扩跳 + 答案合成
    ap.add_argument("--hops", type=int, default=0,
                    help="recall --query 时沿记忆关系(related_to/supports/refutes)扩跳 N 跳，关联记忆加权追加到召回尾部")
    ap.add_argument("--answer", action="store_true",
                    help="recall --query 时启用答案合成 RAG：HyDE 改写→召回→LLM 带引用合成答案；"
                         "无 LLM 自动退回普通列表（零回归）")
    ap.add_argument("--top-n", type=int, default=10,
                    help="token-report 列出的 Top-N 最重记忆条数（默认 10）")
    ap.add_argument("--dry-run", action="store_true", help="危险操作(delete/overwrite/archive/reclassify/link/restore/forget)只预览会动哪些文件，不执行")
    ap.add_argument("--suggest", action="store_true",
                    help="reclassify --pending：对缺轴条目给出保守场景建议（命中明确关键词才给，仅提示不写盘）")
    ap.add_argument("--progress", action="store_true",
                    help="backup：打印备份体积预估与逐文件进度到 stderr（不影响 stdout 的 JSON 结果，CI 不污染）")
    # ：敏感隔离复审（CLI 化，使 AI 对话也能触发；此前仅为内部 Python API）
    ap.add_argument("--action", default="release",
                    help="review_quarantine：release(脱敏放行入活跃库)/purge(删除隔离文件)/keep(标记已复审保留)")
    ap.add_argument("--no-redact", action="store_true",
                    help="review_quarantine --action release 时关闭敏感片段脱敏（默认脱敏替换 ***）")
    # ：行为规则层（export-rules/hot-rules/import-rules）目标文件
    # ：行为规则层（export-rules/hot-rules/import-rules）目标文件（--target 已被 link 占用）
    # ：新增 `text` —— 完全自定义路径（配 --out <绝对路径>），避开所有平台耦合，
    # 给不想让规则自动溢出到 Copilot/Claude 的项目（合规/隐私/不想被加载）一个保险出口。
    ap.add_argument("--rules-target", default="project",
                    choices=["project", "user", "copilot", "claude", "text"],
                    help="export-rules/import-rules 目标："
                         "project=./AGENTS.md（可提交 git）/ "
                         "user=~/.workbuddy/AGENTS.md（全局）/ "
                         "copilot=./.github/copilot-instructions.md（Microsoft/GitHub 官方 Copilot 指令位置，平台自动加载）/ "
                         "claude=./CLAUDE.md（Anthropic 官方 Claude Code 约定，平台自动加载）/ "
                         "text=--out 指定的任意路径（keeper 自有，无平台耦合）")
    # ：轻量零依赖路径（与 SQLite 互斥）
    ap.add_argument("--flat", action="store_true",
                    help="轻量路径：跳过 SQLite 与 LLM，全部落 ~/.workbuddy/memory/keeper_flat.md 纯文本 grep 召回")
    ap.add_argument("--yes", action="store_true", help="危险操作不再打印提示警告（确认已明确知晓后果）")
    # ：backup --keep —— 备份保留 N 份，更旧的**搬**进同级 _retired_backups_<日期>/（只搬不删）
    ap.add_argument("--keep", type=int, default=None,
                    help="backup：只保留最近 N 份整库备份（含本次），更旧的**搬**进同级 "
                         "_retired_backups_<日期>/（不删除、可逆）；不传则不清理，行为与旧版一致")
    # ：release-audit --offline —— 不联网核对，明确报「未知」而不是误判不一致
    ap.add_argument("--offline", action="store_true",
                    help="release-audit：不联网，只报本地版本账状态（verdict=unknown）；"
                         "网络不可用时不加此参数亦可——会被识别为「未知」而非「不一致」")
    ap.add_argument("--verify", action="store_true",
                    help="restore：仅校验备份完整性（manifest sha256 比对），不提取、不动当前库")
    ap.add_argument("--force", action="store_true",
                    help="restore：跳过完整性校验中止（明知备份损坏仍要恢复部分文件，不推荐）；"
                         "self-heal：忽略 dirty 节奏强制跑完整循环")
    ap.add_argument("--discover", action="store_true",
                    help="self-heal --discover：循环末尾发现已达标(≥min_count)但未被任何已注册 skill 覆盖的 area 集群，"
                         "自动建 <root>/skills/auto/<area>-patterns 并登记 registry（保守，仅 --discover 显式开启）")
    ap.add_argument("--fix", action="store_true", help="doctor 自检后自动修复：同步 index 状态/剪枝悬空关系/移除无文件索引条目（不删记忆内容）")
    # A2 ：O4 损坏记忆隔离区修复/还原回路（corrupt/ 不再是单向死胡同）
    ap.add_argument("--repair", action="store_true",
                    help="doctor --repair：尝试 best-effort 修复 corrupt/ 里损坏的记忆 JSON（尾逗号/控制字符/截断），"
                         "修复成功接回 memories/ 并从 corrupt/ 移除；修复失败保留原地等人工处理")
    ap.add_argument("--restore", metavar="FILE", default=None,
                    help="doctor --restore <file.json>：把 corrupt/ 里指定文件（已人工修好或误隔离）直接接回 memories/；"
                         "接回后做 JSON 合法性校验，不合法则警告并保留在 corrupt/")
    ap.add_argument("--contradictions", action="store_true",
                    help="doctor 额外跑主动矛盾/重复扫描（共享标签/品牌/主体预筛 + embedding 语义比对 + 对立信号词标记，供裁决；--fix 时软标记 relations.conflict）")
    # P0 升级：矛盾自动仲裁——强矛盾对按「较新+较高置信」自动 supersede 旧条（只标不删，留版本链）
    ap.add_argument("--arbitrate", action="store_true",
                    help="doctor --contradictions --fix --arbitrate：对强矛盾对自动把旧/低置信条标 superseded（只标不删，可 rollback）；"
                         "需同时带 --contradictions --fix")
    # P0 升级：graph 子命令的动作开关（graph --build 自动推断关系边）
    ap.add_argument("--build", action="store_true",
                    help="graph --build：扫描全库自动推断 supports/refutes/is_a/part_of 关系边（幂等，只标不删）")
    ap.add_argument("--clean", action="store_true",
                    help="graph --clean：仅清理关系键中指向已删除记忆的悬空引用（不删记忆文件）")
    ap.add_argument("--rebuild", action="store_true",
                    help="graph --rebuild：清理悬空引用 + 清空图衍生边 + 重算（干净重算，消除历史 noise 边）")
    ap.add_argument("--json", action="store_true",
                    help="doctor：在结果中附带 health 状态（ok/warn/error）并按健康度设置退出码（CI 巡检用）；默认输出不变以兼容既有调用")
    ap.add_argument("--low-confidence", action="store_true",
                    help="doctor 额外列出 scene_confidence<0.7 或 scene_via=='rule' 的记忆（问题①B档：自动分类非权威，供周六维护复核）")
    # 4.9.13：调度探测结果缓存 24h 用于降噪；改了系统限制后需要一条「立刻看真结果」的路
    ap.add_argument("--no-cache", action="store_true",
                    help="doctor：跳过调度探测缓存、直连探测——刚改过系统限制"
                         "（解除程序黑名单 / 换机器 / 改 PATH）后想立刻看真实结果时用；"
                         "不加则最多复用 24h 内的旧探测结论")
    # 2026-09-15 审计：doctor 建议项 ack 抑制（治「告警疲劳」——同一批建议每轮刷屏会淹没真信号）
    ap.add_argument("--ack-all", action="store_true",
                    help="doctor：展开全部建议项（含已 ack 确认过的）；默认只显示未确认的")
    ap.add_argument("--ack", metavar="KIND:ID", default="",
                    help="doctor --ack <kind>:<id>：把某条建议标记为「已知悉」，后续默认不再显示。"
                         "kind 可用：link / contradiction / adjacent / scope / type / scene / invariant")
    ap.add_argument("--ack-reason", default="",
                    help="doctor --ack 时附带的确认理由（便于日后回溯「当初为什么抑制它」）")
    ap.add_argument("--ack-list", action="store_true",
                    help="doctor --ack-list：列出全部 ack 记录（含是否已过期、已抑制天数）")
    ap.add_argument("--ack-clear", action="store_true",
                    help="doctor --ack-clear：清空全部 ack 抑制（一键让所有建议重新显示）")
    ap.add_argument("--out", default="",
                    help="多命令复用：dashboard 输出 HTML 路径 / export 导出文件或目录 / "
                         "export-rules --rules-target text 时为规则文件写入路径（必填，否则 text 模式不可用）")
    ap.add_argument("--out-dir", default="auto_skill",
                    help="extract-skill：脚手架输出目录（默认 auto_skill）；生成 SKILL.md + references/ + hooks/ + README.md")
    ap.add_argument("--format", default="md", choices=["md", "jsonl", "learnings"],
                    help="export：导出格式 md（默认，Markdown，人读）/ jsonl（每行一 JSON，便于程序处理）/ learnings（标准化可读条目，--out 指向目录时每条记忆一文件，git 可共享）")
    ap.add_argument("--include-archived", action="store_true",
                    help="export：包含已归档 + 被取代记忆（默认仅 active，等价于全量导出）")
    # #9 harvest / feedback（自主进化）
    ap.add_argument("--text", default=None, help="harvest：直接传会话文本做学习点抽取")
    ap.add_argument("--session", default=None, help="harvest：读取会话摘要文件做学习点抽取")
    ap.add_argument("--from-conversations", action="store_true",
                    help="harvest：从 WorkBuddy 历史会话沉淀（AI 编排工作流）。需先在 WB 会话中用 conversation_search 按回溯窗口（默认最近 30 天）检索历史会话、整理为文本文件，再 harvest --from-conversations --session <file>。会话来源记忆打 wb_session 标签并做幂等去重，避免回声/重复沉积")
    ap.add_argument("--self-learn", action="store_true",
                    help="harvest：只读全部 active 记忆 body 做跨记忆深层学习（矛盾/合成/抽取），绝不回写 body")
    ap.add_argument("--max-items", type=int, default=10, help="harvest：单次最多沉积/建议条数（默认 10）")
    ap.add_argument("--signal", choices=["good", "bad"], default=None,
                    help="feedback / recall --outcome：正负反馈信号（自主置信校准）")
    ap.add_argument("--weight", type=float, default=1.0, help="feedback：信号权重（默认 1.0）")
    ap.add_argument("--outcome", choices=["good", "bad"], default=None,
                    help="recall --id 时附带正负反馈（good 升 / bad 降 置信），走 Beta 校准")
    ap.add_argument("--auto-llm", action="store_true",
                    help="harvest：强制启用 LLM 抽取（即便 config 未开）；未配置端点则回退规则")
    ap.add_argument("--no-llm", action="store_true",
                    help="harvest/converse：强制纯规则模式（不调用 LLM，免费、确定性）；用于自动化/后台任务避免意外成本与延迟")
    ap.add_argument("--no-workbuddy", action="store_true",
                    help="harvest --self-learn：关闭与 WorkBuddy 原生记忆打通（默认即关，需显式 --with-workbuddy 才读取 ~/.workbuddy/MEMORY.md + 工作区 .workbuddy/memory/*.md）")
    ap.add_argument("--workbuddy-memory", default=None,
                    help="harvest --self-learn：指定 WorkBuddy 记忆目录（默认自动发现 ~/.workbuddy/MEMORY.md 与工作区 .workbuddy/memory）")
    # #10 converse（对话内自主沉淀，无需自动化）
    ap.add_argument("--end", action="store_true",
                    help="converse：声明本对话收尾，立即触发自学习+自整理（无视轮次）")
    ap.add_argument("--rounds", type=int, default=None,
                    help="converse：本次临时覆盖阈值（不持久化）；默认用 _round_state.json 里用户设定的 threshold")
    ap.add_argument("--set-threshold", type=int, default=None,
                    help="converse：把『每 N 轮自动沉淀+自学习+自整理』的阈值设为 N 并持久化（默认 10）；用户用自然语言让 agent 调用它即可随时改几十/几百轮")
    ap.add_argument("--with-workbuddy", action="store_true",
                    help="converse：开启与 WorkBuddy 原生记忆打通（默认关，避免盲目复制 WB 记忆污染本地库）；默认仅沉淀对话要点")
    # ：智能进化 / 互补协同 参数（--apply 为全局共享标志，复用既有定义）
    ap.add_argument("--duckdb", default=None,
                    help="verify-investment：DuckDB 数据库路径（提供则从库复算数值校验投资记忆）")
    ap.add_argument("--sql-map", default=None,
                    help="verify-investment：metric→SQL 映射 JSON 文件路径（每个 metric 对应一条返回单值的 SQL）")
    ap.add_argument("--forget-reason", default="",
                    help="forget：判错 / 遗忘理由（记入 accessed_from 审计）")
    ap.add_argument("--download-models", action="store_true",
                    help="init：建库后立即预下载中文语义模型（fastembed），避免首次 recall 被动等待。需已 pip install fastembed。")
    # ：批量导入 / 性能基准 / MCP 服务 参数
    ap.add_argument("--file", default=None,
                    help="import：待导入文件路径（JSONL/JSON/CSV/MD）")
    ap.add_argument("--import-format", default="auto",
                    choices=["auto", "jsonl", "json", "csv", "md"],
                    help="import：文件格式（默认 auto 按扩展名/内容嗅探）")
    ap.add_argument("--execute", action="store_true",
                    help="import：真实写入记忆库（默认仅 dry-run 预览，不写库）")
    ap.add_argument("--keep-ids", action="store_true",
                    help="import：复用记录原 id（默认新生成，避免跨库冲突）")
    ap.add_argument("--on-error", choices=["skip", "abort"], default="skip",
                    help="import：遇坏行/坏记录策略（默认 skip 跳过继续）")
    ap.add_argument("--report", default=None,
                    help="import：逐条结果 JSON 报告输出路径")
    ap.add_argument("--n", type=int, default=200,
                    help="benchmark：合成记忆条数（默认 200）")
    ap.add_argument("--recall-times", type=int, default=50,
                    help="benchmark：recall 次数（默认 50）")
    ap.add_argument("--topics", type=int, default=20,
                    help="benchmark：topic 数量空间（默认 20）")
    args = ap.parse_args()
    # F5 修复：位置参数 id 作为 --id 回退，兼容 `delete LRN-001 --yes` 等自然写法。
    if not args.id and args.op_id:
        args.id = args.op_id
    if args.body_file:
        with open(args.body_file, encoding="utf-8") as bf:
            args.body = bf.read()

            # ：装完 skill 首次使用时自动注册会话钩子（根治「易忘点」；KEEPER_AUTO_INSTALL_HOOKS=0 关闭）
    _ensure_hooks()

    # ：MCP 服务是长驻进程，必须在 store 锁之外运行——否则会永久持有跨进程文件锁，
    # 导致服务内部 deposit/recall 自锁死。直接从引擎命名空间拉起，不经过 _store_lock。
    if args.op == "mcp":
        mcp_serve(args.root)
        return

    try:
        # 5.0.0：旧加密库 fail-closed 守卫 —— **CLI 层统一收口点**（在拿任何锁之前）。
        # 为什么不逐 op 设防：① 批处理型命令（import/evolve）会把「逐条异常」吞成
        #   `{"ok": false}` 却仍 `rc=0`，用户与自动化无法据此判断「整库不可用」，
        #   必须让它在 dispatch 层就被拦下；② 在 `_store_lock` 之前拒绝，
        #   顺带避免「被拒命令仍写下 memories/.write_lock」这类无谓副作用。
        # 例外（只读/不碰本库数据的命令，放行属正确）：quickstart/commands/release-audit
        #   （纯帮助或版本对账）、backup（存外归档，迁移前正需要它）、init（幂等建目录）、
        #   mcp（在上一行已 return）、以及 `deposit --flat`（写的是 flat 区，根本不碰本库）。
        _flat_deposit = (args.op == "deposit" and getattr(args, "flat", False))
        if args.op not in _LEGACY_GUARD_EXEMPT_OPS and not _flat_deposit:
            assert_not_legacy_encrypted(args.root, op="执行命令 %s" % args.op)
        with _store_lock(args.root):  # 跨进程串行化可变操作，避免多窗口并发写竞争
            if args.op == "deposit":
                # 轻量路径：--flat 短路，完全不碰 SQLite
                if args.flat:
                    from flat_mode import flat_add
                    r = flat_add(args.summary, args.tags, args.body,
                                 area=args.area or "learning",
                                 priority=args.priority or "normal",
                                 state=args.state or "pending")
                    print(json.dumps(r, ensure_ascii=False)); return 0
                    # P0（3.9.x）：把 --attr K=V 解析为 dict（非法格式报错并退出）
                _explicit_attrs = {}
                for kv in (args.attr or []):
                    if "=" not in kv:
                        print(json.dumps({"ok": False, "error": "--attr 需为 K=V 格式: %s" % kv}, ensure_ascii=False))
                        return 1
                    k, v = kv.split("=", 1)
                    k = _norm_attr_key(k)
                    if k.isdigit() or k in _ATTR_BLACKLIST_TOKEN:
                        print(json.dumps({"ok": False, "error": "--attr 键须为指标名，不接受纯数字/日期类键: %s" % kv}, ensure_ascii=False))
                        return 1
                    try:
                        _explicit_attrs[k] = float(v.strip())
                    except ValueError:
                        print(json.dumps({"ok": False, "error": "--attr 值需为数字: %s" % kv}, ensure_ascii=False))
                        return 1
                        # ：state/priority/area 留空转 None，交由 _deposit_impl 触发词典自动预填
                mid = deposit(args.root, args.category, args.summary, args.tags, args.body,
                             args.id, tier=args.tier or "working",
                             confidence=args.confidence, inferred=args.inferred,
                             importance=args.importance, corrects=args.corrects or None,
                             scope=args.scope or None, project=args.project,
                             auto_link=not args.no_auto_link,
                             recorded_by=args.recorded_by,
                             scene=args.scene or None,
                             subdomain=args.subdomain or None,
                             domain=args.domain or None,
                             attrs=_explicit_attrs or None,
                             state=args.state or None,
                             priority=args.priority or None,
                             area=args.area or None,
                             about_axis=args.about_axis or None,
                             mem_type=args.type or None,
                             sensitive_action="quarantine")
                # deposit 命中敏感时返回结构化 dict（{ok:False, quarantined:True, qid,...}），
                # 直接透传；正常写入返回字符串 id。绝不可把 dict 当 id 塞进 {"ok":True}（会误报成功）。
                if isinstance(mid, dict):
                    print(json.dumps(mid, ensure_ascii=False))
                else:
                    # P0 升级：deposit --why 记录决策理由（复盘可回溯推理链）
                    if args.why and isinstance(mid, str):
                        try:
                            _m, _ = _load_mem(args.root, mid)
                            _m["reason"] = args.why
                            _save_mem(args.root, mid, _m)
                        except Exception:
                            pass
                            # P2：附上 embedding 后端状态，让用户知道这条记忆的召回质量是真·语义还是降级词法
                    print(json.dumps({"ok": True, "id": mid,
                                      "embedding_status": _embedding_status_label()},
                                     ensure_ascii=False))
            elif args.op == "export-rules":
                # 行为规则层：选条目 → 固化进 AGENTS.md（自动生成区块，可回滚）
                # ：--rules-target text 时 --out <路径> 必填；其它目标忽略 --out
                if args.rules_target == "text" and not args.out:
                    print(json.dumps({"ok": False,
                                      "error": "missing_arg",
                                      "message": "--rules-target text 需要 --out <路径> 指定写入位置"},
                                     ensure_ascii=False))
                    sys.exit(2)
                from promote_rules import export_rules
                r = export_rules(args.root, target=args.rules_target,
                                 area=args.area or None, state=args.state or None,
                                 priority=args.priority or None,
                                 filter_str=args.filter or None,
                                 min_count=args.min_count, dry_run=args.dry_run,
                                 out_path=(args.out or None))
                print(json.dumps(r, ensure_ascii=False))
            elif args.op == "hot-rules":
                # ：列出 recurrence≥阈值 的高频条目（候选固化）
                from promote_rules import hot_rules
                sel = hot_rules(args.root, min_count=args.min_count)
                print(json.dumps({"ok": True, "count": len(sel), "items": sel}, ensure_ascii=False))
            elif args.op == "import-rules":
                # ：AGENTS.md 自动区块逆向回灌 SQLite（仅新条目 deposit）
                # ：--rules-target text 时 --out <路径> 必填
                if args.rules_target == "text" and not args.out:
                    print(json.dumps({"ok": False,
                                      "error": "missing_arg",
                                      "message": "--rules-target text 需要 --out <路径> 指定读取位置"},
                                     ensure_ascii=False))
                    sys.exit(2)
                from promote_rules import import_rules
                r = import_rules(args.root, target=args.rules_target,
                                 dry_run=args.dry_run,
                                 out_path=(args.out or None))
                print(json.dumps(r, ensure_ascii=False))
            elif args.op == "extract-skill":
                # 把高频/已确认记忆萃取成可复用 skill 脚手架：生成 SKILL.md + references/ + hooks/ + README.md
                from skill_extract import extract
                r = extract(args.root, min_count=args.min_count,
                            out_dir=args.out_dir, llm=args.llm)
                print(json.dumps(r, ensure_ascii=False))
            elif args.op == "list_quarantine":
                # ：敏感隔离候选列表（CLI 化，使 AI 对话也能触发复审）
                recs = list_quarantine(args.root)
                print(json.dumps({"ok": True, "count": len(recs), "items": recs}, ensure_ascii=False))
            elif args.op == "review_quarantine":
                # ：隔离复审 release/purge/keep（默认脱敏放行）
                if not args.id:
                    print(json.dumps({"ok": False, "error": "missing_id",
                                      "msg": "review_quarantine 需要 --id（隔离候选 qid，用 list_quarantine 查）"},
                                     ensure_ascii=False))
                    sys.exit(2)
                r = review_quarantine(args.root, args.id, action=args.action,
                                     redact=not args.no_redact)
                print(json.dumps({"ok": True, **r}, ensure_ascii=False))
            elif args.op == "init":
                init_store(args.root)
                download_ok = None
                download_msg = ""
                if args.download_models:
                    try:
                        # ：预触发 embedding 后端，把模型下载放到 init 阶段完成。
                        # 关键修复：--download-models 必须强制 fastembed 后端（而非继承当前 lexical），
                        # 否则 lexical 下 _emb_backend 直接返回词法级、根本不触碰模型却谎报"已预触发"。
                        # 强制后走离线捆绑模型（skill/models/，_ensure_fastembed_offline_cache）
                        # 或首次联网下载；任一失败即诚实报 download_ok=False，不掩盖。
                        os.environ["AI_MEM_EMBED_BACKEND"] = "fastembed"
                        _ = _emb_backend()
                        # 诚实验证：后端初始化 ≠ 模型可用。空捆绑模型/未装 fastembed 时
                        # _emb_backend 仍可能返回（惰性），故实际试算一次 embed；
                        # 失败（模型缺失/下载失败）即诚实报 download_ok=False，不掩盖。
                        import embed as _emb_mod
                        _emb_mod.embed("__verify_model_load__")
                        download_ok = True
                        download_msg = "已预触发语义模型下载/加载（fastembed）。"
                    except Exception as e:
                        download_ok = False
                        download_msg = "预下载模型失败（可能未装 fastembed 或离线捆绑模型缺失）：%s" % e
                out = {"ok": True, "store": args.root,
                       "note": "记忆目录已就绪，零配置开箱即用。你不用手动敲命令——"
                               "用自然语言告诉 AI「记一下…/整理一下今天记的」即可，"
                               "它会自动调用本技能。改路径设 AI_MEMORY_STORE 环境变量。"}
                if download_ok is not None:
                    out["download_models"] = {"ok": download_ok, "message": download_msg}
                print(json.dumps(out, ensure_ascii=False))
            elif args.op == "commands":
                print(json.dumps(list_commands(), ensure_ascii=False))
            elif args.op == "quickstart":
                print(json.dumps({"ok": True, "text": quickstart_text()}, ensure_ascii=False))
            elif args.op == "recall" and getattr(args, "roots", None):
                # 多库交叉召回（--roots a,b）
                rows = recall_multi(args.roots, query=args.query, top_n=args.top,
                                    max_tokens=args.max_tokens,
                                    include_auto=not args.exclude_auto,
                                    semantic_gate=getattr(args, "semantic_gate", None))
                print(json.dumps({"ok": True, "count": len(rows), "entries": rows,
                                  "multi_root": True}, ensure_ascii=False))
            elif args.op == "recall":
                # 轻量路径：--flat 短路，走纯文本 grep
                if args.flat:
                    from flat_mode import flat_recall
                    items = flat_recall(args.query or "")
                    print(json.dumps({"ok": True, "count": len(items), "items": items},
                                     ensure_ascii=False)); return 0
                    # P0（3.9.x）：解析 --filter DSL（解析失败报错并退出，不静默忽略）
                _filter_clauses = None
                if args.filter and args.filter.strip():
                    try:
                        _filter_clauses = parse_filter(args.filter)
                    except ValueError as fe:
                        print(json.dumps({"ok": False, "error": "filter 语法错误: %s" % fe}, ensure_ascii=False))
                        return 1
                res = recall(args.root, mid=args.id, tag=args.tag, category=args.category,
                             query=args.query, tier=args.tier or None,
                             min_tier=args.min_tier or None,
                             include_superseded=args.include_superseded,
                             scope=args.scope or None, project=args.project or None,
                             deep=args.deep, touch=args.touch,
                             ann=args.ann or (not args.no_ann),  # O2 (4.5.44)：默认自动启用 ANN（库≥阈值且后端可用时），--no-ann 可关
                             cluster_boost=args.cluster_boost, outcome=args.outcome,
                             domain=args.domain or None, scene=args.scene or None,
                             subdomain=args.subdomain or None,
                             filter_clauses=_filter_clauses,
                             include_auto=not args.exclude_auto,
                             about_axis=args.about_axis,
                             hops=args.hops, max_tokens=args.max_tokens,
                             with_meta=args.with_meta, as_of=args.as_of)
                # A：with_meta 时 recall 返回 {"results":..., "meta":...}（dict），
                # 这里归一化为纯列表 res + 可选 _meta，后续 freshness/answer 逻辑零回归。
                _meta = None
                if isinstance(res, dict) and "results" in res:
                    _meta = res.get("meta")
                    res = res["results"]
                # freshness 过滤：--max-age-days + until: 标签过期双闸门
                if args.max_age_days is not None:
                    _today_d = datetime.date.fromisoformat(today())
                    _max = _today_d - datetime.timedelta(days=args.max_age_days)
                    def _is_fresh(e):
                        ca = e.get("created_at") or e.get("file", "")
                        from datetime import date as _d
                        try:
                            if isinstance(ca, str) and len(ca) >= 10 and ca[4] == "-":
                                _dt = _d.fromisoformat(ca[:10])
                            else:
                                import re as _re
                                fm = _re.search(r"LRN-(\d{8})", str(ca))
                                _dt = _d.fromisoformat("%s-%s-%s" % (fm.group(1)[:4], fm.group(1)[4:6], fm.group(1)[6:8])) if fm else None
                            if _dt is not None and _dt < _max:
                                return False
                        except Exception:
                            pass
                            # until: 标签过期检查（兼容 2026Q4 / / 2026-12-31）
                        for t in (e.get("tags") or []):
                            if isinstance(t, str) and t.startswith("until:"):
                                _exp = t[6:].strip()
                                try:
                                    if len(_exp) == 7 and _exp[4] == "Q":
                                        _y, _q = int(_exp[:4]), int(_exp[6:])
                                        _exp_dt = _d(_y, 12, 31) if _q == 4 else _d(_y, _q * 3, 1) - datetime.timedelta(days=1)
                                    elif "." in _exp:
                                        _exp_dt = _d.fromisoformat(_exp.replace(".", "-"))
                                    else:
                                        _exp_dt = _d.fromisoformat(_exp)
                                    if _exp_dt < _today_d:
                                        return False
                                except Exception:
                                    pass
                        return True
                    if res:
                        res = [e for e in res if _is_fresh(e)]
                        # P0 升级：答案合成 RAG（recall --answer）。无 LLM 自动退回普通列表。
                if args.answer and args.query:
                    try:
                        from p0_upgrade import answer_synthesis
                        _llm_callable, _ = _resolve_llm(args.root, None)
                        _ans = answer_synthesis(args.root, args.query, llm=_llm_callable,
                                                hops=args.hops, entries=res)
                        print(json.dumps(_ans, ensure_ascii=False))
                    except Exception as _ae:
                        print(json.dumps({"ok": True, "count": len(res), "entries": res,
                                         "answer_error": str(_ae),
                                         **({"meta": _meta} if _meta else {})}, ensure_ascii=False))
                else:
                    print(json.dumps({"ok": True, "count": len(res), "entries": res,
                                     **({"meta": _meta} if _meta else {})}, ensure_ascii=False))
            elif args.op == "decay":
                r = decay_apply(args.root, lambda_=args.decay_lambda,
                                dry_run=not args.apply, incremental=args.incremental)
                print(json.dumps(r, ensure_ascii=False))
            elif args.op == "recurrence":
                r = recurrence_report(args.root, min_count=args.min_count,
                                      auto_candidate=args.auto_candidate,
                                      window_days=30)
                print(json.dumps(r, ensure_ascii=False))
            elif args.op == "overwrite":
                r = overwrite(args.root, args.id, summary=args.summary, body=args.body,
                              tags=args.tags, tier=args.tier or None,
                              dry_run=args.dry_run, yes=args.yes)
                if isinstance(r, dict) and r.get("dry_run"):
                    print(json.dumps(r, ensure_ascii=False))
                else:
                    print(json.dumps({"ok": True, "id": args.id}, ensure_ascii=False))
            elif args.op == "rollback":
                r = rollback(args.root, args.id, args.to_version,
                             dry_run=args.dry_run, yes=args.yes)
                if isinstance(r, dict) and r.get("dry_run"):
                    print(json.dumps(r, ensure_ascii=False))
                else:
                    print(json.dumps({"ok": True, **r}, ensure_ascii=False))
            elif args.op == "versions":
                vs = versions(args.root, args.id)
                print(json.dumps({"ok": True, "id": args.id, "versions": vs}, ensure_ascii=False))
            elif args.op == "delete":
                # 硬确认门：delete 是不可逆的物理删除。CLI 下既不 --dry-run
                # 也不 --yes 时**拒绝执行**（exit 7），避免终端手滑误删。与 sandbox-builder
                # 的「外部路径需 --yes」保持一致的安全网。函数级 delete 不变（测试/
                # 编排层直接调用时按原语义执行）。带 --yes 代表已明确确认；带 --dry-run
                # 仅预览会删哪些文件。
                if not args.dry_run and not args.yes:
                    print(json.dumps({
                        "ok": False, "error": "confirm_required",
                        "msg": "delete 是不可逆的物理删除，已拒绝执行。",
                        "hint": "确认要删除请加 --yes（代表你已明确知晓且确认此操作）；"
                                "想先看看会删哪些文件，加 --dry-run。误删可用系统/网盘"
                                "文件历史找回，或先 recall --id %s 把内容存一份再删。" % args.id,
                    }, ensure_ascii=False))
                    sys.exit(7)
                r = delete(args.root, args.id, dry_run=args.dry_run, yes=args.yes)
                if isinstance(r, dict) and r.get("dry_run"):
                    print(json.dumps(r, ensure_ascii=False))
                else:
                    print(json.dumps({"ok": True, "id": args.id}, ensure_ascii=False))
            elif args.op == "archive":
                r = archive(args.root, args.id, dry_run=args.dry_run, yes=args.yes)
                if isinstance(r, dict) and r.get("dry_run"):
                    print(json.dumps(r, ensure_ascii=False))
                else:
                    print(json.dumps({"ok": True, "id": args.id, "status": "archived"}, ensure_ascii=False))
            elif args.op == "unarchive":
                unarchive(args.root, args.id)
                print(json.dumps({"ok": True, "id": args.id, "status": "active"}, ensure_ascii=False))
            elif args.op == "invalidate":
                # 5.0/A3 软失效：置 invalid_at/invalidated_by（不删不搬），status→superseded
                # 注意用 --invalid-at（不是 schedule_reflect 的 --at，后者默认 "03:00"）
                r = invalidate(args.root, args.id, by=args.by, reason=args.reason,
                               at=args.invalid_at, dry_run=args.dry_run)
                print(json.dumps(r, ensure_ascii=False))
            elif args.op == "uninvalidate":
                r = uninvalidate(args.root, args.id, dry_run=args.dry_run)
                print(json.dumps(r, ensure_ascii=False))
            elif args.op == "rebuild":
                # 5.0：rebuild 现在顺带回收派生文件幽灵键（route_registry / recall_counts /
                # maintenance_dirty / clusters），返回体里带 pruned 明细。
                print(json.dumps(rebuild(args.root, return_report=True), ensure_ascii=False))
            elif args.op == "reclaim":
                # 归档清理 起软保留，绝不删除）：默认 dry-run 只报告；--apply 才归档已报告候选
                r = reclaim(args.root, ttl_days=args.ttl_days,
                            importance_floor=args.min_importance,
                            quota_archived=args.quota_archived,
                            quota_superseded=args.quota_superseded,
                            max_archive=args.max_purge,
                            include_staging=not args.no_staging,
                            staging_ttl_days=args.staging_ttl_days,
                            include_quarantine=args.include_quarantine,
                            quarantine_ttl_days=args.quarantine_ttl_days,
                            mirror_ima=not args.no_mirror,
                            dry_run=not args.apply)
                print(json.dumps(r, ensure_ascii=False))
            elif args.op == "link":
                r = link(args.root, args.id, args.rel, args.target,
                         dry_run=args.dry_run, yes=args.yes)
                if isinstance(r, dict) and r.get("dry_run"):
                    print(json.dumps(r, ensure_ascii=False))
                else:
                    print(json.dumps({"ok": True, "id": args.id, "rel": args.rel, "target": args.target}, ensure_ascii=False))
            elif args.op == "promote":
                if args.review:
                    # 列出候选晋升条目（高频但未分类/低置信/够老但不晋升），不修改任何记忆
                    # 配合 --apply 才会真正执行晋升（按 --tier 目标）
                    cands = promote_candidates(args.root, min_recurrence=args.min_count,
                                               min_relevance=args.min_relevance,
                                               min_access=args.min_access,
                                               min_age_days=args.min_age_days)
                    if args.apply:
                        # review + apply：把所有候选晋升到目标 tier
                        results = []
                        for c in cands:
                            try:
                                promote(args.root, c["id"], args.tier or "curated")
                                results.append({"id": c["id"], "tier": args.tier or "curated", "ok": True})
                            except Exception as ex:
                                results.append({"id": c["id"], "ok": False, "error": str(ex)})
                        print(json.dumps({"ok": True, "mode": "review+apply",
                                          "applied": len(results), "results": results,
                                          "tier": args.tier or "curated"}, ensure_ascii=False))
                    else:
                        print(json.dumps({"ok": True, "mode": "review", "count": len(cands),
                                          "candidates": cands,
                                          "hint": "确认晋升加 --apply --tier <core|curated|working>"},
                                         ensure_ascii=False))
                elif args.auto:
                    r = promote_auto(args.root, dry_run=not args.apply,
                                     merge=args.merge, min_recurrence=args.min_count,
                                     min_relevance=args.min_relevance,
                                     min_access=args.min_access,
                                     min_age_days=args.min_age_days,
                                     promote_tier=args.tier or "curated")
                    print(json.dumps(r, ensure_ascii=False))
                else:
                    promote(args.root, args.id, args.tier)
                    print(json.dumps({"ok": True, "id": args.id, "tier": args.tier}, ensure_ascii=False))
            elif args.op == "confirm":
                # （P0）：staging 人工放行——暂存(auto_sourced)记忆确认入库。
                # 置 reviewed=True + 清 auto_sourced（可选 --tier 顺带升级）。
                r = confirm(args.root, args.id, tier=args.tier or None)
                print(json.dumps(r, ensure_ascii=False))
            elif args.op == "summary-index":
                r = summary_index(args.root)
                print(json.dumps(r, ensure_ascii=False))
            elif args.op == "tree-view":
                r = tree_view(args.root)
                print(json.dumps(r, ensure_ascii=False))
            elif args.op == "reflect":
                if args.undo:
                    f = reflect(args.root, undo=True)
                    print(json.dumps({"ok": True, "undo": f}, ensure_ascii=False))
                else:
                    f = reflect(args.root, auto=args.auto,
                                stale_days=args.stale_days,
                                auto_archive=not args.no_auto_archive,
                                context_budget=args.context_budget,
                                llm=args.llm)
                    print(json.dumps({"ok": True, "findings": f}, ensure_ascii=False))
            elif args.op == "schedule_reflect":
                cfg = schedule_reflect(args.root, at=args.at, freq=args.freq)
                print(json.dumps({"ok": True, "automation_config": cfg}, ensure_ascii=False))
            elif args.op == "schedule_self_heal":
                if args.cron:
                    r = schedule_self_heal(args.root, at=args.at,
                                           with_rebuild=args.with_rebuild, cron=True)
                    print(json.dumps({"ok": True, "cron": r}, ensure_ascii=False))
                else:
                    autos = schedule_self_heal(args.root, at=args.at, with_rebuild=args.with_rebuild)
                    print(json.dumps({"ok": True, "automations": autos,
                                      "count": len(autos)}, ensure_ascii=False))
            elif args.op == "self-heal":
                # ：统一自治循环——把 reflect/evolve/decay/doctor/skill-sync/export-rules
                # 串成单一默认全开的维护；dirty-mark 驱动，长会话/调度兜底。
                r = self_heal(args.root, force=args.force, dry_run=args.dry_run,
                              discover=args.discover)
                print(json.dumps(r, ensure_ascii=False))
            elif args.op == "doctor":
                # 2026-09-15：ack 动作独立出口（避免重排下方大段 doctor 逻辑的缩进）；
                # 三者互斥，命中即打印并退出，不跑真自检。
                _kinds = tuple(k for (_r, k, _f) in _ACK_SECTIONS) + ("invariant",)
                if getattr(args, "ack_list", False):
                    _al = doctor_ack_list(args.root)
                    print(json.dumps({"ok": True, "acks": _al, "count": len(_al),
                                      "ttl_days": DOCTOR_ACK_TTL_DAYS}, ensure_ascii=False))
                    sys.exit(0)
                if getattr(args, "ack_clear", False):
                    print(json.dumps({"ok": True, "cleared": doctor_ack_clear(args.root)},
                                     ensure_ascii=False))
                    sys.exit(0)
                if getattr(args, "ack", ""):
                    _k, _, _i = args.ack.partition(":")
                    if not _k or not _i:
                        print(json.dumps({"ok": False,
                                          "error": "--ack 需 KIND:ID 形式，例：--ack link:LRN-A~LRN-B"},
                                         ensure_ascii=False))
                        sys.exit(2)
                    if _k not in _kinds:
                        print(json.dumps({"ok": False,
                                          "error": "未知 kind=%r；可用：%s" % (_k, " / ".join(_kinds))},
                                         ensure_ascii=False))
                        sys.exit(2)
                    print(json.dumps({"ok": True,
                                      "acked": doctor_ack(args.root, _k, _i,
                                                          getattr(args, "ack_reason", ""))},
                                     ensure_ascii=False))
                    sys.exit(0)
                d = doctor(args.root, fix=args.fix, context_budget=args.context_budget,
                           contradictions=args.contradictions, low_confidence=args.low_confidence,
                           repair=args.repair, restore=args.restore,
                           no_cache=getattr(args, "no_cache", False),
                           ack_all=getattr(args, "ack_all", False))
                # P0 升级：矛盾自动仲裁——强矛盾对自动 supersede 旧/低置信条（只标不删）
                if args.arbitrate and args.contradictions and args.fix:
                    try:
                        from p0_upgrade import doctor_arbitrate
                        _llm_callable, _ = _resolve_llm(args.root, None)
                        arb = doctor_arbitrate(args.root, dry_run=args.dry_run,
                                               llm=_llm_callable if callable(_llm_callable) else None)
                        d["arbitrated"] = arb
                    except Exception as _ae:
                        d["arbitrate_error"] = str(_ae)
                _out = {"ok": True, "doctor": d}
                if args.json:
                    # 机器可读健康度：供 CI/自动化按退出码判定
                    if (d.get("corrupt_files") or d.get("missing_files") or
                            d.get("dangling_relations") or d.get("restore_errors") or
                            d.get("index_without_file")):
                        _out["health"] = "error"
                    elif (d.get("orphan_files") or d.get("status_mismatch") or
                          d.get("contradiction_candidates") or d.get("low_confidence_scenes") or
                          d.get("scope_mismatch_candidates") or d.get("type_mismatch_candidates")):
                        _out["health"] = "warn"
                    else:
                        _out["health"] = "ok"
                print(json.dumps(_out, ensure_ascii=False))
                if args.json and _out.get("health") == "error":
                    sys.exit(1)
            elif args.op == "graph":
                # P0 升级：图谱自动建边（离线规则 + 可选 LLM 精化）
                from p0_upgrade import graph_build, graph_clean, graph_rebuild
                _llm_callable, _ = _resolve_llm(args.root, None)
                if args.rebuild:
                    r = graph_rebuild(args.root, llm=_llm_callable if callable(_llm_callable) else None,
                                      dry_run=args.dry_run)
                elif args.clean:
                    r = graph_clean(args.root, dry_run=args.dry_run)
                else:
                    r = graph_build(args.root, llm=_llm_callable if callable(_llm_callable) else None,
                                    dry_run=args.dry_run)
                print(json.dumps(r, ensure_ascii=False))
            elif args.op == "distill":
                # P0 升级：原则蒸馏（--review 离线预览候选；--apply 需 LLM）
                from p0_upgrade import distill_candidates, distill_apply
                if args.review or not args.apply:
                    cands = distill_candidates(args.root)
                    print(json.dumps({"ok": True, "review": True, "candidates": cands,
                                     "count": len(cands)}, ensure_ascii=False))
                else:
                    _llm_callable, _ = _resolve_llm(args.root, None)
                    r = distill_apply(args.root, llm=_llm_callable if callable(_llm_callable) else None,
                                      dry_run=args.dry_run)
                    print(json.dumps(r, ensure_ascii=False))
            elif args.op == "profile":
                # P0 升级：用户画像（离线）
                from p0_upgrade import profile_build
                p = profile_build(args.root)
                print(json.dumps(p, ensure_ascii=False))
            elif args.op == "token-report":
                rep = token_report(args.root, top_n=args.top_n)
                print(json.dumps({"ok": True, "report": rep}, ensure_ascii=False))
            elif args.op == "backup":
                zp = backup(args.root, args.zip or None, progress=args.progress)
                # P2-2：路径键名统一为 "zip"（与 --zip 一致），避免 {"ok":True,"backup":path} 嵌套歧义
                _bres = {"ok": True, "zip": zp}
                # ：--keep N → 保留最近 N 份，更旧的**搬**走（只搬不删，红线 A2）
                if getattr(args, "keep", None) is not None:
                    _bres["pruned"] = backup_prune(args.root, args.keep, protect=zp)
                print(json.dumps(_bres, ensure_ascii=False))
            elif args.op == "restore":
                try:
                    # P2-1：允许位置参数兜底为 zip 路径（与 delete <id> 一致），兼容 --zip
                    zip_path = args.zip or args.op_id or ""
                    r = restore(args.root, zip_path, dry_run=args.dry_run, yes=args.yes,
                                verify=args.verify, force=args.force)
                    print(json.dumps(r, ensure_ascii=False))
                except (FileNotFoundError, ValueError, zipfile.BadZipFile) as e:
                    err_type = "corrupt_backup" if isinstance(e, zipfile.BadZipFile) else "restore_failed"
                    print(json.dumps({"ok": False, "error": err_type,
                                      "msg": str(e)}, ensure_ascii=False))
                    sys.exit(3)
            elif args.op == "release-audit":
                # ：发布账本核对（只读；拿不到平台数据时报「未知」并用退出码 3 区分）
                _ra = release_audit(args.root, offline=args.offline)
                print(json.dumps(_ra, ensure_ascii=False, indent=2))
                sys.exit(0 if _ra.get("verdict") == "ok"
                         else (3 if _ra.get("verdict") == "unknown" else 2))
            elif args.op == "touch":
                touch(args.root, args.id, scope=args.scope or None, project=args.project or None)
                print(json.dumps({"ok": True, "id": args.id, "accessed": today()}, ensure_ascii=False))
            elif args.op == "reclassify":
                if args.pending:
                    # 数据质量队列：列出缺 scene/about_axis/domain 标注的活跃记忆（只读）
                    r = reclassify_pending(args.root, suggest=args.suggest)
                    print(json.dumps(r, ensure_ascii=False))
                else:
                    r = reclassify(args.root, args.id, scope=args.scope or None,
                                   project=args.project or None,
                                   mem_type=args.type or None,
                                   scene=args.scene or None,
                                   reason=args.reason,
                                   dry_run=args.dry_run, yes=args.yes)
                    if isinstance(r, dict) and r.get("dry_run"):
                        print(json.dumps(r, ensure_ascii=False))
                    else:
                        print(json.dumps({"ok": True, "id": args.id, "scope": args.scope or None,
                                          "project": args.project or None,
                                          "type": args.type or None,
                                          "scene": args.scene or None}, ensure_ascii=False))
            elif args.op == "cluster":
                r = cluster_memories(args.root, max_k=args.max_k, apply=args.apply,
                                     dry_run=args.dry_run, min_size=args.min_size)
                print(json.dumps({"ok": True, "cluster": r}, ensure_ascii=False))
            elif args.op == "report":
                r = report(args.root)
                print(json.dumps({"ok": True, "report": r}, ensure_ascii=False))
            elif args.op == "export":
                r = export_memories(args.root, fmt=args.format,
                                     dest=args.out or None,
                                     include_archived=args.include_archived,
                                     include_superseded=args.include_superseded)
                if isinstance(r, dict) and r.get("ok") and r.get("dest"):
                    print(json.dumps(r, ensure_ascii=False))
                elif isinstance(r, dict) and r.get("ok"):
                    # stdout 模式：直接输出原始 md/jsonl，便于管道重定向到文件
                    sys.stdout.write(r.get("content", ""))
                else:
                    print(json.dumps(r, ensure_ascii=False))
            elif args.op == "explain":
                if not args.id:
                    print(json.dumps({"ok": False, "error": "missing_id",
                                      "msg": "explain 需要 --id（记忆 id，用 recall 查）"},
                                     ensure_ascii=False))
                    sys.exit(2)
                r = explain_memory(args.root, args.id)
                print(json.dumps(r, ensure_ascii=False))
            elif args.op == "stats":
                r = stats(args.root, top=args.top)
                print(json.dumps(r, ensure_ascii=False))
            elif args.op == "dashboard":
                d = dashboard(args.root, out=args.out or None)
                print(json.dumps({"ok": True, "dashboard": d}, ensure_ascii=False))
            elif args.op == "timeline":
                # ：记忆时间线回放（只读）
                r = timeline(args.root, mid=args.id or None,
                             query=args.query or None,
                             days=args.days, limit=args.limit)
                print(json.dumps(r, ensure_ascii=False))
            elif args.op == "audit-log":
                # ：变更审计日志查看（只读）
                rows = _audit_log_tail(args.root, n=args.top, op_filter=args.filter_op or None)
                print(json.dumps({"ok": True, "count": len(rows), "entries": rows},
                                 ensure_ascii=False))
            elif args.op == "audit":
                a = audit_features(args.root)
                print(json.dumps({"ok": True, "audit": a}, ensure_ascii=False))
            elif args.op == "llm-setup":
                r = llm_setup(args.root, backend=args.backend, base_url=args.base_url,
                              model=args.model, api_key_env=args.api_key_env,
                              enable=(True if args.enable_llm else (False if args.disable_llm else None)),
                              dry=args.llm_dry,
                              max_suggestions=args.max_suggestions,
                              batch_size=args.batch_size,
                              temperature=args.temperature)
                print(json.dumps({"ok": True, "llm_setup": r}, ensure_ascii=False))
            elif args.op == "harvest":
                # 原生记忆打通：harvest 的 --with-workbuddy 本身默认关（直接 CLI 调用需显式开启），
                # 但 Stop/PreCompact 钩子已默认带 --with-workbuddy 调用，故"会话结束自动沉淀 WB 记忆"为默认开。
                # --no-workbuddy 为显式关闭（与默认一致，保留以防旧调用）。
                with_wb = args.with_workbuddy and not args.no_workbuddy
                if args.from_conversations and not args.text and not args.session:
                    # 工作流提示：harvest --from-conversations 需在 WB 会话中由 AI 编排，
                    # 自身不联网检索历史会话（CLI 无 WB tool 环境），故先打印编排说明。
                    r = {"ok": True, "mode": "from_conversations_workflow",
                         "note": ("此模式需在 WorkBuddy 会话中由 AI 编排：先用 conversation_search "
                                   "按回溯窗口（默认最近 30 天）检索历史会话 → 整理为文本文件 → 再 "
                                   "harvest --from-conversations --session <file> 沉积。"
                                   "会话来源记忆打 wb_session 标签并做幂等去重，避免回声/重复沉积。")}
                    print(json.dumps(r, ensure_ascii=False))
                else:
                    r = harvest(args.root, text=args.text, session_file=args.session,
                                self_learn=args.self_learn, max_items=args.max_items,
                                llm=False if args.no_llm else (True if args.auto_llm else None),
                                with_workbuddy=with_wb,
                                wb_dir=args.workbuddy_memory,
                                dry_run=args.dry_run,
                                from_conversations=args.from_conversations)
                    print(json.dumps(r, ensure_ascii=False))
            elif args.op == "feedback":
                if not args.id:
                    print(json.dumps({"ok": False, "error": "missing_id",
                                      "msg": "feedback 需要 --id"}, ensure_ascii=False))
                    sys.exit(2)
                if not args.signal:
                    print(json.dumps({"ok": False, "error": "missing_signal",
                                      "msg": "feedback 需要 --signal good|bad"}, ensure_ascii=False))
                    sys.exit(2)
                r = feedback(args.root, args.id, args.signal, weight=args.weight)
                print(json.dumps(r, ensure_ascii=False))
            elif args.op == "converse":
                r = converse(args.root, text=args.text, rounds=args.rounds,
                             set_threshold=args.set_threshold, force_end=args.end,
                             max_items=args.max_items, with_workbuddy=args.with_workbuddy,
                             no_llm=args.no_llm)
                print(json.dumps(r, ensure_ascii=False))
            elif args.op == "evolve":
                # 自我进化：默认 review 预览；--apply 才落盘（受 config.auto_evolve 协同）
                r = evolve(args.root, dry_run=not args.apply, auto_apply=args.apply,
                           max_items=args.max_items)
                print(json.dumps(r, ensure_ascii=False))
            elif args.op == "distill-to-wb":
                # keeper→WB 蒸馏：默认 review 预览；--apply 才写 ~/.workbuddy/MEMORY.md
                r = distill_to_wb(args.root, dry_run=not args.apply, max_items=args.max_items)
                print(json.dumps(r, ensure_ascii=False))
            elif args.op == "verify-investment":
                _sql_map = None
                if args.sql_map:
                    try:
                        with open(args.sql_map, encoding="utf-8") as _f:
                            _sql_map = json.load(_f)
                    except Exception as _e:
                        print(json.dumps({"ok": False, "error": "sql_map_read_failed",
                                          "msg": str(_e)}, ensure_ascii=False))
                        sys.exit(2)
                r = verify_investment(args.root, duckdb_path=args.duckdb,
                                      sql_map=_sql_map, dry_run=args.dry_run,
                                      max_items=args.max_items)
                print(json.dumps(r, ensure_ascii=False))
            elif args.op == "forget":
                if not args.id:
                    print(json.dumps({"ok": False, "error": "missing_id",
                                      "msg": "forget 需要 --id"}, ensure_ascii=False))
                    sys.exit(2)
                r = forget(args.root, args.id, reason=args.forget_reason,
                           dry_run=args.dry_run)
                print(json.dumps(r, ensure_ascii=False))
            elif args.op == "import":
                if not args.file:
                    print(json.dumps({"ok": False, "error": "missing_file",
                                      "msg": "import 需要 --file <路径>"}, ensure_ascii=False))
                    sys.exit(2)
                r = keeper_import_run(args.root, args.file, fmt=args.import_format,
                                      dry_run=not args.execute, keep_ids=args.keep_ids,
                                      on_error=args.on_error, report=args.report)
                print(json.dumps(r, ensure_ascii=False))
                if not r.get("ok"):
                    sys.exit(1)
            elif args.op == "benchmark":
                # 🔴 护栏：benchmark 会向 root 写入 N 条合成记忆，禁止对默认真实记忆库跑，
                # 否则污染真实召回。必须显式传 --root 指向隔离目录（如 --root /tmp/keeper_bench）。
                # ⚠️ 必须用 _root_key 规范化后比较：2026-09-16 实锤 —— 写成字符串相等
                # （args.root == DEFAULT_ROOT）时，`--root "D:/<库路径>"`（正斜杠）与
                # DEFAULT_ROOT 的反斜杠形式不相等 → 护栏被绕过 → 200 条合成记忆写进真库。
                if _root_key(args.root) == _root_key(DEFAULT_ROOT):
                    print(json.dumps({"ok": False, "error": "refuse_default_root",
                                      "msg": "benchmark 会写入合成记忆，禁止对默认真实记忆库跑。"
                                             "请显式传 --root <隔离目录>（如 --root /tmp/keeper_bench）"},
                                     ensure_ascii=False))
                    sys.exit(2)
                r = run_benchmark(args.root, n=args.n, recall_times=args.recall_times,
                                  top_n=args.top_n, ann=args.ann, out=args.out,
                                  topic_space=args.topics)
                print(json.dumps(r, ensure_ascii=False))
    except CorruptIndexError as e:
        print(json.dumps({"ok": False, "error": "corrupt_index", "msg": str(e),
                          "hint": "索引文件 index.json 损坏。运行 `rebuild` 扫描记忆文件重建索引即可自动恢复，记忆本身不会丢。"},
                         ensure_ascii=False))
        sys.exit(2)
    except ConflictError as e:
        print(json.dumps({"ok": False, "error": "conflict", "msg": str(e),
                          "hint": "id 大小写冲突或重复。Windows 下 LRN-001 与 lrn-001 是同一文件——永远复用原 id，别改大小写「新建」；或换一个不重复的 id。"},
                         ensure_ascii=False))
        sys.exit(4)
    except MemoryConflictError as e:
        print(json.dumps({"ok": False, "error": "write_conflict", "msg": str(e),
                          "hint": "另一个窗口/进程刚改过这条记忆。先 `recall --id <id>` 重读最新内容，合并你的修改再写，不会互相覆盖。"},
                         ensure_ascii=False))
        sys.exit(6)
    except FileNotFoundError as e:
        print(json.dumps({"ok": False, "error": "not_found", "msg": str(e),
                          "hint": "没找到这条记忆。常见原因：1) id 拼错——`recall` 不带参数列出全部 id；2) 已归档——加 --deep 再试；3) 索引脱节——运行 `rebuild` 重建。"},
                         ensure_ascii=False))
        sys.exit(3)
    except (ValueError, KeyError) as e:
        print(json.dumps({"ok": False, "error": "bad_arg", "msg": str(e),
                          "hint": "参数不合法。看上面提示里列出的合法取值（如 tier 只能是 working/curated/core），照着改即可。"},
                         ensure_ascii=False))
        sys.exit(5)
    except LegacyEncryptedStoreError as e:
        # 5.0.0：旧加密库 fail-closed 守卫。**单独一档、优先于泛化兜底**，因为这是
        # 可预期的兼容性阻断（不是意外错误），必须给出结构化 next_steps 而非 "unexpected"。
        # 退出码 13：0-7 已被占用，11/12 是 4.9.25 的加密错误码（语义不同，不占用）。
        print(json.dumps({
            "ok": False,
            "error": "legacy_encrypted_store",
            "error_code": "LEG-001",
            "msg": str(e),
            "hint": "本库是 4.9.25 的加密库，5.0.0 已移除加解密能力，已拒绝按明文处理（fail-closed）。",
            "next_steps": [
                "继续用本库：重装 4.9.25 并恢复 AI_MEM_ENCRYPTION_KEY（或 store/enc_key.txt / 库外 keyfile）",
                "搬进明文库：在 4.9.25 下用原密钥读出并导出到全新目录，确认无 store/salt.bin 后再用 5.0.0 --root <新目录>",
                "换新库：--root <全新空目录>（或设 AI_MEMORY_STORE），旧库原样留档",
                "不要在本库上继续写入 5.0.0 的明文，会造成密文/明文混库、降级后整库读不出",
            ],
            "doc_link": "references/CHANGELOG.md",
        }, ensure_ascii=False))
        sys.exit(13)
    except Exception as e:  # 兜底：任何意外都不静默吞，明确报出
        msg = str(e).lower()
        # ：对复杂/网络相关错误给出结构化 next_steps，减少"提示绕、多试几次"
        if "timeout" in msg or "timed out" in msg or "network" in msg or "urlopen" in msg:
            err = {
                "ok": False,
                "error": "network_timeout",
                "error_code": "NET-001",
                "msg": str(e),
                "hint": "网络操作超时。模型下载或在线 API 访问受阻。",
                "next_steps": [
                    "若在国内，设环境变量 HF_ENDPOINT=https://hf-mirror.com 后重试",
                    "跑 `python scripts/memory_ops/__init__.py report` 查看当前 embed.backend 与镜像状态",
                    "若不需要语义召回，设 AI_MEM_EMBED_BACKEND=lexical 完全离线运行",
                ],
                "doc_link": "references/QA.md#首次安装中文语义模型-fastembed",
            }
        elif "huggingface" in msg or "fastembed" in msg or "sentence_transformers" in msg or "embedding" in msg:
            err = {
                "ok": False,
                "error": "embed_model_load_failed",
                "error_code": "EMB-001",
                "msg": str(e),
                "hint": "语义模型加载失败，将自动回退到词法级向量。",
                "next_steps": [
                    "确认已装 fastembed：pip install fastembed（装到运行本脚本的同款 Python）",
                    "跑 `python scripts/memory_ops/__init__.py init --download-models` 预下载模型",
                    "在国内网络设 HF_ENDPOINT=https://hf-mirror.com + HF_HUB_DISABLE_XET=1",
                ],
                "doc_link": "references/QA.md#中文换个说法搜不到",
            }
        elif "permission" in msg or "denied" in msg or "access is denied" in msg:
            err = {
                "ok": False,
                "error": "permission_denied",
                "error_code": "FS-001",
                "msg": str(e),
                "hint": "文件/目录权限不足。",
                "next_steps": [
                    "检查 AI_MEMORY_STORE 指向的目录是否可写",
                    "Windows 下不要用系统目录；默认在用户目录下，改位置用 AI_MEMORY_STORE 或 ~/.keeper/store_root",
                ],
                "doc_link": "references/QA.md",
            }
        else:
            err = {
                "ok": False,
                "error": "unexpected",
                "error_code": "UNEXPECTED",
                "msg": repr(e),
                "hint": "出现意外错误。把这段 msg 和 `doctor` 的输出一起反馈，我来定位原因。",
                "next_steps": [
                    "跑 `python scripts/memory_ops/__init__.py doctor` 检查索引/文件一致性",
                    "跑 `python scripts/memory_ops/__init__.py report` 看当前状态",
                    "若索引损坏，跑 `python scripts/memory_ops/__init__.py rebuild` 重建（记忆本身不丢）",
                ],
                "doc_link": "references/QA.md",
            }
        print(json.dumps(err, ensure_ascii=False))
        sys.exit(1)

