import json

from labtools.docker_api import docker_client, human_bytes
from labtools.runtime import mcp


def disk_summary() -> dict:
    """Docker 磁盘占用的结构化摘要，供 disk_usage 和 health_snapshot 共用。"""
    df = docker_client().df()
    images = df.get("Images") or []
    containers = df.get("Containers") or []
    volumes = df.get("Volumes") or []
    cache = df.get("BuildCache") or []

    image_size = sum((item.get("Size") or 0) for item in images)
    unused_image_size = sum(
        (item.get("Size") or 0) for item in images if not (item.get("Containers") or 0)
    )
    container_size = sum((item.get("SizeRw") or 0) for item in containers)
    volume_size = sum(
        ((item.get("UsageData") or {}).get("Size") or 0) for item in volumes
    )
    unused_volume_size = sum(
        ((item.get("UsageData") or {}).get("Size") or 0)
        for item in volumes
        if ((item.get("UsageData") or {}).get("RefCount") or 0) == 0
    )
    cache_size = sum((item.get("Size") or 0) for item in cache)
    unused_cache_size = sum(
        (item.get("Size") or 0) for item in cache if not item.get("InUse")
    )

    return {
        "images": {
            "count": len(images),
            "size": human_bytes(image_size),
            "unused_size": human_bytes(unused_image_size),
        },
        "containers": {
            "count": len(containers),
            "writable_size": human_bytes(container_size),
        },
        "volumes": {
            "count": len(volumes),
            "size": human_bytes(volume_size),
            "unused_size": human_bytes(unused_volume_size),
        },
        "build_cache": {
            "count": len(cache),
            "size": human_bytes(cache_size),
            "unused_size": human_bytes(unused_cache_size),
        },
        "total_reclaimable": human_bytes(
            unused_image_size + unused_volume_size + unused_cache_size
        ),
    }


@mcp.tool()
def disk_usage() -> str:
    """查看 Docker 占用的磁盘空间：镜像、容器、数据卷、构建缓存各自的总量和可回收量。只读。"""
    return json.dumps(disk_summary(), ensure_ascii=False, indent=2)
