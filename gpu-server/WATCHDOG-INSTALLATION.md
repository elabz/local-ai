# GPU Watchdog Service Installation Guide

## Quick Installation (Copy & Paste)

Run these commands on the ASH GPU server as `root`:

```bash
# SSH to ASH (run from your local machine)
ssh root@192.168.0.145

# Then on ASH, run:
cd /home/boss/heartcode/gpu-server/scripts

# Make installation script executable
chmod +x install-watchdog-secure.sh

# Run the installation
sudo ./install-watchdog-secure.sh
```

## What Gets Installed

The enhanced GPU Watchdog Service monitors:

### 1. **VRAM Usage** (OOM/Crash Detection)
- Monitors GPU VRAM to detect when containers crash
- Threshold: < 100MB VRAM indicates crash
- Restarts both GPU server and embedding server containers

### 2. **Health Endpoint** (Unresponsiveness Detection) - **NEW**
- Monitors `/health` endpoint on each GPU port (8080-8087)
- Detects when inference server becomes unresponsive
- Automatically restarts container before performance degrades

## Installation Details

| Component | Details |
|-----------|---------|
| Script | `/home/boss/heartcode/gpu-server/scripts/gpu-watchdog.sh` |
| Service File | `/etc/systemd/system/gpu-watchdog.service` |
| Log File | `/var/log/gpu-watchdog.log` |
| Poll Interval | 30 seconds (checks GPU VRAM + health status) |
| Auto-Start | Yes (enabled on boot) |

## Verification

After installation, verify the service is running:

```bash
# Check service status
sudo systemctl status gpu-watchdog.service

# Follow live logs
sudo journalctl -u gpu-watchdog.service -f

# Or check the log file directly
sudo tail -f /var/log/gpu-watchdog.log
```

## Manual Troubleshooting

### Run watchdog once to test
```bash
sudo /home/boss/heartcode/gpu-server/scripts/gpu-watchdog.sh
```

### View recent watchdog logs
```bash
sudo tail -100 /var/log/gpu-watchdog.log
```

### View systemd journal logs
```bash
sudo journalctl -u gpu-watchdog.service -n 50 --no-pager
```

### Restart the service
```bash
sudo systemctl restart gpu-watchdog.service
```

### Stop the service temporarily
```bash
sudo systemctl stop gpu-watchdog.service
```

## Expected Output

When a GPU becomes unhealthy, you should see logs like:

```
[2026-01-15 12:34:56] WARNING: GPU 4 Chat server health check failed (port 8084) - RESTARTING containers
[2026-01-15 12:34:56]   Restarting container: local-ai-gpu-5
[2026-01-15 12:34:56]   SUCCESS: local-ai-gpu-5 restarted
[2026-01-15 12:34:56]   Restarting container: local-ai-embed-5
[2026-01-15 12:34:57]   SUCCESS: local-ai-embed-5 restarted
[2026-01-15 12:34:57]   Waiting for containers to stabilize (15 seconds)...
[2026-01-15 12:35:12]   VERIFIED: local-ai-gpu-5 is running
[2026-01-15 12:35:12]   VERIFIED: local-ai-embed-5 is running
[2026-01-15 12:35:17]   VERIFIED: Health endpoint is responding
```

## Testing the Watchdog

To test if the watchdog properly detects and restarts a failed GPU:

1. Stop a GPU container manually:
   ```bash
   docker stop local-ai-gpu-4
   ```

2. Watch the watchdog logs:
   ```bash
   sudo tail -f /var/log/gpu-watchdog.log
   ```

3. Within 30 seconds (poll interval), you should see it detect the health check failure and restart the container automatically.

## Key Improvements Over Previous Version

| Feature | Old Watchdog | New Watchdog |
|---------|--------------|------------|
| VRAM Monitoring | ✓ | ✓ |
| Health Check Monitoring | ✗ | ✓ **NEW** |
| Detects Unresponsive Servers | ✗ | ✓ **NEW** |
| Auto-Restart on Crash | ✓ | ✓ |
| Auto-Restart on Unresponsiveness | ✗ | ✓ **NEW** |
| Detailed Logging | ✓ | ✓ Enhanced |
| Verification After Restart | Basic | Enhanced |

## Configuration

To adjust watchdog behavior, edit `/etc/systemd/system/gpu-watchdog.service`:

```bash
# Change poll interval (default: 30 seconds)
Environment="POLL_INTERVAL=30"

# Change VRAM threshold for crash detection (default: 100MB)
Environment="MIN_VRAM_MB=100"

# Change log file location (default: /var/log/gpu-watchdog.log)
Environment="LOG_FILE=/var/log/gpu-watchdog.log"
```

Then reload and restart:
```bash
sudo systemctl daemon-reload
sudo systemctl restart gpu-watchdog.service
```

## Support

If you have issues with the watchdog installation:

1. Check the log file: `sudo tail -100 /var/log/gpu-watchdog.log`
2. Check systemd logs: `sudo journalctl -u gpu-watchdog.service -n 50`
3. Verify docker is running: `docker ps`
4. Verify nvidia-smi is available: `nvidia-smi`
5. Verify GPU containers are named correctly: `docker ps | grep gpu-server`
