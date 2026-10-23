"""跟踪 MeTube 的下载任务，结束后发通知。

MeTube 没有回调，只能轮询 /history（queue + done）。提交成功后由
downloads.download_media 调 track() 登记；后台线程每 POLL_SECONDS 查一次，
命中 done 就发一次通知，状态落在 audit 卷的 downloads.json，重启不丢。
"""

import json
import logging
import os
import threading
import time

import httpx

from labtools import notify
from labtools.runtime import AUDIT_PATH, METUBE_URL

log = logging.getLogger("labtools.watcher")

STATE_PATH = os.getenv("DOWNLOAD_STATE", os.path.join(os.path.dirname(AUDIT_PATH), "downloads.json"))
POLL_SECONDS = max(10, int(os.getenv("DOWNLOAD_POLL_SECONDS", "30")))
KEEP_DONE_SECONDS = 7 * 24 * 3600

_lock = threading.Lock()
_wake = threading.Event()
_jobs: dict[str, dict] = {}
_worker: threading.Thread | None = None


def _load() -> None:
    try:
        with open(STATE_PATH, encoding="utf-8") as handle:
            rows = json.load(handle)
    except (OSError, ValueError):
        return
    for row in rows if isinstance(rows, list) else []:
        if isinstance(row, dict) and row.get("url"):
            _jobs[row["url"]] = row


def _save() -> None:
    """调用方必须持锁。"""
    try:
        os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
        tmp = STATE_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(list(_jobs.values()), handle, ensure_ascii=False, indent=1)
        os.replace(tmp, STATE_PATH)
    except Exception as exc:
        log.warning("写入下载状态失败：%s", exc)


def _history() -> dict:
    with httpx.Client(timeout=10) as client:
        response = client.get(f"{METUBE_URL}/history")
        response.raise_for_status()
        return response.json()


def _same_url(left: str, right: str) -> bool:
    return (left or "").rstrip("/") == (right or "").rstrip("/")


def _entry_matches(job: dict, entry: dict) -> bool:
    job_id = job.get("id")
    if job_id and entry.get("id") == job_id:
        return True
    return _same_url(entry.get("url", ""), job["url"])


def _new_done(job: dict, done: list[dict]) -> list[dict]:
    """排除登记时就已经在 done 里的旧记录，避免重复下载时提前报完成。"""
    baseline = set(job.get("baseline") or [])
    return [
        entry for entry in done
        if _entry_matches(job, entry) and entry.get("id") not in baseline
    ]


def _message(job: dict) -> str:
    folder = job.get("target") or ""
    if job.get("series"):
        folder = f"{folder}/{job['series']}"
    errors = job.get("errors") or []
    total = int(job.get("done_count") or 1)
    if errors and len(errors) >= total:
        header = "【下载失败】"
    elif errors:
        header = "【部分失败】"
    else:
        header = "【下载完成】"

    lines = [header, f"标题：{job.get('title') or job['url']}", f"目录：{folder}"]
    if total > 1:
        lines.append(f"数量：{total} 个视频" + (f"，失败 {len(errors)} 个" if errors else ""))
    if errors:
        lines.append(f"原因：{errors[0]}")
    elif job.get("filename"):
        lines.append(f"文件：{job['filename']}")
    lines.append(f"链接：{job['url']}")
    return "\n".join(lines)


def _announce(job: dict) -> None:
    message = _message(job)
    notify.send_text(message)
    log.info("下载任务结束：%s（%s）", job.get("title"), message.splitlines()[0])


def _loop() -> None:
    while True:
        with _lock:
            pending = [job for job in _jobs.values() if job.get("state") != "done"]
        if not pending:
            _wake.wait(60)
            _wake.clear()
            continue

        try:
            history = _history()
        except Exception as exc:
            log.info("读取 MeTube 历史失败：%s", exc)
            _wake.wait(POLL_SECONDS)
            _wake.clear()
            continue

        queue = [entry for entry in history.get("queue") or [] if isinstance(entry, dict)]
        done = [entry for entry in history.get("done") or [] if isinstance(entry, dict)]
        finished: list[dict] = []

        with _lock:
            now = time.time()
            for job in list(_jobs.values()):
                if job.get("state") == "done":
                    continue

                queued = [entry for entry in queue if _entry_matches(job, entry)]
                if queued:
                    job["seen_queue"] = True
                    # 第一次见到它排队时，把当时已在 done 里的同名记录记为基线
                    if job.get("baseline") is None:
                        job["baseline"] = [
                            entry.get("id") for entry in done
                            if _entry_matches(job, entry) and entry.get("id")
                        ]
                    job["id"] = queued[0].get("id") or job.get("id")
                    job["title"] = queued[0].get("title") or job.get("title")
                    continue

                entries = _new_done(job, done)
                if not entries or not job.get("seen_queue"):
                    continue

                errors = [
                    entry.get("error") or entry.get("msg") or "下载失败"
                    for entry in entries
                    if (entry.get("status") or "").lower() == "error"
                ]
                job.update({
                    "state": "done",
                    "finished_at": now,
                    "title": job.get("title") or (entries[0].get("title") or ""),
                    "filename": entries[0].get("filename") or "",
                    "errors": errors,
                    "done_count": len(entries),
                })
                finished.append(dict(job))

            for url, job in list(_jobs.items()):
                if job.get("state") == "done" and now - (job.get("finished_at") or now) > KEEP_DONE_SECONDS:
                    _jobs.pop(url, None)
            _save()

        for job in finished:
            _announce(job)

        _wake.wait(POLL_SECONDS)
        _wake.clear()


def _ensure_worker() -> None:
    global _worker
    if _worker and _worker.is_alive():
        return
    _worker = threading.Thread(target=_loop, name="metube-watcher", daemon=True)
    _worker.start()


def track(url: str, target: str, series: str = "", title: str = "") -> None:
    """登记一个刚提交给 MeTube 的下载任务。"""
    if not url:
        return
    with _lock:
        job = _jobs.get(url) or {}
        job.update({
            "url": url,
            "target": target,
            "series": series or job.get("series", ""),
            "title": title or job.get("title", ""),
            "state": "queued",
            "seen_queue": False,
            "id": None,
            "baseline": None,
            "submitted_at": time.time(),
        })
        _jobs[url] = job
        _save()
    _wake.set()
    _ensure_worker()


_load()
if any(job.get("state") != "done" for job in _jobs.values()):
    _ensure_worker()
