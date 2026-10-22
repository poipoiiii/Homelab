import json
import os
import secrets
import time
from datetime import datetime

import docker

from labtools.docker_api import docker_write_client, find_container
from labtools.runtime import AUDIT_PATH, mcp

# 这些容器被 stop/restart 会影响入口、日志或 Agent 自身，直接拒绝
PROTECTED = {
    "lab-tools",
    "lab-tools-docker-proxy",
    "librechat",
    "librechat-mongo",
    "homarr",
    "dozzle",
    "frpc",
}

TOKEN_TTL = 120
_pending: dict[str, dict] = {}


def _audit(action: str, target: str, result: str, confirm: str | None = None) -> None:
    row = {
        "ts": datetime.now().astimezone().isoformat(timespec="seconds"),
        "action": action,
        "target": target,
        "result": result,
        "confirm": confirm,
    }
    try:
        os.makedirs(os.path.dirname(AUDIT_PATH), exist_ok=True)
        with open(AUDIT_PATH, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    except Exception:
        pass


def _issue(action: str, name: str) -> str:
    now = time.time()
    for token, item in list(_pending.items()):
        if item["expires"] < now:
            _pending.pop(token, None)
    token = secrets.token_urlsafe(6)
    _pending[token] = {"expires": now + TOKEN_TTL, "action": action, "name": name}
    return token


def _consume(token: str, action: str, name: str) -> str | None:
    item = _pending.pop(token, None)
    if not item:
        return "确认 token 无效或已使用"
    if item["expires"] < time.time():
        return "确认 token 已过期"
    if item["action"] != action or item["name"] != name:
        return "确认 token 与当前操作不匹配"
    return None


def _lookup(name: str):
    container, candidates = find_container(name)
    if container is None:
        return None, json.dumps(
            {"error": "未找到唯一匹配的容器", "query": name, "candidates": candidates},
            ensure_ascii=False,
        )
    return container, None


def _state(container) -> dict:
    container.reload()
    return {
        "name": container.name,
        "state": container.status,
        "running": container.status == "running",
    }


def _lifecycle(container, action: str) -> str:
    """走只开放 start/stop 的写代理，用低级 API 避免 GET 容器详情。"""
    params = {"t": 10} if action == "stop" else None
    try:
        client = docker_write_client()
        client.api.post(client.api._url(f"/containers/{container.id}/{action}"), params=params)
        return "ok"
    except docker.errors.APIError as exc:
        if exc.response is not None and exc.response.status_code == 304:
            return "ok"
        return f"error: {exc}"


@mcp.tool()
def stop_service(name: str, confirm_token: str | None = None) -> str:
    """停止容器。第一次调用只返回确认 token，不会执行；用户确认后再带 confirm_token 调用。保护名单内的容器会被拒绝。"""
    container, error = _lookup(name)
    if error:
        return error
    if container.name in PROTECTED:
        return json.dumps(
            {"error": "该容器受保护，禁止停止", "name": container.name},
            ensure_ascii=False,
        )

    if not confirm_token:
        token = _issue("stop", container.name)
        return json.dumps({
            "action": "stop",
            "name": container.name,
            "command": f"docker stop {container.name}",
            "confirm_token": token,
            "expires_in": TOKEN_TTL,
            "hint": "把 confirm_token 原样传回 stop_service 才会真正执行",
        }, ensure_ascii=False, indent=2)

    token_error = _consume(confirm_token, "stop", container.name)
    if token_error:
        return json.dumps({"error": token_error}, ensure_ascii=False)

    result = _lifecycle(container, "stop")
    _audit("stop", container.name, result, confirm_token)
    payload = _state(container)
    payload["result"] = result
    return json.dumps(payload, ensure_ascii=False, indent=2)


@mcp.tool()
def start_service(name: str) -> str:
    """启动一个已停止的容器。启动不需要确认；已经在运行时会直接返回状态。"""
    container, error = _lookup(name)
    if error:
        return error
    if container.status == "running":
        return json.dumps({"name": container.name, "state": "running", "note": "已在运行"}, ensure_ascii=False)

    result = _lifecycle(container, "start")
    _audit("start", container.name, result)
    payload = _state(container)
    payload["result"] = result
    return json.dumps(payload, ensure_ascii=False, indent=2)


@mcp.tool()
def restart_service(name: str, confirm_token: str | None = None) -> str:
    """重启容器（stop + start）。第一次调用只返回确认 token；保护名单内的容器会被拒绝。"""
    container, error = _lookup(name)
    if error:
        return error
    if container.name in PROTECTED:
        return json.dumps(
            {"error": "该容器受保护，禁止重启", "name": container.name},
            ensure_ascii=False,
        )

    if not confirm_token:
        token = _issue("restart", container.name)
        return json.dumps({
            "action": "restart",
            "name": container.name,
            "command": f"docker stop {container.name} && docker start {container.name}",
            "confirm_token": token,
            "expires_in": TOKEN_TTL,
            "hint": "把 confirm_token 原样传回 restart_service 才会真正执行",
        }, ensure_ascii=False, indent=2)

    token_error = _consume(confirm_token, "restart", container.name)
    if token_error:
        return json.dumps({"error": token_error}, ensure_ascii=False)

    result = _lifecycle(container, "stop")
    if result == "ok":
        result = _lifecycle(container, "start")
    _audit("restart", container.name, result, confirm_token)
    payload = _state(container)
    payload["result"] = result
    return json.dumps(payload, ensure_ascii=False, indent=2)
