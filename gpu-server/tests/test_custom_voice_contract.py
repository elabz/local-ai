import sys
from pathlib import Path

import yaml


CONTRACT = Path(__file__).resolve().parents[2] / "docs" / "contracts" / "custom-voice-control-plane-v1.yaml"


def test_contract_is_versioned_private_and_complete() -> None:
    contract = yaml.safe_load(CONTRACT.read_text())
    assert contract["openapi"] == "3.1.0"
    assert contract["info"]["version"] == "1.0.0"
    assert contract["x-heartcode-change"] == "add-admin-custom-voices"
    assert contract["x-routing"]["litellm"] == "forbidden"
    operations = {
        operation["operationId"]: operation["x-required-scope"]
        for path in contract["paths"].values()
        for method, operation in path.items()
        if method in {"get", "post"}
    }
    assert operations["createCustomVoiceBuild"] == "custom_voice.build"
    assert operations["getCustomVoiceBuild"] == "custom_voice.read"
    assert operations["readCustomVoicePreview"] == "custom_voice.preview.read"
    assert operations["activateCustomVoice"] == "custom_voice.activate"
    assert operations["deleteCustomVoiceVersion"] == "custom_voice.delete"


def test_contract_fails_unknown_request_fields_closed() -> None:
    schemas = yaml.safe_load(CONTRACT.read_text())["components"]["schemas"]
    for name in ("CreateBuildRequest", "BuildJob", "ArtifactMutation", "RegistryVersion", "SafeError"):
        assert schemas[name]["additionalProperties"] is False


def test_contract_never_accepts_host_paths_or_callback_urls() -> None:
    text = CONTRACT.read_text()
    create = yaml.safe_load(text)["components"]["schemas"]["CreateBuildRequest"]["properties"]
    assert "path" not in create
    assert "url" not in create["callback"].get("properties", {})
    assert "file://" not in text
