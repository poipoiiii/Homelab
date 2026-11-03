#!/usr/bin/env bash
# MQTT 联调工具：在 broker 容器内跑 mosquitto_sub / mosquitto_pub，免装本地客户端。
# 用法：
#   bash mqtt.sh watch [filter]            订阅（默认 home/#）
#   bash mqtt.sh state [site]              用设备账号发一条 retained 假状态
#   bash mqtt.sh telemetry [site]          用设备账号发一条假遥测
#   bash mqtt.sh cmd '<payload>' [site]    用控制台账号下发命令
#   bash mqtt.sh pub <topic> '<payload>'   用设备账号发任意 topic（不 retain）
set -euo pipefail

CRED=/home/ubuntu/mqtt/credentials.txt
CONTAINER=mqtt
SITE=dorm

if [[ ! -f "$CRED" ]]; then
  echo "缺少 $CRED，先运行：sudo bash ~/homelab/mqtt/setup.sh" >&2
  exit 1
fi
# shellcheck disable=SC1090
source "$CRED"

sub() {
  docker exec "$CONTAINER" mosquitto_sub -h 127.0.0.1 -u "$APP_USER" -P "$APP_PASS" -t "$1" -v
}

case "${1:-watch}" in
  watch)
    sub "${2:-home/#}"
    ;;
  state)
    site="${2:-$SITE}"
    docker exec "$CONTAINER" mosquitto_pub -h 127.0.0.1 -u "$RONG_USER" -P "$RONG_PASS" \
      -t "home/$site/stm32/rong/state" -r -m "{\"dev\":\"rong\",\"up\":123,\"led\":0}"
    ;;
  telemetry)
    site="${2:-$SITE}"
    docker exec "$CONTAINER" mosquitto_pub -h 127.0.0.1 -u "$RONG_USER" -P "$RONG_PASS" \
      -t "home/$site/stm32/rong/telemetry" -m "{\"dev\":\"rong\",\"ip\":\"10.0.0.61\",\"rssi\":-58}"
    ;;
  cmd)
    payload="${2:?用法: mqtt.sh cmd '<json>' [site]}"
    site="${3:-$SITE}"
    docker exec "$CONTAINER" mosquitto_pub -h 127.0.0.1 -u "$APP_USER" -P "$APP_PASS" \
      -t "home/$site/stm32/rong/cmd" -m "$payload"
    ;;
  pub)
    topic="${2:?用法: mqtt.sh pub <topic> '<json>'}"
    payload="${3:?用法: mqtt.sh pub <topic> '<json>'}"
    docker exec "$CONTAINER" mosquitto_pub -h 127.0.0.1 -u "$RONG_USER" -P "$RONG_PASS" \
      -t "$topic" -m "$payload"
    ;;
  *)
    echo "未知命令：$1" >&2
    exit 1
    ;;
esac
