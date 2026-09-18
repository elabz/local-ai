import copy
import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).parents[1]
MODULE_PATH = ROOT / "scripts" / "check-placement.py"
SPEC = importlib.util.spec_from_file_location("check_placement", MODULE_PATH)
placement = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(placement)

FIXTURES = Path(__file__).parent / "fixtures" / "placement"
GPU5 = "GPU-d8525241-21cb-a127-b4d8-d72b9ac32b1b"
GPU6 = "GPU-fe0fc635-7c25-49b8-866e-3e4f9ce7efc9"
GPU6_PCI = "0000:0b:00.0"


@pytest.fixture
def snapshot():
    """Live PEA state recorded 2026-09-16 with --dump-snapshot (healthy layout)."""
    return json.loads((FIXTURES / "pea-snapshot-2026-09-16.json").read_text())


@pytest.fixture
def topology():
    return json.loads((ROOT / "configs" / "gpu-topology.json").read_text())


@pytest.fixture
def routed():
    return placement.routed_ports(
        (ROOT.parent / "litellm" / "config.yaml").read_text(), (ROOT / "models.yaml").read_text())


def named(snapshot, name):
    return next(c for c in snapshot["containers"] if c["name"] == name)


def add_container(snapshot, name, pins, ports, state="running", cid=None):
    container = {"name": name, "id": cid or name.ljust(64, "0"), "state": state,
                 "health": None, "pins": pins, "ports": ports}
    snapshot["containers"].append(container)
    return container


def kinds(drift):
    return [line.split(":", 1)[0] for line in drift]


def test_recorded_healthy_layout_has_no_drift(snapshot, topology, routed):
    assert placement.check(snapshot, topology, routed) == []


def test_routed_ports_cover_every_manifest_deployment(routed):
    assert {8080, 8081, 8082, 8083, 8084, 8085, 8093, 8094, 8101, 8102, 8104, 8105, 5100} <= routed


def test_routed_ports_ignore_other_hosts():
    config = "api_base: http://192.0.2.9:9000/v1\napi_base: http://192.168.70.144:8085/v1\n"
    assert placement.routed_ports(config, "host: 192.168.70.144\n") == {8085}


def test_parse_container_reads_pins_ports_state_from_inspect():
    raw = json.loads((FIXTURES / "docker-inspect-2026-09-16.json").read_text())
    parsed = {c["name"]: c for c in map(placement.parse_container, raw)}
    assert parsed["pea-gpu-6"] == {
        "name": "pea-gpu-6", "id": parsed["pea-gpu-6"]["id"], "state": "running",
        "health": "healthy", "pins": [GPU6], "ports": [8085]}
    # Exited containers have no live port map: fall back to the bindings.
    assert parsed["pea-sfw-model-canary-gpu6"]["state"] == "exited"
    assert parsed["pea-sfw-model-canary-gpu6"]["ports"] == [18085]
    # An exposed-but-unbound container port is not a host port.
    assert parsed["pea-embed-5"]["ports"] == [8094]
    assert parsed["pea-prometheus"]["pins"] == []


def test_canary_named_for_gpu5_pinned_to_gpu6_is_a_name_pin_mismatch(snapshot, topology, routed):
    add_container(snapshot, "pea-sfw-model-canary-gpu5", [GPU6], [18085])
    topology["slots"][GPU6_PCI]["canary"] = {
        "container": "pea-sfw-model-canary-gpu5", "compose_file": "docker-compose.model-canaries.yml", "uuid": GPU6}
    for name in ("pea-gpu-6", "pea-embed-dino-2"):
        named(snapshot, name)["state"] = "exited"
    drift = placement.check(snapshot, topology, routed)
    assert drift == ["gpu-6 name-pin-mismatch: pea-sfw-model-canary-gpu5 is pinned to gpu-6"]


def test_healthy_embed_replica_not_routed(snapshot, topology, routed):
    drift = placement.check(snapshot, topology, routed - {8094})
    assert drift == ["gpu-5 unrouted: pea-embed-5 (ports [8094], healthy) is not routed in litellm/config.yaml"]


def test_recorded_tenant_not_running(snapshot, topology, routed):
    named(snapshot, "pea-gpu-5")["state"] = "exited"
    assert placement.check(snapshot, topology, routed) == ["gpu-5 not-running: pea-gpu-5 (exited)"]


def test_tenant_pinned_to_another_card(snapshot, topology, routed):
    named(snapshot, "pea-embed-5")["pins"] = [GPU6]
    assert "gpu-5 wrong-card: pea-embed-5 pinned to gpu-6, recorded on gpu-5" in placement.check(
        snapshot, topology, routed)


def test_tenant_process_computing_on_another_card(snapshot, topology, routed):
    pid = next(a for a in snapshot["compute_apps"] if a["container_id"] == named(snapshot, "pea-gpu-5")["id"])
    pid["uuid"] = GPU6
    assert placement.check(snapshot, topology, routed) == [
        f"gpu-5 wrong-card: pea-gpu-5 process {pid['pid']} is computing on gpu-6"]


def test_live_unrecorded_gpu_container(snapshot, topology, routed):
    add_container(snapshot, "qwen3-canary-gpu5", [GPU5], [18084], state="restarting")
    assert placement.check(snapshot, topology, routed) == [
        "gpu-5 unrecorded: qwen3-canary-gpu5 is live on the card but not recorded in gpu-topology.json"]


def test_exited_leftovers_are_ignored(snapshot, topology, routed):
    add_container(snapshot, "old-canary-gpu5", [GPU6], [18084], state="exited")
    assert placement.check(snapshot, topology, routed) == []


def test_recorded_canary_expects_canary_and_flags_displaced_tenants(snapshot, topology, routed):
    topology["slots"][GPU6_PCI]["canary"] = {
        "container": "pea-sfw-model-canary-gpu6", "compose_file": "docker-compose.model-canaries.yml", "uuid": GPU6}
    drift = placement.check(snapshot, topology, routed)
    assert kinds(drift) == ["gpu-6 displaced-running", "gpu-6 displaced-running", "gpu-6 not-running"]


def test_recorded_canary_running_with_tenants_stopped_is_clean(snapshot, topology, routed):
    topology["slots"][GPU6_PCI]["canary"] = {
        "container": "pea-sfw-model-canary-gpu6", "compose_file": "docker-compose.model-canaries.yml", "uuid": GPU6}
    for name in ("pea-gpu-6", "pea-embed-dino-2"):
        named(snapshot, name)["state"] = "exited"
    snapshot["compute_apps"] = [a for a in snapshot["compute_apps"] if a["uuid"] != GPU6]
    add_container(snapshot, "pea-sfw-model-canary-gpu6", [GPU6], [18085])
    assert placement.check(snapshot, topology, routed) == []


def test_stale_controller_inventory_is_reported_but_replacement_uuid_is_not(snapshot, topology, routed):
    inventory = copy.deepcopy(topology)
    inventory["slots"]["0000:0a:00.0"]["uuid"] = "GPU-replacement"
    assert placement.check(snapshot, topology, routed, inventory) == []
    inventory["slots"][GPU6_PCI]["services"] = ["qwen3-canary"]
    assert kinds(placement.check(snapshot, topology, routed, inventory)) == ["gpu-6 inventory-mismatch"]


def test_main_exit_codes(tmp_path, snapshot):
    path = tmp_path / "snap.json"
    path.write_text(json.dumps(snapshot))
    missing = tmp_path / "no-inventory.json"
    assert placement.main(["--snapshot", str(path), "--inventory", str(missing)]) == 0
    named(snapshot, "pea-gpu-1")["state"] = "exited"
    path.write_text(json.dumps(snapshot))
    assert placement.main(["--snapshot", str(path), "--inventory", str(missing)]) == 1
