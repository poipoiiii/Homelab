import json
from urllib.parse import urlparse

import httpx

from labtools.runtime import METUBE_URL, mcp

# 只允许写入这三个目录，模型不能拼任意路径
TARGETS = {
    "game_video": "/downloads/game_video",
    "yt_video": "/downloads/yt_video",
    "movies": "/downloads/movies",
}


@mcp.tool()
def download_media(url: str, target: str = "game_video", limit: int = 0) -> str:
    """把视频/番剧链接交给 MeTube 下载。target 只接受 game_video、yt_video、movies；limit 为 0 表示全部，>0 时只下载前 N 项。返回排队结果，不等待下载完成。"""
    link = (url or "").strip()
    parsed = urlparse(link)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return json.dumps({"error": "只接受 http/https 链接", "url": url}, ensure_ascii=False)

    if target not in TARGETS:
        return json.dumps(
            {"error": "target 不在白名单", "allowed": sorted(TARGETS), "target": target},
            ensure_ascii=False,
        )

    payload = {"url": link, "folder": target}
    if int(limit) > 0:
        payload["playlist_item_limit"] = min(int(limit), 100)
    try:
        with httpx.Client(timeout=15) as client:
            response = client.post(f"{METUBE_URL}/add", json=payload)
            response.raise_for_status()
    except Exception as exc:
        return json.dumps(
            {"error": "MeTube 不可达", "detail": str(exc), "url": METUBE_URL},
            ensure_ascii=False,
        )

    try:
        result = response.json()
    except Exception:
        result = {}

    if isinstance(result, dict) and result.get("status") == "error":
        return json.dumps({
            "queued": False,
            "target": target,
            "error": result.get("msg") or "MeTube 拒绝了该链接",
        }, ensure_ascii=False, indent=2)

    return json.dumps({
        "queued": True,
        "target": target,
        "container_path": TARGETS[target],
        "detail": result or (response.text or "added")[:500],
    }, ensure_ascii=False, indent=2)
