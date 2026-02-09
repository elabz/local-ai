#!/bin/bash
#
# Install GPU Watchdog Service on ASH
#
# Run this script as root on the GPU server:
#   sudo ./install-watchdog.sh
#

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "Installing GPU Watchdog Service..."

# Make watchdog executable
echo "1. Setting permissions..."
chmod +x "$SCRIPT_DIR/gpu-watchdog.sh"

# Install systemd service
echo "2. Installing systemd service..."
cp "$SCRIPT_DIR/gpu-watchdog.service" /etc/systemd/system/

# Reload systemd
echo "3. Reloading systemd..."
systemctl daemon-reload

# Enable and start service
echo "4. Enabling and starting service..."
systemctl enable gpu-watchdog.service
systemctl start gpu-watchdog.service

# Check status
echo "5. Checking status..."
systemctl status gpu-watchdog.service --no-pager

echo ""
echo "Installation complete!"
echo ""
echo "Useful commands:"
echo "  sudo systemctl status gpu-watchdog    # Check status"
echo "  sudo journalctl -u gpu-watchdog -f    # Follow logs"
echo "  sudo tail -f /var/log/gpu-watchdog.log  # View watchdog log"
