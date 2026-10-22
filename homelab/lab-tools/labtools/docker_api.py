from typing import Any

import docker

from labtools.runtime import DOCKER_HOST, DOCKER_HOST_WRITE

_client: docker.DockerClient | None = None
_write_client: docker.DockerClient | None = None


def docker_client() -> docker.DockerClient:
    global _client
    if _client is None:
        _client = docker.DockerClient(base_url=DOCKER_HOST, timeout=15)
    return _client


def docker_write_client() -> docker.DockerClient:
    """只用于 start/stop 的低权限客户端；对应 proxy 不开放 CONTAINERS 查询。"""
    global _write_client
    if _write_client is None:
        _write_client = docker.DockerClient(base_url=DOCKER_HOST_WRITE, timeout=15)
    return _write_client


def human_bytes(value: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            return f"{int(value)} B" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} TB"


def find_container(name: str):
    """返回 (容器, 候选列表)。名称不唯一时不猜，交给上层反问。"""
    containers = docker_client().containers.list(all=True)
    key = name.strip().lower()
    exact = [c for c in containers if c.name.lower() == key]
    if exact:
        return exact[0], []
    partial = [c for c in containers if key in c.name.lower()]
    if len(partial) == 1:
        return partial[0], []
    return None, sorted(c.name for c in partial)


def port_list(attrs: dict[str, Any]) -> list[str]:
    result = []
    ports = (attrs.get("NetworkSettings") or {}).get("Ports") or {}
    for container_port, bindings in ports.items():
        if not bindings:
            result.append(container_port)
            continue
        for binding in bindings:
            host_ip = binding.get("HostIp") or ""
            host_port = binding.get("HostPort") or ""
            result.append(f"{host_ip}:{host_port} -> {container_port}".strip())
    return result
