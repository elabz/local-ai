#!/usr/bin/env python3
"""Extract structured metadata from manual PDFs with two comparison arms.

Second pilot instrument for `content-manuals-pilot`. Where convert.py measures
*conversion*, this measures whether we can pull the fields a manuals library is
organised by — manufacturer, model number(s), product type, document type —
reliably enough to auto-file an upload.

Two arms, deliberately different in modality so the A/B answers a production
question (design decision 6):

    text    a local chat model over the *converted text* of the first pages
            (reads convert.py's document.md — i.e. post-OCR for scanned files).
            Default model: heartcode-chat-sfw, the only general-purpose local
            chat model on the fleet; override with --text-model.

    image   Gemini Flash 3 over a render of the *cover page*. PEA has no
            multimodal chat model yet, so Gemini is the bridge; the A/B tells us
            whether production needs a local VLM on PEA at all or text suffices.

The arms use **different transports**, which is a deliberate 2026-08-03 product
decision rather than an inconsistency:

    text    LiteLLM proxy (LITELLM_BASE_URL / LITELLM_API_KEY) — its local model
            is already routed there, so this arm keeps managed keys and Langfuse
            tracing at no extra cost.
    image   Google's Gemini API directly (GEMINI_API_KEY), the same path the
            shipped Reddit content generation uses. Routing it through the proxy
            would have meant deploying config and restarting the shared proxy
            that live SEO and Reddit features depend on — disproportionate for an
            experimental proof of concept. The trade is that this arm has no
            Langfuse trace; if it is adopted, move it behind the proxy.

Usage is recorded per arm; the image arm's Gemini spend is the one with a real
bill attached, so its tokens are aggregated for the report to price.

    extract_metadata.py <pdf-dir> <out-dir> --arm both \\
        --converted-dir <convert.py out-dir> [--ground-truth truth.json]

Per-manual output: <out-dir>/<stem>.metadata.json (both arms' predictions +
usage). Aggregate: <out-dir>/run.json. With --ground-truth, per-field accuracy
per arm is scored and folded into run.json — that is what task 4.3 runs.
"""

import argparse
import base64
import io
import json
import os
import re
import sys
import time
import traceback
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional

# The fields a manuals library files an upload by. Kept small and unambiguous so
# ground-truth labelling is cheap and scoring is exact rather than fuzzy.
SCHEMA_FIELDS = ("manufacturer", "model_numbers", "product_type", "document_type")

# document_type is a closed set: an open string invites "Owner's Manual" vs
# "owner manual" near-misses that punish the model for formatting, not accuracy.
DOCUMENT_TYPES = (
    "user manual", "service manual", "parts list", "installation guide",
    "quick start", "spec sheet", "other",
)

PROMPT = (
    "You are cataloguing a product manual. Identify these fields and return "
    "ONLY a JSON object, no prose, no code fence:\n"
    '  "manufacturer": brand/maker name, or "" if not stated\n'
    '  "model_numbers": array of distinct model/part numbers, [] if none\n'
    '  "product_type": what the product is (e.g. "dishwasher"), or ""\n'
    f'  "document_type": exactly one of {list(DOCUMENT_TYPES)}\n'
    "Transcribe values as printed; do not invent, translate, or expand."
)


@dataclass
class ArmResult:
    arm: str
    model: str
    ok: bool = False
    seconds: float = 0.0
    prediction: Optional[dict] = None
    usage: Optional[dict] = None
    raw: Optional[str] = None
    error: Optional[str] = None
    traceback: Optional[str] = None
    scores: Optional[dict] = None


@dataclass
class ManualMetadata:
    stem: str
    source: str
    arms: dict = field(default_factory=dict)


def litellm_chat(messages: list, model: str, timeout: float) -> dict:
    """One chat/completions call through the proxy, JSON response requested.

    Shares the env contract with convert.py's VLM arm rather than inventing a
    second one. response_format asks for a JSON object; drop_params on the proxy
    means a backend that ignores it degrades to prompt-only rather than erroring,
    which is why the prompt also demands bare JSON and parsing stays defensive.
    """
    import httpx

    base_url = os.environ.get("LITELLM_BASE_URL", "").rstrip("/")
    api_key = os.environ.get("LITELLM_API_KEY", "")
    if not base_url or not api_key:
        raise RuntimeError("LITELLM_BASE_URL and LITELLM_API_KEY must be set")

    with httpx.Client(timeout=timeout) as client:
        response = client.post(
            f"{base_url}/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "model": model,
                "temperature": 0,
                "response_format": {"type": "json_object"},
                # Without an explicit cap the local model's reply was truncated
                # mid-object — the JSON arrived complete except its closing
                # brace, and parsing failed. That scores as an arm failure while
                # actually being our call configuration, so it would have
                # under-reported the local model's accuracy in task 4.3. The
                # schema is four short fields; 512 is far more than it needs and
                # still bounds a runaway reply.
                "max_tokens": 512,
                "messages": messages,
            },
        )
    if response.status_code != 200:
        raise RuntimeError(f"LiteLLM {response.status_code}: {response.text[:500]}")
    return response.json()


GEMINI_ENDPOINT = (
    "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
)


def gemini_image_chat(prompt: str, png: bytes, model: str, timeout: float) -> dict:
    """One cover-page image through Google's Gemini API directly.

    Product decision 2026-08-03: the Gemini arm calls Google directly instead of
    being routed through our LiteLLM proxy (reversing design decision 6). Adding
    the route would have meant deploying config and restarting the shared proxy
    that live SEO and Reddit features depend on, which is disproportionate for an
    experimental proof of concept. The **text arm still goes through the proxy** —
    its local model is already routed there, so that half keeps its Langfuse
    tracing and managed key, and only the Gemini half loses them.

    Returns an OpenAI-shaped dict so callers and `collect_usage` stay identical
    across the two arms; translating here keeps one response shape in the scoring
    path rather than two.
    """
    import httpx

    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY must be set for the image arm")

    with httpx.Client(timeout=timeout) as client:
        response = client.post(
            GEMINI_ENDPOINT.format(model=model),
            headers={"x-goog-api-key": api_key},
            json={
                "contents": [
                    {
                        "parts": [
                            {"text": prompt},
                            {
                                "inline_data": {
                                    "mime_type": "image/png",
                                    "data": base64.b64encode(png).decode(),
                                }
                            },
                        ]
                    }
                ],
                "generationConfig": {
                    "temperature": 0,
                    "responseMimeType": "application/json",
                    "thinkingConfig": {"thinkingBudget": 0},
                },
            },
        )
    if response.status_code != 200:
        raise RuntimeError(f"Gemini {response.status_code}: {response.text[:500]}")

    payload = response.json()
    candidates = payload.get("candidates") or []
    parts = (candidates[0].get("content", {}) if candidates else {}).get("parts") or []
    content = "".join(part.get("text", "") for part in parts)

    meta = payload.get("usageMetadata") or {}
    return {
        "choices": [{"message": {"content": content}}],
        "usage": {
            "prompt_tokens": meta.get("promptTokenCount", 0) or 0,
            "completion_tokens": meta.get("candidatesTokenCount", 0) or 0,
            "thinking_tokens": meta.get("thoughtsTokenCount", 0) or 0,
            "total_tokens": meta.get("totalTokenCount", 0) or 0,
        },
    }


def parse_prediction(content: str) -> dict:
    """Coerce a model reply into the schema, tolerating stray fences/prose.

    A local gguf model that ignored response_format may wrap the JSON in a code
    fence or a sentence. Rather than fail the manual, salvage the first {...}
    span; a genuinely unparseable reply raises and is recorded as an arm error.
    """
    text = content.strip()
    if text.startswith("```"):
        text = text.strip("`")
        text = text.split("\n", 1)[1] if "\n" in text else text
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ValueError(f"no JSON object in reply: {content[:200]!r}")
    obj = json.loads(text[start : end + 1])

    # Normalise to the schema shape so scoring never trips over a missing key or
    # a scalar where a list belongs.
    models = obj.get("model_numbers", [])
    if isinstance(models, str):
        models = [models] if models else []
    return {
        "manufacturer": str(obj.get("manufacturer", "") or "").strip(),
        "model_numbers": [str(x).strip() for x in models if str(x).strip()],
        "product_type": str(obj.get("product_type", "") or "").strip(),
        "document_type": str(obj.get("document_type", "") or "").strip().lower(),
    }


def collect_usage(payload: dict, model: str) -> dict:
    u = payload.get("usage") or {}
    return {
        "model": model,
        "prompt_tokens": u.get("prompt_tokens", 0) or 0,
        "completion_tokens": u.get("completion_tokens", 0) or 0,
        "total_tokens": u.get("total_tokens", 0) or 0,
    }


def run_text_arm(stem: str, converted_dir: Path, args) -> ArmResult:
    """Local model over the converted first-page text (post-OCR for scans)."""
    result = ArmResult(arm="text", model=args.text_model)
    started = time.monotonic()
    try:
        doc = converted_dir / stem / "document.md"
        if not doc.is_file():
            raise FileNotFoundError(
                f"no converted text at {doc} — run convert.py first (--converted-dir)"
            )
        # First pages only: the identifying block is on the cover/title page, and
        # feeding a 300pp service manual would blow the context for no gain.
        text = doc.read_text(errors="replace")[: args.text_chars]
        payload = litellm_chat(
            [
                {"role": "system", "content": PROMPT},
                {"role": "user", "content": text},
            ],
            args.text_model,
            args.timeout,
        )
        content = payload["choices"][0]["message"]["content"]
        result.raw = content
        result.prediction = parse_prediction(content)
        result.usage = collect_usage(payload, args.text_model)
        result.ok = True
    except Exception as exc:
        result.error = f"{type(exc).__name__}: {exc}"
        result.traceback = traceback.format_exc()
    result.seconds = round(time.monotonic() - started, 2)
    return result


def run_image_arm(pdf: Path, args) -> ArmResult:
    """Gemini Flash 3 over a render of the cover page."""
    import pypdfium2

    result = ArmResult(arm="image", model=args.image_model)
    started = time.monotonic()
    try:
        pdf_doc = pypdfium2.PdfDocument(str(pdf))
        try:
            image = pdf_doc[0].render(scale=2).to_pil()
        finally:
            pdf_doc.close()
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")

        payload = gemini_image_chat(
            PROMPT, buffer.getvalue(), args.image_model, args.timeout
        )
        content = payload["choices"][0]["message"]["content"]
        result.raw = content
        result.prediction = parse_prediction(content)
        result.usage = collect_usage(payload, args.image_model)
        result.ok = True
    except Exception as exc:
        result.error = f"{type(exc).__name__}: {exc}"
        result.traceback = traceback.format_exc()
    result.seconds = round(time.monotonic() - started, 2)
    return result


def score(prediction: dict, truth: dict) -> dict:
    """Per-field scoring: exact-match for scalars, set-overlap for model numbers.

    Model numbers are the field a library actually keys on and the one a model
    is most likely to get partly right, so they get precision/recall/F1 over the
    label set rather than an all-or-nothing exact match. Scalars are compared
    case-folded so casing never counts as a miss.
    """

    def norm(x):
        return str(x or "").strip().lower()

    out = {}
    for field_name in ("manufacturer", "product_type", "document_type"):
        out[field_name] = {
            "exact": norm(prediction.get(field_name)) == norm(truth.get(field_name)),
            "predicted": prediction.get(field_name, ""),
            "truth": truth.get(field_name, ""),
        }

    # `product_type` also gets a token-overlap score, and that is the one the
    # report should quote.
    #
    # The spec asks for exact match on brand and document type only, and
    # document_type is a closed set for exactly this reason. product_type is
    # free text: ground truth says "undercounter refrigerator/freezer" and a
    # model answering "refrigerator" is right about the product and scored
    # wrong. In the first run both arms landed near 20% on this field while
    # being substantially correct — that measured phrasing agreement, not
    # comprehension, and reporting it as accuracy would have been misleading.
    pred_words = set(re.findall(r"[a-z]+", norm(prediction.get("product_type"))))
    true_words = set(re.findall(r"[a-z]+", norm(truth.get("product_type"))))
    overlap = len(pred_words & true_words)
    p = overlap / len(pred_words) if pred_words else (1.0 if not true_words else 0.0)
    r = overlap / len(true_words) if true_words else 1.0
    out["product_type"]["token_f1"] = round(
        2 * p * r / (p + r) if (p + r) else 0.0, 4
    )

    pred_set = {norm(x) for x in prediction.get("model_numbers", []) if norm(x)}
    true_set = {norm(x) for x in truth.get("model_numbers", []) if norm(x)}
    hit = len(pred_set & true_set)
    precision = hit / len(pred_set) if pred_set else (1.0 if not true_set else 0.0)
    recall = hit / len(true_set) if true_set else 1.0
    f1 = (
        2 * precision * recall / (precision + recall)
        if (precision + recall)
        else 0.0
    )
    out["model_numbers"] = {
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
        "predicted": sorted(pred_set),
        "truth": sorted(true_set),
    }
    return out


def aggregate_scores(results: list) -> dict:
    """Mean per-field accuracy per arm across every scored manual."""
    by_arm: dict[str, dict] = {}
    for manual in results:
        for arm_name, arm in manual.arms.items():
            if not (arm.get("ok") and arm.get("scores")):
                continue
            acc = by_arm.setdefault(
                arm_name,
                {"n": 0, "manufacturer": 0, "product_type": 0,
                 "document_type": 0, "model_numbers_f1": 0.0,
                 "product_type_f1": 0.0},
            )
            acc["n"] += 1
            for f in ("manufacturer", "product_type", "document_type"):
                acc[f] += 1 if arm["scores"][f]["exact"] else 0
            acc["model_numbers_f1"] += arm["scores"]["model_numbers"]["f1"]
            acc["product_type_f1"] += arm["scores"]["product_type"].get("token_f1", 0.0)
    summary = {}
    for arm_name, acc in by_arm.items():
        n = acc["n"] or 1
        summary[arm_name] = {
            "scored": acc["n"],
            "manufacturer_accuracy": round(acc["manufacturer"] / n, 4),
            # Exact is kept for continuity; the token F1 is the honest figure
            # for a free-text field, and the one the report quotes.
            "product_type_exact": round(acc["product_type"] / n, 4),
            "product_type_mean_token_f1": round(acc["product_type_f1"] / n, 4),
            "document_type_accuracy": round(acc["document_type"] / n, 4),
            "model_numbers_mean_f1": round(acc["model_numbers_f1"] / n, 4),
        }
    return summary


def aggregate_usage(results: list) -> dict:
    by_arm: dict[str, dict] = {}
    for manual in results:
        for arm_name, arm in manual.arms.items():
            u = arm.get("usage")
            if not u:
                continue
            acc = by_arm.setdefault(
                arm_name,
                {"model": u.get("model"), "calls": 0, "prompt_tokens": 0,
                 "completion_tokens": 0, "total_tokens": 0},
            )
            acc["calls"] += 1
            for k in ("prompt_tokens", "completion_tokens", "total_tokens"):
                acc[k] += u.get(k, 0) or 0
    for acc in by_arm.values():
        acc["tokens_per_manual"] = (
            round(acc["total_tokens"] / acc["calls"], 1) if acc["calls"] else None
        )
    return by_arm


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Extract manual metadata via LiteLLM, two arms, scored vs truth."
    )
    parser.add_argument("pdf_dir", type=Path, help="directory of source PDFs (image arm)")
    parser.add_argument("out_dir", type=Path, help="directory for per-manual metadata")
    parser.add_argument(
        "--arm", choices=("text", "image", "both"), default="both",
        help="which extraction arm(s) to run (default: both)",
    )
    parser.add_argument(
        "--converted-dir", type=Path,
        help="convert.py out-dir holding <stem>/document.md (required for the text arm)",
    )
    parser.add_argument(
        "--text-model", default=os.environ.get("METADATA_TEXT_MODEL", "heartcode-chat-sfw"),
        help="LiteLLM chat model for the text arm (default: heartcode-chat-sfw)",
    )
    parser.add_argument(
        "--image-model", default=os.environ.get("METADATA_IMAGE_MODEL", "gemini-3-flash-preview"),
        help="LiteLLM vision model for the image arm (default: gemini-3-flash-preview)",
    )
    parser.add_argument(
        "--text-chars", type=int, default=6000,
        help="chars of converted text fed to the text arm (default: 6000 ≈ first pages)",
    )
    parser.add_argument("--timeout", type=float, default=120.0, help="per-call timeout (s)")
    parser.add_argument(
        "--ground-truth", type=Path,
        help="JSON {stem: {manufacturer, model_numbers, product_type, document_type}} to score against",
    )
    parser.add_argument("--limit", type=int, default=0, help="process at most N PDFs (0 = all)")
    parser.add_argument(
        "--overwrite", action="store_true",
        help="re-extract manuals that already have a metadata file (default: skip)",
    )
    args = parser.parse_args()

    if not args.pdf_dir.is_dir():
        print(f"error: {args.pdf_dir} is not a directory", file=sys.stderr)
        return 2
    if args.arm in ("text", "both") and not args.converted_dir:
        print("error: --converted-dir is required for the text arm", file=sys.stderr)
        return 2

    pdfs = sorted(p for p in args.pdf_dir.rglob("*.pdf") if p.is_file())
    if not pdfs:
        print(f"error: no PDFs found under {args.pdf_dir}", file=sys.stderr)
        return 2

    truth = {}
    if args.ground_truth:
        truth = json.loads(args.ground_truth.read_text())

    args.out_dir.mkdir(parents=True, exist_ok=True)
    run_arms = ("text", "image") if args.arm == "both" else (args.arm,)
    print(f"arms={','.join(run_arms)}  pdfs={len(pdfs)}  scoring={'yes' if truth else 'no'}")

    results: list[ManualMetadata] = []
    processed = 0
    run_started = time.monotonic()

    for index, pdf in enumerate(pdfs, start=1):
        if args.limit and processed >= args.limit:
            break
        stem = pdf.stem
        marker = args.out_dir / f"{stem}.metadata.json"
        if marker.exists() and not args.overwrite:
            print(f"[{index}/{len(pdfs)}] {stem}: already extracted, skipping")
            continue

        manual = ManualMetadata(stem=stem, source=str(pdf.relative_to(args.pdf_dir)))
        print(f"[{index}/{len(pdfs)}] {stem}: {' + '.join(run_arms)} ...", flush=True)

        for arm_name in run_arms:
            if arm_name == "text":
                arm = run_text_arm(stem, args.converted_dir, args)
            else:
                arm = run_image_arm(pdf, args)
            if arm.ok and arm.prediction and truth.get(stem):
                arm.scores = score(arm.prediction, truth[stem])
            manual.arms[arm_name] = asdict(arm)
            status = "ok" if arm.ok else f"FAILED: {arm.error}"
            print(f"    {arm_name}: {status} ({arm.seconds}s)", flush=True)

        marker.write_text(json.dumps(asdict(manual), indent=2))
        results.append(manual)
        processed += 1

    run = {
        "arms": list(run_arms),
        "pdf_dir": str(args.pdf_dir),
        "converted_dir": str(args.converted_dir) if args.converted_dir else None,
        "wall_clock_seconds": round(time.monotonic() - run_started, 2),
        "processed": len(results),
        "usage": aggregate_usage(results),
        "accuracy": aggregate_scores(results) if truth else None,
    }
    (args.out_dir / "run.json").write_text(json.dumps(run, indent=2))

    print(f"\n{len(results)} manuals processed")
    if run["accuracy"]:
        for arm_name, acc in run["accuracy"].items():
            print(
                f"  {arm_name}: mfr {acc['manufacturer_accuracy']:.0%}  "
                f"type F1 {acc['product_type_mean_token_f1']:.2f}  "
                f"doctype {acc['document_type_accuracy']:.0%}  "
                f"model# F1 {acc['model_numbers_mean_f1']:.2f}  (n={acc['scored']})"
            )

    return 0 if results else 1


if __name__ == "__main__":
    sys.exit(main())
