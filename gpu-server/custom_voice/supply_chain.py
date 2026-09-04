"""Fail-closed production supply-chain evidence verification."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path

SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class SupplyChainReport:
    outcome: str
    reason_codes: tuple[str, ...]
    sbom_sha256: str
    package_count: int
    approval_id: str | None


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def verify_production_evidence(
    *,
    artifact_sha256: str,
    sbom_path: str | Path,
    approval_path: str | Path,
) -> SupplyChainReport:
    """Verify SPDX completeness and externally approved exact-digest binding."""

    reasons: list[str] = []
    if not SHA256_RE.fullmatch(artifact_sha256):
        reasons.append("artifact_digest_invalid")

    sbom_sha256 = sha256_file(sbom_path)
    with open(sbom_path, "rb") as source:
        sbom = json.load(source)
    packages = sbom.get("packages")
    if not str(sbom.get("spdxVersion", "")).startswith("SPDX-"):
        reasons.append("sbom_format_invalid")
    if not sbom.get("documentNamespace"):
        reasons.append("sbom_namespace_missing")
    if not isinstance(packages, list) or not packages:
        reasons.append("sbom_packages_missing")
        packages = []
    for package in packages:
        concluded = package.get("licenseConcluded") if isinstance(package, dict) else None
        if not concluded or concluded in {"NOASSERTION", "NONE"}:
            reasons.append("sbom_license_unresolved")
            break

    with open(approval_path, "rb") as source:
        approval = json.load(source)
    approval_id = approval.get("approval_id")
    if not isinstance(approval_id, str) or not approval_id:
        reasons.append("legal_approval_id_missing")
        approval_id = None
    if approval.get("status") != "approved":
        reasons.append("legal_approval_not_approved")
    if approval.get("scope") != "production":
        reasons.append("legal_approval_scope_invalid")
    if approval.get("artifact_sha256") != artifact_sha256:
        reasons.append("legal_approval_artifact_mismatch")
    if approval.get("sbom_sha256") != sbom_sha256:
        reasons.append("legal_approval_sbom_mismatch")

    return SupplyChainReport(
        outcome="reject" if reasons else "pass",
        reason_codes=tuple(dict.fromkeys(reasons)),
        sbom_sha256=sbom_sha256,
        package_count=len(packages),
        approval_id=approval_id,
    )
