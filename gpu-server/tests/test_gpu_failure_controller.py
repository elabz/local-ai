import importlib.util
import json
import socket
import subprocess
import urllib.error
import urllib.request
from pathlib import Path

import pytest


MODULE_PATH = Path(__file__).parents[1] / "scripts" / "gpu_failure_controller.py"
SPEC = importlib.util.spec_from_file_location("gpu_failure_controller", MODULE_PATH)
gpu = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(gpu)


def completed(args, code=0, stdout=""):
    return subprocess.CompletedProcess(args, code, stdout, "")


def topology(tmp_path, ports=None):
    path = tmp_path / "topology.json"
    path.write_text(json.dumps({"schema_version": 1, "slots": {
        "0000:04:00.0": {"id": "gpu-2", "uuid": "GPU-old", "services": ["gpu-server-2", "vision-embed-2"],
                           "containers": ["pea-gpu-2", "pea-vision-2"], "ports": ports or [18081, 18102]}
    }}))
    return path


class FakeQuarantine:
    def __init__(self): self.started, self.stopped = [], []
    def start(self, ports): self.started.append(list(ports))
    def stop(self, ports=None): self.stopped.append(None if ports is None else list(ports))


def controller(tmp_path, runner, quarantine=None):
    compose = tmp_path / "compose"
    compose.mkdir()
    return gpu.Controller(topology(tmp_path), tmp_path / "state", compose, runner=runner,
                          quarantine=quarantine or FakeQuarantine(), sleep=lambda _n: None)


def test_replacement_rotates_inventory_and_writes_override(tmp_path):
    ctl = controller(tmp_path, lambda args, **kw: completed(args))
    assert ctl.reconcile_replacements({"0000:04:00.0": "GPU-new"})
    assert ctl.inventory["slots"]["0000:04:00.0"]["uuid"] == "GPU-new"
    assert ctl.failed["failed"][0]["uuid"] == "GPU-old"
    assert list((ctl.state_dir / "inventory-archive").glob("*.json"))
    override = json.loads(ctl.override_path.read_text())
    assert override["services"]["gpu-server-2"]["environment"]["EXPECTED_GPU_UUID"] == "GPU-new"
    assert "deploy" not in override["services"]["vision-embed-2"]
    assert gpu.os.environ["PEA_GPU_2_UUID"] == "GPU-new"


def test_three_failures_persist_and_alert_once(tmp_path, monkeypatch):
    commands, alerts, quarantine = [], [], FakeQuarantine()
    def runner(args, **kw):
        commands.append(args)
        if args[0] == "nvidia-smi": return completed(args, 1)
        return completed(args, 1 if "up" in args else 0)
    ctl = controller(tmp_path, runner, quarantine)
    monkeypatch.setattr(ctl, "alert", lambda pci, slot, reason: alerts.append((pci, slot["uuid"], reason)) or True)
    for _ in range(3):
        assert ctl.attempt("0000:04:00.0", ctl.inventory["slots"]["0000:04:00.0"], {}, force=False) is False
    assert ctl.recovery["slots"]["0000:04:00.0"]["attempts"] == 3
    assert len(alerts) == 1
    up_count = sum(command[0:2] == ["docker", "compose"] and "up" in command for command in commands)
    ctl.attempt("0000:04:00.0", ctl.inventory["slots"]["0000:04:00.0"], {}, force=False)
    assert sum(command[0:2] == ["docker", "compose"] and "up" in command for command in commands) == up_count
    assert len(alerts) == 1


def test_success_resets_durable_attempt_state_and_restarts_all(tmp_path):
    commands = []
    def runner(args, **kw):
        commands.append(args)
        if args[0] == "nvidia-smi":
            return completed(args, stdout="GPU-old, 00000000:04:00.0\n")
        if args[:3] == ["docker", "inspect", "-f"]: return completed(args, stdout="true\n")
        return completed(args)
    ctl = controller(tmp_path, runner)
    slot = ctl.inventory["slots"]["0000:04:00.0"]
    assert ctl.attempt("0000:04:00.0", slot, {"0000:04:00.0": "GPU-old"})
    assert "0000:04:00.0" not in ctl.recovery["slots"]
    assert any("--gpu-reset" in command for command in commands)
    up = next(command for command in commands if command[:2] == ["docker", "compose"] and "up" in command)
    assert up[-2:] == ["gpu-server-2", "vision-embed-2"]


def free_ports(count):
    sockets, ports = [], []
    for _ in range(count):
        sock = socket.socket(); sock.bind(("127.0.0.1", 0)); sockets.append(sock); ports.append(sock.getsockname()[1])
    for sock in sockets: sock.close()
    return ports


def test_quarantine_returns_503_for_all_methods_on_all_ports():
    ports = free_ports(2)
    quarantine = gpu.Quarantine(host="127.0.0.1")
    try:
        quarantine.start(ports)
        for port in ports:
            for method in ("GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"):
                request = urllib.request.Request(f"http://127.0.0.1:{port}/any/model/path", method=method)
                with pytest.raises(urllib.error.HTTPError) as error:
                    urllib.request.urlopen(request, timeout=2)
                assert error.value.code == 503
                if method != "HEAD": assert json.loads(error.value.read())["reason"] == "gpu_hardware_failed"
    finally:
        quarantine.stop()


def test_inventory_and_recovery_files_are_valid_after_reload(tmp_path):
    ctl = controller(tmp_path, lambda args, **kw: completed(args, 1))
    ctl.recovery["slots"]["0000:04:00.0"] = {"uuid": "GPU-old", "attempts": 2, "notified": False}
    gpu.atomic_json(ctl.recovery_path, ctl.recovery)
    reloaded = gpu.Controller(ctl.template_path, ctl.state_dir, ctl.compose_dir,
                              runner=lambda args, **kw: completed(args, 1), quarantine=FakeQuarantine())
    assert reloaded.recovery["slots"]["0000:04:00.0"]["attempts"] == 2


def test_healthy_poll_does_not_recreate_running_services(tmp_path):
    commands = []
    def runner(args, **kw):
        commands.append(args)
        if args[0] == "nvidia-smi": return completed(args, stdout="GPU-old, 00000000:04:00.0\n")
        if args[:3] == ["docker", "inspect", "-f"]: return completed(args, stdout="true\n")
        return completed(args)
    ctl = controller(tmp_path, runner)
    assert ctl.cycle()["0000:04:00.0"]
    assert not any(command[:2] == ["docker", "compose"] for command in commands)


def test_command_timeout_is_bounded_and_does_not_crash_controller(tmp_path):
    def runner(args, **kw):
        raise subprocess.TimeoutExpired(args, kw["timeout"])
    ctl = controller(tmp_path, runner)
    result = ctl.command(["docker", "inspect", "missing"], timeout=1)
    assert result.returncode == 124
