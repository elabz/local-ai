#!/usr/bin/env python3
"""Validate LiteLLM proxy config files.

Checks each given config (default: config.yaml + config-local.yaml next to this
script):
  - the YAML parses
  - model_list is a non-empty list
  - every deployment has a model_name and a litellm_params.api_base
  - model_info.id is unique across deployments

Note: model_name is intentionally repeated across deployments (LiteLLM load-
balances every entry sharing a name), so uniqueness is enforced on model_info.id,
not model_name.

Exit code is non-zero if any file fails. Usage: validate_config.py [config ...]
"""

import sys
from pathlib import Path

import yaml


def validate(path: Path) -> list[str]:
    errors: list[str] = []
    try:
        data = yaml.safe_load(path.read_text())
    except yaml.YAMLError as exc:
        return [f"YAML parse error: {exc}"]

    if not isinstance(data, dict):
        return ["top-level document is not a mapping"]

    model_list = data.get("model_list")
    if not isinstance(model_list, list) or not model_list:
        return ["model_list is missing or empty"]

    seen_ids: dict[str, int] = {}
    for i, entry in enumerate(model_list):
        where = f"model_list[{i}]"
        if not isinstance(entry, dict):
            errors.append(f"{where}: not a mapping")
            continue

        name = entry.get("model_name")
        if not name:
            errors.append(f"{where}: missing model_name")

        params = entry.get("litellm_params")
        if not isinstance(params, dict) or not params.get("api_base"):
            errors.append(f"{where} ({name}): missing litellm_params.api_base")

        dep_id = (entry.get("model_info") or {}).get("id")
        if not dep_id:
            errors.append(f"{where} ({name}): missing model_info.id")
        elif dep_id in seen_ids:
            errors.append(
                f"{where} ({name}): duplicate model_info.id '{dep_id}' "
                f"(also model_list[{seen_ids[dep_id]}])"
            )
        else:
            seen_ids[dep_id] = i

    return errors


def main(argv: list[str]) -> int:
    here = Path(__file__).resolve().parent
    if argv:
        paths = [Path(a) for a in argv]
    else:
        paths = [here / "config.yaml", here / "config-local.yaml"]

    failed = False
    for path in paths:
        if not path.exists():
            print(f"skip {path} (not found)")
            continue
        errors = validate(path)
        if errors:
            failed = True
            print(f"FAIL {path}")
            for err in errors:
                print(f"  - {err}")
        else:
            print(f"OK   {path}")

    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
