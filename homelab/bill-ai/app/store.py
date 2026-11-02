"""SQLite 账本：账户、分类、流水，以及聚合查询。

金额统一用「分」存整数，排序和汇总都在 Python 侧完成（数据量在万级以内）。
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import time
from datetime import date, datetime, timedelta
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
                -- 余额最后一次被确认的时间与来源（sms / notification / manual / ocr）
                balance_updated_at TEXT,
                balance_source TEXT,
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

            -- 手机上报的短信/通知原文，确认后才写入 transactions
            CREATE TABLE IF NOT EXISTS inbox (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source TEXT NOT NULL,
                sender TEXT NOT NULL DEFAULT '',
                raw_text TEXT NOT NULL,
                received_at INTEGER NOT NULL,
                device TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'pending',
                txn_id INTEGER,
                parsed TEXT NOT NULL DEFAULT '',
                note TEXT NOT NULL DEFAULT '',
                fingerprint TEXT NOT NULL UNIQUE,
                created_at INTEGER NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_inbox_status ON inbox(status, id DESC);

            -- 已写入过的账单指纹，避免同一笔重复入账
            CREATE TABLE IF NOT EXISTS committed (
                hash TEXT PRIMARY KEY,
                group_id TEXT,
                created_at INTEGER NOT NULL
            );

            -- 卡号尾号 → 账户的映射，短信只认得出尾号时靠它匹配
            CREATE TABLE IF NOT EXISTS account_cards (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_id INTEGER NOT NULL REFERENCES accounts(id),
                card_tail TEXT NOT NULL,
                sender TEXT NOT NULL DEFAULT '',
                created_at INTEGER NOT NULL
            );

            CREATE UNIQUE INDEX IF NOT EXISTS idx_card_tail
                ON account_cards(account_id, card_tail, sender);

            -- 短信/通知/截图识别出的余额候选，人工核对后才回写账户余额
            CREATE TABLE IF NOT EXISTS account_balance_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_id INTEGER REFERENCES accounts(id),
                card_tail TEXT NOT NULL DEFAULT '',
                balance INTEGER NOT NULL,
                currency TEXT NOT NULL DEFAULT 'CNY',
                source TEXT NOT NULL,
                observed_at TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                raw_text TEXT NOT NULL DEFAULT '',
                raw_hash TEXT NOT NULL,
                dedup_key TEXT NOT NULL,
                sender TEXT NOT NULL DEFAULT '',
                note TEXT NOT NULL DEFAULT '',
                created_at INTEGER NOT NULL,
                decided_at INTEGER
            );

            CREATE UNIQUE INDEX IF NOT EXISTS idx_balance_raw
                ON account_balance_snapshots(raw_hash);
            CREATE UNIQUE INDEX IF NOT EXISTS idx_balance_dedup
                ON account_balance_snapshots(dedup_key);
            CREATE INDEX IF NOT EXISTS idx_balance_status
                ON account_balance_snapshots(status, id DESC);
            """
        )
        # 老库补齐余额新鲜度字段；SQLite 不支持 ADD COLUMN IF NOT EXISTS
        existing = {row["name"] for row in con.execute("PRAGMA table_info(accounts)")}
        for column, ddl in (("balance_updated_at", "TEXT"), ("balance_source", "TEXT")):
            if column not in existing:
                con.execute(f"ALTER TABLE accounts ADD COLUMN {column} {ddl}")
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


def _iso(ts: int | None) -> str | None:
    if not ts:
        return None
    return datetime.fromtimestamp(int(ts)).astimezone().isoformat(timespec="seconds")


def iso_now() -> str:
    return _iso(int(time.time())) or ""


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
                "balance_updated_at": row["balance_updated_at"],
                "balance_source": row["balance_source"],
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


def reconcile_account(
    account_id: int,
    target_balance: Any,
    *,
    source: str = "manual",
    updated_at: str | None = None,
) -> str:
    """按实际余额反推期初，使账户当前余额等于 target，并记录新鲜度。"""
    target = cents(target_balance)
    flow = account_flow(account_id)
    opening = target - flow
    con = connect()
    try:
        con.execute(
            "UPDATE accounts SET opening_balance = ?, balance_updated_at = ?, balance_source = ? "
            "WHERE id = ?",
            (opening, updated_at or iso_now(), source, account_id),
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


# ------------------------------------------------------------------ inbox


def _inbox_row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "source": row["source"],
        "sender": row["sender"],
        "raw_text": row["raw_text"],
        "received_at": row["received_at"],
        "device": row["device"],
        "status": row["status"],
        "txn_id": row["txn_id"],
        "parsed": json.loads(row["parsed"]) if row["parsed"] else None,
        "note": row["note"],
        "fingerprint": row["fingerprint"],
        "created_at": row["created_at"],
    }


def add_inbox(
    *,
    source: str,
    sender: str,
    raw_text: str,
    received_at: int,
    device: str,
    fingerprint: str,
    parsed: dict[str, Any] | None,
    note: str = "",
) -> tuple[int, bool]:
    """写入一条待入账消息，返回 (id, 是否新建)。同一个 fingerprint 只保留一条。"""
    payload = json.dumps(parsed, ensure_ascii=False) if parsed else ""
    con = connect()
    try:
        cursor = con.execute(
            "INSERT OR IGNORE INTO inbox "
            "(source, sender, raw_text, received_at, device, status, parsed, note, fingerprint, created_at) "
            "VALUES (?, ?, ?, ?, ?, 'pending', ?, ?, ?, ?)",
            (source, sender, raw_text, received_at, device, payload, note, fingerprint, int(time.time())),
        )
        con.commit()
        if cursor.rowcount:
            return int(cursor.lastrowid), True
        row = con.execute("SELECT id FROM inbox WHERE fingerprint = ?", (fingerprint,)).fetchone()
        return int(row["id"]), False
    finally:
        con.close()


def list_inbox(status: str = "pending", limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
    con = connect()
    try:
        if status == "all":
            rows = con.execute(
                "SELECT * FROM inbox ORDER BY id DESC LIMIT ? OFFSET ?",
                (max(1, min(limit, 500)), max(0, offset)),
            ).fetchall()
        else:
            rows = con.execute(
                "SELECT * FROM inbox WHERE status = ? ORDER BY id DESC LIMIT ? OFFSET ?",
                (status, max(1, min(limit, 500)), max(0, offset)),
            ).fetchall()
        return [_inbox_row(row) for row in rows]
    finally:
        con.close()


def get_inbox(inbox_id: int) -> dict[str, Any] | None:
    con = connect()
    try:
        row = con.execute("SELECT * FROM inbox WHERE id = ?", (inbox_id,)).fetchone()
        return _inbox_row(row) if row else None
    finally:
        con.close()


def update_inbox_parsed(inbox_id: int, parsed: dict[str, Any] | None, note: str | None = None) -> None:
    con = connect()
    try:
        fields, values = ["parsed = ?"], [json.dumps(parsed, ensure_ascii=False) if parsed else ""]
        if note is not None:
            fields.append("note = ?")
            values.append(note)
        values.append(inbox_id)
        con.execute(f"UPDATE inbox SET {', '.join(fields)} WHERE id = ?", values)
        con.commit()
    finally:
        con.close()


def finish_inbox(inbox_id: int, status: str, txn_id: int | None = None, note: str | None = None) -> None:
    fields = ["status = ?", "txn_id = ?"]
    values: list[Any] = [status, txn_id]
    if note is not None:
        fields.append("note = ?")
        values.append(note)
    values.append(inbox_id)
    con = connect()
    try:
        con.execute(f"UPDATE inbox SET {', '.join(fields)} WHERE id = ?", values)
        con.commit()
    finally:
        con.close()


def inbox_pending_count() -> int:
    con = connect()
    try:
        return int(con.execute("SELECT COUNT(*) FROM inbox WHERE status = 'pending'").fetchone()[0])
    finally:
        con.close()


# ------------------------------------------------------- balance snapshots

RAW_EXCERPT_CHARS = 80


def mask_numbers(text: str) -> str:
    """8 位以上连续数字只保留后 4 位，避免列表和日志泄露完整卡号。"""
    return re.sub(
        r"\d{8,}",
        lambda match: "*" * (len(match.group(0)) - 4) + match.group(0)[-4:],
        text or "",
    )


def _excerpt(text: str, limit: int = RAW_EXCERPT_CHARS) -> str:
    compact = " ".join(mask_numbers(text).split())
    return compact if len(compact) <= limit else compact[:limit] + "…"


def _account_for_card(con: sqlite3.Connection, card_tail: str, sender: str) -> int | None:
    """按 sender + 尾号匹配账户映射；sender 对不上时只有尾号唯一才采用。"""
    if not card_tail:
        return None
    row = con.execute(
        "SELECT account_id FROM account_cards WHERE card_tail = ? AND sender = ? "
        "ORDER BY id DESC LIMIT 1",
        (card_tail, sender or ""),
    ).fetchone()
    if row:
        return int(row["account_id"])
    rows = con.execute(
        "SELECT DISTINCT account_id FROM account_cards WHERE card_tail = ?",
        (card_tail,),
    ).fetchall()
    return int(rows[0]["account_id"]) if len(rows) == 1 else None


def add_balance_candidate(
    candidate: Any,
    *,
    sender: str = "",
    raw_text: str = "",
) -> tuple[int, bool]:
    """写入一条 pending 候选，按 raw_hash / dedup_key 幂等，返回 (id, 是否新建)。"""
    now = int(time.time())
    con = connect()
    try:
        account_id = _account_for_card(con, candidate.card_tail, sender)
        cursor = con.execute(
            "INSERT OR IGNORE INTO account_balance_snapshots "
            "(account_id, card_tail, balance, currency, source, observed_at, status, raw_text, "
            "raw_hash, dedup_key, sender, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?, ?, ?)",
            (
                account_id,
                candidate.card_tail,
                cents(candidate.balance),
                candidate.currency or "CNY",
                candidate.source,
                candidate.observed_at,
                (raw_text or "")[:500],
                candidate.raw_hash,
                candidate.dedup_key,
                sender or "",
                now,
            ),
        )
        con.commit()
        if cursor.rowcount:
            return int(cursor.lastrowid), True
        row = con.execute(
            "SELECT id FROM account_balance_snapshots WHERE raw_hash = ? OR dedup_key = ? "
            "ORDER BY id LIMIT 1",
            (candidate.raw_hash, candidate.dedup_key),
        ).fetchone()
        return int(row["id"]), False
    finally:
        con.close()


def list_balance_candidates(
    status: str = "pending",
    limit: int = 50,
    anomaly_ratio: float = 0.5,
) -> dict[str, Any]:
    con = connect()
    try:
        sql = "SELECT * FROM account_balance_snapshots"
        params: list[Any] = []
        if status != "all":
            sql += " WHERE status = ?"
            params.append(status)
        sql += " ORDER BY observed_at DESC, id DESC LIMIT ?"
        params.append(max(1, min(limit, 200)))
        rows = con.execute(sql, params).fetchall()
        accounts = {
            row["id"]: row["name"]
            for row in con.execute("SELECT id, name FROM accounts").fetchall()
        }
        balances = _balances(con)
        items = []
        for row in rows:
            account_id = row["account_id"]
            balance_cents = int(row["balance"])
            current = balances.get(account_id) if account_id else None
            anomaly = False
            if current is not None and current != 0:
                anomaly = abs(balance_cents - current) / abs(current) > anomaly_ratio
            items.append({
                "id": row["id"],
                "account_id": account_id,
                "account_name": accounts.get(account_id, ""),
                "card_tail": row["card_tail"],
                "balance": yuan(balance_cents),
                "currency": row["currency"],
                "source": row["source"],
                "observed_at": row["observed_at"],
                "created_at": _iso(row["created_at"]),
                "raw_excerpt": _excerpt(row["raw_text"]),
                "current_balance": None if current is None else yuan(current),
                "delta": None if current is None else yuan(balance_cents - current),
                "anomaly": anomaly,
                "status": row["status"],
            })
        return {"items": items, "pending_count": pending_balance_count()}
    finally:
        con.close()


def confirm_balance_candidates(
    ids: list[int],
    account_id: int | None = None,
) -> dict[str, Any]:
    """确认候选：写 confirmed、记下卡号映射，并把最新一条回写到账户余额。"""
    now = int(time.time())
    results: list[dict[str, Any]] = []
    confirmed: list[dict[str, Any]] = []
    con = connect()
    try:
        known_accounts = {
            int(row["id"]) for row in con.execute("SELECT id FROM accounts").fetchall()
        }
        for raw_id in ids:
            snapshot_id = int(raw_id)
            row = con.execute(
                "SELECT * FROM account_balance_snapshots WHERE id = ?", (snapshot_id,)
            ).fetchone()
            if not row:
                results.append({"id": snapshot_id, "status": "missing", "error": "记录不存在"})
                continue
            if row["status"] != "pending":
                results.append({
                    "id": snapshot_id,
                    "status": row["status"],
                    "error": "已经处理过了",
                })
                continue
            target = row["account_id"] or account_id
            if not target:
                results.append({
                    "id": snapshot_id,
                    "status": "skipped",
                    "error": "还没指定账户",
                })
                continue
            if int(target) not in known_accounts:
                results.append({
                    "id": snapshot_id,
                    "status": "skipped",
                    "error": "账户不存在",
                })
                continue
            con.execute(
                "UPDATE account_balance_snapshots "
                "SET account_id = ?, status = 'confirmed', decided_at = ? WHERE id = ?",
                (int(target), now, snapshot_id),
            )
            if row["card_tail"]:
                con.execute(
                    "INSERT OR IGNORE INTO account_cards "
                    "(account_id, card_tail, sender, created_at) VALUES (?, ?, ?, ?)",
                    (int(target), row["card_tail"], row["sender"], now),
                )
            confirmed.append({
                "account_id": int(target),
                "balance": yuan(row["balance"]),
                "source": row["source"],
                "observed_at": row["observed_at"],
            })
            results.append({
                "id": snapshot_id,
                "status": "confirmed",
                "account_id": int(target),
                "balance": yuan(row["balance"]),
            })
        con.commit()
    finally:
        con.close()

    # 同一账户一次确认多条时，只让 observed_at 最新的那条决定余额
    latest: dict[int, dict[str, Any]] = {}
    for item in confirmed:
        current = latest.get(item["account_id"])
        if current is None or item["observed_at"] > current["observed_at"]:
            latest[item["account_id"]] = item
    if latest:
        con = connect()
        try:
            fresh = {
                int(row["id"]): row["balance_updated_at"]
                for row in con.execute("SELECT id, balance_updated_at FROM accounts").fetchall()
            }
        finally:
            con.close()
        for target, item in latest.items():
            # 已经同步过更新的余额时，迟到的旧候选不覆盖
            if fresh.get(target) and fresh[target] > item["observed_at"]:
                continue
            reconcile_account(
                target,
                item["balance"],
                source=item["source"],
                updated_at=item["observed_at"],
            )
    return {"items": results, "pending_count": pending_balance_count()}


def reject_balance_candidates(ids: list[int], note: str = "") -> dict[str, Any]:
    now = int(time.time())
    results: list[dict[str, Any]] = []
    con = connect()
    try:
        for raw_id in ids:
            snapshot_id = int(raw_id)
            row = con.execute(
                "SELECT status FROM account_balance_snapshots WHERE id = ?", (snapshot_id,)
            ).fetchone()
            if not row:
                results.append({"id": snapshot_id, "status": "missing", "error": "记录不存在"})
                continue
            if row["status"] != "pending":
                results.append({
                    "id": snapshot_id,
                    "status": row["status"],
                    "error": "已经处理过了",
                })
                continue
            con.execute(
                "UPDATE account_balance_snapshots "
                "SET status = 'rejected', decided_at = ?, note = ? WHERE id = ?",
                (now, note or "人工驳回", snapshot_id),
            )
            results.append({"id": snapshot_id, "status": "rejected"})
        con.commit()
    finally:
        con.close()
    return {"items": results, "pending_count": pending_balance_count()}


def expire_balance_candidates(days: int = 7) -> int:
    """pending 超过 N 天自动驳回，返回处理条数。"""
    keep_days = max(1, int(days))
    now = int(time.time())
    cutoff = now - keep_days * 86400
    con = connect()
    try:
        cursor = con.execute(
            "UPDATE account_balance_snapshots "
            "SET status = 'rejected', decided_at = ?, note = ? "
            "WHERE status = 'pending' AND created_at < ?",
            (now, f"超过 {keep_days} 天未确认，自动驳回", cutoff),
        )
        con.commit()
        return int(cursor.rowcount or 0)
    finally:
        con.close()


def pending_balance_count() -> int:
    con = connect()
    try:
        return int(con.execute(
            "SELECT COUNT(*) FROM account_balance_snapshots WHERE status = 'pending'"
        ).fetchone()[0])
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
        "accounts": [
            {
                "id": a["id"],
                "name": a["name"],
                "balance": a["balance"],
                "balance_updated_at": a["balance_updated_at"],
                "balance_source": a["balance_source"],
            }
            for a in accounts
        ],
        "pending_balance_candidates": pending_balance_count(),
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
