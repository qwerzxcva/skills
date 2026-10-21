# -*- coding: utf-8 -*-
"""
investment_seed.py — 从投资数据库 duckdb catalog 批量播种 L0「数据/参数注册表」记忆。

只读 duckdb 的 5 张自描述 catalog 表，批量 deposit 成
--domain investment --subdomain data_catalog
的记忆。每条字段/指标/单位对账/跨源码映射/新鲜度都成为一条可检索的 L0 记忆，
根治「手搓快照过期、加表不登记」的痛点（数据库的每一个参数/字段都可能成为某因子的原料）。

设计要点：
- 数值维度（IC/sharpe 等）走 --attr；字符串维度（单位/频率/数据源）走标签
mcp:/unit:/freq:（--attr 仅收数值，详见 INVESTMENT.md）。
- 每条记忆带稳定标签 seed:<table>:<key>，使重跑幂等（已存在的跳过，不覆盖）。
- --db 必填（或环境变量 INVESTMENT_DUCKDB / --discover 自动选最新副本）。
- 批量 defer_index=True，结束 flush_memory_index 一次落盘，避免每条重写索引。

依赖：duckdb（pip install duckdb）。本脚本只读 duckdb，只写记忆库。

用法：
python investment_seed.py --root <记忆库根目录> --db <投资数据目录>/.../unified_market.duckdb [--dry-run]
python investment_seed.py --root <记忆库根目录> --discover [--table field_catalog,dim_metric]

路径默认值可经环境变量覆盖（便于换机 / CI）：
AI_MEMORY_STORE    记忆库根目录（默认：环境变量；未设则 --root 必填）
KEEPER_SEED_DIR    自动发现 duckdb 的根目录（默认：环境变量；未设则跳过自动发现）
INVESTMENT_DUCKDB  duckdb 路径（等价 --db）
"""
import os, sys, argparse, glob, json, re

SK = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts")
sys.path.insert(0, os.path.abspath(SK))
import memory_ops as mo

try:
    import duckdb
except ImportError:
    sys.stderr.write("[investment_seed] 需要 duckdb：pip install duckdb\n")
    sys.exit(2)

DOMAIN = "investment"
SUBDOMAIN = "data_catalog"

# 每张 catalog 表 → 如何构造记忆。
# body_cols: 进 body 的字段；tag_cols: 进标签的字段（字符串维度）；
# key: 稳定主键（用于 seed 标签与幂等）；summary: 摘要模板。
TABLE_CFG = {
    "field_catalog": {
        "summary": lambda r: "字段 %s.%s：%s" % (r["table_name"], r["field_name"],
                                                 (r.get("note") or "")[:40]),
        "body_cols": ["acquisition_type", "source_mcp", "mcp_code", "retrieval_tool",
                      "retrieval_condition", "unit", "frequency", "note"],
        "tag_cols": {"source_mcp": "mcp", "unit": "unit", "frequency": "freq"},
        "key": lambda r: "field:%s.%s" % (r["table_name"], r["field_name"]),
    },
    "dim_metric": {
        "summary": lambda r: "指标 %s：%s" % (r["metric_code"], r.get("metric_name") or ""),
        "body_cols": ["metric_id", "category", "unit", "frequency", "formula",
                      "description", "source", "is_derived"],
        "tag_cols": {"unit": "unit", "frequency": "freq"},
        "key": lambda r: "metric:%s" % r["metric_code"],
    },
    "unit_standard": {
        "summary": lambda r: "单位对账 %s → %s" % (r.get("xlsx_label") or r["id"],
                                                   r.get("db_metric") or ""),
        "body_cols": ["xlsx_file", "xlsx_sheet", "xlsx_label", "xlsx_unit",
                      "db_table", "db_column", "db_metric", "db_unit",
                      "scale_factor", "conversion", "frequency", "note"],
        "tag_cols": {"db_unit": "unit", "frequency": "freq"},
        "key": lambda r: "unit:%s" % r["id"],
    },
    "mcp_code_map": {
        "summary": lambda r: "跨源码映射 %s：%s" % (r["industry_code"],
                                                   r.get("industry_name") or ""),
        "body_cols": ["industry_code", "ifind_code", "mx_code", "tdx_code",
                      "westock_code", "industry_name", "wind_status",
                      "fallback_mcp", "last_verified"],
        "tag_cols": {},
        "key": lambda r: "mcp:%s" % r["industry_code"],
    },
    "metric_freshness": {
        "summary": lambda r: "新鲜度 %s.%s：%s" % (r["table_name"], r["metric_code"],
                                                  r.get("status") or ""),
        "body_cols": ["table_name", "metric_code", "last_data_date", "status",
                      "recommended_source", "note", "checked_at"],
        "tag_cols": {},
        "key": lambda r: "fresh:%s.%s" % (r["table_name"], r["metric_code"]),
    },
}

# ── F9：L2 因子测试层种子配置（与 L0 data_catalog 同构，支持 --layer factor_test）──
FACTOR_TEST_CFG = {
    "factor_test": {
        "summary": lambda r: "因子测试 %s：%s" % (r.get("test_id") or "?",
                                                   (r.get("conclusion") or "")[:40]),
        "body_cols": ["test_id", "factor", "config", "ic", "ir", "pass_flag",
                      "conclusion", "oos_ic", "note"],
        "tag_cols": {},
        "key": lambda r: "ftest:%s" % (r.get("test_id") or "?"),
        "type": "PREF",
    },
}

# --layer → (子域, 记忆类型, 该层用的表配置)。data_catalog 为默认 L0；factor_test 为 L2。
LAYER_SUBDOMAIN = {"data_catalog": "data_catalog", "factor_test": "factor_test"}
LAYER_TYPE = {"data_catalog": "FACT", "factor_test": "PREF"}
LAYER_TABLES = {"data_catalog": TABLE_CFG, "factor_test": FACTOR_TEST_CFG}

# F23：投资域已知子域（单一事实源见 investment_taxonomy.json）；deposit 时若不符仅告警不阻断。
KNOWN_INV_SUB = {"data_catalog", "factor", "factor_test", "system",
                 "data_integrity", "backtest_integrity"}


def discover_db():
    seed_dir = os.environ.get("KEEPER_SEED_DIR", "")
    if not seed_dir:
        return None
    cands = glob.glob(os.path.join(seed_dir, "**", "unified_market.duckdb"), recursive=True)
    if not cands:
        return None
        # 选 mtime 最新（忽略 _回收站/_portable_build 等中间产物：优先含「数据调用专属数据库」的）
    pref = [c for c in cands if "数据调用专属数据库" in c]
    pool = pref or cands
    pool.sort(key=lambda p: os.path.getmtime(p), reverse=True)
    return pool[0]


def existing_seed_tags(root):
    """返回已存在的 seed: 标签集合。

    既扫磁盘 JSON（mem_dir + archive_dir）也并上索引，确保幂等不受「索引是否刚刷新」影响——
    即便上一次播种中途异常导致索引未 flush，重跑也能靠磁盘上的 seed: 标签跳过，杜绝重复 deposit。
    """
    tags = set()
    for d in (mo.mem_dir(root), mo.archive_dir(root)):
        if not os.path.isdir(d):
            continue
        for fn in os.listdir(d):
            if not fn.endswith(".json"):
                continue
            try:
                m = json.load(open(os.path.join(d, fn), encoding="utf-8"))
            except Exception:
                continue
            for t in (m.get("tags") or []):
                if t.startswith("seed:"):
                    tags.add(t)
    try:
        idx = mo.load_index(root)
        for e in idx.get("entries", []):
            for t in (e.get("tags") or []):
                if t.startswith("seed:"):
                    tags.add(t)
    except Exception:
        pass
    return tags


def build_memory(table, row, tables_cfg=TABLE_CFG):
    cfg = tables_cfg[table]
    summary = cfg["summary"](row)
    body_lines = []
    for c in cfg["body_cols"]:
        v = row.get(c)
        if v is None or v == "":
            continue
        body_lines.append("%s: %s" % (c, v))
    body = "\n".join(body_lines)
    tags = ["seed:%s" % cfg["key"](row)]
    for col, prefix in cfg["tag_cols"].items():
        v = row.get(col)
        if v and v != "":
            tags.append("%s:%s" % (prefix, v))
    return summary, body, tags


def main():
    ap = argparse.ArgumentParser(description="从 duckdb catalog 批量播种 L0 投资记忆")
    ap.add_argument("--root", default=os.environ.get("AI_MEMORY_STORE", ""),
                    help="记忆库根目录（默认 AI_MEMORY_STORE；未设则 --root 必填）")
    ap.add_argument("--db", default=os.environ.get("INVESTMENT_DUCKDB", ""),
                    help="unified_market.duckdb 路径（必填，或设 INVESTMENT_DUCKDB）")
    ap.add_argument("--discover", action="store_true",
                    help="自动选 KEEPER_SEED_DIR（默认环境变量；未设则跳过自动发现）下最新 unified_market.duckdb（忽略 --db）")
    ap.add_argument("--table", default=",".join(TABLE_CFG.keys()),
                    help="要播种的 catalog 表，逗号分隔（默认全 5 张 L0 表）")
    ap.add_argument("--layer", default="data_catalog",
                    choices=list(LAYER_TABLES.keys()),
                    help="播种层：data_catalog(L0 数据/参数) | factor_test(L2 因子测试)")
    ap.add_argument("--dry-run", action="store_true", help="只打印计划，不落库")
    ap.add_argument("--resync", action="store_true",
                    help="增量：已存在 seed 标签的记忆跳过（默认即幂等跳过，此 flag 仅显式语义）")
    args = ap.parse_args()
    if not args.root:
        ap.error("--root 必填（或设 AI_MEMORY_STORE 环境变量指向记忆库根目录）")

    db = discover_db() if args.discover else args.db
    if not db or not os.path.exists(db):
        sys.stderr.write("[investment_seed] 找不到 duckdb：--db/--discover/INVESTMENT_DUCKDB 均未命中 %r\n" % db)
        sys.exit(1)

    tables_cfg = LAYER_TABLES[args.layer]
    SUB = LAYER_SUBDOMAIN[args.layer]
    TYPE = LAYER_TYPE[args.layer]
    # F23：子域合法性校验（仅告警不阻断，避免破坏既有自动化）
    if SUB not in KNOWN_INV_SUB:
        sys.stderr.write("[investment_seed] ⚠ 子域 %s 不在 investment 已知子域，将照常 deposit"
                         "（建议用 %s）\n" % (SUB, sorted(KNOWN_INV_SUB)))

    tables = [t.strip() for t in args.table.split(",") if t.strip() in tables_cfg]
    if not tables:
        sys.stderr.write("[investment_seed] --table 必须子集于 %s\n" % list(TABLE_CFG))
        sys.exit(1)

    existing = existing_seed_tags(args.root) if not args.dry_run else set()
    con = duckdb.connect(db, read_only=True)
    total = 0
    skipped = 0
    try:
        for table in tables:
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", table):
                sys.stderr.write("[investment_seed] 非法表名（仅允许标识符）: %s\n" % table)
                sys.exit(1)
            rows = con.execute("SELECT * FROM %s" % table).fetchall()
            cols = [d[0] for d in con.description]
            n = 0
            for raw in rows:
                row = dict(zip(cols, raw))
                summary, body, tags = build_memory(table, row, tables_cfg)
                seed_tag = tags[0]
                if seed_tag in existing:
                    skipped += 1
                    continue
                total += 1
                n += 1
                if args.dry_run:
                    print("[DRY] + %s | %s" % (seed_tag, summary))
                    continue
                mo.deposit(args.root, category=TYPE, summary=summary, tags=tags,
                           body=body, domain=DOMAIN, subdomain=SUB,
                           auto_link=False, defer_index=True, recorded_by="investment_seed")
            print("[%s] 计划/新增 %d 条（累计跳过 %d）" % (table, n, skipped))
        if args.dry_run:
            print("\n[DRY-RUN] 未落库。去掉 --dry-run 执行。")
            return
            # 批量收尾：一次 save_index + 合并反向边
        mo.flush_memory_index(args.root, auto_link=False)
    except Exception:
        # 异常也要尽力把已写文件 flush 进索引，避免索引与磁盘不一致
        if not args.dry_run:
            try:
                mo.flush_memory_index(args.root, auto_link=False)
            except Exception:
                pass
        raise
    finally:
        try:
            con.close()
        except Exception:
            pass
    print("\n[OK] 新增 %d 条记忆（domain=investment, layer=%s, subdomain=%s）；"
          "跳过已存在 %d 条。语义向量将在下次 recall 时惰性回填。" % (total, args.layer, SUB, skipped))


if __name__ == "__main__":
    main()
