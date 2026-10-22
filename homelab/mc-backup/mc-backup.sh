#!/bin/bash
set -euo pipefail

INSTANCE_DIR="/opt/mcsmanager/daemon/data/InstanceData/e0eeefcd-5756-4d34-99ba-4f014ba69684"
BACKUP_DIR="/home/ubuntu/backups"
DEST_DIR="/mnt/d/ubuntu_/.cache/homelab-migration/backup/mc-daily"
STAMP="$(date +%Y%m%d-%H%M)"
ARCHIVE="$BACKUP_DIR/mc-$STAMP.tar.gz"

mkdir -p "$BACKUP_DIR" "$DEST_DIR"
chown -R ubuntu:ubuntu "$BACKUP_DIR" "$DEST_DIR"

exec >> "$BACKUP_DIR/backup.log" 2>&1
echo "[$(date '+%F %T')] start backup"

if ! docker inspect mc-rt2home >/dev/null 2>&1; then
  echo "container mc-rt2home not found"
  exit 1
fi

# 暂停容器，保证世界文件一致；退出时确保恢复
docker pause mc-rt2home
trap 'docker unpause mc-rt2home >/dev/null 2>&1 || true' EXIT

tar -czf "$ARCHIVE" -C "$INSTANCE_DIR" \
  --exclude='RT_2_Home/session.lock' \
  RT_2_Home server.properties config kubejs defaultconfigs \
  ops.json whitelist.json banned-ips.json banned-players.json \
  usercache.json usernamecache.json

docker unpause mc-rt2home
trap - EXIT

chown ubuntu:ubuntu "$ARCHIVE"
echo "[$(date '+%F %T')] archive: $ARCHIVE ($(du -h "$ARCHIVE" | cut -f1))"

# 本地保留 7 天
find "$BACKUP_DIR" -maxdepth 1 -name 'mc-*.tar.gz' -mtime +7 -delete

# 复制到 D 盘并保留 7 天
cp -f "$ARCHIVE" "$DEST_DIR/"
find "$DEST_DIR" -maxdepth 1 -name 'mc-*.tar.gz' -mtime +7 -delete

echo "[$(date '+%F %T')] done"
