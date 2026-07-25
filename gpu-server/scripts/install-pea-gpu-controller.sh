#!/bin/bash
#
# Install the durable GPU recovery controller (gpu_failure_controller.py) as a
# supervised systemd service on PEA, replacing the boss @reboot crontab launcher.
#
#   sudo ./install-pea-gpu-controller.sh
#
# Idempotent: safe to re-run. Migrates existing controller state from the old
# cron location (~boss/.local/state) into the systemd StateDirectory once.
set -euo pipefail

if [[ $EUID -ne 0 ]]; then
    echo "ERROR: run as root (sudo $0)"; exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
UNIT_SRC="$SCRIPT_DIR/pea-gpu-controller.service"
UNIT_DST="/etc/systemd/system/pea-gpu-controller.service"
CONTROLLER="$SCRIPT_DIR/gpu_failure_controller.py"
OLD_STATE="/home/boss/.local/state/pea-gpu-controller"
NEW_STATE="/var/lib/pea-gpu-controller"
CRON_USER="boss"

[[ -f "$UNIT_SRC" ]]   || { echo "ERROR: unit not found: $UNIT_SRC"; exit 1; }
[[ -f "$CONTROLLER" ]] || { echo "ERROR: controller not found: $CONTROLLER"; exit 1; }
command -v docker >/dev/null     || { echo "ERROR: docker not installed"; exit 1; }
command -v nvidia-smi >/dev/null || { echo "ERROR: nvidia-smi not installed"; exit 1; }

echo "1. Stopping any running controller (cron or manual) ..."
pkill -f 'gpu_failure_controller.py' 2>/dev/null && sleep 2 || echo "   none running"

echo "2. Removing the @reboot crontab launcher for ${CRON_USER} ..."
if crontab -u "$CRON_USER" -l 2>/dev/null | grep -q 'gpu_failure_controller'; then
    crontab -u "$CRON_USER" -l 2>/dev/null | grep -v 'gpu_failure_controller' | crontab -u "$CRON_USER" -
    echo "   removed"
else
    echo "   none found"
fi

echo "3. Migrating controller state -> ${NEW_STATE} ..."
mkdir -p "$NEW_STATE"
if [[ -d "$OLD_STATE" && ! -f "$NEW_STATE/current-inventory.json" ]]; then
    cp -a "$OLD_STATE/." "$NEW_STATE/"
    echo "   copied from ${OLD_STATE}"
else
    echo "   ${NEW_STATE} already populated or no old state; leaving as-is"
fi
chown -R root:root "$NEW_STATE"

echo "4. Installing unit -> ${UNIT_DST} ..."
install -m 0644 "$UNIT_SRC" "$UNIT_DST"
systemctl daemon-reload
systemctl enable --now pea-gpu-controller.service

echo "5. Status:"
sleep 3
systemctl --no-pager --full status pea-gpu-controller.service | head -18 || true
echo
echo "Done. Follow logs with:  journalctl -u pea-gpu-controller -f"
