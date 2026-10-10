#!/bin/bash
#
# Keep the NVIDIA driver out of unattended-upgrades on Pea, and verify it.
#
#   sudo ./install-driver-upgrade-guard.sh
#
# Idempotent. See 51unattended-upgrades-nvidia for why, and
# docs/nvidia-driver-upgrades.md for how to upgrade the driver deliberately.
set -euo pipefail

if [[ $EUID -ne 0 ]]; then
    echo "ERROR: run as root (sudo $0)"; exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC="$SCRIPT_DIR/51unattended-upgrades-nvidia"
DST="/etc/apt/apt.conf.d/51unattended-upgrades-nvidia"

install -m 0644 "$SRC" "$DST"
echo "Installed $DST"

# apt merges every Package-Blacklist list across apt.conf.d; confirm ours landed.
if apt-config dump | grep -q 'Unattended-Upgrade::Package-Blacklist:: "libnvidia-"'; then
    echo "OK: NVIDIA packages are blacklisted from unattended-upgrades"
else
    echo "ERROR: blacklist not visible in apt-config dump"; exit 1
fi

# A driver package that would otherwise upgrade unattended shows up here as kept back.
if command -v unattended-upgrade >/dev/null; then
    echo "Dry run (NVIDIA lines only; empty is fine when no driver update is pending):"
    unattended-upgrade --dry-run --debug 2>&1 | grep -i nvidia || true
fi

if apt-mark showhold | grep -qi nvidia; then
    echo "NOTE: apt-mark holds on NVIDIA packages also exist; they block deliberate upgrades too."
fi
