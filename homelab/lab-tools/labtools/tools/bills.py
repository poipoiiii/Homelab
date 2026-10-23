import json
from datetime import date, timedelta
from typing import Any

import httpx

from labtools.runtime import BILL_AI_URL, mcp

PAGE = 100
MAX_ROWS = 2000  # 防止把整本账都拉下来


def _fetch(params: dict[str, Any]) -> dict[str, Any]:
    with httpx.Client(timeout=10) as client:
        response = client.get(f"{BILL_AI_URL}/api/transactions", params=params)
        response.raise_for_status()
        return response.json()


@mcp.tool()
def recent_expenses(limit: int = 5, month: str | None = None, query: str | None = None) -> str:
    """查询记账应用里的最近流水。limit 默认 5、最多 20；month 形如 2026-10；query 可按商户/备注搜索。只读。"""
    limit = max(1, min(int(limit), 20))
    params: dict[str, Any] = {"limit": limit}
    if month:
        params["month"] = month
    if query:
        params["q"] = query

    try:
        data = _fetch(params)
    except Exception as exc:
        return json.dumps(
            {"error": "记账服务不可达", "detail": str(exc), "url": BILL_AI_URL},
            ensure_ascii=False,
        )

    return json.dumps({
        "total": data.get("total"),
        "sums": data.get("sums"),
        "items": (data.get("items") or [])[:limit],
    }, ensure_ascii=False, indent=2)


@mcp.tool()
def largest_expenses(days: int = 90, top: int = 5) -> str:
    """按金额从大到小列出最近 days 天里最大的几笔支出（默认 90 天、前 5 笔）。问“最近最大的一笔开销”时用它。只读。"""
    days = max(1, min(int(days), 3650))
    top = max(1, min(int(top), 20))
    end = date.today()
    start = end - timedelta(days=days)

    rows: list[dict[str, Any]] = []
    offset = 0
    try:
        while offset < MAX_ROWS:
            data = _fetch({
                "start": start.isoformat(),
                "end": end.isoformat(),
                "type": "expense",
                "limit": PAGE,
                "offset": offset,
            })
            batch = data.get("items") or []
            rows.extend(batch)
            total = int(data.get("total") or 0)
            offset += PAGE
            if len(batch) < PAGE or offset >= total:
                break
    except Exception as exc:
        return json.dumps(
            {"error": "记账服务不可达", "detail": str(exc), "url": BILL_AI_URL},
            ensure_ascii=False,
        )

    rows.sort(key=lambda r: r.get("amount_cents", 0), reverse=True)
    return json.dumps({
        "range": {"start": start.isoformat(), "end": end.isoformat(), "days": days},
        "scanned": len(rows),
        "largest": rows[:top],
    }, ensure_ascii=False, indent=2)
