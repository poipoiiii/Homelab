"""只读状态页：把容器、媒体盘、下载和备份汇总成一张卡，供 Homarr iframe 嵌入。

数据源与 Agent 共用：容器走只读 Docker 代理，下载读 watcher，备份读只读挂载的
.cache 目录。页面只展示状态，不提供任何写操作。
"""

import html
import os
import shutil
import threading
import time
from datetime import datetime

from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse

from labtools import watcher
from labtools.docker_api import docker_client, human_bytes
from labtools.runtime import BACKUP_DIR, MC_BACKUP_DIR, MEDIA_TARGETS, mcp
from labtools.tools.disk import disk_summary

CACHE_SECONDS = 15
MEDIA_LABELS = {
    "game_video": "游戏录像",
    "yt_video": "YouTube",
    "movies": "电影",
    "anime": "番剧",
}

_cache_lock = threading.Lock()
_cache_at = 0.0
_cache_data: dict | None = None


def _containers() -> dict:
    try:
        containers = docker_client().containers.list(all=True)
    except Exception as exc:
        return {"error": str(exc), "total": 0, "running": 0, "stopped": 0, "attention": []}

    rows = []
    for container in containers:
        attrs = container.attrs or {}
        state = attrs.get("State") or {}
        status = state.get("Status") or "unknown"
        health = (state.get("Health") or {}).get("Status")
        exit_code = state.get("ExitCode")
        needs_attention = (
            status in ("restarting", "dead", "paused")
            or health == "unhealthy"
            or (status == "exited" and (exit_code or 0) != 0)
        )
        if needs_attention:
            rows.append({
                "name": container.name,
                "state": status,
                "health": health,
                "exit_code": exit_code,
            })

    total = len(containers)
    running = sum(1 for c in containers if (c.attrs.get("State") or {}).get("Status") == "running")
    return {
        "total": total,
        "running": running,
        "stopped": total - running,
        "attention": rows,
    }


def _media() -> list[dict]:
    rows = []
    for name, path in MEDIA_TARGETS.items():
        row = {"name": name, "label": MEDIA_LABELS.get(name, name), "path": path}
        try:
            usage = shutil.disk_usage(path)
            row.update(free=usage.free, total=usage.total)
        except OSError:
            row["missing"] = True
        rows.append(row)
    return rows


def _bill_backup() -> dict | None:
    root = os.path.join(BACKUP_DIR, "bill-ai")
    try:
        entries = [entry for entry in os.scandir(root) if entry.is_dir() and not entry.name.startswith(".")]
    except OSError:
        return None
    if not entries:
        return None
    try:
        latest = max(entries, key=lambda entry: entry.stat().st_mtime)
        age_hours = (time.time() - latest.stat().st_mtime) / 3600
    except OSError:
        return None
    db_path = os.path.join(latest.path, "bill.db")
    size = None
    try:
        size = os.path.getsize(db_path)
    except OSError:
        pass
    return {"name": latest.name, "age_hours": round(age_hours, 1), "size": size}


def _mc_backup() -> dict | None:
    try:
        files = [
            entry for entry in os.scandir(MC_BACKUP_DIR)
            if entry.is_file() and entry.name.startswith("mc-") and entry.name.endswith(".tar.gz")
        ]
    except OSError:
        return None
    if not files:
        return None
    try:
        latest = max(files, key=lambda entry: entry.stat().st_mtime)
        stat = latest.stat()
    except OSError:
        return None
    return {
        "name": latest.name,
        "age_hours": round((time.time() - stat.st_mtime) / 3600, 1),
        "size": stat.st_size,
    }


def _downloads() -> dict:
    jobs = watcher.snapshot()
    active = [job for job in jobs if job.get("state") not in watcher.DONE_STATES]
    finished = [job for job in jobs if job.get("state") == "done"]
    failed = [job for job in finished if job.get("errors")]

    def compact(job: dict) -> dict:
        return {
            "title": job.get("title") or job.get("series") or job.get("url"),
            "target": job.get("target"),
            "series": job.get("series") or None,
            "state": job.get("state"),
            "errors": job.get("errors") or [],
        }

    return {
        "active": len(active),
        "failed": len(failed),
        "items": [compact(job) for job in (active + finished[:3])],
    }


def _safe_disk() -> dict:
    try:
        return disk_summary()
    except Exception as exc:
        return {"error": str(exc)}


def collect() -> dict:
    """汇总状态；15 秒内复用上一次结果，避免 iframe 刷新把 Docker 打满。"""
    global _cache_at, _cache_data

    now = time.time()
    with _cache_lock:
        if _cache_data is not None and now - _cache_at < CACHE_SECONDS:
            return _cache_data

    data = {
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "containers": _containers(),
        "disk": _safe_disk(),
        "media": _media(),
        "downloads": _downloads(),
        "backups": {"bill": _bill_backup(), "mc": _mc_backup()},
    }

    with _cache_lock:
        _cache_at = now
        _cache_data = data
    return data


def _bytes(value: int | float | None) -> str:
    if not isinstance(value, (int, float)):
        return "—"
    return human_bytes(value)


def _age(hours: float | None) -> str:
    if hours is None:
        return "无记录"
    if hours < 1:
        return f"{max(1, int(hours * 60))} 分钟前"
    if hours < 48:
        return f"{hours:.0f} 小时前"
    return f"{hours / 24:.0f} 天前"


def _esc(value: object) -> str:
    return html.escape(str(value if value is not None else ""), quote=True)


def _tone(hours: float | None) -> str:
    if hours is None:
        return "bad"
    if hours <= 30:
        return "ok"
    if hours <= 72:
        return "warn"
    return "bad"


def _render_attention(containers: dict) -> str:
    if containers.get("error"):
        return f'<p class="empty">容器状态读取失败：{_esc(containers["error"])}</p>'

    rows = containers.get("attention") or []
    if not rows:
        return '<p class="empty">全部容器都在运行，没有需要处理的异常。</p>'

    items = []
    for row in rows:
        health = f" · {row['health']}" if row.get("health") else ""
        exit_code = f" · exit {row['exit_code']}" if row.get("state") == "exited" and row.get("exit_code") else ""
        tone = "bad" if row.get("health") == "unhealthy" or row.get("state") in ("dead", "restarting") else "warn"
        items.append(
            f'<div class="row"><span class="dot {tone}"></span>'
            f'<span class="name">{_esc(row.get("name"))}</span>'
            f'<span class="meta">{_esc(row.get("state"))}{_esc(health)}{_esc(exit_code)}</span></div>'
        )
    return '<div class="rows">' + "".join(items) + "</div>"


def _render_media(media: list[dict]) -> str:
    items = []
    for row in media:
        if row.get("missing"):
            items.append(
                f'<div class="media-item"><div class="media-head"><span>{_esc(row["label"])}</span>'
                f'<span>未挂载</span></div><div class="bar"><i class="low" style="width:0"></i></div></div>'
            )
            continue
        total = row.get("total") or 0
        free = row.get("free") or 0
        percent = (free / total * 100) if total else 0
        low = " low" if percent < 15 else ""
        items.append(
            f'<div class="media-item"><div class="media-head">'
            f'<span>{_esc(row["label"])}</span><span>剩 {_bytes(free)} / {_bytes(total)}</span></div>'
            f'<div class="bar"><i class="{low.strip()}" style="width:{percent:.1f}%"></i></div></div>'
        )
    return '<div class="media">' + "".join(items) + "</div>"


def _render_downloads(downloads: dict) -> str:
    items = []
    for row in downloads.get("items") or []:
        state = row.get("state") or "unknown"
        labels = {"done": "完成", "cancelled": "已取消", "queued": "排队", "downloading": "下载中"}
        tone = "bad" if row.get("errors") else ("ok" if state == "done" else "warn")
        target = row.get("series") or row.get("target") or ""
        errors = len(row.get("errors") or [])
        if errors and target:
            meta = f"{target} · {errors} 个失败"
        elif errors:
            meta = f"{errors} 个失败"
        else:
            meta = target
        items.append(
            f'<div class="row"><span class="dot {tone}"></span>'
            f'<span class="name">{_esc(row.get("title"))}</span>'
            f'<span class="state">{_esc(labels.get(state, state))}</span>'
            f'<span class="meta">{_esc(meta)}</span></div>'
        )
    if not items:
        return '<p class="empty">队列是空的，最近也没有完成记录。</p>'
    return '<div class="dl">' + "".join(items) + "</div>"


def _render_backups(backups: dict) -> str:
    rows = []
    for label, item in (("账单", backups.get("bill")), ("Minecraft", backups.get("mc"))):
        if not item:
            rows.append(
                f'<div class="row"><span class="dot bad"></span><span class="name">{label}</span>'
                f'<span class="meta">没有找到备份</span></div>'
            )
            continue
        rows.append(
            f'<div class="row"><span class="dot {_tone(item.get("age_hours"))}"></span>'
            f'<span class="name">{label}</span>'
            f'<span class="meta">{_esc(_age(item.get("age_hours")))} · {_bytes(item.get("size"))}</span></div>'
        )
    return '<div class="rows">' + "".join(rows) + "</div>"


def render_html(data: dict) -> str:
    containers = data.get("containers") or {}
    downloads = data.get("downloads") or {}
    backups = data.get("backups") or {}
    disk = data.get("disk") or {}
    attention = containers.get("attention") or []
    bill = backups.get("bill")

    if containers.get("error") or any(row.get("health") == "unhealthy" for row in attention):
        attention_tone = "bad"
    elif attention:
        attention_tone = "warn"
    else:
        attention_tone = ""
    backup_tone = _tone(bill.get("age_hours")) if bill else "bad"
    updated = datetime.fromisoformat(data["generated_at"]).strftime("%H:%M")

    reclaimable = disk.get("total_reclaimable")
    disk_hint = f"可回收 {reclaimable}" if reclaimable else "Docker 磁盘占用不可用"

    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="refresh" content="30">
<title>homelab · 状态</title>
<style>
  :root {{
    --ink: #fff3f8;
    --muted: #dfbccb;
    --line: rgba(255, 220, 232, 0.18);
    --panel: linear-gradient(150deg, rgba(255, 241, 247, 0.10), rgba(255, 214, 230, 0.045));
    --accent: #ff7aa8;
    --ok: #79e0b0;
    --warn: #ffcf6e;
    --bad: #ff6b8b;
  }}
  * {{ box-sizing: border-box; }}
  html, body {{ margin: 0; min-height: 100%; }}
  body {{
    background:
      radial-gradient(110% 80% at 0% 0%, rgba(214, 51, 108, 0.20), transparent 58%),
      radial-gradient(90% 70% at 100% 0%, rgba(255, 214, 230, 0.10), transparent 55%),
      #0b0509;
    color: var(--ink);
    font: 14px/1.5 "PingFang SC", "Microsoft YaHei", system-ui, -apple-system, sans-serif;
    -webkit-font-smoothing: antialiased;
  }}
  .wrap {{ max-width: 760px; margin: 0 auto; padding: 18px 16px 22px; display: flex; flex-direction: column; gap: 12px; }}
  .head {{ display: flex; justify-content: space-between; align-items: flex-end; gap: 12px; }}
  .eyebrow {{ margin: 0 0 2px; font-size: 10px; letter-spacing: 0.22em; color: var(--accent); font-weight: 600; }}
  h1 {{ margin: 0; font-size: 20px; line-height: 1.2; letter-spacing: 0.01em; }}
  .stamp {{ margin: 0; font-size: 11px; color: var(--muted); white-space: nowrap; }}
  .tiles {{ display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 8px; }}
  .tile {{ background: var(--panel); border: 1px solid var(--line); border-radius: 14px; padding: 10px 12px; display: flex; flex-direction: column; gap: 1px; min-width: 0; }}
  .tile.warn {{ border-color: rgba(255, 207, 110, 0.42); }}
  .tile.bad {{ border-color: rgba(255, 107, 139, 0.50); }}
  .tile .k {{ font-size: 11px; color: var(--muted); }}
  .tile .v {{ font-size: 20px; font-weight: 650; line-height: 1.2; }}
  .tile .v small {{ font-size: 12px; font-weight: 500; color: var(--muted); }}
  .tile .s {{ font-size: 10px; color: var(--muted); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
  .panel {{ background: var(--panel); border: 1px solid var(--line); border-radius: 16px; padding: 12px 14px; }}
  .panel-head {{ display: flex; justify-content: space-between; align-items: baseline; gap: 10px; margin-bottom: 8px; }}
  h2 {{ margin: 0; font-size: 12px; letter-spacing: 0.12em; color: var(--muted); font-weight: 600; }}
  .tag {{ font-size: 11px; color: var(--muted); }}
  .rows, .dl {{ display: flex; flex-direction: column; gap: 6px; }}
  .row {{ display: flex; align-items: center; gap: 8px; min-width: 0; }}
  .row .name {{ font-size: 13px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
  .row .meta {{ margin-left: auto; font-size: 11px; color: var(--muted); white-space: nowrap; }}
  .row .state {{ font-size: 10px; color: var(--muted); border: 1px solid var(--line); border-radius: 999px; padding: 1px 7px; white-space: nowrap; }}
  .dot {{ width: 7px; height: 7px; border-radius: 50%; flex: 0 0 auto; background: var(--muted); }}
  .dot.ok {{ background: var(--ok); box-shadow: 0 0 8px rgba(121, 224, 176, 0.5); }}
  .dot.warn {{ background: var(--warn); }}
  .dot.bad {{ background: var(--bad); box-shadow: 0 0 8px rgba(255, 107, 139, 0.55); }}
  .empty {{ margin: 0; font-size: 12px; color: var(--muted); }}
  .media {{ display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px 16px; }}
  .media-item {{ min-width: 0; }}
  .media-head {{ display: flex; justify-content: space-between; gap: 8px; font-size: 12px; margin-bottom: 4px; }}
  .media-head span:last-child {{ color: var(--muted); font-size: 11px; }}
  .bar {{ height: 5px; border-radius: 999px; background: rgba(255, 220, 232, 0.14); overflow: hidden; }}
  .bar i {{ display: block; height: 100%; border-radius: 999px; background: linear-gradient(90deg, #d6336c, #ff9ec2); }}
  .bar i.low {{ background: linear-gradient(90deg, #ff6b8b, #ffcf6e); }}
  footer {{ font-size: 10px; color: var(--muted); text-align: center; padding-top: 2px; }}
  @media (max-width: 560px) {{
    .wrap {{ padding: 14px 12px 18px; }}
    .tiles {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
    .media {{ grid-template-columns: 1fr; }}
    h1 {{ font-size: 18px; }}
    .stamp {{ display: none; }}
  }}
</style>
</head>
<body>
<main class="wrap">
  <header class="head">
    <div>
      <p class="eyebrow">HOMELAB</p>
      <h1>家里现在怎么样</h1>
    </div>
    <p class="stamp">{updated} 更新 · 30 秒刷新</p>
  </header>

  <section class="tiles">
    <div class="tile">
      <span class="k">容器</span>
      <span class="v">{containers.get("running", 0)}<small>/{containers.get("total", 0)}</small></span>
      <span class="s">运行中</span>
    </div>
    <div class="tile {attention_tone}">
      <span class="k">需要看一眼</span>
      <span class="v">{len(attention)}</span>
      <span class="s">{_esc(attention[0].get("name")) if attention else "全部正常"}</span>
    </div>
    <div class="tile">
      <span class="k">下载</span>
      <span class="v">{downloads.get("active", 0)}</span>
      <span class="s">进行中</span>
    </div>
    <div class="tile {backup_tone}">
      <span class="k">账单备份</span>
      <span class="v" style="font-size:16px">{_esc(_age(bill.get("age_hours")) if bill else "无记录")}</span>
      <span class="s">{_esc(_bytes(bill.get("size")) if bill else "检查 timer")}</span>
    </div>
  </section>

  <section class="panel">
    <div class="panel-head"><h2>容器</h2><span class="tag">{_esc(disk_hint)}</span></div>
    {_render_attention(containers)}
  </section>

  <section class="panel">
    <div class="panel-head"><h2>媒体盘余量</h2><span class="tag">只读挂载</span></div>
    {_render_media(data.get("media") or [])}
  </section>

  <section class="panel">
    <div class="panel-head"><h2>下载</h2><span class="tag">最近任务</span></div>
    {_render_downloads(downloads)}
  </section>

  <section class="panel">
    <div class="panel-head"><h2>备份</h2><span class="tag">每天自动</span></div>
    {_render_backups(backups)}
  </section>

  <footer>只读状态页 · 数据来自 lab-tools</footer>
</main>
</body>
</html>"""


@mcp.custom_route("/status", methods=["GET"])
async def status_page(request: Request) -> HTMLResponse:
    return HTMLResponse(render_html(collect()), headers={"Cache-Control": "no-store"})


@mcp.custom_route("/status.json", methods=["GET"])
async def status_json(request: Request) -> JSONResponse:
    return JSONResponse(collect(), headers={"Cache-Control": "no-store"})
