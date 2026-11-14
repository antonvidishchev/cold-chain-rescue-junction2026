#!/usr/bin/env bash
# Copy the watchdog app to the Uno Q over adb and (re)start it.
# Usage: scripts/deploy-device.sh [logs]
set -euo pipefail

APP_DIR="$(cd "$(dirname "$0")/../device/coldchain-watchdog" && pwd)"
REMOTE=/home/arduino/ArduinoApps/coldchain-watchdog
APP_ID=user:coldchain-watchdog

adb get-state >/dev/null
adb shell "arduino-app-cli app stop $APP_ID >/dev/null 2>&1 || true"
# Stop any other running app so the matrix, buzzer and port 7000 are free.
for other in $(adb shell "arduino-app-cli app ps 2>/dev/null" | awk 'NR>1 && $1 ~ /^user:/ {print $1}'); do
  adb shell "arduino-app-cli app stop $other" || true
done
adb shell "rm -rf $REMOTE/python $REMOTE/sketch $REMOTE/assets && mkdir -p $REMOTE"
for item in app.yaml python sketch assets; do
  adb push "$APP_DIR/$item" "$REMOTE/" >/dev/null
done
adb shell "rm -rf $REMOTE/python/__pycache__"
adb shell "arduino-app-cli app start $APP_ID"

IP=$(adb shell "ip -4 addr show wlan0" | awk '/inet /{split($2,a,"/");print a[1]}')
echo "Watchdog API: http://$IP:7000/api/state"

if [[ "${1:-}" == "logs" ]]; then
  adb shell "arduino-app-cli app logs $APP_ID --follow"
fi
