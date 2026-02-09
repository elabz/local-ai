#!/bin/bash
#
# Secure GPU Watchdog Service Installation for ASH
#
# This script installs the enhanced GPU watchdog service that monitors both:
# 1. GPU VRAM usage (detects OOM crashes)
# 2. Health endpoint status (detects unresponsive servers)
#
# Run this script as root on the GPU server:
#   sudo ./install-watchdog-secure.sh
#

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WATCHDOG_SCRIPT="$SCRIPT_DIR/gpu-watchdog.sh"
SERVICE_FILE="/etc/systemd/system/gpu-watchdog.service"

echo "=================================================="
echo "GPU Watchdog Service Installation (ASH)"
echo "=================================================="
echo ""

# Check if running as root
if [[ $EUID -ne 0 ]]; then
    echo "ERROR: This script must be run as root"
    echo "Usage: sudo $0"
    exit 1
fi

# Check if watchdog script exists
if [[ ! -f "$WATCHDOG_SCRIPT" ]]; then
    echo "ERROR: Watchdog script not found at: $WATCHDOG_SCRIPT"
    exit 1
fi

# Check docker is installed
if ! command -v docker &> /dev/null; then
    echo "ERROR: docker is not installed"
    exit 1
fi

# Check nvidia-smi is available
if ! command -v nvidia-smi &> /dev/null; then
    echo "ERROR: nvidia-smi is not installed (NVIDIA drivers required)"
    exit 1
fi

echo "1. Setting permissions on watchdog script..."
chmod +x "$WATCHDOG_SCRIPT"
echo "   ✓ Permissions updated"
echo ""

echo "2. Installing systemd service..."
cat > "$SERVICE_FILE" << 'EOF'
[Unit]
Description=HeartCode GPU Watchdog Service (Enhanced)
Documentation=https://github.com/heartcode/gpu-server
After=docker.service nvidia-persistenced.service
Requires=docker.service
PartOf=docker.service

[Service]
Type=simple
ExecStart=/home/boss/heartcode/gpu-server/scripts/gpu-watchdog.sh --daemon
Restart=always
RestartSec=10

# Environment variables
Environment="POLL_INTERVAL=30"
Environment="MIN_VRAM_MB=100"
Environment="LOG_FILE=/var/log/gpu-watchdog.log"
Environment="COMPOSE_FILE=/home/boss/heartcode/gpu-server/docker-compose.yml"

# Logging
StandardOutput=journal
StandardError=journal
SyslogIdentifier=gpu-watchdog

# Security
User=root
Group=docker

# Don't restart on exit
ExecStop=/bin/kill -TERM $MAINPID
KillMode=process

[Install]
WantedBy=multi-user.target
EOF

if [[ -f "$SERVICE_FILE" ]]; then
    echo "   ✓ Service file installed at $SERVICE_FILE"
else
    echo "   ✗ ERROR: Failed to install service file"
    exit 1
fi
echo ""

echo "3. Creating log directory and file..."
mkdir -p "$(dirname "/var/log/gpu-watchdog.log")"
touch "/var/log/gpu-watchdog.log"
chmod 644 "/var/log/gpu-watchdog.log"
echo "   ✓ Log file created at /var/log/gpu-watchdog.log"
echo ""

echo "4. Reloading systemd daemon..."
systemctl daemon-reload
echo "   ✓ Systemd reloaded"
echo ""

echo "5. Enabling service to auto-start on boot..."
systemctl enable gpu-watchdog.service
if systemctl is-enabled gpu-watchdog.service &> /dev/null; then
    echo "   ✓ Service enabled for auto-start"
else
    echo "   ✗ WARNING: Service may not be enabled"
fi
echo ""

echo "6. Starting GPU Watchdog service..."
systemctl start gpu-watchdog.service
sleep 2
echo ""

echo "7. Verifying service status..."
if systemctl is-active gpu-watchdog.service &> /dev/null; then
    echo "   ✓ Service is running"
    systemctl status gpu-watchdog.service --no-pager | head -20
else
    echo "   ✗ ERROR: Service failed to start"
    echo ""
    echo "Recent logs:"
    journalctl -u gpu-watchdog.service -n 20 --no-pager || echo "No logs available"
    exit 1
fi
echo ""

echo "=================================================="
echo "Installation Complete!"
echo "=================================================="
echo ""
echo "Watchdog Service Details:"
echo "  Service Name: gpu-watchdog.service"
echo "  Script Path: $WATCHDOG_SCRIPT"
echo "  Service File: $SERVICE_FILE"
echo "  Log File: /var/log/gpu-watchdog.log"
echo "  Poll Interval: 30 seconds"
echo "  VRAM Threshold: 100MB (crash detection)"
echo "  Health Check: Health endpoint monitoring (NEW)"
echo ""
echo "Useful Commands:"
echo "  sudo systemctl status gpu-watchdog          # Check status"
echo "  sudo systemctl restart gpu-watchdog         # Restart service"
echo "  sudo journalctl -u gpu-watchdog -f          # Follow systemd logs"
echo "  sudo tail -f /var/log/gpu-watchdog.log      # Follow watchdog logs"
echo "  sudo systemctl stop gpu-watchdog            # Stop service"
echo ""
echo "Testing the Watchdog:"
echo "  sudo /home/boss/heartcode/gpu-server/scripts/gpu-watchdog.sh  # Run once"
echo ""
