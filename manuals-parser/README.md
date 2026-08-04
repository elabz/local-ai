# manuals-parser

Batch PDF → structured-document conversion for product manuals. Built for the
`content-manuals-pilot` measurement run (site-2017 repo); designed so the same
container can become the phase-2 conversion worker unchanged if the pilot
returns a go.

Unlike the components under `gpu-server/`, this is a **batch container**: no
HTTP surface, no metrics endpoint, no healthcheck. You invoke it with a command
and it writes files.

## Engines

| Arm | Engine | Scope | Code | Weights |
|---|---|---|---|---|
| `docling` | [Docling](https://github.com/docling-project/docling) 2.114.0 | whole corpus, primary | MIT (IBM) | CDLA-Permissive-2.0 + Apache-2.0 |
| `paddle` | [PaddleOCR](https://github.com/PaddlePaddle/PaddleOCR) PP-StructureV3 3.2.0 | scanned subset | Apache-2.0 | Apache-2.0 |
| `vlm` | page images → our LiteLLM proxy | cost-bounded subset | ours | routed model |

## Licensing — read before adding an engine

**The rule: audit the model weights separately from the repository licence.**
Permissively-licensed code routinely loads restrictively-licensed weights, and
nothing in the repo warns you. This is not hypothetical — it removed two of the
strongest candidates below.

Engines **excluded** from this component, with the specific disqualifying
clause, so the decision survives a future version bump:

| Engine | Why excluded |
|---|---|
| **MinerU** 3.4.4 | `LICENSE.md` is Apache-2.0 **plus additional terms**. §1's commercial thresholds (100M MAU / $20M monthly revenue) are irrelevant at our scale, but **§2 mandates that any online service built on MinerU prominently credit it**, and §3 auto-terminates all rights on non-compliance. Product decision 2026-07-22: a "converted with MinerU" credit on published manual pages is unacceptable. Note MinerU 2.5.4 was **AGPL-3.0** — this project has relicensed twice, so pin and re-check. |
| **Marker** | Repo is plain Apache-2.0 with no appended terms — it looks clean. But it runs on Surya's weights, which are **CC-BY-NC-SA-4.0 (non-commercial)**. Disqualifying for an ad-monetised site. |
| **Surya** | Weights **CC-BY-NC-SA-4.0**, same reason. |
| **LlamaParse** | Self-hosting is Enterprise-plan-only (sales-led, licence key, Kubernetes/Helm) — a new commercial relationship, not a reuse of infrastructure we run. The default path uploads every PDF to LlamaIndex Cloud, and production scale (~2M pages) runs ~$7.5k recurring against the pilot's `$0 external` posture. |

Permissive alternatives held in reserve, verified clean in code *and* weights,
if the three shipped arms miss the quality bar: `granite-docling-258M`
(Apache-2.0, tiny enough for Pascal), `dots.ocr` (MIT), `olmOCR-7B` (Apache-2.0,
but wants a modern GPU — its serving stack has poor Pascal support).

Docling and PaddleOCR impose no obligation beyond retaining notices.

## Build

```bash
cd manuals-parser
docker build -t local-ai-manuals-parser:latest .
```

The image builds on the CUDA 12.1 + torch cu121 base proven for PEA's Pascal
(sm_61) cards in `gpu-server/dino-embed`. Whether the conversion stacks actually
*accelerate* on sm_61 is an open pilot question — `convert.py` records the
device it ran on in `run.json`, and the container runs CPU-only unmodified when
CUDA is absent or unusable.

## Run

```bash
# Docling over the whole corpus (CPU)
docker run --rm \
  -v /path/to/corpus:/corpus:ro -v /path/to/out:/out -v manuals-models:/models \
  local-ai-manuals-parser:latest /corpus /out --engine docling

# Same, GPU (PEA)
docker run --rm --gpus all \
  -v /path/to/corpus:/corpus:ro -v /path/to/out:/out -v manuals-models:/models \
  local-ai-manuals-parser:latest /corpus /out --engine docling

# PaddleOCR over the scanned subset only
docker run --rm --gpus all \
  -v /path/to/corpus:/corpus:ro -v /path/to/out-paddle:/out -v manuals-models:/models \
  local-ai-manuals-parser:latest /corpus /out --engine paddle --scanned-only

# VLM arm through the LiteLLM proxy, page-capped to bound spend
docker run --rm \
  -v /path/to/corpus:/corpus:ro -v /path/to/out-vlm:/out \
  -e LITELLM_BASE_URL=http://192.168.0.152:4000/v1 \
  -e LITELLM_API_KEY=sk-... \
  local-ai-manuals-parser:latest /corpus /out --engine vlm --vlm-max-pages 20
```

Mount `/models` as a named volume — layout, table and OCR weights download on
first run and are large. Corpus PDFs are **never** committed to either repo.

### Options

| Flag | Effect |
|---|---|
| `--engine docling\|paddle\|vlm` | conversion arm (default `docling`) |
| `--scanned-only` | convert only PDFs triaged as scanned — the PaddleOCR subset |
| `--ocr-lang eng,deu` | OCR languages; PaddleOCR takes the first only. **Not optional on non-English scans — see below** |
| `--scanned-threshold N` | extractable chars/page below which a PDF counts as scanned (default 100) |
| `--vlm-model` | LiteLLM-routed vision model (default `gemini-3-flash-preview`) |
| `--vlm-max-pages N` | cap pages per manual on the VLM arm; 0 = all |
| `--vlm-timeout N` | per-page request timeout, seconds (default 180) |
| `--limit N` | stop after N manuals — use for smoke tests |
| `--overwrite` | reconvert manuals that already have `metrics.json` (default: skip) |

### `--ocr-lang` is load-bearing, and its default is wrong for half a corpus

Leaving `--ocr-lang` at its `eng` default silently degrades every non-English
scan, and the damage looks like bad OCR rather than misconfiguration. Measured on
the pilot's German scan (`wandel_goltermann_mu30_de`, 24pp), same file, same
engine, only the flag changed:

| `--ocr-lang eng` | `--ocr-lang deu` |
|---|---|
| `MeBstellen-Umschalter` | `Meßstellen-Umschalter` |
| `fur die sende…` | `für die sende…` |
| `30 Fernsprechkanalen` | `30 Fernsprechkanälen` |
| `Anderungen vorbehalten` | `Änderungen vorbehalten` |

Every umlaut in the document was wrong, and the text still *read* as plausible
German to a spell-check-free eye. That moves the file from "not publishable" to
"clean" on the readability rubric — a whole quality tier bought with a flag.

Two consequences worth carrying into any production design:

1. **Language must be detected before OCR, not after.** A pipeline that OCRs
   first and identifies language later has already destroyed the evidence.
2. **The image ships `eng`, `deu`, `fra`, `spa`, `ita` only.** Japanese is
   absent, which is why the pilot's two Japanese scans could not be rescued the
   same way — `hitachi_kh2200_service` came out as character soup. Adding a
   language means adding its `tesseract-ocr-*` package to the Dockerfiles.

Note the interaction with pre-OCR'd scans: `yamaha_champ_cj50em_parts` is
Japanese and came out with *correct* Japanese text, because Docling used the text
layer the digitiser had already embedded rather than running OCR at all. The same
mechanism that hurts you on `lecroy_9450a_service` (a corrupt embedded layer,
ingested verbatim) helps you here.

### The VLM arm — two limitations that must reach the report

1. **It extracts no figures.** It emits Markdown with figure *placeholders* and
   never crops artwork to disk. For a manuals library built around exploded-view
   diagrams that is disqualifying on its own unless paired with Docling's figure
   extraction.
2. **One model call per page.** Metadata extraction is one call per *manual*;
   this is one per *page* — roughly 40× the volume. A favourable metadata result
   does not transfer. Token usage is recorded per page and aggregated into
   `run.json` so the report extrapolates from measurement, not guesswork. Use
   `--vlm-max-pages` on the 300pp service manual, which would otherwise dominate
   the arm's entire spend.

## Output

```
<out>/<stem>/document.md          structured Markdown, headings + reading order
<out>/<stem>/document.html        docling only; other arms emit Markdown alone
<out>/<stem>/figures/*.png        extracted figures, referenced in-flow
<out>/<stem>/pages/*.png          vlm arm only — render inputs, not output
<out>/<stem>/metrics.json         per-manual record
<out>/run.json                    aggregate + environment + LLM usage totals
```

Docling and PaddleOCR write figures in `REFERENCED` mode, so images live on disk
and are linked from their real position in the document flow rather than inlined
or appended. Figure placement is a scored rubric dimension, so this is
load-bearing, not cosmetic.

`metrics.json` per manual: pages, wall-clock seconds, input bytes, output bytes
bucketed by type, figure count, expansion ratio, scanned/born-digital triage,
LLM usage where applicable, and — on failure — the error and traceback.

Page renders are bucketed as `page_renders` and **excluded** from
`publishable_bytes` and the expansion ratio: they are conversion inputs, not
things the library would ever store or serve, and counting them would inflate
the storage sizing that feeds the go/no-go.

**A failed manual never aborts the batch.** Failures are recorded per-file and
the run continues; `convert.py` exits non-zero only if *nothing* converted.
Nineteen good conversions and one failure is a result, not an error.

## Status

**Built and smoke-tested on Elm, CPU-only, 2026-08-03 (pilot task 1.4).** Four
real manuals (24/84/28 pages born-digital + a 41-page 1954 scan), 177 pages,
4 converted / 0 failed. `Dockerfile.cpu` image is 3.09 GB and the downloaded
model set is 506 MB, close to the ~530 MB the design predicted.

Measured on `--cpus 8 --memory 16g` (Elm has 20 threads; the cap keeps the batch
clear of page serving for 13 production sites):

| | pages/hour |
|---|---|
| born-digital | ~3,400 |
| scanned (OCR-dominated) | ~870 |
| mixed batch overall | **2,179** |

This is the CPU baseline the deferred GPU question (task 1.7) is judged against.
Note the ~4× spread: the GPU case rests entirely on the scanned subset, which is
also the only place Docling's GPU OCR path applies.

Writing this file from documentation and validating it later cost three defects,
all of which killed *every* conversion and none of which was visible without a
live install:

1. **`transformers` 5.x against torch 2.4.1.** `docling-ibm-models` allows
   `>=4.42,<6.0`, so the resolver took 5.14.1, which imports `DTensor` from
   `torch.distributed.tensor` at import time — a name torch 2.4.1 does not
   export. torch is pinned to the proven Pascal sm_61 build, so `requirements.txt`
   now pins `transformers>=4.42,<5` (4.57.6 verified).
2. **`DOCLING_ARTIFACTS_PATH` pointed at an empty volume.** Docling reads it as
   "the models are already here", not "download them here", and aborts. Removed
   from both Dockerfiles; `HF_HOME`/`HF_HUB_CACHE` already cache into the same
   mounted volume.
3. **OCR engine left on docling's default.** The default is `OcrAutoOptions`,
   which selects RapidOCR and fetches weights from `modelscope.cn` — unreachable
   from Elm. `convert.py` now names `TesseractCliOcrOptions` explicitly on the
   CPU path, which is what the image actually provisions, and records the engine
   in `run.json`.

Also fixed: `artifacts_dir` was absolute, so Markdown/HTML carried
`/out/<stem>/figures/...` image refs that break as soon as the output leaves the
container. It is now relative and the output directory is self-contained.

Still unvalidated against a live install: the **PaddleOCR arm**
(`PPStructureV3.predict`) and the **VLM arm** (LiteLLM `/chat/completions` image
contract) — both are first exercised in task 3.1.
