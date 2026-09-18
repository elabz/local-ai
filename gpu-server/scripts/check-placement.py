#!/usr/bin/env python3
"""Compare recorded GPU placement with what is actually running on the GPU host.

Recorded truth:
  - gpu-server/configs/gpu-topology.json   slot -> uuid, main tenants, optional canary
  - litellm/config.yaml                    which host ports LiteLLM routes to
  - the GPU failure controller inventory   (/var/lib/pea-gpu-controller), when readable

Live truth (collected on the GPU host):
  - nvidia-smi --query-gpu / --query-compute-apps   GPU UUIDs, process -> UUID
  - /proc/<pid>/cgroup                              process -> container id
  - docker inspect                                  names, state, UUID pins, host ports

Drift reported (one line each, exit 1 when any is found):
  not-running         a recorded tenant (main or canary) is not running
  wrong-card          a tenant is pinned to, or computing on, a different card than its slot
  name-pin-mismatch   a container named *-gpuN / *-gpu-N is pinned to another card
  unrouted            a running chat/embed container publishes no port LiteLLM routes
  unrecorded          a live GPU-pinned container is not a tenant of any slot
  displaced-running   a slot records a canary but its main tenants are also running
  inventory-mismatch  the controller inventory disagrees with gpu-topology.json

Usage (on the GPU host, from the repo checkout):
  check-placement.py                      collect live state and check
  check-placement.py --dump-snapshot F    also write the collected live state to F
  check-placement.py --snapshot F         check a previously recorded snapshot (tests)

Pure stdlib so it runs on the host without a venv.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
TOPOLOGY = REPO_ROOT / "gpu-server" / "configs" / "gpu-topology.json"
LITELLM_CONFIG = REPO_ROOT / "litellm" / "config.yaml"
MANIFEST = REPO_ROOT / "gpu-server" / "models.yaml"
CONTROLLER_INVENTORY = Path("/var/lib/pea-gpu-controller/current-inventory.json")

# Containers that serve a routed chat or embedding model group.
ROUTED_PREFIXES = ("pea-gpu-", "pea-embed-")
CARD_SUFFIX = re.compile(r"gpu-?(\d+)$")
CONTAINER_ID = re.compile(r"[0-9a-f]{64}")
LIVE_STATES = {"running", "restarting"}


class CollectError(Exception):
    pass


# --------------------------------------------------------------------------- collection

def _run(args: list[str], timeout: int = 30) -> str:
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=timeout, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise CollectError(f"{args[0]} failed: {exc}") from exc
    if result.returncode:
        raise CollectError(f"{' '.join(args[:2])} exited {result.returncode}: {result.stderr.strip()}")
    return result.stdout


def parse_csv_pairs(text: str) -> list[tuple[str, str]]:
    pairs = []
    for line in text.splitlines():
        parts = [p.strip() for p in line.split(",", 1)]
        if len(parts) == 2 and parts[0] and parts[1]:
            pairs.append((parts[0], parts[1]))
    return pairs


def parse_container(inspect: dict) -> dict:
    """Reduce one `docker inspect` object to the fields the checks use."""
    config, host = inspect.get("Config") or {}, inspect.get("HostConfig") or {}
    state = inspect.get("State") or {}
    pins: list[str] = []
    for request in host.get("DeviceRequests") or []:
        pins.extend(request.get("DeviceIDs") or [])
    for env in config.get("Env") or []:
        if env.startswith("NVIDIA_VISIBLE_DEVICES="):
            pins.extend(env.split("=", 1)[1].split(","))
    pins = sorted({p.strip() for p in pins if p.strip().startswith("GPU-")})

    ports: set[int] = set()
    live_ports = (inspect.get("NetworkSettings") or {}).get("Ports") or {}
    bindings = live_ports if any(live_ports.values()) else (host.get("PortBindings") or {})
    for binds in bindings.values():
        for bind in binds or []:
            if str(bind.get("HostPort", "")).isdigit():
                ports.add(int(bind["HostPort"]))

    return {
        "name": inspect.get("Name", "").lstrip("/"),
        "id": inspect.get("Id", ""),
        "state": state.get("Status", "unknown"),
        "health": (state.get("Health") or {}).get("Status"),
        "pins": pins,
        "ports": sorted(ports),
    }


def container_for_pid(pid: str) -> str | None:
    try:
        match = CONTAINER_ID.search(Path(f"/proc/{pid}/cgroup").read_text())
    except OSError:
        return None
    return match.group(0) if match else None


def collect() -> dict:
    gpus = [{"uuid": u, "pci": p} for u, p in parse_csv_pairs(
        _run(["nvidia-smi", "--query-gpu=uuid,pci.bus_id", "--format=csv,noheader,nounits"]))]
    if not gpus:
        raise CollectError("nvidia-smi reported no GPUs")
    apps = [{"pid": pid, "uuid": uuid, "container_id": container_for_pid(pid)}
            for pid, uuid in parse_csv_pairs(
                _run(["nvidia-smi", "--query-compute-apps=pid,gpu_uuid", "--format=csv,noheader,nounits"]))]
    ids = _run(["docker", "ps", "-aq", "--no-trunc"]).split()
    containers = [parse_container(c) for c in json.loads(_run(["docker", "inspect", *ids]))] if ids else []
    return {"gpus": gpus, "compute_apps": apps, "containers": containers}


# --------------------------------------------------------------------------- recorded state

def routed_ports(litellm_config: str, manifest: str) -> set[int]:
    """Ports on the GPU host that LiteLLM routes (manifest + extra canary routes)."""
    host = re.search(r"^host:\s*(\S+)", manifest, re.MULTILINE)
    host_pattern = re.escape(host.group(1)) if host else r"[^:/\s]+"
    return {int(p) for p in re.findall(rf"api_base:\s*['\"]?http://{host_pattern}:(\d+)", litellm_config)}


def slot_tenants(topology: dict) -> dict[str, dict]:
    """Map every recorded container name to its slot and role (main/canary)."""
    tenants = {}
    for pci, slot in topology.get("slots", {}).items():
        for name in slot.get("containers", []):
            tenants[name] = {"pci": pci, "slot": slot, "role": "main"}
        canary = slot.get("canary")
        if canary:
            tenants[canary["container"]] = {"pci": pci, "slot": slot, "role": "canary"}
    return tenants


# --------------------------------------------------------------------------- checks

def check(snapshot: dict, topology: dict, routed: set[int], inventory: dict | None = None) -> list[str]:
    drift: list[str] = []
    containers = {c["name"]: c for c in snapshot["containers"]}
    by_id = {c["id"]: c for c in snapshot["containers"]}
    slots = topology.get("slots", {})
    card_of = {slot["uuid"]: slot["id"] for slot in slots.values()}
    tenants = slot_tenants(topology)

    def card(uuid: str) -> str:
        return card_of.get(uuid, f"unknown {uuid}")

    for pci, slot in slots.items():
        sid, uuid = slot["id"], slot["uuid"]
        canary = slot.get("canary")
        expected = [canary["container"]] if canary else list(slot.get("containers", []))
        if canary and canary.get("uuid") and canary["uuid"] != uuid:
            drift.append(f"{sid} wrong-card: canary {canary['container']} recorded on "
                         f"{card(canary['uuid'])}, slot is {sid}")
        if canary:
            for name in slot.get("containers", []):
                if containers.get(name, {}).get("state") in LIVE_STATES:
                    drift.append(f"{sid} displaced-running: {name} is running while canary "
                                 f"{canary['container']} is recorded on this slot")
        for name in expected:
            c = containers.get(name)
            if not c or c["state"] not in LIVE_STATES:
                drift.append(f"{sid} not-running: {name} ({c['state'] if c else 'absent'})")
                continue
            for pin in c["pins"]:
                if pin != uuid:
                    drift.append(f"{sid} wrong-card: {name} pinned to {card(pin)}, recorded on {sid}")

    for app in snapshot.get("compute_apps", []):
        c = by_id.get(app.get("container_id") or "")
        if not c:
            continue
        home = tenants.get(c["name"])
        if home and app["uuid"] != home["slot"]["uuid"]:
            drift.append(f"{home['slot']['id']} wrong-card: {c['name']} process {app['pid']} "
                         f"is computing on {card(app['uuid'])}")

    for c in snapshot["containers"]:
        # Only live containers: a long-exited leftover must not fail every deploy.
        if c["state"] not in LIVE_STATES:
            continue
        name = c["name"]
        match = CARD_SUFFIX.search(name)
        if match:
            for pin in c["pins"]:
                pinned = card_of.get(pin)
                if pinned and pinned != f"gpu-{match.group(1)}":
                    drift.append(f"{pinned} name-pin-mismatch: {name} is pinned to {pinned}")
        if c["pins"] and name not in tenants:
            drift.append(f"{card(c['pins'][0])} unrecorded: {name} is live on the card but not "
                         f"recorded in gpu-topology.json")
        if name.startswith(ROUTED_PREFIXES) and c["ports"] and not routed.intersection(c["ports"]):
            health = f", {c['health']}" if c["health"] else ""
            drift.append(f"{card(c['pins'][0]) if c['pins'] else '-'} unrouted: {name} "
                         f"(ports {c['ports']}{health}) is not routed in litellm/config.yaml")

    if inventory is not None:
        for pci, slot in slots.items():
            live = inventory.get("slots", {}).get(pci)
            fields = ("id", "services", "containers", "ports", "canary")
            # uuid is excluded: the controller legitimately adopts replacement cards.
            if live is None or any(live.get(f) != slot.get(f) for f in fields):
                drift.append(f"{slot['id']} inventory-mismatch: controller inventory differs from "
                             f"gpu-topology.json for {pci}; copy the topology over the inventory "
                             f"and restart pea-gpu-controller")
    return drift


# --------------------------------------------------------------------------- main

def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--topology", type=Path, default=TOPOLOGY)
    parser.add_argument("--litellm-config", type=Path, default=LITELLM_CONFIG)
    parser.add_argument("--manifest", type=Path, default=MANIFEST)
    parser.add_argument("--inventory", type=Path, default=CONTROLLER_INVENTORY)
    parser.add_argument("--snapshot", type=Path, help="check a recorded snapshot instead of live state")
    parser.add_argument("--dump-snapshot", type=Path, help="write the collected live state here")
    args = parser.parse_args(argv)

    topology = json.loads(args.topology.read_text())
    routed = routed_ports(args.litellm_config.read_text(), args.manifest.read_text())
    try:
        snapshot = json.loads(args.snapshot.read_text()) if args.snapshot else collect()
    except CollectError as exc:
        print(f"ERROR: could not collect live placement: {exc}", file=sys.stderr)
        return 2
    if args.dump_snapshot:
        args.dump_snapshot.write_text(json.dumps(snapshot, indent=2, sort_keys=True) + "\n")

    inventory = None
    try:
        inventory = json.loads(args.inventory.read_text())
    except FileNotFoundError:
        pass
    except PermissionError:
        print(f"WARN: {args.inventory} not readable; controller inventory not compared (run with sudo)",
              file=sys.stderr)

    drift = check(snapshot, topology, routed, inventory)
    for line in drift:
        print(f"DRIFT {line}")
    if drift:
        print(f"\n{len(drift)} placement drift finding(s)", file=sys.stderr)
        return 1
    print("OK: live placement matches gpu-topology.json and LiteLLM routing")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
