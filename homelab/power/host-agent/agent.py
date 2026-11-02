"""宿主机 systemd 服务的小代理，只服务电源面板。

白名单固定，只放行 status / start / stop；不接任意命令、不接 restart/disable。
监听 172.17.0.1:8093，只有本机容器网络能访问。
"""

import json
import subprocess
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ALLOWED = ("mcsm-web.service", "mcsm-daemon.service", "1panel.service", "comfyui.service")
LISTEN = ("172.17.0.1", 8093)


def unit_state(unit: str) -> str:
    result = subprocess.run(["systemctl", "is-active", unit], capture_output=True, text=True, timeout=10)
    return result.stdout.strip() or "unknown"


def unit_action(action: str, unit: str) -> tuple[bool, str]:
    result = subprocess.run(["systemctl", action, unit], capture_output=True, text=True, timeout=90)
    return result.returncode == 0, result.stderr.strip()


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _send(self, code: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):  # 不往 journal 里刷访问日志
        pass

    def do_GET(self):
        if self.path.split("?")[0] != "/units":
            return self._send(404, {"error": "not found"})
        units = [{"name": u, "state": unit_state(u)} for u in ALLOWED]
        self._send(200, {"units": units})

    def do_POST(self):
        parts = self.path.split("?")[0].strip("/").split("/")
        if len(parts) != 3 or parts[0] != "units":
            return self._send(404, {"error": "not found"})

        _, unit, action = parts
        if unit not in ALLOWED:
            return self._send(403, {"error": "unit 不在白名单", "allowed": list(ALLOWED)})
        if action not in ("start", "stop"):
            return self._send(400, {"error": "action 只能是 start 或 stop"})

        ok, detail = unit_action(action, unit)
        if not ok:
            return self._send(500, {"ok": False, "unit": unit, "error": detail or "systemctl 失败"})
        self._send(200, {"ok": True, "unit": unit, "state": unit_state(unit)})


if __name__ == "__main__":
    ThreadingHTTPServer(LISTEN, Handler).serve_forever()
