## Context

`manuals-parser/` was built during the site-2017 `content-manuals-pilot` and lives on this repo's `manuals-parser-pilot` branch. It has no spec — the pilot deliberately shipped it as measurement code, not product code.

The pilot's scanned result moved twice, and how it moved is the whole argument for this change:

| Configuration | scanned publishable |
|---|---|
| default (`--ocr-lang` unset, embedded layers trusted) | 13% |
| `--force-ocr` + matched languages | **40%** |

Per-dimension, the correction was uneven — which is what points at the remaining work:

| Dimension | born-digital | scanned (first pass) | scanned (corrected) |
|---|---|---|---|
| Readability | 100% | 40% | **80%** |
| Heading/TOC structure | 100% | 80% | 87% |
| Table fidelity | 100% | 47% | **53%** |
| Figure placement | 100% | 87% | 87% |
| Language purity | 100% | 40% | **100%** |

Language purity is solved. Readability doubled. **Table fidelity barely moved and is now the blocker.** Structure and figure placement were never the problem.

Current OCR configuration in `convert.py` (`_apply_docling_device`): CPU runs `TesseractCliOcrOptions(lang=args.ocr_lang or ["eng"], force_full_page_ocr=bool(args.force_ocr))`; CUDA runs `RapidOcrOptions(backend="torch")`. `options.do_ocr = True` and `do_table_structure = True` are set unconditionally in `convert_docling`. Tesseract is named explicitly rather than left on docling's `OcrAutoOptions`, because that default fetches RapidOCR weights from modelscope.cn, which is unreachable from elm.

Constraints: CPU-only on elm (12 cores / 24 GB cap, shared with page serving for 13 production sites), no GPU, and the licence-clean engine pool is materially smaller than the feasibility research assumed — MinerU, Marker and Surya are all excluded on weights or added terms, and they are most of the top of the OmniDocBench leaderboard.

## Goals / Non-Goals

**Goals:**
- Make a corrupt embedded text layer impossible to emit silently.
- Remove the orientation regression that forcing OCR introduced, so forcing can become the default for scans.
- Attempt scanned table structure, the dimension that did not move.
- Produce a re-scored, comparable scanned pass rate so the phase-2 decision rests on measurement.

**Non-Goals:**
- Re-opening the licence exclusions. Not negotiable.
- GPU adoption. Deferred until backfill volume justifies a maintenance window on the production web server.
- The VLM conversion arm. Rejected on cost and zero figure extraction.
- Any product code in site-2017. This is parser-only.
- Auto-publishing scanned parts lists — that stays a human-review policy decision, not something this change fixes.

## Decisions

### 1. Validation before extraction, not after

The garbage-text check runs as a gate on the embedded layer, before extraction, and forces OCR on failure. Checking output after the fact would still have produced 420 pages of mojibake — it would only have labelled them.

*Alternative considered:* post-hoc scoring of emitted text with a quality flag. Rejected — it makes the failure visible without preventing it, and the pilot's failure mode was precisely that a bad conversion counted as a success.

### 2. Forcing OCR becomes the default for scans, but only after orientation is fixed

`--force-ocr` is currently opt-in and, used blind, trades one defect for another: it fixed every part number in `millers_falls` while dropping its prose from 1 to 0. Making it the default before orientation is corrected would ship a known regression across the whole scanned cohort.

Sequencing is therefore load-bearing: orientation correction lands first, the no-regression scenario is proven, then the default flips.

### 3. Orientation is corrected upstream of Tesseract, not delegated to OSD

OSD is the obvious lever and is the thing currently failing — "Too few characters" on exactly the pages that need it, because a rotated page yields too little text for OSD to work from. Depending on the component that is already failing is not a fix.

The approach is to detect rotation from page imagery ahead of OCR and correct it, using OSD as a signal where it succeeds rather than as the sole decision. Deskew/rotation detection on the rendered page is available without adding a restrictively-licensed dependency.

*Alternative considered:* re-enable the embedded layer's orientation handling by extracting from the layer when it is sound and forcing OCR only where it is not, per page. Worth keeping as a fallback — it is close to what decision 1 already builds — but it inherits the digitiser's errors on any page where the layer is trusted, which is the failure this whole line of work exists to remove.

### 4. Table structure is attempted, and may not be fixable here

Table fidelity moved 47% → 53% under a correction that doubled readability, which suggests the residue is engine limitation rather than configuration. Docling's `do_table_structure` with `do_cell_matching` is already on. The realistic levers are cell-matching parameters, rasterisation scale ahead of table detection (`images_scale` is currently 2.0), and pre-segmenting ruled tables.

This is scoped as an attempt with a measured outcome, not a promise. **The honest possibility is that scanned table fidelity does not clear the bar without an engine we cannot licence or a GPU we have not adopted** — and that is a legitimate finding that would settle the phase-2 question the other way.

### 5. Re-score against the identical rubric and corpus

The pilot's numbers are only comparable if the instrument does not move. Same 15 scanned manuals, same five dimensions, same rubric file in site-2017. The pilot itself had to fix its scoring instrument twice (a missing `max_tokens` truncating valid JSON; `product_type` scored by exact match) — that lesson applies here.

## Risks / Trade-offs

- **Table fidelity may not be fixable on this hardware with licence-clean engines.** → Scoped as a measured attempt. A negative result is publishable and decides phase 2 honestly. There is also a known evidence gap: PaddleOCR PP-StructureV3, adopted specifically for table extraction, never completed on CPU (>21 min on an 8-page manual), so no quality comparison exists at all.
- **Orientation correction could regress documents that currently work.** → The spec carries an explicit no-regression scenario across the whole scanned cohort, not just the affected manuals.
- **The corpus may be deleted before this runs.** Pilot task 6.3 ("archive/delete corpus PDFs") is still open, and the 4.9 GB tree on elm is the only copy — re-scoring is impossible without it. → Resolve 6.3 in favour of retention before starting, or accept re-acquisition cost.
- **Re-runs compete with production page serving.** → Same containment the pilot used: 12 cores / 24 GB cap on elm. The scanned cohort is ~1,293 pages at 1,285 pages/hr, so roughly an hour of contained CPU.
- **Cross-repo split.** Parser here, rubric and report in site-2017. → Re-scored results are written beside the pilot's existing results in site-2017; this repo holds only the code change.

## Migration Plan

1. Confirm the pilot corpus on elm still exists (blocks everything).
2. Land embedded-layer validation with the rejection recorded in metrics; verify against `lecroy_9450a_service`, the known 420-page mojibake case.
3. Land orientation correction; verify against `millers_falls`, the known regression case, and prove the no-regression scenario across the cohort.
4. Flip forcing to default-on for detected scans.
5. Attempt table structure; measure per-dimension.
6. Re-score all 15 scanned manuals; publish beside the 13%/40% baselines.

**Rollback:** every change is confined to the parser's conversion configuration and is revertible by commit. Nothing is deployed to a production service — the parser is batch tooling run by hand.

## Open Questions

- **Does the corpus survive?** Pilot task 6.3 is unresolved and this change depends on the answer.
- **Is a GPU required to settle table fidelity?** If the CPU attempt fails, the PaddleOCR comparison that was never run becomes the deciding evidence, and it needs a GPU — which reopens the deferred hardware trade on a production web server.
- **What pass rate would revive the scanned-legacy premise?** The pilot set the original kill criterion but not a threshold for the retry. Worth agreeing before the re-score, so the answer is not chosen after seeing it.
