import os

from mcp.server.fastmcp import FastMCP

PORT = int(os.getenv("PORT", "8765"))
DOCKER_HOST = os.getenv("DOCKER_HOST", "unix:///var/run/docker.sock")
DOCKER_HOST_WRITE = os.getenv("DOCKER_HOST_WRITE", DOCKER_HOST)
BILL_AI_URL = os.getenv("BILL_AI_URL", "http://bill-ai:8091").rstrip("/")
METUBE_URL = os.getenv("METUBE_URL", "http://metube:8081").rstrip("/")
AUDIT_PATH = os.getenv("AUDIT_PATH", "/audit/actions.jsonl")

# 所有工具模块都从这个实例注册
mcp = FastMCP("lab-tools", host="0.0.0.0", port=PORT)
