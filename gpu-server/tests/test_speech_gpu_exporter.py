"""speech/gpu_exporter.py inventory logic.

The exporter container is pinned to one GPU, so nvidia-smi inside it renumbers
that card to index 0. Comparing that against the configured host index made
SpeechGPUInventoryMismatch fire from deployment until 2026-09-20 while the card
was correctly placed. aiohttp is stubbed so this runs on the CI test deps.
"""
import importlib.util
import sys
import types
from pathlib import Path

import pytest

EXPORTER = Path(__file__).resolve().parents[1] / "speech" / "gpu_exporter.py"
SPEECH_GPU = "GPU-f417c539-26db-94e9-4c8f-c5a775291988"
OTHER_GPU = "GPU-d8525241-21cb-a127-b4d8-d72b9ac32b1b"


@pytest.fixture(scope="module")
def exporter():
    # Imported once: the module registers its gauges in the default Prometheus
    # registry at import, and a second import raises "Duplicated timeseries".
    monkeypatch = pytest.MonkeyPatch()
    web = types.ModuleType("aiohttp.web")
    web.Application = lambda *a, **k: types.SimpleNamespace(
        router=types.SimpleNamespace(add_get=lambda *args, **kwargs: None)
    )
    web.Response = web.json_response = lambda *a, **k: None
    web.run_app = lambda *a, **k: pytest.fail("import must not start the server")
    aiohttp = types.ModuleType("aiohttp")
    aiohttp.web = web
    monkeypatch.setitem(sys.modules, "aiohttp", aiohttp)
    monkeypatch.setitem(sys.modules, "aiohttp.web", web)
    monkeypatch.setenv("SPEECH_GPU_UUID", SPEECH_GPU)
    monkeypatch.setenv("SPEECH_GPU_PHYSICAL_INDEX", "6")

    spec = importlib.util.spec_from_file_location("speech_gpu_exporter", EXPORTER)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    yield module
    monkeypatch.undo()


def test_pinned_container_sees_index_0_and_still_matches(exporter):
    # What the deployed exporter actually sees: NVIDIA_VISIBLE_DEVICES pins one
    # card, which nvidia-smi then calls index 0.
    uuid, index, util, match = exporter.inventory([f"{SPEECH_GPU}, 0, 17"])
    assert (uuid, match) == (SPEECH_GPU, True)
    assert index == "6", "the label must report the configured host index, not the container-local one"
    assert util == "17"


def test_wrong_card_pinned_does_not_match(exporter):
    with pytest.raises(LookupError):
        exporter.inventory([f"{OTHER_GPU}, 0, 3"])


def test_no_visible_gpu_does_not_match(exporter):
    with pytest.raises(LookupError):
        exporter.inventory([])


def test_full_host_view_compares_the_real_index(exporter):
    rows = [f"{OTHER_GPU}, 4, 0", f"{SPEECH_GPU}, 6, 40", "GPU-c710b68a-493d-0d55-9b1a-f48d8ad71978, 7, 0"]
    uuid, index, _util, match = exporter.inventory(rows)
    assert (uuid, index, match) == (SPEECH_GPU, "6", True)


def test_full_host_view_reports_a_moved_card(exporter):
    rows = [f"{SPEECH_GPU}, 3, 0", f"{OTHER_GPU}, 4, 0"]
    _uuid, index, _util, match = exporter.inventory(rows)
    assert (index, match) == ("3", False), "a real index move must still alert"
