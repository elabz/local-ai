"""Emit an allow-listed, content-free custom-voice build-plan summary."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


SAFE_FIELDS = (
    "schema_version",
    "job_id",
    "seed",
    "population_limit",
    "fitness_text_count",
    "checkpoint_interval",
    "step_limit",
    "max_duration_seconds",
    "active_work_budget_seconds",
    "maximum_wall_lifetime_seconds",
    "builder_revision",
    "worker_image_digest",
    "kokoro_model_digest",
    "kokoro_config_digest",
)


def summarize(path: Path) -> dict[str, object]:
    raw = path.read_bytes()
    plan = json.loads(raw)
    samples = plan.get("samples", [])
    excluded = set(plan.get("excluded_adaptation_sample_ids", []))
    return {
        "plan_sha256": hashlib.sha256(raw).hexdigest(),
        "fields": {field: plan.get(field, "missing") for field in SAFE_FIELDS},
        "construction_reference_ids": sorted(
            item.get("sample_id", "")
            for item in samples
            if isinstance(item, dict)
            and item.get("role") == "adaptation"
            and item.get("sample_id") not in excluded
        ),
        "heldout_reference_count": sum(
            1
            for item in samples
            if isinstance(item, dict)
            and item.get("role") == "heldout"
            and item.get("sample_id") not in excluded
            and item.get("construction_reference")
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("plan", type=Path)
    args = parser.parse_args()
    print(json.dumps(summarize(args.plan), sort_keys=True, separators=(",", ":")))


if __name__ == "__main__":
    main()
