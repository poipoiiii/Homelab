"""片源搜索：让 Agent 只凭片名就能找到链接，不必用户手贴 URL。

B 站走官方搜索接口 + 本地 cookies；YouTube 走 yt-dlp 的 ytsearch（无需 API key）。
抖音网页搜索接口需要 a_bogus 签名，实测直接返回 blocked，所以抖音只支持贴链接下载。
"""

import json
import re
import time

import httpx

from labtools.runtime import BILI_COOKIES, mcp

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
SEARCH_URL = "https://api.bilibili.com/x/web-interface/search/type"

SOURCES = ("bilibili", "youtube")


class SourceUnavailable(RuntimeError):
    """片源站点不可达（如当前网络连不上 YouTube）。"""

# kind -> 依次尝试的搜索类型；media_ft 是电影/电视剧，media_bangumi 是番剧
KINDS = {
    "all": ("media_bangumi", "media_ft", "video"),
    "bangumi": ("media_bangumi",),
    "movie": ("media_ft",),
    "video": ("video",),
}


def _cookies() -> str:
    """整条 cookie 头（SESSDATA + buvid3 + b_nut 等），缺 buvid 时搜索接口容易 412。"""
    jar = []
    try:
        with open(BILI_COOKIES, encoding="utf-8") as fh:
            for line in fh:
                parts = line.rstrip("\n").split("\t")
                if len(parts) >= 7 and parts[5]:
                    jar.append(f"{parts[5]}={parts[6]}")
    except OSError:
        pass
    return "; ".join(jar)


def _clean(title: str) -> str:
    return re.sub(r"<[^>]+>", "", title or "").strip()


def _normalize(title: str) -> str:
    return re.sub(r"[\s\W_]+", "", title or "").lower()


def _query(search_type: str, keyword: str) -> list[dict]:
    headers = {
        "User-Agent": UA,
        "Referer": "https://search.bilibili.com/",
        "Origin": "https://search.bilibili.com",
        "Accept": "application/json, text/plain, */*",
    }
    cookie = _cookies()
    if cookie:
        headers["Cookie"] = cookie

    params = {"search_type": search_type, "keyword": keyword, "page": 1}
    payload = {}
    for attempt in range(3):
        with httpx.Client(timeout=15, headers=headers) as client:
            response = client.get(SEARCH_URL, params=params)
        if response.status_code == 412:  # 风控：退避后重试
            time.sleep(2 + attempt * 3)
            continue
        response.raise_for_status()
        payload = response.json()
        break

    if payload.get("code") != 0:
        return []

    entries = []
    for item in (payload.get("data") or {}).get("result") or []:
        title = _clean(item.get("title"))
        if not title:
            continue
        if search_type == "video":
            bvid = item.get("bvid")
            if not bvid:
                continue
            url = f"https://www.bilibili.com/video/{bvid}"
            entries.append({
                "title": title,
                "url": url,
                "kind": "video",
                "author": item.get("author"),
                "duration": item.get("duration"),
                "episodes": 1,
            })
        else:
            season_id = item.get("season_id")
            if not season_id:
                continue
            entries.append({
                "title": title,
                "url": f"https://www.bilibili.com/bangumi/play/ss{season_id}",
                "kind": "bangumi" if search_type == "media_bangumi" else "movie",
                "author": None,
                "duration": None,
                "episodes": item.get("eps_count"),
            })
    return entries


def search_youtube_entries(keyword: str, limit: int = 6) -> list[dict]:
    """用 yt-dlp 的 ytsearch 搜 YouTube；网络不通时抛 SourceUnavailable。"""
    from yt_dlp import YoutubeDL

    count = max(1, min(int(limit), 15))
    options = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "extract_flat": "in_playlist",
        "socket_timeout": 10,
        "retries": 1,
        "playlistend": count,
    }
    try:
        with YoutubeDL(options) as ydl:
            info = ydl.extract_info(f"ytsearch{count}:{keyword}", download=False)
    except Exception as exc:
        raise SourceUnavailable(str(exc)[:200] or "YouTube 不可达") from exc

    entries = []
    for item in (info or {}).get("entries") or []:
        if not item:
            continue
        video_id = item.get("id")
        url = item.get("webpage_url") or item.get("url")
        if not url and video_id:
            url = f"https://www.youtube.com/watch?v={video_id}"
        title = _clean(item.get("title"))
        if not url or not title:
            continue
        entries.append({
            "title": title,
            "url": url,
            "kind": "video",
            "author": item.get("uploader") or item.get("channel"),
            "duration": item.get("duration"),
            "episodes": 1,
        })
    return entries


def search_entries(keyword: str, kind: str = "all", limit: int = 6, source: str = "bilibili") -> list[dict]:
    """按片名搜索，返回按匹配度排序的候选。"""
    keyword = (keyword or "").strip()
    if not keyword:
        return []

    if source == "youtube":
        return search_youtube_entries(keyword, limit)

    seen, results = set(), []
    for search_type in KINDS.get(kind, KINDS["all"]):
        try:
            entries = _query(search_type, keyword)
        except Exception:
            entries = []
        for entry in entries:
            if entry["url"] in seen:
                continue
            seen.add(entry["url"])
            results.append(entry)
        time.sleep(1)  # 连续请求会被风控成 412

    target = _normalize(keyword)

    def score(entry: dict) -> int:
        name = _normalize(entry["title"])
        if name == target:
            return 100
        if name.startswith(target) or name.endswith(target):
            return 80
        if target in name:
            return 60
        return 0

    results.sort(key=lambda e: (-score(e), e["kind"] != "bangumi" and e["kind"] != "movie"))
    return results[: max(1, min(limit, 15))]


@mcp.tool()
def search_bilibili(keyword: str, kind: str = "all", limit: int = 6) -> str:
    """按片名在 B 站搜索片源，返回可下载的链接。kind 可选 all、bangumi（番剧）、movie（电影/影视）、video（UP 主稿件）。用户只说了片名、没给链接时先用它。"""
    entries = search_entries(keyword, kind, limit)
    if not entries:
        return json.dumps(
            {"found": False, "keyword": keyword, "hint": "B 站没有搜到结果；换片名（含标点/原名）或改用 video"},
            ensure_ascii=False,
        )
    return json.dumps({"found": True, "keyword": keyword, "results": entries}, ensure_ascii=False, indent=2)


@mcp.tool()
def search_youtube(keyword: str, limit: int = 6) -> str:
    """按标题在 YouTube 搜索视频，返回可下载的链接。需要容器能访问 YouTube（当前环境未配代理时多半不可达，会返回 found=false 和原因）。"""
    try:
        entries = search_youtube_entries(keyword, limit)
    except SourceUnavailable as exc:
        return json.dumps(
            {"found": False, "keyword": keyword, "error": "YouTube 不可达", "detail": str(exc),
             "hint": "当前容器访问不了 YouTube，需给 MeTube/lab-tools 配代理；抖音等站点请直接给链接"},
            ensure_ascii=False,
        )
    if not entries:
        return json.dumps(
            {"found": False, "keyword": keyword, "hint": "YouTube 没搜到结果，换关键词或直接给链接"},
            ensure_ascii=False,
        )
    return json.dumps({"found": True, "keyword": keyword, "results": entries}, ensure_ascii=False, indent=2)
