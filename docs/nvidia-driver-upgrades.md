# NVIDIA driver upgrades on Pea

The NVIDIA driver is the one package on Pea that must never upgrade unattended.

## Why

The driver comes in two halves:

- the **userspace library** (`libnvidia-*`, `nvidia-utils`), which switches over the
  moment the package installs;
- the **kernel module** (`nvidia-dkms-*`), which switches only when the host reboots.

Pea runs unattended-upgrades with `Automatic-Reboot` off, so an unattended driver
upgrade leaves the host half-upgraded:

- Containers that were already running keep serving, because they opened the GPUs
  before the switch.
- `nvidia-smi` fails with `Failed to initialize NVML: Driver/library version mismatch`.
- No GPU container can start. That includes a crash restart, a canary swap or a
  rollback.
- `pea-gpu-controller` cannot discover GPUs, so it cannot recover anything.
- `nvidia-cdi-refresh.service` fails.

This happened on 2026-10-10. Ubuntu's security pocket upgraded 580.173.02 to
580.178.04 at 06:49 UTC, and it went unnoticed until someone ran `nvidia-smi`.

## The guard (install once per host)

```bash
cd ~/local-ai/gpu-server/scripts
sudo ./install-driver-upgrade-guard.sh
```

The script installs `51unattended-upgrades-nvidia` into `/etc/apt/apt.conf.d/`.
That file blacklists `nvidia-`, `libnvidia-` and `xserver-xorg-video-nvidia-`
from unattended-upgrades. Every other security update still installs on its own.
Kernel updates also stay automatic: DKMS rebuilds the *installed* driver for a new
kernel, so the library and the module still match.

The guard is a blacklist, not `apt-mark hold`, on purpose. A hold blocks your
deliberate upgrade too, and it is easy to forget.

## The alert

`pea-gpu-controller` posts to `#hardware-alerts` (via `SLACK_WEBHOOK_URL` in
`gpu-server/.gpu-watchdog.env`):

- once, after `GPU_DISCOVERY_ALERT_CYCLES` consecutive failed discoveries (default 5,
  so about 5 minutes);
- once more when discovery recovers.

The alert carries `nvidia-smi`'s own error line. If it says "Driver/library version
mismatch", follow [Recovering from a half-applied upgrade](#recovering-from-a-half-applied-upgrade).

## Upgrading the driver deliberately

Pick a quiet window. Chat goes down for the length of a reboot, about 3 minutes plus
model load.

1. **Check that nothing is mid-measurement.** Look for canary runs, evaluations and
   load tests. Note any canary loan recorded in the topology (`canary:` on a slot):
   it survives the reboot, and the controller will not start that slot's displaced
   services.
2. **See what will change:**
   ```bash
   apt list --upgradable 2>/dev/null | grep -i nvidia
   ```
   Pascal (P104-100) support is the constraint. Read the release notes before moving
   to a new driver *branch*; a point release inside the same branch is the normal case.
3. **Upgrade and reboot immediately.** Do not leave the host half-upgraded:
   ```bash
   sudo apt-get install --only-upgrade $(dpkg -l | awk '/^ii  (lib)?nvidia-|^ii  xserver-xorg-video-nvidia-/{print $2}')
   sudo reboot
   ```
4. **Verify:**
   ```bash
   nvidia-smi                                   # 8 GPUs, new driver version
   cat /proc/driver/nvidia/version              # kernel module matches nvidia-smi
   systemctl is-active nvidia-cdi-refresh nvidia-power-limit pea-gpu-controller
   journalctl -u pea-gpu-controller -b | grep -E "GPU driver ready|discovery failed"
   docker ps --format '{{.Names}} {{.Status}}' | grep -E 'pea-gpu|canary|speech|image'
   ```
   Expect `GPU driver ready: 8/8`, every slot container healthy, and the power limits
   back at 90 W (`nvidia-smi -q -d POWER | grep 'Power Limit'`).

## Recovering from a half-applied upgrade

This is the state the guard prevents. If it happens anyway (a manual `apt upgrade`,
or the guard is missing):

1. **Leave running containers alone.** They are serving. Restarting one fails, and it
   stays down until the reboot.
2. **Confirm the mismatch.** The two versions differ:
   ```bash
   cat /proc/driver/nvidia/version   # loaded kernel module
   grep nvidia /var/log/dpkg.log | tail -5
   ```
3. **Reboot at the first safe moment**, then run step 4 of the upgrade procedure above.
4. If `nvidia-cdi-refresh` is still failed after the reboot, run
   `sudo systemctl restart nvidia-cdi-refresh`. Then install the guard if it was missing.

## Housekeeping

`nvidia-driver-570-server` was still installed next to the 580 branch as of
2026-10-10. Remove it in a maintenance window, so apt has only one driver to manage.

On 2026-10-10 a simulated purge removed only three packages:
`nvidia-driver-570-server`, `nvidia-utils-570-server` and
`libnvidia-compute-570-server`. `/usr/bin/nvidia-smi` belongs to
`nvidia-utils-580-server`, so it stays. Re-run the simulation first:

```bash
apt-get -s purge 'nvidia-*570*' 'libnvidia-*570*' | grep -E '^(Purg|Remv)'
sudo apt purge 'nvidia-*570*' 'libnvidia-*570*'
```
