import json
import re
from urllib.parse import urlparse

import httpx

from labtools.runtime import METUBE_URL, mcp
from labtools.tools.search import SOURCES, SourceUnavailable, search_entries

# 只允许写入这几个目录，模型不能拼任意路径
TARGETS = {
    "game_video": "/downloads/game_video",
    "yt_video": "/downloads/yt_video",
    "movies": "/downloads/movies",
    "anime": "/downloads/anime",
}

# 分享口令里夹带的链接（“7.43 复制打开抖音…”之类），抖音/B站/YouTube 的分享文本都能命中
URL_RE = re.compile(r"https?://[^\s<>\"'，。！？；、（）()【】《》]+")


def _extract_link(text: str) -> str:
    match = URL_RE.search(text or "")
    return match.group(0).rstrip(".,;:") if match else ""


def _safe_name(name: str) -> str:
    """剧名做目录名/文件名前缀：去掉路径分隔符与 Windows 非法字符。"""
    cleaned = re.sub(r'[\\/:*?"<>|]+', " ", name or "")
    return re.sub(r"\s+", " ", cleaned).strip()[:80]


def _submit(link: str, target: str, limit: int, items: str, series: str = "") -> dict:
    payload = {"url": link, "folder": target}
    if int(limit) > 0:
        payload["playlist_item_limit"] = min(int(limit), 100)

    overrides = {}
    if items.strip():
        overrides["playlist_items"] = items.strip()
    if series:
        # 番剧：落到 <target>/<剧名>/Season 01/剧名 - S01E01.mp4，Jellyfin 才能识别成剧集
        payload["folder"] = f"{target}/{series}"
        overrides["outtmpl"] = f"Season 01/{series} - S01E%(playlist_index,autonumber)02d.%(ext)s"
    if overrides:
        payload["ytdl_options_overrides"] = overrides

    try:
        with httpx.Client(timeout=15) as client:
            response = client.post(f"{METUBE_URL}/add", json=payload)
            response.raise_for_status()
    except Exception as exc:
        return {"error": "MeTube 不可达", "detail": str(exc), "url": METUBE_URL}

    try:
        result = response.json()
    except Exception:
        result = {}

    if isinstance(result, dict) and result.get("status") == "error":
        return {"queued": False, "error": result.get("msg") or "MeTube 拒绝了该链接"}
    return {"queued": True, "detail": result or (response.text or "added")[:300]}


@mcp.tool()
def download_media(
    url: str = "",
    query: str = "",
    target: str = "anime",
    limit: int = 0,
    items: str = "",
    source: str = "bilibili",
    series: str = "",
) -> str:
    """把视频/番剧/电影下载到指定目录。

    用户给了链接就传 url（可以是抖音/B站/YouTube 的分享口令或纯文本，会自动提取链接）；
    只说了片名（如“你的名字”“BanG Dream 第一季”）就传 query，source 决定去哪搜：
    bilibili（默认）或 youtube（当前网络多半不可达）。
    target 只接受 game_video、yt_video、movies、anime；limit 为 0 表示全部，>0 时只下前 N 项；
    items 选具体集数，如 "10-13" 或 "1,3,5"。
    target 为 anime 时传 series（干净的剧名，如“砂糖的幸福生活”）会按
    anime/<剧名>/Season 01/剧名 - S01E01.mp4 落盘，Jellyfin 直接当剧集识别；不传则退回 query。
    返回实际选中的片源和排队结果，不等待下载完成。
    """
    if target not in TARGETS:
        return json.dumps(
            {"error": "target 不在白名单", "allowed": sorted(TARGETS), "target": target},
            ensure_ascii=False,
        )
    if source not in SOURCES:
        return json.dumps(
            {"error": "source 不支持", "allowed": list(SOURCES), "source": source},
            ensure_ascii=False,
        )

    if items.strip() and not re.fullmatch(r"[\d,\-]+", items.strip()):
        return json.dumps({"error": "items 只接受数字、逗号和连字符，如 10-13", "items": items}, ensure_ascii=False)

    link = _extract_link(url)
    chosen = None
    candidates = []

    if not link:
        keyword = (query or "").strip()
        if not keyword:
            if (url or "").strip():
                return json.dumps(
                    {"error": "url 里没找到 http/https 链接", "url": url, "hint": "直接粘贴完整链接或分享口令"},
                    ensure_ascii=False,
                )
            return json.dumps({"error": "要么给 url（链接/分享口令），要么给 query（片名）"}, ensure_ascii=False)

        try:
            candidates = search_entries(keyword, "all", 6, source)
        except SourceUnavailable as exc:
            return json.dumps(
                {"queued": False, "keyword": keyword, "source": source,
                 "error": f"{source} 不可达", "detail": str(exc)},
                ensure_ascii=False,
            )
        if not candidates:
            return json.dumps(
                {"queued": False, "keyword": keyword, "source": source, "found": False,
                 "hint": f"{source} 没搜到；可换片名/加标点，或用户直接给链接"},
                ensure_ascii=False,
            )
        chosen = candidates[0]
        link = chosen["url"]
    else:
        parsed = urlparse(link)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            return json.dumps({"error": "只接受 http/https 链接", "url": url}, ensure_ascii=False)

    # 番剧按 Jellyfin 规范命名；没给 series 时退回用户说的片名
    series_name = ""
    if target == "anime":
        series_name = _safe_name(series) or _safe_name(query)

    result = _submit(link, target, limit, items, series_name)

    payload = {
        "target": target,
        "container_path": TARGETS[target],
        "url": link,
    }
    if series_name:
        payload["series"] = series_name
        payload["layout"] = f"{target}/{series_name}/Season 01/{series_name} - S01E01.mp4"
    if chosen:
        payload["source"] = source
        payload["chosen"] = {"title": chosen["title"], "kind": chosen["kind"], "episodes": chosen["episodes"]}
        rest = [c for c in candidates if c["url"] != link][:4]
        if rest:
            payload["alternatives"] = [{"title": c["title"], "url": c["url"]} for c in rest]
    payload.update(result)
    return json.dumps(payload, ensure_ascii=False, indent=2)
