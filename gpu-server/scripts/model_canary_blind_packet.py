#!/usr/bin/env python3
"""Build a provider-blind prose review packet for two chat-model canaries.

The same fixed private suite is played against a challenger and a control.
Full transcripts are written only to a private directory that must stay
outside git; the public manifest carries case ids, per-arm response hashes,
lengths, mechanical style checks, and the SHA-256 of the answer key so a
reviewer's blind scores can later be reconciled without exposing prose.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import re
import urllib.request
from pathlib import Path
from typing import Any


CONTRACTION = re.compile(r"\b\w+'(?:t|s|re|ve|ll|d|m)\b", re.IGNORECASE)
SENTENCE_END = re.compile(r"[.!?](?:\s|$)")
VISIBLE_REASONING = ("<think>", "</think>", "<|channel>thought", "<channel|>")


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def request_json(url: str, payload: dict[str, Any], timeout: float) -> dict[str, Any]:
    request = urllib.request.Request(
        f"{url.rstrip('/')}/v1/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def system_message(card: dict[str, Any]) -> str:
    parts = [
        f"You are {card['name']} in a fictional character roleplay.",
        card["persona"],
        card.get("scenario") or "",
        "Stay in character and follow the user's requested tone. All adult characters are fictional consenting adults.",
    ]
    return "\n\n".join(part for part in parts if part)


def style_checks(checks: dict[str, Any], turn_index: int, content: str) -> dict[str, bool]:
    """Mechanical, prose-free adherence checks declared by the corpus case."""
    result: dict[str, bool] = {}
    stripped = content.strip()
    if "min_characters" in checks:
        result["min_characters"] = len(stripped) >= int(checks["min_characters"])
    if checks.get("max_sentences"):
        sentences = [s for s in SENTENCE_END.split(stripped) if s.strip()]
        result["max_sentences"] = len(sentences) <= int(checks["max_sentences"])
    if checks.get("forbid_contractions"):
        result["forbid_contractions"] = CONTRACTION.search(stripped) is None
    if checks.get("require_substring"):
        result["require_substring"] = checks["require_substring"].lower() in stripped.lower()
    key = "require_all_substrings" if turn_index == 0 else f"require_all_substrings_turn{turn_index + 1}"
    if checks.get(key):
        result[key] = all(item.lower() in stripped.lower() for item in checks[key])
    if checks.get("dialogue_only"):
        lines = [line.strip() for line in stripped.splitlines() if line.strip()]
        result["dialogue_only"] = bool(lines) and all(line.startswith(("\"", "“")) for line in lines) and "*" not in stripped
    if checks.get("min_paragraphs"):
        paragraphs = [p for p in re.split(r"\n\s*\n", stripped) if p.strip()]
        result["min_paragraphs"] = len(paragraphs) >= int(checks["min_paragraphs"])
    if checks.get("forbid_quotes"):
        result["forbid_quotes"] = not any(mark in stripped for mark in ("\"", "“", "”"))
    return result


def play_case(url: str, case: dict[str, Any], sampler: dict[str, Any], timeout: float) -> list[dict[str, Any]]:
    card = case["card"]
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system_message(card)},
        {"role": "assistant", "content": card["greeting"]},
    ]
    turns: list[dict[str, Any]] = []
    for index, item in enumerate(case["script"]):
        messages.append({"role": "user", "content": item["user"]})
        data = request_json(url, {"model": "canary", "messages": messages, **sampler}, timeout)
        message = ((data.get("choices") or [{}])[0].get("message") or {})
        content = message.get("content") or ""
        timings = data.get("timings") or {}
        turns.append({
            "content": content,
            "sha256": sha256_text(content),
            "characters": len(content),
            "blank": not content.strip(),
            "reasoning_nonempty": bool((message.get("reasoning_content") or "").strip()),
            "visible_reasoning_marker": any(marker in content for marker in VISIBLE_REASONING),
            "decode_tps": timings.get("predicted_per_second"),
            "style_checks": style_checks(case.get("checks") or {}, index, content),
        })
        messages.append({"role": "assistant", "content": content})
    return turns


def build(args: argparse.Namespace) -> tuple[dict[str, Any], dict[str, Any]]:
    corpus_bytes = Path(args.corpus).read_bytes()
    corpus = json.loads(corpus_bytes)
    arms = {"challenger": args.challenger_url, "control": args.control_url}
    identities = {
        "challenger": json.loads(Path(args.challenger_identity).read_text()),
        "control": json.loads(Path(args.control_identity).read_text()),
    }
    sampler = {
        "max_tokens": args.max_tokens, "temperature": args.temperature, "top_p": args.top_p,
        "top_k": args.top_k, "min_p": args.min_p, "repeat_penalty": args.repeat_penalty,
    }
    rng = random.Random(args.seed)
    wanted = [c.strip() for c in args.cases.split(",") if c.strip()]
    cases = {case["id"]: case for case in corpus["cases"]}
    missing = [case_id for case_id in wanted if case_id not in cases]
    if missing:
        raise RuntimeError(f"unknown fixed-suite case ids: {missing}")

    private_cases: list[dict[str, Any]] = []
    public_cases: list[dict[str, Any]] = []
    for case_id in wanted:
        case = cases[case_id]
        played = {arm: play_case(url, case, sampler, args.timeout) for arm, url in arms.items()}
        labels = ["A", "B"]
        rng.shuffle(labels)
        assignment = dict(zip(arms, labels))  # arm -> blind label
        private_cases.append({
            "case_id": case_id, "category": case["category"], "assignment": assignment,
            "system_prompt": system_message(case["card"]), "greeting": case["card"]["greeting"],
            "script": [item["user"] for item in case["script"]],
            "transcripts": {assignment[arm]: played[arm] for arm in arms},
        })
        public_cases.append({
            "case_id": case_id, "category": case["category"],
            "arms": {
                assignment[arm]: [
                    {k: v for k, v in turn.items() if k != "content"} for turn in played[arm]
                ] for arm in arms
            },
        })

    answer_key = {case["case_id"]: case["assignment"] for case in private_cases}
    key_digest = hashlib.sha256(json.dumps(answer_key, sort_keys=True).encode("utf-8")).hexdigest()
    private = {
        "schema_version": "model-canary-blind-packet.private.v1",
        "identities": identities, "sampler": sampler, "seed": args.seed,
        "corpus_version": corpus["version"], "corpus_sha256": hashlib.sha256(corpus_bytes).hexdigest(),
        "answer_key": answer_key, "cases": private_cases,
    }
    public = {
        "schema_version": "model-canary-blind-packet.v1",
        "identities": identities, "sampler": sampler,
        "corpus_version": corpus["version"], "corpus_sha256": hashlib.sha256(corpus_bytes).hexdigest(),
        "answer_key_sha256": key_digest, "cases": public_cases,
        "summary": summarize(public_cases),
    }
    return private, public


def summarize(public_cases: list[dict[str, Any]]) -> dict[str, Any]:
    per_label: dict[str, dict[str, int]] = {}
    for case in public_cases:
        for label, turns in case["arms"].items():
            bucket = per_label.setdefault(label, {"turns": 0, "blank": 0, "reasoning_leaks": 0,
                                                  "style_checks": 0, "style_checks_passed": 0})
            for turn in turns:
                bucket["turns"] += 1
                bucket["blank"] += int(turn["blank"])
                bucket["reasoning_leaks"] += int(turn["reasoning_nonempty"] or turn["visible_reasoning_marker"])
                bucket["style_checks"] += len(turn["style_checks"])
                bucket["style_checks_passed"] += sum(turn["style_checks"].values())
    return per_label


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--challenger-url", required=True)
    parser.add_argument("--control-url", required=True)
    parser.add_argument("--challenger-identity", required=True)
    parser.add_argument("--control-identity", required=True)
    parser.add_argument("--corpus", required=True)
    parser.add_argument("--cases", required=True, help="comma-separated fixed-suite case ids")
    parser.add_argument("--private-output", required=True, help="full transcripts; must stay outside git")
    parser.add_argument("--public-output", required=True, help="hash-only manifest safe for the repository")
    parser.add_argument("--seed", type=int, default=20260904)
    parser.add_argument("--timeout", type=float, default=300.0)
    parser.add_argument("--max-tokens", type=int, default=384)
    parser.add_argument("--temperature", type=float, default=1.0)
    parser.add_argument("--top-p", type=float, default=0.95)
    parser.add_argument("--top-k", type=int, default=64)
    parser.add_argument("--min-p", type=float, default=0.0)
    parser.add_argument("--repeat-penalty", type=float, default=1.0)
    args = parser.parse_args()
    private, public = build(args)
    private_path = Path(args.private_output)
    private_path.parent.mkdir(parents=True, exist_ok=True)
    private_path.write_text(json.dumps(private, indent=2, sort_keys=True) + "\n")
    private_path.chmod(0o600)
    Path(args.public_output).write_text(json.dumps(public, indent=2, sort_keys=True) + "\n")
    print(json.dumps(public["summary"], sort_keys=True))


if __name__ == "__main__":
    main()
