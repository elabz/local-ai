"""Fail-closed internal Pea supply-chain and admin evidence verification."""

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
    attestation_id: str | None


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
    """Verify SPDX evidence and HeartCode's exact-digest internal-use decision."""

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
    unresolved = sum(
        1 for package in packages
        if not isinstance(package, dict) or package.get("licenseConcluded") in {None, "", "NOASSERTION", "NONE"}
    )

    with open(approval_path, "rb") as source:
        approval = json.load(source)
    attestation_id = approval.get("attestation_id")
    if not isinstance(attestation_id, str) or not attestation_id:
        reasons.append("admin_attestation_id_missing")
        attestation_id = None
    if approval.get("status") != "approved":
        reasons.append("admin_attestation_not_approved")
    if approval.get("scope") != "internal_pea":
        reasons.append("admin_attestation_scope_invalid")
    if approval.get("speaker_authority_confirmed") is not True:
        reasons.append("speaker_authority_missing")
    if approval.get("no_redistribution_confirmed") is not True:
        reasons.append("no_redistribution_missing")
    if approval.get("license_findings_acknowledged") is not True:
        reasons.append("license_findings_not_acknowledged")
    if approval.get("unresolved_license_count") != unresolved:
        reasons.append("license_findings_mismatch")
    if approval.get("artifact_sha256") != artifact_sha256:
        reasons.append("admin_attestation_artifact_mismatch")
    if approval.get("sbom_sha256") != sbom_sha256:
        reasons.append("admin_attestation_sbom_mismatch")

    return SupplyChainReport(
        outcome="reject" if reasons else "pass",
        reason_codes=tuple(dict.fromkeys(reasons)),
        sbom_sha256=sbom_sha256,
        package_count=len(packages),
        attestation_id=attestation_id,
    )
