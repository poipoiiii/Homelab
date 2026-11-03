#!/usr/bin/env bash
# MQTT 初始化：生成设备/控制台账号，打印连接信息。
# 用法（WSL 内）：sudo bash ~/homelab/mqtt/setup.sh
# 幂等：已存在 passwd 时不会覆盖；重置需先删除 /home/ubuntu/mqtt/passwd。
set -euo pipefail

BASE_DIR=/home/ubuntu/mqtt
STACK_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
IMAGE=eclipse-mosquitto:2

if [[ ${EUID} -ne 0 ]]; then
  echo "需要 root（要 chown 给容器内的 1883 用户）：sudo bash $0" >&2
  exit 1
fi

mkdir -p "$BASE_DIR"
chmod 700 "$BASE_DIR"

if [[ -f "$BASE_DIR/passwd" ]]; then
  echo "已存在 $BASE_DIR/passwd，跳过账号生成。"
  echo "重置方法：rm $BASE_DIR/passwd $BASE_DIR/credentials.txt && sudo bash $0"
else
  RONG_PW="$(openssl rand -hex 16)"
  APP_PW="$(openssl rand -hex 16)"
  docker run --rm -v "$BASE_DIR:/work" "$IMAGE" sh -c \
    "mosquitto_passwd -b -c /work/passwd rong '$RONG_PW' && mosquitto_passwd -b /work/passwd app '$APP_PW'"
  chown 1883:1883 "$BASE_DIR/passwd"
  chmod 600 "$BASE_DIR/passwd"
  cat > "$BASE_DIR/credentials.txt" <<EOF
# MQTT 账号（只保存在本机 ext4，勿提交、勿外发）
RONG_USER=rong
RONG_PASS=$RONG_PW
APP_USER=app
APP_PASS=$APP_PW
EOF
  chmod 600 "$BASE_DIR/credentials.txt"
  echo "已生成 $BASE_DIR/passwd 与 $BASE_DIR/credentials.txt"
fi

# aclfile 不是机密，但 Mosquitto 2.1+ 要求它不能 world-readable，否则新版会拒绝加载
if [[ -f "$STACK_DIR/aclfile" ]]; then
  chown 1883:1883 "$STACK_DIR/aclfile"
  chmod 640 "$STACK_DIR/aclfile"
fi

TAILSCALE_IP="$(tailscale ip -4 2>/dev/null | head -n1 || true)"

cat <<EOF
连接信息：
  公网(frp)  : poipoiii.cn:1883
  tailnet    : ${TAILSCALE_IP:-未获取到}:1883
  TCP 明文，无 TLS（AT 1.3.0.0 不支持）

topic 约定  : home/<site>/stm32/rong/{state,telemetry,cmd,status}
当前站点    : dorm（设备搬回家后更换 site 即可）
凭据文件    : $BASE_DIR/credentials.txt
EOF
