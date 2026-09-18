"""The LiteLLM least-busy tie-break patch (litellm/patches/README.md).

Loads the patched module with stub LiteLLM imports so it runs in CI without
installing litellm, and pins the patch to the image digest it was written for.
"""
import ast
import hashlib
import importlib.util
import random
import re
import sys
import types
from collections import Counter
from pathlib import Path

import pytest

LITELLM = Path(__file__).resolve().parents[2] / "litellm"
PATCHED = LITELLM / "patches" / "least_busy.py"
UPSTREAM = LITELLM / "patches" / "least_busy.upstream.py"

# The image the patch was written against, and its unmodified least_busy.py.
# Bumping the image means re-fetching the upstream file, re-applying the patch
# and updating both values (see litellm/patches/README.md).
IMAGE_DIGEST = "sha256:bb0639701796218a3447160e55c0f1097446e4e6085df7dfd39f476d4143743f"
UPSTREAM_SHA256 = "1048acdd98b98ba666987493af6f585c2adede4c0074a53e4616202f06dce197"


@pytest.fixture
def handler(monkeypatch):
    for name in ("litellm", "litellm.caching", "litellm.integrations"):
        monkeypatch.setitem(sys.modules, name, types.ModuleType(name))
    caching = types.ModuleType("litellm.caching.caching")
    caching.DualCache = object
    logger = types.ModuleType("litellm.integrations.custom_logger")
    logger.CustomLogger = type("CustomLogger", (), {})
    monkeypatch.setitem(sys.modules, "litellm.caching.caching", caching)
    monkeypatch.setitem(sys.modules, "litellm.integrations.custom_logger", logger)
    spec = importlib.util.spec_from_file_location("least_busy_patched", PATCHED)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.LeastBusyLoggingHandler(router_cache=None)


def deployments(*ids):
    return [{"model_info": {"id": i}} for i in ids]


def pick(handler, healthy, counts):
    return handler._get_available_deployments(healthy, dict(counts))["model_info"]["id"]


def test_idle_ties_spread_across_every_replica(handler):
    random.seed(7)
    healthy = deployments("heartcode-gpu1", "heartcode-gpu2", "heartcode-gpu3")
    picks = Counter(pick(handler, healthy, {}) for _ in range(3000))
    assert set(picks) == {"heartcode-gpu1", "heartcode-gpu2", "heartcode-gpu3"}
    assert min(picks.values()) > 850  # ~1000 each; upstream gives gpu1 all 3000


def test_least_in_flight_still_wins(handler):
    healthy = deployments("heartcode-gpu1", "heartcode-gpu2", "heartcode-gpu3")
    counts = {"heartcode-gpu1": 1, "heartcode-gpu2": 0, "heartcode-gpu3": 2}
    assert {pick(handler, healthy, counts) for _ in range(50)} == {"heartcode-gpu2"}


def test_unhealthy_ids_in_the_counter_are_ignored(handler):
    healthy = deployments("heartcode-gpu2", "heartcode-gpu3")
    counts = {"heartcode-gpu1": 0, "heartcode-gpu2": 1, "heartcode-gpu3": 2}
    assert {pick(handler, healthy, counts) for _ in range(50)} == {"heartcode-gpu2"}


def test_negative_drift_counts_as_idle_not_preferred(handler):
    random.seed(3)
    healthy = deployments("heartcode-gpu1", "heartcode-gpu2")
    counts = {"heartcode-gpu1": -4, "heartcode-gpu2": 0}
    assert {pick(handler, healthy, counts) for _ in range(200)} == {"heartcode-gpu1", "heartcode-gpu2"}


def test_upstream_reference_is_the_pinned_images_file():
    assert hashlib.sha256(UPSTREAM.read_bytes()).hexdigest() == UPSTREAM_SHA256


def test_compose_pins_the_image_the_patch_was_written_for():
    compose = (LITELLM / "docker-compose.yml").read_text()
    assert re.search(r"image: ghcr\.io/berriai/litellm:[^\s@]+@" + re.escape(IMAGE_DIGEST), compose), (
        "LiteLLM image changed: re-fetch least_busy.upstream.py from the new image, "
        "re-apply the patch, and update IMAGE_DIGEST/UPSTREAM_SHA256"
    )
    assert "./patches/least_busy.py:/usr/lib/python3.13/site-packages/litellm/router_strategy/least_busy.py:ro" in compose


def test_patch_touches_only_the_tie_break_method():
    def methods(path):
        cls = next(n for n in ast.parse(path.read_text()).body if isinstance(n, ast.ClassDef))
        return {n.name: ast.dump(n) for n in cls.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}

    patched, upstream = methods(PATCHED), methods(UPSTREAM)
    assert patched.keys() == upstream.keys()
    changed = {name for name in patched if patched[name] != upstream[name]}
    assert changed == {"_get_available_deployments"}
