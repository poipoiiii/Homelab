"""一次性健康快照：容器状态 + Docker 磁盘占用 + 最近的错误日志。

模型排查“机器现在怎么样”时，不必先 list_services 再逐个 service_logs。
"""

import json
import re
from datetime import datetime

from labtools.docker_api import docker_client, port_list
from labtools.runtime import mcp
from labtools.tools.disk import disk_summary

# 日志里按这些词判断“像错误”；宁可多抓一点，也别漏掉真正的报错
ERROR_RE = re.compile(
    r"(?i)\b(error|fatal|panic|exception|traceback|failed|failure|refused|denied|timeout)\b"
)
ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")

MAX_ERRORS_PER_CONTAINER = 3
MAX_ERROR_CHARS = 240


def _status(container) -> dict:
    attrs = container.attrs
    state = attrs.get("State") or {}
    return {
        "name": container.name,
        "state": state.get("Status") or "unknown",
        "health": (state.get("Health") or {}).get("Status"),
        "exit_code": state.get("ExitCode"),
        "restarts": attrs.get("RestartCount") or 0,
        "started_at": state.get("StartedAt"),
        "ports": port_list(attrs),
    }


def _errors(container, lines: int) -> list[str]:
    try:
        raw = container.logs(tail=lines)
    except Exception:
        return []

    text = ANSI_RE.sub("", raw.decode("utf-8", errors="replace"))
    hits: list[str] = []
    for line in text.splitlines():
        line = line.strip()
        if not line or not ERROR_RE.search(line):
            continue
        line = line[:MAX_ERROR_CHARS]
        if line not in hits:
            hits.append(line)
    return hits[-MAX_ERRORS_PER_CONTAINER:]


@mcp.tool()
def health_snapshot(log_lines: int = 60) -> str:
    """一次拿到全机健康状态：所有容器状态、Docker 磁盘占用、以及最近日志里的错误行。

    log_lines 是每个容器回看的日志行数（默认 60，最大 300）。只读。
    返回 summary（总数/运行数/异常数）、attention（需要处理的容器 + 错误日志）、
    containers（全部容器简表）和 disk（镜像/卷/缓存占用）。排查“为什么服务挂了”先调它。
    """
    log_lines = max(10, min(int(log_lines), 300))
    containers = sorted(docker_client().containers.list(all=True), key=lambda c: c.name)

    rows, attention = [], []
    for container in containers:
        status = _status(container)
        errors = _errors(container, log_lines)
        status["errors"] = errors
        rows.append(status)

        needs_attention = (
            status["state"] in ("restarting", "dead", "paused")
            or status["health"] == "unhealthy"
            or (status["state"] == "exited" and (status["exit_code"] or 0) != 0)
            or (status["restarts"] or 0) > 0
            or bool(errors)
        )
        if needs_attention:
            attention.append(status)

    running = sum(1 for r in rows if r["state"] == "running")
    summary = {
        "total": len(rows),
        "running": running,
        "stopped": len(rows) - running,
        "unhealthy": sum(1 for r in rows if r["health"] == "unhealthy"),
        "attention": len(attention),
        "checked_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    }

    return json.dumps({
        "summary": summary,
        "disk": disk_summary(),
        "attention": attention,
        "containers": [
            {k: v for k, v in row.items() if k != "errors"} | {"error_count": len(row["errors"])}
            for row in rows
        ],
    }, ensure_ascii=False, indent=2)
