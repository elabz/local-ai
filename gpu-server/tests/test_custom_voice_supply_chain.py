import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from custom_voice.supply_chain import verify_production_evidence


def write_json(path: Path, value: dict) -> str:
    path.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def valid_sbom() -> dict:
    return {
        "spdxVersion": "SPDX-2.3",
        "documentNamespace": "urn:uuid:test-sbom",
        "packages": [
            {"name": "builder", "licenseConcluded": "Apache-2.0"},
            {"name": "model", "licenseConcluded": "Apache-2.0"},
        ],
    }


def test_exact_approved_evidence_passes(tmp_path: Path) -> None:
    artifact_digest = "a" * 64
    sbom = tmp_path / "sbom.json"
    approval = tmp_path / "approval.json"
    sbom_digest = write_json(sbom, valid_sbom())
    write_json(
        approval,
        {
            "attestation_id": "heartcode-admin-001",
            "status": "approved",
            "scope": "internal_pea",
            "speaker_authority_confirmed": True,
            "no_redistribution_confirmed": True,
            "license_findings_acknowledged": True,
            "unresolved_license_count": 0,
            "artifact_sha256": artifact_digest,
            "sbom_sha256": sbom_digest,
        },
    )

    report = verify_production_evidence(
        artifact_sha256=artifact_digest,
        sbom_path=sbom,
        approval_path=approval,
    )

    assert report.outcome == "pass"
    assert report.reason_codes == ()


def test_unresolved_license_requires_exact_admin_acknowledgement(tmp_path: Path) -> None:
    artifact_digest = "a" * 64
    sbom = tmp_path / "sbom.json"
    approval = tmp_path / "approval.json"
    value = valid_sbom()
    value["packages"][0]["licenseConcluded"] = "NOASSERTION"
    sbom_digest = write_json(sbom, value)
    write_json(
        approval,
        {
            "attestation_id": "heartcode-admin-001",
            "status": "approved",
            "scope": "internal_pea",
            "speaker_authority_confirmed": True,
            "no_redistribution_confirmed": True,
            "license_findings_acknowledged": True,
            "unresolved_license_count": 1,
            "artifact_sha256": artifact_digest,
            "sbom_sha256": sbom_digest,
        },
    )

    report = verify_production_evidence(
        artifact_sha256=artifact_digest,
        sbom_path=sbom,
        approval_path=approval,
    )

    assert report.outcome == "pass"


def test_digest_mismatch_fails_closed(tmp_path: Path) -> None:
    sbom = tmp_path / "sbom.json"
    approval = tmp_path / "approval.json"
    write_json(sbom, valid_sbom())
    write_json(
        approval,
        {
            "attestation_id": "heartcode-admin-001",
            "status": "approved",
            "scope": "internal_pea",
            "speaker_authority_confirmed": True,
            "no_redistribution_confirmed": True,
            "license_findings_acknowledged": True,
            "unresolved_license_count": 0,
            "artifact_sha256": "b" * 64,
            "sbom_sha256": "c" * 64,
        },
    )

    report = verify_production_evidence(
        artifact_sha256="a" * 64,
        sbom_path=sbom,
        approval_path=approval,
    )

    assert report.outcome == "reject"
    assert "admin_attestation_artifact_mismatch" in report.reason_codes
    assert "admin_attestation_sbom_mismatch" in report.reason_codes
