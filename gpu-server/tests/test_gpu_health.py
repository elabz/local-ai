import subprocess
import sys
import threading
import types
import importlib.util
from contextlib import contextmanager
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from gpu_health import GPUHealthMonitor, GPUReadiness, GPUUnavailable, probe_nvidia_smi

VISION_GPU_HEALTH_PATH = Path(__file__).resolve().parents[1] / "vision-embed" / "gpu_health.py"
vision_spec = importlib.util.spec_from_file_location("vision_gpu_health", VISION_GPU_HEALTH_PATH)
vision_gpu_health = importlib.util.module_from_spec(vision_spec)
assert vision_spec.loader is not None
sys.modules[vision_spec.name] = vision_gpu_health
vision_spec.loader.exec_module(vision_gpu_health)
probe_torch_gpu = vision_gpu_health.probe_torch_gpu


def completed(output: str):
    return subprocess.CompletedProcess([], 0, stdout=output, stderr="")


def test_readiness_fails_immediately_and_requires_two_successes_to_recover():
    transitions = []
    readiness = GPUReadiness(enabled=True, on_transition=lambda state, reason: transitions.append((state, reason)))
    assert readiness.success().state == "starting"
    assert readiness.success().state == "ready"
    readiness.fail("gpu_execution_failed")
    assert readiness.snapshot().state == "unavailable"
    assert readiness.success().state == "unavailable"
    assert readiness.success().state == "ready"
    assert transitions[-2:] == [("unavailable", "gpu_execution_failed"), ("ready", "ready")]


def test_disabled_gate_preserves_ready_behavior():
    readiness = GPUReadiness(enabled=False)
    assert readiness.ready
    assert readiness.snapshot().reason == "disabled"


def test_unavailable_admission_has_only_safe_reason():
    readiness = GPUReadiness(enabled=True)
    readiness.fail("private prompt /host/path")
    with pytest.raises(GPUUnavailable, match="gpu_query_failed"):
        readiness.require_ready()


def test_nvidia_probe_accepts_exact_uuid_and_memory():
    runner = lambda *args, **kwargs: completed("GPU-good, 8192\n")
    assert probe_nvidia_smi("GPU-good", runner=runner) is None


def test_nvidia_probe_rejects_uuid_mismatch_and_bad_memory():
    assert probe_nvidia_smi("GPU-good", runner=lambda *a, **k: completed("GPU-other, 8192\n")) == "gpu_identity_mismatch"
    assert probe_nvidia_smi("GPU-good", runner=lambda *a, **k: completed("GPU-good, 0\n")) == "gpu_memory_failed"


def test_nvidia_probe_maps_query_error_to_safe_reason():
    def failed(*args, **kwargs):
        raise subprocess.TimeoutExpired("nvidia-smi", 5)
    assert probe_nvidia_smi("GPU-good", runner=failed) == "gpu_query_failed"


def test_monitor_maps_probe_result_and_recovery():
    results = iter(["gpu_query_failed", None, None])
    readiness = GPUReadiness(enabled=True)
    monitor = GPUHealthMonitor(readiness, lambda: next(results))
    assert monitor.check().state == "unavailable"
    assert monitor.check().state == "unavailable"
    assert monitor.check().state == "ready"


class TrackingLock:
    def __init__(self):
        self.lock = threading.Lock()
        self.entered = False

    def __enter__(self):
        self.lock.acquire()
        self.entered = True
        return self

    def __exit__(self, *_args):
        self.lock.release()


def install_gpu_modules(monkeypatch, *, uuid="GPU-good", memory=8192, execution_error=False):
    lock_holder = {}

    class Tensor:
        def add_(self, _value):
            if execution_error:
                raise RuntimeError("device unavailable")
            return self

        def item(self):
            return 2

    torch = types.SimpleNamespace(
        cuda=types.SimpleNamespace(is_available=lambda: True, device_count=lambda: 1, synchronize=lambda: None),
        ones=lambda *_args, **_kwargs: Tensor(),
    )
    pynvml = types.SimpleNamespace(
        nvmlInit=lambda: None,
        nvmlDeviceGetHandleByUUID=lambda expected: ("handle", expected),
        nvmlDeviceGetUUID=lambda _handle: uuid,
        nvmlDeviceGetMemoryInfo=lambda _handle: types.SimpleNamespace(total=memory),
    )
    monkeypatch.setitem(sys.modules, "torch", torch)
    monkeypatch.setitem(sys.modules, "pynvml", pynvml)
    return lock_holder


def test_torch_probe_verifies_expected_uuid_memory_and_execution_under_lock(monkeypatch):
    install_gpu_modules(monkeypatch)
    lock = TrackingLock()
    assert probe_torch_gpu("GPU-good", lock=lock) is None
    assert lock.entered


def test_torch_probe_returns_bounded_identity_memory_and_execution_reasons(monkeypatch):
    install_gpu_modules(monkeypatch, uuid="GPU-other")
    assert probe_torch_gpu("GPU-good") == "gpu_identity_mismatch"
    install_gpu_modules(monkeypatch, memory=0)
    assert probe_torch_gpu("GPU-good") == "gpu_memory_failed"
    install_gpu_modules(monkeypatch, execution_error=True)
    assert probe_torch_gpu("GPU-good") == "gpu_execution_failed"


def test_torch_probe_maps_missing_configured_uuid_to_identity_mismatch(monkeypatch):
    install_gpu_modules(monkeypatch)
    class NVMLError_NotFound(Exception):
        pass
    sys.modules["pynvml"].nvmlDeviceGetHandleByUUID = lambda _expected: (_ for _ in ()).throw(NVMLError_NotFound())
    assert probe_torch_gpu("GPU-missing") == "gpu_identity_mismatch"


def test_service_routes_gate_health_and_inference_before_model_work():
    for relative in ("vision-embed/routes.py", "dino-embed/routes.py", "multimodal-embed/routes.py"):
        content = (Path(__file__).resolve().parents[1] / relative).read_text()
        assert '@router.get("/live")' in content
        assert "readiness.require_ready()" in content
        assert 'status_code=503, detail={"code": "GPU_UNAVAILABLE"' in content
        assert 'logger.error("Embedding error: gpu_execution_failed")' in content


class Metric:
    def labels(self, **_labels):
        return self

    def inc(self, *_args):
        pass

    def dec(self):
        pass

    def observe(self, _value):
        pass


@contextmanager
def loaded_routes(monkeypatch, service):
    service_dir = Path(__file__).resolve().parents[1] / service
    settings = types.SimpleNamespace(server_id="test", model_id="test/model", precision="fp32")
    monkeypatch.setitem(sys.modules, "config", types.SimpleNamespace(settings=settings))
    monkeypatch.setitem(sys.modules, "metrics", types.SimpleNamespace(
        active_requests_gauge=Metric(), embedding_items_total=Metric(),
        inference_duration_seconds=Metric(), inference_requests_total=Metric(),
    ))
    monkeypatch.setitem(sys.modules, "gpu_health", vision_gpu_health)
    image_input = types.SimpleNamespace(
        ImageInputError=type("ImageInputError", (ValueError,), {}),
        InputItem=object,
        parse_input=lambda value: [types.SimpleNamespace(index=0, modality="text", text=value, image=None)],
    )
    monkeypatch.setitem(sys.modules, "image_input", image_input)
    spec = importlib.util.spec_from_file_location(f"{service.replace('-', '_')}_routes_test", service_dir / "routes.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    yield module


@pytest.mark.parametrize("service", ["vision-embed", "dino-embed", "multimodal-embed"])
def test_unavailable_gpu_returns_503_before_model_invocation(monkeypatch, service):
    with loaded_routes(monkeypatch, service) as routes:
        app = FastAPI()
        app.include_router(routes.router)
        calls = []
        app.state.embedder = types.SimpleNamespace(
            loaded=True, dimension=2,
            embed_texts=lambda _items: calls.append("text"),
            embed_images=lambda _items: calls.append("image"),
        )
        readiness = vision_gpu_health.GPUReadiness(enabled=True)
        readiness.fail("gpu_query_failed")
        app.state.gpu_readiness = readiness
        client = TestClient(app)
        assert client.get("/live").status_code == 200
        health = client.get("/health")
        assert health.status_code == 503
        assert health.json()["detail"]["reason"] == "gpu_query_failed"
        response = client.post("/v1/embeddings", json={"input": "do-not-process"})
        assert response.status_code == 503
        assert response.json()["detail"] == {"code": "GPU_UNAVAILABLE", "reason": "gpu_query_failed"}
        assert calls == []


def test_dino_litellm_health_sentinel_preserves_image_only_contract(monkeypatch):
    with loaded_routes(monkeypatch, "dino-embed") as routes:
        app = FastAPI()
        app.include_router(routes.router)
        calls = []
        app.state.embedder = types.SimpleNamespace(
            loaded=True, dimension=2, embed_images=lambda _items: calls.append("image"),
        )
        readiness = vision_gpu_health.GPUReadiness(enabled=True)
        readiness.success()
        readiness.success()
        app.state.gpu_readiness = readiness
        client = TestClient(app)
        health = client.post("/v1/embeddings", json={
            "model": "heartcode-embed-visual-health", "input": ["test from litellm"],
        })
        assert health.status_code == 200
        assert health.json()["data"][0]["embedding"] == [0.0, 0.0]
        assert calls == []
        ordinary = client.post("/v1/embeddings", json={
            "model": "heartcode-embed-visual", "input": ["test from litellm"],
        })
        assert ordinary.status_code == 400


def test_inference_device_failure_marks_readiness_unavailable_without_error_detail(monkeypatch):
    with loaded_routes(monkeypatch, "vision-embed") as routes:
        app = FastAPI()
        app.include_router(routes.router)
        def lost_device(_items):
            raise RuntimeError("CUDA error containing /private/path and request data")
        app.state.embedder = types.SimpleNamespace(
            loaded=True, dimension=2, embed_texts=lost_device, embed_images=lambda _items: [],
        )
        readiness = vision_gpu_health.GPUReadiness(enabled=True)
        readiness.success()
        readiness.success()
        app.state.gpu_readiness = readiness
        response = TestClient(app).post("/v1/embeddings", json={"input": "private input"})
        assert response.status_code == 503
        assert response.json()["detail"] == {"code": "GPU_UNAVAILABLE", "reason": "gpu_execution_failed"}
        assert readiness.snapshot().reason == "gpu_execution_failed"
        assert "/private/path" not in response.text
        assert "private input" not in response.text


def test_non_gpu_inference_failure_does_not_withdraw_ready_replica(monkeypatch):
    with loaded_routes(monkeypatch, "vision-embed") as routes:
        app = FastAPI()
        app.include_router(routes.router)
        app.state.embedder = types.SimpleNamespace(
            loaded=True, dimension=2,
            embed_texts=lambda _items: (_ for _ in ()).throw(RuntimeError("application bug")),
            embed_images=lambda _items: [],
        )
        readiness = vision_gpu_health.GPUReadiness(enabled=True)
        readiness.success()
        readiness.success()
        app.state.gpu_readiness = readiness
        response = TestClient(app).post("/v1/embeddings", json={"input": "private input"})
        assert response.status_code == 500
        assert response.json()["detail"] == {"code": "INTERNAL_ERROR"}
        assert readiness.ready
        assert "application bug" not in response.text


def test_chat_routes_gate_all_inference_entrypoints():
    content = (Path(__file__).resolve().parents[1] / "routes.py").read_text()
    assert '@router.get("/live")' in content
    assert content.count("require_gpu_ready(request)") == 3


@contextmanager
def loaded_chat_routes(monkeypatch):
    settings = types.SimpleNamespace(server_id="chat-test", model_path="/models/test.gguf")
    monkeypatch.setitem(sys.modules, "config", types.SimpleNamespace(settings=settings))
    monkeypatch.setitem(sys.modules, "metrics", types.SimpleNamespace(
        active_requests_gauge=Metric(), inference_tokens_total=Metric(),
        inference_duration_seconds=Metric(), inference_requests_total=Metric(),
    ))
    monkeypatch.setitem(sys.modules, "gpu_health", sys.modules[__name__].GPUReadiness.__module__ and __import__("gpu_health"))
    path = Path(__file__).resolve().parents[1] / "routes.py"
    spec = importlib.util.spec_from_file_location("chat_routes_test", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    yield module


class LlamaStub:
    def __init__(self, status="ok"):
        self.status = status
        self.calls = []

    async def health_check(self):
        self.calls.append("health")
        return {"status": self.status}

    async def completion(self, **_kwargs):
        self.calls.append("completion")
        return {}

    async def chat_completion(self, **_kwargs):
        self.calls.append("chat")
        return {}

    async def tokenize(self, _content):
        self.calls.append("tokenize")
        return {"tokens": []}


def test_chat_health_combines_child_and_gpu_readiness(monkeypatch):
    with loaded_chat_routes(monkeypatch) as routes:
        app = FastAPI()
        app.include_router(routes.router)
        child = LlamaStub()
        app.state.llama_client = child
        readiness = GPUReadiness(enabled=True)
        readiness.fail("gpu_identity_mismatch")
        app.state.gpu_readiness = readiness
        client = TestClient(app)
        assert client.get("/live").status_code == 200
        assert client.get("/health").status_code == 503
        assert child.calls == []
        readiness.success()
        assert client.get("/health").status_code == 503
        readiness.success()
        assert client.get("/health").status_code == 200
        child.status = "loading model"
        assert client.get("/health").status_code == 503


def test_chat_gpu_unavailable_rejects_every_inference_route(monkeypatch):
    with loaded_chat_routes(monkeypatch) as routes:
        app = FastAPI()
        app.include_router(routes.router)
        child = LlamaStub()
        app.state.llama_client = child
        readiness = GPUReadiness(enabled=True)
        readiness.fail("gpu_query_failed")
        app.state.gpu_readiness = readiness
        client = TestClient(app)
        requests = (
            client.post("/v1/completions", json={"prompt": "secret"}),
            client.post("/v1/chat/completions", json={"messages": [{"role": "user", "content": "secret"}]}),
            client.post("/tokenize", json={"content": "secret"}),
        )
        assert [response.status_code for response in requests] == [503, 503, 503]
        assert child.calls == []
