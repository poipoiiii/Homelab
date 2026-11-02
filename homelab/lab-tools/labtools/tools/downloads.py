import json
import re
import shutil
from datetime import datetime
from urllib.parse import urlparse

import httpx

from labtools import watcher
from labtools.docker_api import human_bytes
from labtools.runtime import MEDIA_MIN_FREE_BYTES, MEDIA_TARGETS, METUBE_URL, mcp
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


def _iso(ts: float | int | None) -> str | None:
    if not ts:
        return None
    return datetime.fromtimestamp(float(ts)).astimezone().isoformat(timespec="seconds")


def _free_space(target: str) -> dict:
    """读取只读挂载的媒体目录余量；目录没挂上时返回错误而不是猜。"""
    path = MEDIA_TARGETS.get(target, "")
    try:
        usage = shutil.disk_usage(path)
    except OSError as exc:
        return {"path": path, "error": str(exc)}
    return {"path": path, "free": usage.free, "total": usage.total}


def _preflight(target: str, free: dict | None = None) -> dict | None:
    """提交前检查目标盘余量，避免一个 limit=0 把盘写满。"""
    free = free or _free_space(target)
    if "free" not in free:
        return {
            "error": "媒体目录不可用，无法检查磁盘余量",
            "target": target,
            "path": free.get("path"),
            "detail": free.get("error"),
            "hint": "确认 compose 已把 /mnt/d 的媒体目录只读挂到 /media/<target>，然后重建 lab-tools",
        }
    if MEDIA_MIN_FREE_BYTES > 0 and free["free"] < MEDIA_MIN_FREE_BYTES:
        return {
            "error": "磁盘余量不足，已拒绝下载",
            "target": target,
            "path": free["path"],
            "free": human_bytes(free["free"]),
            "required": human_bytes(MEDIA_MIN_FREE_BYTES),
            "hint": "清理旧文件，或调低 MEDIA_MIN_FREE_GB 后重启 lab-tools",
        }
    return None


def _history() -> dict | None:
    """MeTube 的 /history；不可达时返回 None，不影响本地任务展示。"""
    try:
        with httpx.Client(timeout=10) as client:
            response = client.get(f"{METUBE_URL}/history")
            response.raise_for_status()
            history = response.json()
    except Exception:
        return None
    return history if isinstance(history, dict) else None


def _find_queue_entry(entries: list[dict], url: str, job_id: str) -> dict | None:
    for entry in entries:
        if job_id and entry.get("id") == job_id:
            return entry
        if url and (entry.get("url") or "").rstrip("/") == url.rstrip("/"):
            return entry
    return None


def _submit(link: str, target: str, limit: int, items: str, series: str = "") -> dict:
    payload = {"url": link, "folder": target}
    if int(limit) > 0:
        payload["playlist_item_limit"] = min(int(limit), 100)

    overrides = {}
    if items.strip():
        overrides["playlist_items"] = items.strip()
    if series:
        # 番剧：落到 <target>/<剧名>/Season 01/剧名 - S01E01.mp4，Jellyfin 才能识别成剧集。
        # MeTube 会把合集页拆成每集一个独立任务，playlist_index 在单集任务里是空的，
        # 必须优先用 episode_number，否则每集都会写成 S01E01 互相覆盖。
        payload["folder"] = f"{target}/{series}"
        overrides["outtmpl"] = (
            f"Season 01/{series} - S01E%(episode_number,playlist_index,autonumber)02d.%(ext)s"
        )
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

    free = _free_space(target)
    space_error = _preflight(target, free)
    if space_error:
        return json.dumps(space_error, ensure_ascii=False)

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

    active = watcher.find_active(link)
    if active:
        return json.dumps({
            "queued": False,
            "duplicate": True,
            "target": active.get("target"),
            "title": active.get("title") or active.get("series") or "",
            "state": active.get("state"),
            "submitted_at": _iso(active.get("submitted_at")),
            "url": link,
            "hint": "这个链接已经在队列里；要重下请先 cancel_download，或换一个链接",
        }, ensure_ascii=False, indent=2)

    # 番剧按 Jellyfin 规范命名；没给 series 时退回用户说的片名
    series_name = ""
    if target == "anime":
        series_name = _safe_name(series) or _safe_name(query)

    result = _submit(link, target, limit, items, series_name)
    if result.get("queued"):
        # 交给后台轮询 MeTube 队列，完成/失败时发通知（未配置企业微信则只记日志）
        watcher.track(link, target, series=series_name, title=(chosen or {}).get("title", ""))

    payload = {
        "target": target,
        "container_path": TARGETS[target],
        "free_space": human_bytes(free["free"]),
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


def _job_row(job: dict) -> dict:
    return {
        "title": job.get("title") or job.get("series") or job.get("url"),
        "url": job.get("url"),
        "target": job.get("target"),
        "series": job.get("series") or None,
        "state": job.get("state") or "unknown",
        "id": job.get("id") or None,
        "submitted_at": _iso(job.get("submitted_at")),
        "finished_at": _iso(job.get("finished_at")),
        "episodes": job.get("done_count") or None,
        "filename": job.get("filename") or None,
        "errors": job.get("errors") or [],
        "source": "agent",
    }


@mcp.tool()
def list_downloads(limit: int = 20) -> str:
    """查看下载队列和最近完成的任务，回答“下好了吗 / 排到哪了 / 为什么失败”。只读。

    limit 默认 20、最多 100。返回 active（进行中数量）、metube（MeTube 是否可达）和 items；
    state 可能是 queued、downloading、done、cancelled，errors 里是失败原因。
    """
    limit = max(1, min(int(limit), 100))
    history = _history()
    queue = [entry for entry in (history or {}).get("queue") or [] if isinstance(entry, dict)]

    rows = [_job_row(job) for job in watcher.snapshot()]
    known = {(row.get("url") or "").rstrip("/") for row in rows}

    # MeTube 页面里直接提交的任务也一并展示，避免“队列里有、Agent 说没有”
    for entry in queue:
        url = (entry.get("url") or "").rstrip("/")
        if not url or url in known:
            continue
        rows.append({
            "title": entry.get("title") or url,
            "url": url,
            "target": entry.get("folder") or None,
            "series": None,
            "state": entry.get("status") or "queued",
            "id": entry.get("id") or None,
            "submitted_at": None,
            "finished_at": None,
            "episodes": None,
            "filename": entry.get("filename") or None,
            "errors": [],
            "source": "metube",
        })
        known.add(url)

    active = [row for row in rows if row["state"] not in watcher.DONE_STATES]
    finished = [row for row in rows if row["state"] in watcher.DONE_STATES]
    # 已取消的任务排在完成之后，避免占满列表前半屏
    finished.sort(key=lambda row: row["state"] == "cancelled")
    return json.dumps({
        "active": len(active),
        "total": len(rows),
        "metube": "ok" if history is not None else "unreachable",
        "items": (active + finished)[:limit],
    }, ensure_ascii=False, indent=2)


@mcp.tool()
def cancel_download(url: str = "", job_id: str = "") -> str:
    """取消排队或下载中的任务；只移除 MeTube 队列项，不删除已经落盘的文件。

    url 和 job_id 二选一，通常传 url（download_media 返回或 list_downloads 里的链接）。
    """
    url = (url or "").strip()
    job_id = (job_id or "").strip()
    if not url and not job_id:
        return json.dumps({"cancelled": False, "error": "需要 url 或 job_id"}, ensure_ascii=False)

    history = _history()
    if history is None:
        return json.dumps({
            "cancelled": False,
            "error": "MeTube 不可达，无法取消",
            "url": METUBE_URL,
        }, ensure_ascii=False)

    queue = [entry for entry in history.get("queue") or [] if isinstance(entry, dict)]
    entry = _find_queue_entry(queue, url, job_id)
    if not entry:
        return json.dumps({
            "cancelled": False,
            "error": "MeTube 队列里没有匹配的任务（可能已经完成或已被取消）",
            "url": url,
            "job_id": job_id,
        }, ensure_ascii=False)
    if not entry.get("id"):
        return json.dumps({"cancelled": False, "error": "队列项缺少 id，无法取消"}, ensure_ascii=False)

    # MeTube 的 /delete 需要 where=queue；delete_files 固定 false，避免误删已下载文件
    payload = {"ids": [entry["id"]], "where": "queue", "delete_files": False}
    try:
        with httpx.Client(timeout=15) as client:
            response = client.post(f"{METUBE_URL}/delete", json=payload)
            response.raise_for_status()
            result = response.json()
    except Exception as exc:
        return json.dumps({
            "cancelled": False,
            "error": "MeTube 取消请求失败",
            "detail": str(exc),
        }, ensure_ascii=False)

    watcher.mark_cancelled(url=url or entry.get("url") or "", job_id=entry.get("id") or job_id)
    return json.dumps({
        "cancelled": True,
        "id": entry["id"],
        "title": entry.get("title") or entry.get("url"),
        "delete_files": False,
        "result": result,
        "hint": "只移除了队列项，已经写入磁盘的文件不会被删除",
    }, ensure_ascii=False, indent=2)
