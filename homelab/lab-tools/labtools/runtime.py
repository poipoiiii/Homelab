import os

from mcp.server.fastmcp import FastMCP

PORT = int(os.getenv("PORT", "8765"))
DOCKER_HOST = os.getenv("DOCKER_HOST", "unix:///var/run/docker.sock")
DOCKER_HOST_WRITE = os.getenv("DOCKER_HOST_WRITE", DOCKER_HOST)
BILL_AI_URL = os.getenv("BILL_AI_URL", "http://rong-ledger:8091").rstrip("/")
METUBE_URL = os.getenv("METUBE_URL", "http://metube:8081").rstrip("/")
AUDIT_PATH = os.getenv("AUDIT_PATH", "/audit/actions.jsonl")
# B 站搜索用的 cookies（与 MeTube 共用同一份，只读挂载）
BILI_COOKIES = os.getenv("BILI_COOKIES", "/cookies/cookies.txt")

# 宿主机媒体目录（只读挂载），用于下载前检查剩余空间；路径与 MeTube 的落盘目录一一对应
MEDIA_ROOT = os.getenv("MEDIA_ROOT", "/media")
MEDIA_TARGETS = {
    "game_video": f"{MEDIA_ROOT}/game_video",
    "yt_video": f"{MEDIA_ROOT}/yt_video",
    "movies": f"{MEDIA_ROOT}/movies",
    "anime": f"{MEDIA_ROOT}/anime",
}
# 低于这个余量就拒绝提交下载，0 表示关闭检查
MEDIA_MIN_FREE_BYTES = int(float(os.getenv("MEDIA_MIN_FREE_GB", "20")) * 1024**3)

# 只读挂载的备份产物，状态页用它们判断“最近一次备份是什么时候”
BACKUP_DIR = os.getenv("BACKUP_DIR", "/backup")
MC_BACKUP_DIR = os.getenv("MC_BACKUP_DIR", "/backup-mc")

# 所有工具模块都从这个实例注册
mcp = FastMCP("lab-tools", host="0.0.0.0", port=PORT)
