import json
from typing import Any

import httpx

from labtools.runtime import BILL_AI_URL, mcp


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
        with httpx.Client(timeout=10) as client:
            response = client.get(f"{BILL_AI_URL}/api/transactions", params=params)
            response.raise_for_status()
            data = response.json()
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
