"""SQLite 账本：账户、分类、流水，以及聚合查询。

金额统一用「分」存整数，排序和汇总都在 Python 侧完成（数据量在万级以内）。
"""

from __future__ import annotations

import os
import sqlite3
import time
from datetime import date, timedelta
from typing import Any

DB_PATH = os.getenv("DB_PATH", "/data/bill.db")

TXN_TYPES = ("expense", "income", "transfer")


def connect() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    con = sqlite3.connect(DB_PATH, timeout=15)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA foreign_keys=ON")
    return con


def init_db() -> None:
    con = connect()
    try:
        con.executescript(
            """
            CREATE TABLE IF NOT EXISTS accounts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                kind TEXT NOT NULL DEFAULT 'asset',
                opening_balance INTEGER NOT NULL DEFAULT 0,
                opening_date TEXT,
                sort INTEGER NOT NULL DEFAULT 0,
                archived INTEGER NOT NULL DEFAULT 0,
                created_at INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS categories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                kind TEXT NOT NULL DEFAULT 'expense',
                sort INTEGER NOT NULL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT NOT NULL,
                time TEXT NOT NULL DEFAULT '12:00',
                type TEXT NOT NULL,
                amount INTEGER NOT NULL,
                account_id INTEGER NOT NULL REFERENCES accounts(id),
                to_account_id INTEGER REFERENCES accounts(id),
                category_id INTEGER REFERENCES categories(id),
                merchant TEXT NOT NULL DEFAULT '',
                description TEXT NOT NULL DEFAULT '',
                note TEXT NOT NULL DEFAULT '',
                external_id TEXT,
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL,
                deleted_at INTEGER
            );

            CREATE UNIQUE INDEX IF NOT EXISTS idx_tx_external
                ON transactions(external_id) WHERE external_id IS NOT NULL;
            CREATE INDEX IF NOT EXISTS idx_tx_date ON transactions(date);
            CREATE INDEX IF NOT EXISTS idx_tx_account ON transactions(account_id);
            CREATE INDEX IF NOT EXISTS idx_tx_category ON transactions(category_id);
            """
        )
        con.commit()
    finally:
        con.close()


def cents(value: Any) -> int:
    """把 "12.34" / 12.34 / "¥1,234.5" 转成分。"""
    if isinstance(value, int):
        return value
    text = str(value or "").replace(",", "").replace("¥", "").replace("￥", "").strip()
    try:
        return int(round(float(text) * 100))
    except ValueError:
        return 0


def yuan(value: int) -> str:
    return f"{value / 100:.2f}"


# ---------------------------------------------------------------- accounts


def list_accounts(include_archived: bool = False) -> list[dict[str, Any]]:
    con = connect()
    try:
        clause = "" if include_archived else "WHERE archived = 0"
        rows = con.execute(
            f"SELECT * FROM accounts {clause} ORDER BY sort, id"
        ).fetchall()
        counts = {
            row["account_id"]: row["n"]
            for row in con.execute(
                "SELECT account_id, COUNT(*) AS n FROM transactions "
                "WHERE deleted_at IS NULL GROUP BY account_id"
            ).fetchall()
        }
        balances = _balances(con)
        return [
            {
                "id": row["id"],
                "name": row["name"],
                "kind": row["kind"],
                "opening_balance": yuan(row["opening_balance"]),
                "opening_date": row["opening_date"],
                "archived": bool(row["archived"]),
                "balance": yuan(balances.get(row["id"], 0)),
                "count": counts.get(row["id"], 0),
            }
            for row in rows
        ]
    finally:
        con.close()


def _balances(con: sqlite3.Connection) -> dict[int, int]:
    balances: dict[int, int] = {}
    for row in con.execute(
        "SELECT id, opening_balance FROM accounts WHERE archived = 0"
    ).fetchall():
        balances[row["id"]] = row["opening_balance"]
    for row in con.execute(
        "SELECT type, amount, account_id, to_account_id FROM transactions "
        "WHERE deleted_at IS NULL"
    ).fetchall():
        amount = row["amount"]
        if row["type"] == "income":
            balances[row["account_id"]] = balances.get(row["account_id"], 0) + amount
        elif row["type"] == "expense":
            balances[row["account_id"]] = balances.get(row["account_id"], 0) - amount
        elif row["type"] == "transfer":
            balances[row["account_id"]] = balances.get(row["account_id"], 0) - amount
            target = row["to_account_id"]
            if target:
                balances[target] = balances.get(target, 0) + amount
    return balances


def create_account(name: str, opening_balance: Any = 0, opening_date: str | None = None) -> int:
    con = connect()
    try:
        cursor = con.execute(
            "INSERT INTO accounts (name, kind, opening_balance, opening_date, sort, created_at) "
            "VALUES (?, 'asset', ?, ?, (SELECT COALESCE(MAX(sort), 0) + 1 FROM accounts), ?)",
            (name.strip(), cents(opening_balance), opening_date, int(time.time())),
        )
        con.commit()
        return int(cursor.lastrowid)
    finally:
        con.close()


def update_account(account_id: int, name: str | None = None, opening_balance: Any = None,
                   opening_date: str | None = None, archived: bool | None = None) -> None:
    fields, values = [], []
    if name is not None:
        fields.append("name = ?")
        values.append(name.strip())
    if opening_balance is not None:
        fields.append("opening_balance = ?")
        values.append(cents(opening_balance))
    if opening_date is not None:
        fields.append("opening_date = ?")
        values.append(opening_date or None)
    if archived is not None:
        fields.append("archived = ?")
        values.append(1 if archived else 0)
    if not fields:
        return
    values.append(account_id)
    con = connect()
    try:
        con.execute(f"UPDATE accounts SET {', '.join(fields)} WHERE id = ?", values)
        con.commit()
    finally:
        con.close()


def delete_account(account_id: int) -> None:
    con = connect()
    try:
        used = con.execute(
            "SELECT COUNT(*) FROM transactions WHERE deleted_at IS NULL "
            "AND (account_id = ? OR to_account_id = ?)",
            (account_id, account_id),
        ).fetchone()[0]
        if used:
            raise ValueError("账户下还有流水，先归档而不是删除")
        con.execute("DELETE FROM accounts WHERE id = ?", (account_id,))
        con.commit()
    finally:
        con.close()


def account_id_by_name(name: str) -> int | None:
    con = connect()
    try:
        row = con.execute("SELECT id FROM accounts WHERE name = ?", (name,)).fetchone()
        return int(row["id"]) if row else None
    finally:
        con.close()


def account_flow(account_id: int) -> int:
    """账户全部流水的净额（分），不含期初。"""
    con = connect()
    try:
        row = con.execute(
            "SELECT COALESCE(SUM(CASE "
            "WHEN type = 'income' THEN amount "
            "WHEN type = 'expense' THEN -amount "
            "WHEN type = 'transfer' AND account_id = ? THEN -amount "
            "WHEN type = 'transfer' AND to_account_id = ? THEN amount "
            "ELSE 0 END), 0) "
            "FROM transactions WHERE deleted_at IS NULL "
            "AND (account_id = ? OR to_account_id = ?)",
            (account_id, account_id, account_id, account_id),
        ).fetchone()
        return int(row[0])
    finally:
        con.close()


def reconcile_account(account_id: int, target_balance: Any) -> str:
    """按实际余额反推期初，使账户当前余额等于 target。"""
    target = cents(target_balance)
    flow = account_flow(account_id)
    opening = target - flow
    con = connect()
    try:
        con.execute(
            "UPDATE accounts SET opening_balance = ? WHERE id = ?",
            (opening, account_id),
        )
        con.commit()
    finally:
        con.close()
    return yuan(opening)


# -------------------------------------------------------------- categories


def list_categories() -> list[dict[str, Any]]:
    con = connect()
    try:
        counts = {
            row["category_id"]: row["n"]
            for row in con.execute(
                "SELECT category_id, COUNT(*) AS n FROM transactions "
                "WHERE deleted_at IS NULL GROUP BY category_id"
            ).fetchall()
        }
        return [
            {
                "id": row["id"],
                "name": row["name"],
                "kind": row["kind"],
                "sort": row["sort"],
                "count": counts.get(row["id"], 0),
            }
            for row in con.execute("SELECT * FROM categories ORDER BY sort, id").fetchall()
        ]
    finally:
        con.close()


def create_category(name: str, kind: str = "expense") -> int:
    con = connect()
    try:
        cursor = con.execute(
            "INSERT INTO categories (name, kind, sort) VALUES (?, ?, "
            "(SELECT COALESCE(MAX(sort), 0) + 1 FROM categories))",
            (name.strip(), kind),
        )
        con.commit()
        return int(cursor.lastrowid)
    finally:
        con.close()


def update_category(category_id: int, name: str | None = None, kind: str | None = None) -> None:
    fields, values = [], []
    if name is not None:
        fields.append("name = ?")
        values.append(name.strip())
    if kind is not None:
        fields.append("kind = ?")
        values.append(kind)
    if not fields:
        return
    values.append(category_id)
    con = connect()
    try:
        con.execute(f"UPDATE categories SET {', '.join(fields)} WHERE id = ?", values)
        con.commit()
    finally:
        con.close()


def delete_category(category_id: int) -> None:
    con = connect()
    try:
        used = con.execute(
            "SELECT COUNT(*) FROM transactions WHERE deleted_at IS NULL AND category_id = ?",
            (category_id,),
        ).fetchone()[0]
        if used:
            raise ValueError("分类下还有流水，不能删除")
        con.execute("DELETE FROM categories WHERE id = ?", (category_id,))
        con.commit()
    finally:
        con.close()


def category_id_by_name(name: str) -> int | None:
    con = connect()
    try:
        row = con.execute("SELECT id FROM categories WHERE name = ?", (name,)).fetchone()
        return int(row["id"]) if row else None
    finally:
        con.close()


# ------------------------------------------------------------ transactions

_TX_SELECT = """
SELECT t.*, a.name AS account_name, b.name AS to_account_name, c.name AS category_name
FROM transactions t
LEFT JOIN accounts a ON a.id = t.account_id
LEFT JOIN accounts b ON b.id = t.to_account_id
LEFT JOIN categories c ON c.id = t.category_id
WHERE t.deleted_at IS NULL
"""


def _tx_row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "date": row["date"],
        "time": row["time"],
        "type": row["type"],
        "amount": yuan(row["amount"]),
        "amount_cents": row["amount"],
        "account_id": row["account_id"],
        "account": row["account_name"] or "",
        "to_account_id": row["to_account_id"],
        "to_account": row["to_account_name"] or "",
        "category_id": row["category_id"],
        "category": row["category_name"] or "",
        "merchant": row["merchant"],
        "description": row["description"],
        "note": row["note"],
        "external_id": row["external_id"],
    }


def list_transactions(
    *,
    month: str | None = None,
    start: str | None = None,
    end: str | None = None,
    account_id: int | None = None,
    category_id: int | None = None,
    txn_type: str | None = None,
    query: str | None = None,
    limit: int = 200,
    offset: int = 0,
) -> dict[str, Any]:
    clauses, values = [], []
    if month:
        clauses.append("substr(t.date, 1, 7) = ?")
        values.append(month)
    if start:
        clauses.append("t.date >= ?")
        values.append(start)
    if end:
        clauses.append("t.date <= ?")
        values.append(end)
    if account_id:
        clauses.append("(t.account_id = ? OR t.to_account_id = ?)")
        values.extend([account_id, account_id])
    if category_id:
        clauses.append("t.category_id = ?")
        values.append(category_id)
    if txn_type in TXN_TYPES:
        clauses.append("t.type = ?")
        values.append(txn_type)
    if query:
        clauses.append("(t.merchant LIKE ? OR t.description LIKE ? OR t.note LIKE ?)")
        like = f"%{query}%"
        values.extend([like, like, like])

    where = (" AND " + " AND ".join(clauses)) if clauses else ""
    con = connect()
    try:
        total = con.execute(
            f"SELECT COUNT(*) FROM transactions t WHERE t.deleted_at IS NULL{where}",
            values,
        ).fetchone()[0]
        rows = con.execute(
            f"{_TX_SELECT}{where} ORDER BY t.date DESC, t.time DESC, t.id DESC LIMIT ? OFFSET ?",
            [*values, max(1, min(limit, 20000)), max(0, offset)],
        ).fetchall()
        sums = con.execute(
            "SELECT "
            "COALESCE(SUM(CASE WHEN t.type = 'expense' THEN t.amount END), 0) AS out_cents, "
            "COALESCE(SUM(CASE WHEN t.type = 'income' THEN t.amount END), 0) AS in_cents, "
            "COUNT(*) AS n "
            f"FROM transactions t WHERE t.deleted_at IS NULL{where}",
            values,
        ).fetchone()
        return {
            "items": [_tx_row(row) for row in rows],
            "total": total,
            "sums": {
                "out": yuan(sums["out_cents"]),
                "in": yuan(sums["in_cents"]),
                "count": sums["n"],
            },
        }
    finally:
        con.close()


def get_transaction(txn_id: int) -> dict[str, Any] | None:
    con = connect()
    try:
        row = con.execute(f"{_TX_SELECT} AND t.id = ?", (txn_id,)).fetchone()
        return _tx_row(row) if row else None
    finally:
        con.close()


def create_transaction(data: dict[str, Any]) -> int:
    now = int(time.time())
    con = connect()
    try:
        cursor = con.execute(
            "INSERT INTO transactions (date, time, type, amount, account_id, to_account_id, "
            "category_id, merchant, description, note, external_id, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                data["date"],
                data.get("time") or "12:00",
                data["type"],
                cents(data["amount"]),
                data["account_id"],
                data.get("to_account_id"),
                data.get("category_id"),
                (data.get("merchant") or "")[:120],
                (data.get("description") or "")[:200],
                (data.get("note") or "")[:500],
                data.get("external_id"),
                now,
                now,
            ),
        )
        con.commit()
        return int(cursor.lastrowid)
    finally:
        con.close()


def update_transaction(txn_id: int, data: dict[str, Any]) -> None:
    fields, values = [], []
    for key in ("date", "time", "type", "merchant", "description", "note", "external_id"):
        if key in data:
            fields.append(f"{key} = ?")
            values.append(data[key])
    if "amount" in data:
        fields.append("amount = ?")
        values.append(cents(data["amount"]))
    for key in ("account_id", "to_account_id", "category_id"):
        if key in data:
            fields.append(f"{key} = ?")
            values.append(data[key])
    if not fields:
        return
    fields.append("updated_at = ?")
    values.append(int(time.time()))
    values.append(txn_id)
    con = connect()
    try:
        con.execute(f"UPDATE transactions SET {', '.join(fields)} WHERE id = ?", values)
        con.commit()
    finally:
        con.close()


def delete_transaction(txn_id: int) -> None:
    con = connect()
    try:
        con.execute(
            "UPDATE transactions SET deleted_at = ?, updated_at = ? WHERE id = ?",
            (int(time.time()), int(time.time()), txn_id),
        )
        con.commit()
    finally:
        con.close()


# ------------------------------------------------------------- aggregates


def _month_shift(day: date, delta: int) -> date:
    index = day.year * 12 + day.month - 1 + delta
    return date(index // 12, index % 12 + 1, 1)


def month_range(month: str | None) -> tuple[date, date]:
    today = date.today()
    if month:
        start = date(int(month[:4]), int(month[5:7]), 1)
    else:
        start = today.replace(day=1)
    if start > today.replace(day=1):
        start = today.replace(day=1)
    end = min(_month_shift(start, 1) - timedelta(days=1), today)
    return start, end


def month_data(month: str) -> dict[str, Any]:
    start, end = month_range(month)
    result = list_transactions(start=start.isoformat(), end=end.isoformat(), limit=5000)
    return {
        "month": start.strftime("%Y-%m"),
        "range": {"start": start.isoformat(), "end": end.isoformat()},
        "items": result["items"],
        "stats": {
            "out": result["sums"]["out"],
            "in": result["sums"]["in"],
            "net": yuan(cents(result["sums"]["in"]) - cents(result["sums"]["out"])),
            "count_out": sum(1 for item in result["items"] if item["type"] == "expense"),
            "count_in": sum(1 for item in result["items"] if item["type"] == "income"),
        },
    }


def overview(month: str | None = None) -> dict[str, Any]:
    start, end = month_range(month)
    key = start.strftime("%Y-%m")
    trend_start = _month_shift(start, -11)

    accounts = list_accounts()
    net_worth = sum(cents(a["balance"]) for a in accounts)

    result = list_transactions(start=trend_start.isoformat(), end=end.isoformat(), limit=5000)
    all_items = result["items"]

    months: dict[str, dict[str, int]] = {}
    cursor = trend_start
    while cursor <= start:
        months[cursor.strftime("%Y-%m")] = {"in": 0, "out": 0}
        cursor = _month_shift(cursor, 1)

    month_items = []
    by_category: dict[str, int] = {}
    by_merchant: dict[str, dict[str, Any]] = {}
    active_days: set[str] = set()
    total_out = total_in = 0

    for item in all_items:
        item_month = item["date"][:7]
        amount = item["amount_cents"]
        if item_month in months:
            if item["type"] == "expense":
                months[item_month]["out"] += amount
            elif item["type"] == "income":
                months[item_month]["in"] += amount
        if item_month != key:
            continue
        month_items.append(item)
        if item["type"] == "expense":
            total_out += amount
            active_days.add(item["date"])
            by_category[item["category"] or "未分类"] = by_category.get(item["category"] or "未分类", 0) + amount
            entry = by_merchant.setdefault(item["merchant"] or "未命名", {"amount": 0, "count": 0})
            entry["amount"] += amount
            entry["count"] += 1
        elif item["type"] == "income":
            total_in += amount

    month_items.sort(key=lambda x: (x["date"], x["time"]), reverse=True)

    return {
        "month": key,
        "range": {"start": start.isoformat(), "end": end.isoformat()},
        "accounts": [{"id": a["id"], "name": a["name"], "balance": a["balance"]} for a in accounts],
        "net_worth": yuan(net_worth),
        "month_stats": {
            "out": yuan(total_out),
            "in": yuan(total_in),
            "net": yuan(total_in - total_out),
            "count_out": sum(1 for item in month_items if item["type"] == "expense"),
            "daily_avg": yuan(total_out // len(active_days)) if active_days else "0.00",
            "active_days": len(active_days),
        },
        "months": [
            {"month": name, "in": yuan(value["in"]), "out": yuan(value["out"])}
            for name, value in months.items()
        ],
        "by_category": [
            {"name": name, "amount": yuan(amount)}
            for name, amount in sorted(by_category.items(), key=lambda x: -x[1])
        ],
        "top_merchants": [
            {"name": name, "amount": yuan(value["amount"]), "count": value["count"]}
            for name, value in sorted(by_merchant.items(), key=lambda x: -x[1]["amount"])[:8]
        ],
        "recent": month_items[:10],
    }


def aggregate(start: date, end: date) -> dict[str, Any]:
    """给 AI 分析用的区间聚合。"""
    result = list_transactions(start=start.isoformat(), end=end.isoformat(), limit=5000)
    items = result["items"]
    total_out = total_in = 0
    count_out = count_in = 0
    by_category: dict[str, dict[str, Any]] = {}
    by_account: dict[str, int] = {}
    merchants: dict[str, dict[str, Any]] = {}
    by_month: dict[str, dict[str, int]] = {}
    largest = []
    small_count = 0
    small_amount = 0
    weekend_out = weekday_out = 0

    for item in items:
        amount = item["amount_cents"]
        bucket = by_month.setdefault(item["date"][:7], {"out": 0, "in": 0})
        if item["type"] == "expense":
            total_out += amount
            count_out += 1
            bucket["out"] += amount
            category = item["category"] or "未分类"
            cat = by_category.setdefault(category, {"amount": 0, "count": 0})
            cat["amount"] += amount
            cat["count"] += 1
            by_account[item["account"]] = by_account.get(item["account"], 0) + amount
            merchant = item["merchant"] or "未命名"
            entry = merchants.setdefault(merchant, {"amount": 0, "count": 0})
            entry["amount"] += amount
            entry["count"] += 1
            largest.append({
                "date": item["date"],
                "description": merchant,
                "amount": yuan(amount),
                "category": category,
                "account": item["account"],
            })
            if amount <= 1000:
                small_count += 1
                small_amount += amount
            try:
                if date.fromisoformat(item["date"]).weekday() >= 5:
                    weekend_out += amount
                else:
                    weekday_out += amount
            except ValueError:
                pass
        elif item["type"] == "income":
            total_in += amount
            count_in += 1
            bucket["in"] += amount

    days = max((end - start).days + 1, 1)
    return {
        "range": {"start": start.isoformat(), "end": end.isoformat(), "days": days},
        "total_out": yuan(total_out),
        "total_in": yuan(total_in),
        "net": yuan(total_in - total_out),
        "count_out": count_out,
        "count_in": count_in,
        "daily_avg": yuan(total_out // days),
        "by_category": [
            {"name": name, "amount": yuan(value["amount"]), "count": value["count"]}
            for name, value in sorted(by_category.items(), key=lambda x: -x[1]["amount"])
        ],
        "by_account": [
            {"name": name, "amount": yuan(value)}
            for name, value in sorted(by_account.items(), key=lambda x: -x[1])
        ],
        "by_month": [
            {"month": name, "out": yuan(value["out"]), "in": yuan(value["in"])}
            for name, value in sorted(by_month.items())
        ],
        "top_merchants": [
            {"name": name, "amount": yuan(value["amount"]), "count": value["count"]}
            for name, value in sorted(merchants.items(), key=lambda x: -x[1]["amount"])[:12]
        ],
        "largest": sorted(largest, key=lambda x: -cents(x["amount"]))[:10],
        "small_frequent": {"count": small_count, "amount": yuan(small_amount)},
        "weekend_out": yuan(weekend_out),
        "weekday_out": yuan(weekday_out),
    }
