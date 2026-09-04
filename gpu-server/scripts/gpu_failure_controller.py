#!/usr/bin/env python3
"""Durable PCI-slot GPU recovery, port quarantine, and hardware alerting."""
from __future__ import annotations

import argparse
import copy
import json
import logging
import os
import shutil
import signal
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

LOG = logging.getLogger("gpu-failure-controller")
MAX_ATTEMPTS = 3


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def atomic_json(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=path.name + ".", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as handle:
            json.dump(value, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def normalize_pci(value: str) -> str:
    value = value.strip().lower()
    if value.count(":") == 1:
        value = "0000:" + value
    domain, bus, device = value.rsplit(":", 2)
    return f"{domain[-4:]}:{bus}:{device}"


class Quiet503(BaseHTTPRequestHandler):
    body = b'{"status":"unavailable","reason":"gpu_hardware_failed"}\n'

    def _reply(self):
        self.send_response(503)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(self.body)))
        self.send_header("Retry-After", "300")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(self.body)

    do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = do_OPTIONS = do_HEAD = _reply

    def log_message(self, *_args):
        return


class Quarantine:
    def __init__(self, host="0.0.0.0"):
        self.host, self.servers = host, {}

    def start(self, ports):
        for port in ports:
            if int(port) in self.servers:
                continue
            try:
                server = ThreadingHTTPServer((self.host, int(port)), Quiet503)
            except OSError as exc:
                # The port is already bound — normally by the real service
                # container that is actually healthy. Never let one quarantine
                # bind failure crash the whole controller (that left the boot
                # rollout half-done). Log and move on.
                LOG.warning("Quarantine bind skipped on port %s: %s", port, exc)
                continue
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            self.servers[int(port)] = server

    def stop(self, ports=None):
        for port in list(self.servers if ports is None else ports):
            server = self.servers.pop(int(port), None)
            if server:
                server.shutdown()
                server.server_close()


class Controller:
    def __init__(self, topology: Path, state_dir: Path, compose_dir: Path,
                 runner=subprocess.run, quarantine=None, sleep=time.sleep):
        self.template_path, self.state_dir, self.compose_dir = topology, state_dir, compose_dir
        self.inventory_path = state_dir / "current-inventory.json"
        self.recovery_path = state_dir / "recovery-state.json"
        self.failed_path = state_dir / "failed-gpus.json"
        self.override_path = state_dir / "gpu-uuid.override.json"
        self.archive_dir = state_dir / "inventory-archive"
        self.runner, self.quarantine, self.sleep = runner, quarantine or Quarantine(), sleep
        state_dir.mkdir(parents=True, exist_ok=True)
        self.inventory = self._load_or_copy_inventory()
        self.recovery = self._load(self.recovery_path, {"slots": {}})
        self.failed = self._load(self.failed_path, {"failed": []})

    @staticmethod
    def _load(path, default):
        try:
            with Path(path).open() as handle:
                return json.load(handle)
        except FileNotFoundError:
            return copy.deepcopy(default)

    def _load_or_copy_inventory(self):
        if not self.inventory_path.exists():
            shutil.copyfile(self.template_path, self.inventory_path)
        return self._load(self.inventory_path, {})

    def command(self, args, timeout=90):
        try:
            return self.runner(args, capture_output=True, text=True, timeout=timeout, check=False)
        except subprocess.TimeoutExpired:
            LOG.warning("Command timed out: %s", args[0])
            return subprocess.CompletedProcess(args, 124, "", "")

    def discover(self):
        result = self.command(["nvidia-smi", "--query-gpu=uuid,pci.bus_id", "--format=csv,noheader,nounits"])
        if result.returncode:
            LOG.warning("GPU discovery failed")
            return {}
        found = {}
        for line in result.stdout.splitlines():
            parts = [part.strip() for part in line.split(",", 1)]
            if len(parts) == 2:
                found[normalize_pci(parts[1])] = parts[0]
        return found

    def reconcile_replacements(self, discovered):
        changed = False
        for pci, slot in self.inventory["slots"].items():
            new_uuid, old_uuid = discovered.get(normalize_pci(pci)), slot["uuid"]
            if new_uuid and new_uuid != old_uuid:
                self.archive_dir.mkdir(parents=True, exist_ok=True)
                atomic_json(self.archive_dir / (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + ".json"), self.inventory)
                self.failed["failed"].append({"uuid": old_uuid, "pci": pci, "replaced_at": utc_now()})
                slot["uuid"] = new_uuid
                self.recovery.setdefault("slots", {}).pop(pci, None)
                changed = True
                LOG.info("Adopted replacement for %s at %s", slot["id"], pci)
        if changed:
            atomic_json(self.inventory_path, self.inventory)
            atomic_json(self.failed_path, self.failed)
            atomic_json(self.recovery_path, self.recovery)
        self.write_override()
        return changed

    def write_override(self):
        services = {}
        for slot in self.inventory["slots"].values():
            uuid = slot["uuid"]
            os.environ[f"PEA_{slot['id'].upper().replace('-', '_')}_UUID"] = uuid
            for service in slot["services"]:
                env = {"NVIDIA_VISIBLE_DEVICES": uuid}
                if service.startswith(("gpu-server-", "vision-embed-", "dino-embed-")):
                    env["EXPECTED_GPU_UUID"] = uuid
                services[service] = {"environment": env}
        atomic_json(self.override_path, {"services": services})

    def compose(self, action, services):
        args = ["docker", "compose", "-f", str(self.compose_dir / "docker-compose.yml"),
                "-f", str(self.compose_dir / "docker-compose.gpu-health-canary.yml"),
                "-f", str(self.override_path), action]
        if action == "up":
            args.extend(["-d", "--no-build"])
        args.extend(services)
        return self.command(args, timeout=300)

    def containers_ready(self, names):
        for name in names:
            result = self.command(["docker", "inspect", "-f", "{{.State.Running}}", name], timeout=15)
            if result.returncode or result.stdout.strip() != "true":
                return False
        return True

    def alert(self, pci, slot, reason):
        webhook = os.getenv("SLACK_WEBHOOK_URL", "")
        if not webhook:
            LOG.error("Slack webhook is not configured")
            return False
        payload = {"channel": "#hardware-alerts", "text": (
            f"GPU hardware recovery exhausted: id={slot['id']} uuid={slot['uuid']} "
            f"pci={pci} attempts={MAX_ATTEMPTS} reason={reason}")}
        request = urllib.request.Request(webhook, json.dumps(payload).encode(), {"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                return 200 <= response.status < 300
        except (OSError, urllib.error.URLError):
            LOG.error("Slack hardware alert delivery failed")
            return False

    def attempt(self, pci, slot, discovered, force=False):
        record = self.recovery.setdefault("slots", {}).setdefault(pci, {"uuid": slot["uuid"], "attempts": 0, "notified": False})
        if record.get("uuid") != slot["uuid"]:
            record.clear(); record.update({"uuid": slot["uuid"], "attempts": 0, "notified": False})
        if record["attempts"] >= MAX_ATTEMPTS and not force:
            self.quarantine.start(slot["ports"])
            return False
        self.quarantine.stop(slot["ports"])
        self.compose("stop", slot["services"])
        if pci in discovered:
            self.command(["nvidia-smi", "--gpu-reset", "-i", slot["uuid"]], timeout=60)
        record["attempts"] += 1
        record["last_attempt_at"] = utc_now()
        atomic_json(self.recovery_path, self.recovery)
        result = self.compose("up", slot["services"])
        self.sleep(float(os.getenv("GPU_RECOVERY_SETTLE_SECONDS", "20")))
        success = result.returncode == 0 and pci in self.discover() and self.containers_ready(slot["containers"])
        if success:
            self.recovery["slots"].pop(pci, None)
            atomic_json(self.recovery_path, self.recovery)
            return True
        self.compose("stop", slot["services"])
        self.quarantine.start(slot["ports"])
        record["reason"] = "gpu_absent" if pci not in discovered else "restart_failed"
        if record["attempts"] >= MAX_ATTEMPTS and not record.get("notified"):
            record["notified"] = self.alert(pci, slot, record["reason"])
        atomic_json(self.recovery_path, self.recovery)
        return False

    def wait_for_driver(self):
        """Block until nvidia-smi reports the full expected GPU set, or a bounded
        timeout elapses. Prevents the first cold-boot cycle from running before
        the driver is ready and falsely quarantining every slot as gpu_absent."""
        expected = len(self.inventory.get("slots", {}))
        if not expected:
            return
        deadline = time.time() + float(os.getenv("GPU_DRIVER_WAIT_SECONDS", "180"))
        while True:
            found = len(self.discover())
            if found >= expected:
                LOG.info("GPU driver ready: %d/%d GPUs visible", found, expected)
                return
            if time.time() >= deadline:
                LOG.warning("Driver wait timed out: %d/%d GPUs visible", found, expected)
                return
            LOG.info("Waiting for GPU driver: %d/%d visible", found, expected)
            self.sleep(float(os.getenv("GPU_DRIVER_POLL_SECONDS", "5")))

    def cycle(self, force=False):
        discovered = self.discover()
        if not discovered:
            # nvidia-smi returned nothing: the driver is not ready (cold boot) or
            # the probe transiently failed — never a simultaneous per-slot
            # hardware failure. Treating every slot as absent here is what tore
            # down and quarantined the whole stack at boot, then stuck at
            # attempts>=MAX. Skip the cycle and let a later poll reconcile.
            LOG.warning("No GPUs discovered; skipping cycle (driver not ready?)")
            return {}
        self.reconcile_replacements(discovered)
        results = {}
        for pci, slot in self.inventory["slots"].items():
            key = normalize_pci(pci)
            existing = self.recovery.get("slots", {}).get(pci, {})
            failed = key not in discovered or existing.get("attempts", 0) > 0
            if failed:
                results[pci] = self.attempt(pci, slot, discovered, force=force)
            else:
                self.quarantine.stop(slot["ports"])
                # On a normal daemon poll, leave healthy running workloads alone.
                # Cold boot and replacement still take this path because their
                # mapped containers are absent or stopped.
                results[pci] = (self.containers_ready(slot["containers"]) or
                                self.compose("up", slot["services"]).returncode == 0)
        return results


def main():
    parser = argparse.ArgumentParser()
    root = Path(__file__).resolve().parents[1]
    parser.add_argument("--topology", type=Path, default=root / "configs/gpu-topology.json")
    parser.add_argument("--state-dir", type=Path, default=Path("/var/lib/pea-gpu-controller"))
    parser.add_argument("--compose-dir", type=Path, default=root)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    controller = Controller(args.topology, args.state_dir, args.compose_dir)
    stopping = threading.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: stopping.set())
    controller.wait_for_driver()
    while True:
        controller.cycle(force=args.force)
        if args.once or stopping.wait(float(os.getenv("GPU_CONTROLLER_POLL_SECONDS", "60"))):
            break
    controller.quarantine.stop()


if __name__ == "__main__":
    main()
