import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from custom_voice.sbom import generate


def test_spdx_inventory_is_bound_to_exact_artifact_and_reports_licenses() -> None:
    digest = "a" * 64
    value = generate(artifact_sha256=digest, worker_image_digest="worker@sha256:123", runtime_image="kokoro@sha256:456")
    assert value["spdxVersion"] == "SPDX-2.3"
    assert value["documentNamespace"].endswith(digest)
    assert any(item["name"] == "KVoiceWalk" and item["licenseConcluded"] == "Apache-2.0" for item in value["packages"])
    assert all(item.get("licenseConcluded") for item in value["packages"])
