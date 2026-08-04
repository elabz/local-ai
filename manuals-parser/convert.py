#!/usr/bin/env python3
"""Batch-convert a directory of product-manual PDFs to structured documents.

Pilot instrument for `content-manuals-pilot`: the point is not just the
conversion but the measurement around it. Every manual yields its own output
directory (Markdown + HTML + extracted figures) and a metrics record; a manual
that fails is recorded and the batch carries on, because a batch that aborts on
the first bad scan tells us nothing about the other nineteen.

    convert.py <in-dir> <out-dir> --engine docling|paddle|vlm

Three arms, all licence-clean for a commercially operated site (see README
§ Licensing — this constraint excluded several stronger-scoring engines):

    docling  Docling (MIT code, permissive weights) — primary, whole corpus
    paddle   PaddleOCR PP-StructureV3 (Apache-2.0 throughout) — scanned subset
    vlm      Page images through our own LiteLLM proxy — cost-bounded subset

Output layout, one directory per source PDF:

    <out-dir>/<stem>/document.md
    <out-dir>/<stem>/document.html      (docling only; the others emit Markdown)
    <out-dir>/<stem>/figures/*.png      (docling + paddle; the vlm arm has none)
    <out-dir>/<stem>/pages/*.png        (vlm arm only — render inputs, not output)
    <out-dir>/<stem>/metrics.json
    <out-dir>/run.json                  (aggregate + environment + LLM usage)
"""

import argparse
import base64
import json
import os
import sys
import time
import traceback
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional

# Which extensions roll up into which "output bytes by type" bucket. Anything
# unrecognised lands in "other" rather than being dropped, so the byte totals
# always reconcile against the directory.
BYTE_BUCKETS = {
    "markdown": {".md"},
    "html": {".html", ".htm"},
    "images": {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tiff"},
    "json": {".json"},
}


@dataclass
class Triage:
    """Cheap pre-conversion facts, gathered before either engine runs."""

    pages: int = 0
    input_bytes: int = 0
    extractable_chars: int = 0
    chars_per_page: float = 0.0
    # Both scan signals are kept, not merged away. `thin_text_layer` means the
    # PDF carries no usable text; `full_page_image_ratio` means the pages *are*
    # images. A scan that was OCR'd by whoever digitised it shows the second
    # without the first, and that combination is the one where an engine can
    # silently inherit someone else's OCR errors instead of reading the page.
    thin_text_layer: bool = False
    full_page_image_ratio: float = 0.0
    likely_scanned: bool = False
    triage_error: Optional[str] = None


@dataclass
class ManualMetrics:
    stem: str
    source: str
    engine: str
    ok: bool = False
    seconds: float = 0.0
    pages: int = 0
    input_bytes: int = 0
    output_bytes: dict = field(default_factory=dict)
    output_bytes_total: int = 0
    # Excludes the VLM arm's page renders: they are conversion inputs, not
    # things a manuals library would ever store or serve.
    publishable_bytes: int = 0
    figure_count: int = 0
    llm_usage: Optional[dict] = None
    likely_scanned: bool = False
    chars_per_page: float = 0.0
    # Carried through from triage so the report can separate "no text layer" from
    # "scanned but pre-OCR'd by the digitiser" — see Triage.
    thin_text_layer: bool = False
    full_page_image_ratio: float = 0.0
    expansion_ratio: float = 0.0
    error: Optional[str] = None
    traceback: Optional[str] = None


def triage_pdf(pdf: Path, scanned_threshold: float) -> Triage:
    """Page count plus a born-digital/scanned classification.

    Two independent signals, because the obvious one is wrong on its own:

    * **Text layer density.** A born-digital page has hundreds of extractable
      characters; a raw scan has none.
    * **Full-page image coverage.** A page whose content is a single image
      covering most of the sheet is a scan, whatever its text layer says.

    The second signal is what makes this correct. Scanning workflows — every
    archive.org upload among them — routinely embed an OCR text layer, so a scan
    can present 1,000+ chars/page and pass a text-layer test as born-digital. On
    the pilot corpus that mistake was not marginal: 14 of 27 files are scans, and
    the text-layer test alone recognised 5 of them. Since `--scanned-only`
    selects the PaddleOCR comparison subset, the arm meant to prove itself on
    scanned documents would have been handed mostly the ones that were easy.

    Both signals are recorded, not just the verdict: "no text layer at all" and
    "a scan carrying someone else's OCR" are different documents, and the second
    is the one where an engine can quietly inherit upstream OCR errors rather
    than making its own.

    Only the first few pages are probed — enough to classify, cheap on a
    300-page service manual.
    """
    t = Triage(input_bytes=pdf.stat().st_size)
    try:
        from pypdf import PdfReader

        reader = PdfReader(str(pdf))
        t.pages = len(reader.pages)

        probe = min(t.pages, 5)
        for page in reader.pages[:probe]:
            t.extractable_chars += len((page.extract_text() or "").strip())
        t.chars_per_page = round(t.extractable_chars / probe, 1) if probe else 0.0
        t.full_page_image_ratio = _full_page_image_ratio(pdf, probe)
        t.thin_text_layer = t.chars_per_page < scanned_threshold
        t.likely_scanned = t.thin_text_layer or t.full_page_image_ratio >= 0.5
    except Exception as exc:  # triage must never sink a manual
        t.triage_error = f"{type(exc).__name__}: {exc}"
        t.likely_scanned = True  # unreadable text layer → treat as the hard case
    return t


def _full_page_image_ratio(pdf: Path, probe: int) -> float:
    """Share of the probed pages whose content is one page-sized image.

    Measured on the *placed* area from pdfplumber rather than the image
    XObject's own pixel dimensions: a scan is defined by an image drawn across
    the sheet, and pypdf exposes the decoded bitmap without the content-stream
    transform that positions it. A big bitmap placed as a small inset is a
    figure, not a scan, and only the placed geometry can tell them apart.
    """
    try:
        import pdfplumber

        hits = 0
        with pdfplumber.open(str(pdf)) as doc:
            pages = doc.pages[:probe]
            if not pages:
                return 0.0
            for page in pages:
                area = (page.width or 0) * (page.height or 0)
                if not area:
                    continue
                for image in page.images:
                    width = abs(image.get("x1", 0) - image.get("x0", 0))
                    height = abs(image.get("y1", 0) - image.get("y0", 0))
                    if (width * height) / area > 0.6:
                        hits += 1
                        break
            return round(hits / len(pages), 2)
    except Exception:
        # A failed image probe must not change the text-layer verdict; returning
        # 0.0 leaves `likely_scanned` resting on chars-per-page alone.
        return 0.0


def measure_output(out_dir: Path) -> tuple[dict, int, int]:
    """Bytes by type, total bytes, and extracted-figure count.

    Page renders — the VLM arm's intermediate PNGs under `pages/` — are bucketed
    separately and excluded from the figure count. They are conversion *inputs*,
    not extracted artwork; counting them would flatter both the figure tally and
    the storage expansion ratio, and those two numbers feed the go/no-go.
    """
    by_type: dict[str, int] = {}
    figures = 0
    for path in out_dir.rglob("*"):
        if not path.is_file():
            continue
        size = path.stat().st_size
        parents = path.relative_to(out_dir).parts[:-1]
        bucket = next(
            (name for name, exts in BYTE_BUCKETS.items() if path.suffix.lower() in exts),
            "other",
        )
        if "pages" in parents:
            bucket = "page_renders"
        elif bucket == "images" and "figures" in parents:
            figures += 1
        by_type[bucket] = by_type.get(bucket, 0) + size
    return by_type, sum(by_type.values()), figures


def resolve_device(requested: str) -> str:
    """Map --device auto|cpu|cuda to the device the run will actually use.

    'auto' picks cuda only when torch reports a usable CUDA device, else cpu.
    An explicit 'cuda' is honoured as asked and left to fail loudly at
    conversion time if the runtime can't back it — a mis-set flag should surface
    rather than silently drop to CPU and quietly wreck the throughput number the
    pilot exists to measure. Elm is CPU-only today, so 'auto' resolves to cpu
    there until the deferred GPU card (task 1.7) is fitted.
    """
    if requested == "cpu":
        return "cpu"
    if requested == "cuda":
        return "cuda"
    try:
        import torch

        return "cuda" if torch.cuda.is_available() else "cpu"
    except Exception:
        return "cpu"


def _apply_docling_device(options, device: str, args) -> None:
    """Point Docling at the chosen device and pick a matching OCR engine.

    Two Pascal-specific facts drive this (design decisions 2–3), and both are
    why `--device cuda` is not just a flag flip:

    * **Device selection alone does not move OCR onto the GPU.** Docling's only
      known GPU-capable OCR path is RapidOCR with the torch backend; the default
      engine stays on CPU regardless of AcceleratorDevice. OCR dominates runtime
      on scanned manuals — exactly the hard cases the card is wanted for — so on
      CUDA we switch the OCR *engine*, not merely the accelerator.
    * **FP32 is forced by staying on FP32.** Consumer Pascal runs FP16 at 1:64,
      so half precision would be slower than CPU. RapidOCR's torch backend and
      the layout/table models run FP32; we enable no half-precision path. (Same
      reason gpu-server/dino-embed pins PRECISION=float32.)

    The accelerator-options import moved across docling 2.x minors, so both
    known module paths are tried — this file is written from documentation and
    first validated live at task 1.4.
    """
    try:
        from docling.datamodel.accelerator_options import (
            AcceleratorDevice,
            AcceleratorOptions,
        )
    except ImportError:  # older 2.x layout
        from docling.datamodel.pipeline_options import (
            AcceleratorDevice,
            AcceleratorOptions,
        )

    options.accelerator_options = AcceleratorOptions(
        device=AcceleratorDevice.CUDA if device == "cuda" else AcceleratorDevice.CPU
    )

    if device == "cuda":
        from docling.datamodel.pipeline_options import RapidOcrOptions

        # RapidOCR carries its own language model set with codes unlike the
        # default engine's; leave it at default and confirm multi-language
        # behaviour when the GPU path is first exercised (task 1.7). --ocr-lang
        # continues to steer the CPU engine below.
        options.ocr_options = RapidOcrOptions(backend="torch")
    else:
        from docling.datamodel.pipeline_options import TesseractCliOcrOptions

        # Tesseract is named explicitly rather than left on docling's default.
        # That default is OcrAutoOptions, which picks RapidOCR and fetches its
        # weights from modelscope.cn — unreachable from Elm, so every conversion
        # died on a download error before a page was read (pilot task 1.4).
        # Tesseract is also what the image actually provisions (the CLI plus the
        # eng/deu/fra/spa/ita packs), and naming the engine keeps the run
        # reproducible: the report has to state which OCR engine produced the
        # scores, and an auto-selector can change that answer between versions.
        options.ocr_options = TesseractCliOcrOptions(
            lang=args.ocr_lang or ["eng"],
            force_full_page_ocr=bool(getattr(args, "force_ocr", False)),
        )

    # Which OCR engine ran is a reported fact, not an assumption: on CUDA only
    # the RapidOCR torch backend is actually accelerated, so the report needs the
    # engine name next to the device name to mean anything.
    args.ocr_engine = type(options.ocr_options).__name__


def convert_docling(pdf: Path, out_dir: Path, args) -> Optional[dict]:
    """Docling → document.md + document.html with figures written alongside.

    ImageRefMode.REFERENCED is what makes the figures *placed*: images are
    written to figures/ and referenced from the flow at their real position,
    rather than being inlined as base64 or dumped in an unordered appendix.
    Figure placement is one of the rubric dimensions, so this is load-bearing.
    """
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import PdfPipelineOptions
    from docling.document_converter import DocumentConverter, PdfFormatOption
    from docling_core.types.doc import ImageRefMode

    options = PdfPipelineOptions()
    options.do_ocr = True
    options.do_table_structure = True
    options.table_structure_options.do_cell_matching = True
    options.generate_picture_images = True
    options.images_scale = 2.0
    _apply_docling_device(options, getattr(args, "resolved_device", "cpu"), args)

    converter = DocumentConverter(
        format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=options)}
    )
    doc = converter.convert(str(pdf)).document

    # Relative, not out_dir / "figures": an absolute artifacts_dir makes docling
    # emit absolute image refs (`/out/<stem>/figures/...`), which are dead links
    # the moment the output leaves the container that produced it. Relative keeps
    # the output directory self-contained and movable — figure placement is a
    # scored rubric dimension, and a placed figure that 404s scores nothing.
    figures = Path("figures")
    doc.save_as_markdown(
        out_dir / "document.md",
        artifacts_dir=figures,
        image_mode=ImageRefMode.REFERENCED,
    )
    doc.save_as_html(
        out_dir / "document.html",
        artifacts_dir=figures,
        image_mode=ImageRefMode.REFERENCED,
    )
    return None


def convert_paddle(pdf: Path, out_dir: Path, args) -> Optional[dict]:
    """PaddleOCR PP-StructureV3 → document.md + figures.

    Replaced MinerU on 2026-07-22: MinerU's licence mandates user-visible
    attribution on any online service built on it (see README § Licensing), and
    that credit is unacceptable on published manual pages. PP-StructureV3 is
    Apache-2.0 in both code and weights, and its table extraction is the
    strongest in the permissive tier — which is what the scanned subset is for,
    since parts-list fidelity is a scored rubric dimension.
    """
    from paddleocr import PPStructureV3

    staging = out_dir / "_paddle"
    staging.mkdir(parents=True, exist_ok=True)

    # Only the sub-pipelines this pilot actually scores are enabled.
    #
    # PP-StructureV3's defaults pull in the whole model zoo — PP-FormulaNet_plus-L
    # for LaTeX formula recognition and PP-Chart2Table for turning charts into
    # tables, plus document- and textline-orientation classifiers. Product
    # manuals have no formulas and no statistical charts, so those two are pure
    # cost: they dominated model download and load time, and the first attempt
    # never reached page one of the second manual. Orientation classification is
    # dropped too — these scans are upright, and the rubric scores layout, OCR
    # and table fidelity, none of which it feeds.
    #
    # What stays on is what the rubric measures: layout detection, OCR, and
    # table structure recognition (the reason PaddleOCR is in the pilot at all).
    pipeline = PPStructureV3(
        lang=(args.ocr_lang or ["en"])[0],
        use_formula_recognition=False,
        use_chart_recognition=False,
        use_seal_recognition=False,
        use_doc_orientation_classify=False,
        use_doc_unwarping=False,
        use_textline_orientation=False,
    )
    for page_result in pipeline.predict(input=str(pdf)):
        page_result.save_to_markdown(save_path=str(staging))

    produced = sorted(staging.rglob("*.md"))
    if not produced:
        raise RuntimeError(f"PP-StructureV3 produced no markdown under {staging}")

    # Predict yields one result per page; concatenate in page order so the
    # document reads as one manual rather than N fragments.
    document = "\n\n".join(p.read_text(errors="replace") for p in produced)
    (out_dir / "document.md").write_text(document)

    figures = out_dir / "figures"
    figures.mkdir(exist_ok=True)
    for image in staging.rglob("*"):
        if image.is_file() and image.suffix.lower() in BYTE_BUCKETS["images"]:
            (figures / image.name).write_bytes(image.read_bytes())
    return None


VLM_PROMPT = (
    "Convert this page of a product manual to clean, structured Markdown.\n"
    "- Preserve heading hierarchy and reading order.\n"
    "- Render tables as GitHub-flavoured Markdown tables, preserving every cell; "
    "parts lists and specification tables must not be summarised or truncated.\n"
    "- Where a figure or diagram appears, emit a placeholder line "
    "`![figure](figure-N)` with a one-line description beneath it.\n"
    "- Transcribe text verbatim. Do not translate, summarise, correct, or add "
    "commentary. Multi-language pages keep each language in its own section.\n"
    "- Output only the Markdown, with no preamble or code fence."
)


GEMINI_ENDPOINT = (
    "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
)


def _call_gemini(client, model: str, api_key: str, prompt: str, png: bytes) -> tuple:
    """One page through Google's Gemini API directly. Returns (text, usage).

    Product decision 2026-08-03: the VLM arms call Google directly rather than
    routing through our LiteLLM proxy, reversing design decisions 5 and 6. The
    proxy route would have required deploying a config change and restarting the
    shared proxy that live SEO and Reddit features depend on — too much standing
    infrastructure for an experimental proof of concept. This is also the path
    the shipped Reddit content generation already uses, so the request contract
    below matches `ImageDescriptionService::callGemini` in site-2017 rather than
    being invented here.

    The cost of that choice, which belongs in the report: no Langfuse tracing and
    no Postgres-managed key for this arm. If the arm is ever adopted, moving it
    behind the proxy restores both.

    `thinkingBudget: 0` matters at this volume. This arm is one call per *page*,
    and Gemini 3 bills thinking tokens at several times the output rate; leaving
    thinking on would make the measured cost per page a measurement of thinking,
    not of conversion.
    """
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
                "thinkingConfig": {"thinkingBudget": 0},
            },
        },
    )
    if response.status_code != 200:
        raise RuntimeError(f"Gemini {response.status_code}: {response.text[:500]}")
    payload = response.json()

    candidates = payload.get("candidates") or []
    parts = (candidates[0].get("content", {}) if candidates else {}).get("parts") or []
    # A 200 with no content is a known gemini-3-flash-preview quirk (the same one
    # LlmProviderPreflight guards against), so treat it as an empty page rather
    # than letting an IndexError sink the manual.
    text = "".join(part.get("text", "") for part in parts)

    meta = payload.get("usageMetadata") or {}
    usage = {
        "prompt_tokens": meta.get("promptTokenCount", 0) or 0,
        "completion_tokens": meta.get("candidatesTokenCount", 0) or 0,
        "thinking_tokens": meta.get("thoughtsTokenCount", 0) or 0,
        "total_tokens": meta.get("totalTokenCount", 0) or 0,
    }
    return text, usage


def convert_vlm(pdf: Path, out_dir: Path, args) -> Optional[dict]:
    """Render each page and convert it through a vision model.

    Two limitations are deliberate and must reach the report rather than be
    papered over:

    1. **No figure extraction.** This arm emits Markdown with figure
       *placeholders* — it never crops artwork to disk. For a manuals library
       built around exploded-view diagrams that is disqualifying on its own
       unless paired with Docling's figure extraction.
    2. **One model call per page.** Metadata extraction is one call per *manual*;
       this is one per *page*, roughly 40× the volume. A favourable metadata
       result does not transfer, so usage is recorded per page and extrapolated
       in the report before any adoption recommendation.
    """
    import io

    import httpx
    import pypdfium2

    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY must be set for the VLM arm")

    pages_dir = out_dir / "pages"
    pages_dir.mkdir(exist_ok=True)

    document: list[str] = []
    usage = {
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "thinking_tokens": 0,
        "total_tokens": 0,
        "calls": 0,
    }

    pdf_doc = pypdfium2.PdfDocument(str(pdf))
    page_limit = args.vlm_max_pages or len(pdf_doc)
    try:
        with httpx.Client(timeout=args.vlm_timeout) as client:
            for index in range(min(len(pdf_doc), page_limit)):
                # 2x scale ≈ 144 DPI: enough for small-print parts tables
                # without pushing every page over the model's image budget.
                image = pdf_doc[index].render(scale=2).to_pil()
                buffer = io.BytesIO()
                image.save(buffer, format="PNG")
                png = buffer.getvalue()
                (pages_dir / f"page-{index + 1:04d}.png").write_bytes(png)

                try:
                    text, page_usage = _call_gemini(
                        client, args.vlm_model, api_key, VLM_PROMPT, png
                    )
                except Exception as exc:
                    raise RuntimeError(f"page {index + 1}: {exc}") from exc
                document.append(text)

                usage["calls"] += 1
                for key in (
                    "prompt_tokens",
                    "completion_tokens",
                    "thinking_tokens",
                    "total_tokens",
                ):
                    usage[key] += page_usage.get(key, 0) or 0
    finally:
        pdf_doc.close()

    if not document:
        raise RuntimeError("VLM arm produced no pages")

    (out_dir / "document.md").write_text("\n\n---\n\n".join(document))
    usage["pages_converted"] = len(document)
    usage["model"] = args.vlm_model
    return usage


def describe_environment() -> dict:
    """Record what the batch actually ran on — the PEA/Pascal open question."""
    env = {"python": sys.version.split()[0], "cuda_available": False}
    try:
        import torch

        env["torch"] = torch.__version__
        env["cuda_available"] = bool(torch.cuda.is_available())
        if env["cuda_available"]:
            env["device_name"] = torch.cuda.get_device_name(0)
            major, minor = torch.cuda.get_device_capability(0)
            env["compute_capability"] = f"{major}.{minor}"
            env["cuda_version"] = torch.version.cuda
    except Exception as exc:
        env["torch_error"] = f"{type(exc).__name__}: {exc}"
    return env


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Batch-convert manual PDFs to structured documents with metrics."
    )
    parser.add_argument("in_dir", type=Path, help="directory of source PDFs")
    parser.add_argument("out_dir", type=Path, help="directory for per-manual output")
    parser.add_argument(
        "--engine",
        choices=("docling", "paddle", "vlm"),
        default="docling",
        help="conversion engine (default: docling)",
    )
    parser.add_argument(
        "--device",
        choices=("auto", "cpu", "cuda"),
        default="auto",
        help="compute device for Docling (default: auto). 'cuda' also switches "
        "OCR to the RapidOCR torch backend, the only GPU-accelerated OCR path; "
        "device selection alone leaves OCR on the CPU. Elm is CPU-only until the "
        "deferred GPU card (task 1.7) is fitted.",
    )
    parser.add_argument(
        "--scanned-only",
        action="store_true",
        help="convert only PDFs triaged as scanned (the PaddleOCR comparison subset)",
    )
    parser.add_argument(
        "--vlm-model",
        default=os.environ.get("GEMINI_VLM_MODEL", "gemini-3-flash-preview"),
        help="Gemini vision model for --engine vlm (called directly, not via LiteLLM)",
    )
    parser.add_argument(
        "--vlm-max-pages",
        type=int,
        default=0,
        help="cap pages per manual on the VLM arm (0 = all); bounds cost on the "
        "300pp service manual, which alone would dominate the arm's spend",
    )
    parser.add_argument(
        "--vlm-timeout",
        type=float,
        default=180.0,
        help="per-page LiteLLM request timeout in seconds",
    )
    parser.add_argument(
        "--ocr-lang",
        default="",
        help="comma-separated OCR languages, e.g. eng,deu (default: eng). Only "
        "affects pages where OCR actually runs — a scan carrying an embedded "
        "text layer is read from that layer and this flag does nothing for it "
        "unless --force-ocr is also given",
    )
    parser.add_argument(
        "--force-ocr",
        action="store_true",
        help="re-OCR every page from its image instead of reading an embedded "
        "text layer. Slower, and the right default for scans: a digitiser's "
        "embedded OCR is inherited verbatim, errors and all (pilot task 3.2 "
        "measured a scan whose layer read part number 61967 as 01967 and merged "
        "adjacent table rows; forcing OCR recovered both)",
    )
    parser.add_argument(
        "--scanned-threshold",
        type=float,
        default=100.0,
        help="extractable chars/page below which a PDF is treated as scanned",
    )
    parser.add_argument(
        "--limit", type=int, default=0, help="convert at most N PDFs (0 = all)"
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="reconvert manuals that already have output (default: skip)",
    )
    args = parser.parse_args()

    if not args.in_dir.is_dir():
        print(f"error: {args.in_dir} is not a directory", file=sys.stderr)
        return 2

    pdfs = sorted(p for p in args.in_dir.rglob("*.pdf") if p.is_file())
    if not pdfs:
        print(f"error: no PDFs found under {args.in_dir}", file=sys.stderr)
        return 2

    args.out_dir.mkdir(parents=True, exist_ok=True)
    args.ocr_lang = [x.strip() for x in args.ocr_lang.split(",") if x.strip()]
    engine = {
        "docling": convert_docling,
        "paddle": convert_paddle,
        "vlm": convert_vlm,
    }[args.engine]

    # Resolve the requested device once and record both what was asked and what
    # the run actually used — the report has to state the device per the
    # "accelerated OCR is verified, not assumed" requirement, and 'auto' hides
    # the answer otherwise.
    args.resolved_device = resolve_device(args.device)
    environment = describe_environment()
    environment["requested_device"] = args.device
    environment["resolved_device"] = args.resolved_device
    print(
        f"engine={args.engine}  pdfs={len(pdfs)}  "
        f"device={args.resolved_device} (--device {args.device})  "
        f"cuda={environment['cuda_available']}"
    )
    if environment.get("compute_capability"):
        print(f"gpu={environment.get('device_name')} sm_{environment['compute_capability']}")

    results: list[ManualMetrics] = []
    skipped_born_digital = 0
    run_started = time.monotonic()

    for index, pdf in enumerate(pdfs, start=1):
        if args.limit and len(results) >= args.limit:
            break

        stem = pdf.stem
        manual_out = args.out_dir / stem
        marker = manual_out / "metrics.json"
        if marker.exists() and not args.overwrite:
            print(f"[{index}/{len(pdfs)}] {stem}: already converted, skipping")
            continue

        triage = triage_pdf(pdf, args.scanned_threshold)
        if args.scanned_only and not triage.likely_scanned:
            skipped_born_digital += 1
            print(f"[{index}/{len(pdfs)}] {stem}: born-digital, skipping (--scanned-only)")
            continue

        metrics = ManualMetrics(
            stem=stem,
            source=str(pdf.relative_to(args.in_dir)),
            engine=args.engine,
            pages=triage.pages,
            input_bytes=triage.input_bytes,
            likely_scanned=triage.likely_scanned,
            chars_per_page=triage.chars_per_page,
            thin_text_layer=triage.thin_text_layer,
            full_page_image_ratio=triage.full_page_image_ratio,
        )

        print(
            f"[{index}/{len(pdfs)}] {stem}: {triage.pages}pp "
            f"{'scanned' if triage.likely_scanned else 'born-digital'} ...",
            flush=True,
        )

        manual_out.mkdir(parents=True, exist_ok=True)
        started = time.monotonic()
        try:
            metrics.llm_usage = engine(pdf, manual_out, args)
            metrics.ok = True
        except Exception as exc:
            metrics.error = f"{type(exc).__name__}: {exc}"
            metrics.traceback = traceback.format_exc()
            print(f"    FAILED: {metrics.error}", file=sys.stderr, flush=True)
        metrics.seconds = round(time.monotonic() - started, 2)

        by_type, total, figures = measure_output(manual_out)
        metrics.output_bytes = by_type
        metrics.output_bytes_total = total
        metrics.publishable_bytes = total - by_type.get("page_renders", 0)
        metrics.figure_count = figures
        if metrics.input_bytes:
            # Ratio is against publishable bytes: storage sizing for the library
            # must not be inflated by the VLM arm's throwaway page renders.
            metrics.expansion_ratio = round(
                metrics.publishable_bytes / metrics.input_bytes, 4
            )

        marker.write_text(json.dumps(asdict(metrics), indent=2))
        results.append(metrics)

        if metrics.ok:
            rate = metrics.pages / metrics.seconds * 3600 if metrics.seconds else 0
            line = (
                f"    ok in {metrics.seconds}s  ({rate:,.0f} pages/hr)  "
                f"{figures} figures  {metrics.publishable_bytes / 1e6:.2f} MB out"
            )
            if metrics.llm_usage:
                line += f"  {metrics.llm_usage['total_tokens']:,} tokens"
            print(line, flush=True)

    # Set by the docling arm once the pipeline is configured, so it is only known
    # after the first conversion attempt — read it here rather than up front.
    environment["ocr_engine"] = getattr(args, "ocr_engine", None)

    converted = [m for m in results if m.ok]
    failed = [m for m in results if not m.ok]
    total_pages = sum(m.pages for m in converted)
    total_seconds = sum(m.seconds for m in converted)

    # The VLM arm's economics are the whole reason to measure it: pilot-scale
    # spend is trivial, production scale is one call per page across the entire
    # library. Aggregate the tokens so the report can extrapolate from measured
    # numbers rather than guesses.
    usages = [m.llm_usage for m in converted if m.llm_usage]
    llm_totals = None
    if usages:
        pages_converted = sum(u.get("pages_converted", 0) for u in usages)
        total_tokens = sum(u.get("total_tokens", 0) for u in usages)
        llm_totals = {
            "model": usages[0].get("model"),
            "calls": sum(u.get("calls", 0) for u in usages),
            "prompt_tokens": sum(u.get("prompt_tokens", 0) for u in usages),
            "completion_tokens": sum(u.get("completion_tokens", 0) for u in usages),
            "total_tokens": total_tokens,
            "pages_converted": pages_converted,
            "tokens_per_page": (
                round(total_tokens / pages_converted, 1) if pages_converted else None
            ),
        }

    run = {
        "engine": args.engine,
        "environment": environment,
        "in_dir": str(args.in_dir),
        "out_dir": str(args.out_dir),
        "wall_clock_seconds": round(time.monotonic() - run_started, 2),
        "pdfs_discovered": len(pdfs),
        "attempted": len(results),
        "converted": len(converted),
        "failed": len(failed),
        "skipped_born_digital": skipped_born_digital,
        "total_pages": total_pages,
        "total_conversion_seconds": round(total_seconds, 2),
        "pages_per_hour": round(total_pages / total_seconds * 3600, 1) if total_seconds else None,
        "total_input_bytes": sum(m.input_bytes for m in converted),
        "total_output_bytes": sum(m.output_bytes_total for m in converted),
        "total_publishable_bytes": sum(m.publishable_bytes for m in converted),
        "llm_usage": llm_totals,
        "mean_expansion_ratio": (
            round(sum(m.expansion_ratio for m in converted) / len(converted), 4)
            if converted
            else None
        ),
        "failures": [{"stem": m.stem, "error": m.error} for m in failed],
        "manuals": [asdict(m) for m in results],
    }
    (args.out_dir / "run.json").write_text(json.dumps(run, indent=2))

    print(
        f"\n{len(converted)} converted, {len(failed)} failed, "
        f"{total_pages} pages in {total_seconds:.0f}s"
        + (f"  ({run['pages_per_hour']:,.0f} pages/hr)" if run["pages_per_hour"] else "")
    )
    if failed:
        print("failures: " + ", ".join(m.stem for m in failed))

    # A batch that converted nothing is a run-level failure; individual manual
    # failures are data, not an error exit.
    return 0 if converted else 1


if __name__ == "__main__":
    sys.exit(main())
