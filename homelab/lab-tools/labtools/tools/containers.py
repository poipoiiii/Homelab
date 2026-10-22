import json

from labtools.docker_api import docker_client, find_container, port_list
from labtools.runtime import mcp


@mcp.tool()
def list_services() -> str:
    """列出本机所有容器（运行中和已停止），包含状态、镜像、端口和 compose 归属。只读。"""
    rows = []
    for container in sorted(docker_client().containers.list(all=True), key=lambda c: c.name):
        attrs = container.attrs
        labels = (attrs.get("Config") or {}).get("Labels") or {}
        rows.append({
            "name": container.name,
            "state": attrs.get("State", {}).get("Status"),
            "image": (attrs.get("Config") or {}).get("Image"),
            "ports": port_list(attrs),
            "compose_project": labels.get("com.docker.compose.project"),
            "compose_service": labels.get("com.docker.compose.service"),
        })
    return json.dumps(rows, ensure_ascii=False, indent=2)


@mcp.tool()
def service_status(name: str) -> str:
    """查看单个容器的详细状态：是否运行、健康检查、启动时间、重启次数、端口、挂载点。只读。"""
    container, candidates = find_container(name)
    if container is None:
        return json.dumps(
            {"error": "未找到唯一匹配的容器", "query": name, "candidates": candidates},
            ensure_ascii=False,
        )

    attrs = container.attrs
    state = attrs.get("State") or {}
    labels = (attrs.get("Config") or {}).get("Labels") or {}
    return json.dumps({
        "name": container.name,
        "image": (attrs.get("Config") or {}).get("Image"),
        "state": state.get("Status"),
        "running": state.get("Running"),
        "health": (state.get("Health") or {}).get("Status"),
        "started_at": state.get("StartedAt"),
        "finished_at": state.get("FinishedAt"),
        "exit_code": state.get("ExitCode"),
        "restart_count": attrs.get("RestartCount"),
        "ports": port_list(attrs),
        "mounts": [
            {"destination": m.get("Destination"), "mode": m.get("Mode")}
            for m in attrs.get("Mounts") or []
        ],
        "compose_project": labels.get("com.docker.compose.project"),
        "compose_file": labels.get("com.docker.compose.project.config_files"),
    }, ensure_ascii=False, indent=2)


@mcp.tool()
def service_logs(name: str, lines: int = 100) -> str:
    """读取单个容器最近的日志，默认 100 行，最多 500 行。只读。"""
    container, candidates = find_container(name)
    if container is None:
        return json.dumps(
            {"error": "未找到唯一匹配的容器", "query": name, "candidates": candidates},
            ensure_ascii=False,
        )

    lines = max(1, min(int(lines), 500))
    try:
        raw = container.logs(tail=lines)
    except Exception as exc:
        return json.dumps({"error": str(exc)}, ensure_ascii=False)

    text = raw.decode("utf-8", errors="replace")
    if len(text) > 12000:
        text = text[-12000:]
    return f"# {container.name} 最近 {lines} 行日志\n{text}"
