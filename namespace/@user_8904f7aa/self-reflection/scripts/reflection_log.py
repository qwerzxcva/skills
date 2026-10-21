#!/usr/bin/env python3
"""三省引擎 · 反省日志脚本（v2.0.0）

数据落 ~/\\.self-reflection\\log.db（纯 sqlite3 + 标准库，零外部依赖）。

命令
----
    add       归档一条反省
    verify    T+7 回查：标 verified / failed / untriggered
    patterns  模式聚合（同类型事件自动归并）
    stats     验证率、最近趋势
    check     当日三省快检（3 问模板）
    list      列出待回查队列
    challenge 启动 / 续接 21 天三省挑战
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path

DB_PATH = Path.home() / ".self-reflection" / "log.db"

REFLECTION_TYPES = ("A1", "A2", "A3", "A4")
CHECKOUT_STATES = ("verified", "failed", "untriggered", "third-time")


# ──────────── 存储层 ────────────
def db() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS reflections (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at  TEXT NOT NULL DEFAULT (datetime('now')),
            type        TEXT NOT NULL,
            title       TEXT,
            fact        TEXT,
            lesson      TEXT,
            if_then     TEXT,
            lever       TEXT,
            context     TEXT,
            status      TEXT DEFAULT 'pending',
            checkout_at TEXT,
            result      TEXT
        );
        CREATE TABLE IF NOT EXISTS patterns (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            name        TEXT NOT NULL UNIQUE,
            first_seen  TEXT NOT NULL,
            last_seen   TEXT NOT NULL,
            count       INTEGER DEFAULT 1,
            history_fn  TEXT
        );
        CREATE TABLE IF NOT EXISTS challenge (
            id            INTEGER PRIMARY KEY,
            started_at    TEXT NOT NULL,
            last_check_at TEXT,
            streak_days   INTEGER DEFAULT 0
        );
        """
    )
    conn.commit()
    return conn


# ──────────── 工具 ────────────
def _prompt(label: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    val = input(f"{label}{suffix}: ").strip()
    return val or default


def _print_reflection(row: sqlite3.Row) -> None:
    print(f"  #{row['id']} ({row['type']}) {row['title'] or '(无标题)'}")
    print(f"    创建：{row['created_at']}  回查：{row['checkout_at'] or 'T+7'}  状态：{row['status']}")
    if row["lesson"]:
        print(f"    教训：{row['lesson']}")
    if row["if_then"]:
        print(f"    if-then：{row['if_then']}")
    if row["lever"]:
        print(f"    杠杆：{row['lever']}")


# ──────────── 命令 ────────────
def cmd_add(args: argparse.Namespace) -> int:
    """归档一条反省。interactive 模式逐项提示；pipe 模式从 stdin/--json 读取。"""
    conn = db()
    try:
        if args.json:
            data = json.loads(args.json)
            row = conn.execute(
                """INSERT INTO reflections
                   (type, title, fact, lesson, if_then, lever, context)
                   VALUES (?,?,?,?,?,?,?)""",
                (
                    data["type"],
                    data.get("title", ""),
                    data.get("fact", ""),
                    data.get("lesson", ""),
                    data.get("if_then", ""),
                    data.get("lever", ""),
                    data.get("context", ""),
                ),
            )
        else:
            t = (args.type or _prompt("类型 (A1/A2/A3/A4)", "A1")).upper()
            if t not in REFLECTION_TYPES:
                print(f"类型必须为 {REFLECTION_TYPES}", file=sys.stderr)
                return 1
            print("\n─ 三省模板（直接回车跳过） ─")
            title = _prompt("一句话标题")
            fact = _prompt("事实")
            lesson = _prompt("一条教训")
            if_then = _prompt("执行意图 if-then")
            lever = _prompt("杠杆 (环境/执行意图/问责伙伴)", "")
            row = conn.execute(
                """INSERT INTO reflections
                   (type, title, fact, lesson, if_then, lever)
                   VALUES (?,?,?,?,?,?)""",
                (t, title, fact, lesson, if_then, lever),
            )

        rid = row.lastrowid
        checkout = (datetime.now() + timedelta(days=7)).strftime("%Y-%m-%d")
        conn.execute(
            "UPDATE reflections SET checkout_at=? WHERE id=?", (checkout, rid)
        )
        conn.commit()
        print(f"✓ 已归档 #{rid} · T+7 回查：{checkout}")
        return 0
    finally:
        conn.close()


def cmd_verify(args: argparse.Namespace) -> int:
    """T+7 回查：交互式判 + 模式聚合触发。"""
    conn = db()
    try:
        rows = conn.execute(
            """SELECT * FROM reflections
               WHERE status='pending' AND date(checkout_at) <= date('now')
               ORDER BY checkout_at ASC"""
        ).fetchall()
        if not rows:
            print("✓ 无待回查项。")
            return 0
        if args.id:
            rows = [r for r in rows if r["id"] == args.id]
            if not rows:
                print(f"#{args.id} 不在待回查列表", file=sys.stderr)
                return 1

        print(f"== 待回查 {len(rows)} 条 ==\n")
        for row in rows:
            _print_reflection(row)
            print("\n  回查结果：[v]erified  [f]ailed  [u]ntriggered  [t]hird-time  [s]kip")
            choice = input("  → ").strip().lower()
            result = {
                "v": "verified",
                "f": "failed",
                "u": "untriggered",
                "t": "third-time",
            }.get(choice)
            if not result:
                print("  · 跳过")
                continue
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            conn.execute(
                "UPDATE reflections SET status=?, result=?, checkout_at=? WHERE id=?",
                (result, result, now, row["id"]),
            )
            print(f"  ✓ 标记为 {result}")
            if result == "third-time":
                print(f"  ⚠ 第三次出现，停止加深反省，专攻执行系统")
        conn.commit()

        # 回查完触发模式聚合
        _aggregate_patterns(conn)
        return 0
    finally:
        conn.close()


def _aggregate_patterns(conn: sqlite3.Connection) -> None:
    """把同 type 且关键词重叠 ≥2 的事件合并到 patterns 表。"""
    rows = conn.execute(
        "SELECT id, type, title, lesson FROM reflections ORDER BY created_at"
    ).fetchall()
    groups: dict[str, list[sqlite3.Row]] = {}
    for r in rows:
        key = (r["type"], (r["title"] or r["lesson"] or "")[:20])
        groups.setdefault(key, []).append(r)
    for (typ, key), grp in groups.items():
        if len(grp) >= 2 and key:
            existing = conn.execute(
                "SELECT id, count FROM patterns WHERE name=?", (f"{typ}:{key}",)
            ).fetchone()
            if existing:
                conn.execute(
                    "UPDATE patterns SET last_seen=?, count=? WHERE id=?",
                    (datetime.now().isoformat(), existing["count"] + 1, existing["id"]),
                )
            else:
                conn.execute(
                    """INSERT INTO patterns(name, first_seen, last_seen, count)
                       VALUES (?,?,?,?)""",
                    (
                        f"{typ}:{key}",
                        grp[0]["id"] and datetime.now().isoformat(),
                        datetime.now().isoformat(),
                        len(grp),
                    ),
                )
    conn.commit()


def cmd_patterns(args: argparse.Namespace) -> int:
    conn = db()
    try:
        rows = conn.execute(
            "SELECT * FROM patterns ORDER BY count DESC, last_seen DESC"
        ).fetchall()
        if not rows:
            print("暂无模式。再做几次同类型反省会自动浮现。")
            return 0
        print(f"== 发现模式 {len(rows)} 条 ==\n")
        for r in rows:
            print(f"  · {r['name']}  出现 {r['count']} 次  最近 {r['last_seen'][:10]}")
        return 0
    finally:
        conn.close()


def cmd_stats(args: argparse.Namespace) -> int:
    conn = db()
    try:
        total = conn.execute("SELECT COUNT(*) c FROM reflections").fetchone()["c"]
        if total == 0:
            print("尚无反省记录。运行 `add` 或 `check` 开始。")
            return 0
        print(f"== 总数 {total} 条 ==\n")
        for status, label in [
            ("verified", "已验证 verified"),
            ("failed", "未执行 failed"),
            ("untriggered", "未触发 untriggered"),
            ("third-time", "第三次出现"),
            ("pending", "待回查 pending"),
        ]:
            c = conn.execute(
                "SELECT COUNT(*) c FROM reflections WHERE status=?", (status,)
            ).fetchone()["c"]
            pct = c * 100 // total
            bar = "█" * (pct // 5) + "·" * (20 - pct // 5)
            print(f"  {label:<28} {c:>3}  {bar} {pct}%")
        verified = conn.execute(
            "SELECT COUNT(*) c FROM reflections WHERE result='verified'"
        ).fetchone()["c"]
        completed = conn.execute(
            "SELECT COUNT(*) c FROM reflections WHERE status!='pending'"
        ).fetchone()["c"]
        if completed:
            rate = verified * 100 // completed
            print(f"\n  ★ 验证率 {rate}%（目标 ≥ 50%）")
        return 0
    finally:
        conn.close()


def cmd_check(args: argparse.Namespace) -> int:
    """当日三省快检（30 秒模板）。"""
    print("═" * 50)
    print("  当日三省（30 秒模板）")
    print("═" * 50)
    print("\n[1] 差了什么？")
    q1 = input("    → ").strip()
    print("\n[2] 为什么？")
    q2 = input("    → ").strip()
    print("\n[3] 下次换什么动作？")
    q3 = input("    → ").strip()

    if not (q1 or q2 or q3):
        print("\n留白 = 今日无偏差（难得的稳态！）")
        return 0

    conn = db()
    try:
        title = q1[:30] + ("…" if len(q1) > 30 else "")
        row = conn.execute(
            """INSERT INTO reflections(type, title, fact, if_then)
               VALUES ('A1', ?, ?, ?)""",
            (title, f"差：{q1}\n因：{q2}", f"动作：{q3}"),
        )
        rid = row.lastrowid
        checkout = (datetime.now() + timedelta(days=7)).strftime("%Y-%m-%d")
        conn.execute("UPDATE reflections SET checkout_at=? WHERE id=?", (checkout, rid))
        conn.commit()
    finally:
        conn.close()
    print(f"\n✓ 已归档 #{rid}（A1 微反省）· T+7 回查：{checkout}")
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    conn = db()
    try:
        rows = conn.execute(
            """SELECT id, type, title, status, checkout_at, result
               FROM reflections
               ORDER BY
                 CASE WHEN status='pending' AND date(checkout_at) <= date('now') THEN 0
                      WHEN status='pending' THEN 1
                      ELSE 2 END,
                 checkout_at ASC"""
        ).fetchall()
        if not rows:
            print("无反省记录。")
            return 0
        print(f"== 共 {len(rows)} 条 ==\n")
        for r in rows:
            mark = "🔥" if r["status"] == "pending" and r["checkout_at"] and r["checkout_at"] <= datetime.now().strftime("%Y-%m-%d") else "  "
            res = f" → {r['result']}" if r["result"] else ""
            print(f"  {mark} #{r['id']} [{r['type']}] {r['title'] or '—'}  回查 {r['checkout_at'] or '—'}  {r['status']}{res}")
        return 0
    finally:
        conn.close()


def cmd_challenge(args: argparse.Namespace) -> int:
    """21 天三省挑战：启动 / 续接 / 状态。"""
    conn = db()
    try:
        rec = conn.execute(
            "SELECT id, started_at, last_check_at, streak_days FROM challenge WHERE id=1"
        ).fetchone()
        if args.action == "start":
            if rec and rec["streak_days"] and rec["streak_days"] < 21:
                print(f"已有进行中的挑战：第 {rec['streak_days']} 天 / 21 天")
                return 1
            now = datetime.now().isoformat()
            conn.execute(
                """INSERT INTO challenge(id, started_at, last_check_at, streak_days)
                   VALUES (1, ?, ?, 0)
                   ON CONFLICT(id) DO UPDATE SET
                     started_at=excluded.started_at,
                     last_check_at=excluded.last_check_at,
                     streak_days=0""",
                (now, now),
            )
            conn.commit()
            print("🏆 21 天三省挑战已启动！每天 `check` 或 `add` 完成打卡。")
            return 0
        if not rec:
            print("尚未启动挑战。运行 `challenge start`")
            return 1
        # 续接 / 状态检查
        today = datetime.now().strftime("%Y-%m-%d")
        last = (rec["last_check_at"] or "")[:10]
        streak = rec["streak_days"] or 0
        if last == today:
            print(f"今日已打卡（连击 {streak}/21）。")
        elif last and (datetime.strptime(today, "%Y-%m-%d") - datetime.strptime(last, "%Y-%m-%d")).days > 1:
            streak = 0
            print(f"⚠ 漏打卡超过 1 天，计数清零。重新从第 1 天开始！")
            conn.execute("UPDATE challenge SET streak_days=0 WHERE id=1")
        else:
            streak += 1
            conn.execute(
                "UPDATE challenge SET streak_days=?, last_check_at=? WHERE id=1",
                (streak, datetime.now().isoformat()),
            )
            print(f"✓ 已打卡！连击 {streak}/21")
        conn.commit()
        if streak >= 21:
            print("\n🏆🏆🏆 21 天挑战完成！")
            print("下一步：季度自我治理（每 90 天一次大复盘）")
        return 0
    finally:
        conn.close()


# ──────────── CLI ────────────
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="reflection_log.py", description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)

    add = sub.add_parser("add", help="归档一条反省")
    add.add_argument("--type", choices=REFLECTION_TYPES)
    add.add_argument("--json", help="JSON 字符串，包含 type/title/fact/lesson/if_then/lever/context")
    add.set_defaults(func=cmd_add)

    vfy = sub.add_parser("verify", help="T+7 回查")
    vfy.add_argument("--id", type=int, help="仅回查指定 id")
    vfy.set_defaults(func=cmd_verify)

    sub.add_parser("patterns", help="模式聚合").set_defaults(func=cmd_patterns)
    sub.add_parser("stats", help="验证率统计").set_defaults(func=cmd_stats)
    sub.add_parser("check", help="当日三省快检").set_defaults(func=cmd_check)
    sub.add_parser("list", help="列出待回查队列").set_defaults(func=cmd_list)

    ch = sub.add_parser("challenge", help="21 天三省挑战")
    ch.add_argument("action", choices=["start", "status"], nargs="?", default="status")
    ch.set_defaults(func=cmd_challenge)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args) or 0


if __name__ == "__main__":
    sys.exit(main())
