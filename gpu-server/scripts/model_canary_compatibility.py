#!/usr/bin/env python3
"""Safe synthetic compatibility probes for isolated chat-model canaries."""

from __future__ import annotations

import argparse
import json
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


MARKERS = ("CEDAR-1742", "EMBER-5831", "QUARTZ-9064")
VISIBLE_REASONING_MARKERS = ("<think>", "</think>", "<|channel>thought", "<channel|>")


def request_json(url: str, payload: dict[str, Any], timeout: float) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def message(data: dict[str, Any]) -> dict[str, Any]:
    return ((data.get("choices") or [{}])[0].get("message") or {})


def content_object(data: dict[str, Any]) -> dict[str, Any]:
    content = message(data).get("content") or ""
    parsed = json.loads(content)
    if not isinstance(parsed, dict):
        raise ValueError("content is not an object")
    return parsed


def reasoning_leaked(data: dict[str, Any]) -> bool:
    value = message(data)
    content = value.get("content") or ""
    return bool(value.get("reasoning_content")) or any(
        marker in content for marker in VISIBLE_REASONING_MARKERS
    )


def synthetic_retrieval_prompt(padding_words: int) -> str:
    pad = " neutral filler" * max(1, padding_words // 2)
    return (
        f"The beginning marker is {MARKERS[0]}.{pad} "
        f"The middle marker is {MARKERS[1]}.{pad} "
        f"The ending marker is {MARKERS[2]}. "
        "Return all three markers in order as the markers JSON array."
    )


def schema(name: str, properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {
        "type": "json_schema",
        "json_schema": {
            "name": name,
            "schema": {
                "type": "object",
                "additionalProperties": False,
                "required": required,
                "properties": properties,
            },
        },
    }


def run(base_url: str, timeout: float, padding_words: int) -> dict[str, Any]:
    endpoint = f"{base_url.rstrip('/')}/v1/chat/completions"
    result: dict[str, Any] = {
        "schema_version": "model-canary-compatibility.v1",
        "direct_response": {"passed": False},
        "retrieval": {"passed": False},
        "json_schema": {"passed": False},
        "multi_turn_tool": {"passed": False},
    }

    try:
        direct = request_json(
            endpoint,
            {
                "model": "canary",
                "temperature": 0,
                "max_tokens": 32,
                "messages": [{"role": "user", "content": "Reply with exactly: READY"}],
            },
            timeout,
        )
        result["direct_response"]["passed"] = (
            (message(direct).get("content") or "").strip() == "READY"
            and not reasoning_leaked(direct)
        )
    except (OSError, ValueError, KeyError, json.JSONDecodeError, urllib.error.URLError) as error:
        result["direct_response"]["error_type"] = type(error).__name__

    try:
        retrieval = request_json(
            endpoint,
            {
                "model": "canary",
                "temperature": 0,
                "max_tokens": 96,
                "messages": [{"role": "user", "content": synthetic_retrieval_prompt(padding_words)}],
                "response_format": schema(
                    "retrieval_probe",
                    {"markers": {"type": "array", "items": {"type": "string"}, "minItems": 3, "maxItems": 3}},
                    ["markers"],
                ),
            },
            timeout,
        )
        returned = content_object(retrieval).get("markers")
        result["retrieval"]["passed"] = returned == list(MARKERS)
    except (OSError, ValueError, KeyError, json.JSONDecodeError, urllib.error.URLError) as error:
        result["retrieval"]["error_type"] = type(error).__name__

    try:
        structured = request_json(
            endpoint,
            {
                "model": "canary",
                "temperature": 0,
                "max_tokens": 48,
                "messages": [{"role": "user", "content": "Return status ready and count 3."}],
                "response_format": schema(
                    "schema_probe",
                    {"status": {"type": "string", "const": "ready"}, "count": {"type": "integer", "const": 3}},
                    ["status", "count"],
                ),
            },
            timeout,
        )
        result["json_schema"]["passed"] = content_object(structured) == {"status": "ready", "count": 3}
    except (OSError, ValueError, KeyError, json.JSONDecodeError, urllib.error.URLError) as error:
        result["json_schema"]["error_type"] = type(error).__name__

    tool = {
        "type": "function",
        "function": {
            "name": "lookup_marker",
            "description": "Return the synthetic marker for a numeric slot.",
            "parameters": {
                "type": "object",
                "additionalProperties": False,
                "required": ["slot"],
                "properties": {"slot": {"type": "integer", "const": 2}},
            },
        },
    }
    try:
        first = request_json(
            endpoint,
            {
                "model": "canary",
                "temperature": 0,
                "max_tokens": 96,
                "messages": [{"role": "user", "content": "Use lookup_marker for slot 2."}],
                "tools": [tool],
                "tool_choice": {"type": "function", "function": {"name": "lookup_marker"}},
                "parallel_tool_calls": False,
            },
            timeout,
        )
        assistant = message(first)
        tool_calls = assistant.get("tool_calls") or []
        call = tool_calls[0]
        call_id = call["id"]
        second = request_json(
            endpoint,
            {
                "model": "canary",
                "temperature": 0,
                "max_tokens": 64,
                "messages": [
                    {"role": "user", "content": "Use lookup_marker for slot 2."},
                    {"role": "assistant", "content": assistant.get("content"), "tool_calls": tool_calls},
                    {"role": "tool", "tool_call_id": call_id, "content": json.dumps({"marker": MARKERS[1]})},
                ],
                "tools": [tool],
            },
            timeout,
        )
        final_content = message(second).get("content") or ""
        result["multi_turn_tool"]["passed"] = MARKERS[1] in final_content
    except (OSError, ValueError, KeyError, IndexError, TypeError, json.JSONDecodeError, urllib.error.URLError) as error:
        result["multi_turn_tool"]["error_type"] = type(error).__name__

    result["passed"] = all(
        result[name]["passed"]
        for name in ("direct_response", "retrieval", "json_schema", "multi_turn_tool")
    )
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True)
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument("--padding-words", type=int, default=0)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    result = run(args.url, args.timeout, args.padding_words)
    Path(args.output).write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, sort_keys=True))
    raise SystemExit(0 if result["passed"] else 1)


if __name__ == "__main__":
    main()
