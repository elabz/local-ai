#!/usr/bin/env python3
"""Cap max_parallel_requests on issued LiteLLM keys (run on Prod).

    cd ~/local-ai/litellm && set -a && . ./.env && set +a
    python3 scripts/cap-key-concurrency.py            # show current caps
    python3 scripts/cap-key-concurrency.py --apply    # apply CAPS below

Every key must carry a cap no greater than the total slot count of the model
groups it may call (docs/proxy-client-contract.md). Batch consumers get 1-2.
Unknown aliases are listed but never modified; add them to CAPS deliberately.
"""

import argparse
import json
import os
import sys
import urllib.request

PROXY = os.getenv("LITELLM_URL", "http://localhost:4000")

# alias -> max_parallel_requests. Ceiling = sum of slots of callable groups.
CAPS = {
    "heartcode-backend": 8,   # sfw 3 + nsfw 3 + embed 2 (speech/canaries share)
    "manuals-pilot": 3,       # heartcode-chat-sfw only (3 slots)
    "vox-speech": 4,          # stt + tts
    "rediska": 2,             # batch consumer: 1-2 by contract
}


def call(master: str, path: str, body=None):
    req = urllib.request.Request(
        f"{PROXY}{path}",
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Authorization": f"Bearer {master}", "Content-Type": "application/json"},
        method="POST" if body is not None else "GET",
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.load(resp)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--apply", action="store_true", help="write the caps; default is a dry run")
    args = parser.parse_args()
    master = os.getenv("LITELLM_MASTER_KEY")
    if not master:
        print("LITELLM_MASTER_KEY is not set (source litellm/.env)", file=sys.stderr)
        return 2

    keys = call(master, "/key/list?return_full_object=true&page=1&size=100")["keys"]
    rc = 0
    for key in keys:
        alias = key.get("key_alias") or "<no alias>"
        current = key.get("max_parallel_requests")
        target = CAPS.get(alias.lower())
        if target is None:
            print(f"UNMANAGED  {alias:<22} max_parallel={current}  models={key.get('models')}")
            rc = 1
            continue
        if current == target:
            print(f"OK         {alias:<22} max_parallel={current}")
            continue
        if args.apply:
            call(master, "/key/update", {"key": key["token"], "max_parallel_requests": target})
            print(f"UPDATED    {alias:<22} max_parallel={current} -> {target}")
        else:
            print(f"WOULD SET  {alias:<22} max_parallel={current} -> {target}   (re-run with --apply)")
            rc = 1
    return rc


if __name__ == "__main__":
    sys.exit(main())
