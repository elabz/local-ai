"""Deterministic SPDX 2.3 evidence for private custom-voice activation."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import re
from pathlib import Path

SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def _license(distribution: importlib.metadata.Distribution) -> str:
    declared = (distribution.metadata.get("License") or "").strip()
    if declared and declared.upper() not in {"UNKNOWN", "NONE"}:
        return declared
    for classifier in distribution.metadata.get_all("Classifier") or []:
        if classifier.startswith("License :: OSI Approved :: Apache Software License"):
            return "Apache-2.0"
        if classifier.startswith("License :: OSI Approved :: MIT License"):
            return "MIT"
        if classifier.startswith("License :: OSI Approved :: BSD License"):
            return "BSD-3-Clause"
    return "NOASSERTION"


def generate(*, artifact_sha256: str, worker_image_digest: str, runtime_image: str) -> dict[str, object]:
    if not SHA256_RE.fullmatch(artifact_sha256):
        raise ValueError("artifact_digest_invalid")
    fixed = [
        ("custom-voice-artifact", artifact_sha256[:12], "NOASSERTION"),
        ("KVoiceWalk", "3a38c6030cc4657df073c67ded37cdf7627c4969", "Apache-2.0"),
        ("Kokoro-82M", "v1.0", "Apache-2.0"),
        ("Kokoro-FastAPI", "v0.6.0", "Apache-2.0"),
        ("custom-voice-worker-image", worker_image_digest, "NOASSERTION"),
    ]
    discovered = sorted(
        {(distribution.metadata.get("Name") or "unknown", distribution.version, _license(distribution))
         for distribution in importlib.metadata.distributions()},
        key=lambda item: (item[0].lower(), item[1]),
    )
    packages = []
    for index, (name, version, license_concluded) in enumerate(fixed + discovered, start=1):
        packages.append({
            "SPDXID": f"SPDXRef-Package-{index}",
            "name": name,
            "versionInfo": version,
            "downloadLocation": "NOASSERTION",
            "filesAnalyzed": False,
            "licenseConcluded": license_concluded,
            "licenseDeclared": license_concluded,
            "copyrightText": "NOASSERTION",
        })
    return {
        "spdxVersion": "SPDX-2.3",
        "dataLicense": "CC0-1.0",
        "SPDXID": "SPDXRef-DOCUMENT",
        "name": f"custom-voice-{artifact_sha256[:12]}",
        "documentNamespace": f"urn:heartcode:custom-voice:sha256:{artifact_sha256}",
        "creationInfo": {"creators": ["Tool: local-ai-custom-voice-sbom.v1"], "created": "2026-07-18T00:00:00Z"},
        "comment": f"Private Pea deployment; no redistribution. Runtime: {runtime_image}",
        "packages": packages,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact-sha256", required=True)
    parser.add_argument("--worker-image-digest", required=True)
    parser.add_argument("--runtime-image", required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    value = generate(artifact_sha256=arguments.artifact_sha256,
                     worker_image_digest=arguments.worker_image_digest,
                     runtime_image=arguments.runtime_image)
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    arguments.output.write_bytes(encoded)
    arguments.output.chmod(0o600)
    unresolved = sum(1 for item in value["packages"] if item["licenseConcluded"] in {"NOASSERTION", "NONE"})
    print(json.dumps({"sbom_sha256": hashlib.sha256(encoded).hexdigest(), "package_count": len(value["packages"]), "unresolved_license_count": unresolved}, sort_keys=True))


if __name__ == "__main__":
    main()
