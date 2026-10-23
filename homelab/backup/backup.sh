#!/bin/bash
# 统一备份入口：目前备份 Rong的账单（SQLite 一致快照 + CSV 导出）。
# 由 backup.service / backup.timer 每天触发；产物写到 D 盘 .cache，保留 14 天。
# 新增服务时在备份动作区继续追加，保持“一个脚本、一处落点”的约定。
set -euo pipefail

BASE_DIR="${BASE_DIR:-/mnt/d/ubuntu_/.cache/backup}"
STAMP="$(date +%Y%m%d-%H%M)"
OUT_DIR="$BASE_DIR/bill-ai/$STAMP"
KEEP_DAYS="${KEEP_DAYS:-14}"

mkdir -p "$OUT_DIR"

echo "[$(date '+%F %T')] start homelab backup -> $OUT_DIR"

# Rong的账单：/api/backup.db 用 sqlite3 在线备份，避免直接拷 WAL 中的库
curl -fsS --max-time 120 http://127.0.0.1:8091/api/backup.db -o "$OUT_DIR/bill.db.part"
mv "$OUT_DIR/bill.db.part" "$OUT_DIR/bill.db"
curl -fsS --max-time 120 http://127.0.0.1:8091/api/export.csv -o "$OUT_DIR/transactions.csv.part"
mv "$OUT_DIR/transactions.csv.part" "$OUT_DIR/transactions.csv"

chown -R ubuntu:ubuntu "$OUT_DIR" 2>/dev/null || true

find "$BASE_DIR/bill-ai" -mindepth 1 -maxdepth 1 -type d -mtime "+$KEEP_DAYS" -exec rm -rf {} +

echo "[$(date '+%F %T')] done: $(du -sh "$OUT_DIR" | cut -f1)"
