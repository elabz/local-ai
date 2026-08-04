# manuals-ocr-quality

## Why

The manuals pilot (report at `docs/research/MANUALS_PILOT_REPORT.md` in the **site-2017** repo) returned a split verdict: **born-digital 12/12 publishable (100%), scanned 6/15 (40%)**. The scanned cohort is not a side case — it is the entire differentiator. The feasibility work names the moat as *"legacy/discontinued brands whose manufacturer sites are gone"*, and those manuals exist only as scans. Of 7 legacy-brand manuals in the corpus, **1 was publishable.**

That 40% is also not a converged number. It was 13% until the pilot found that Docling reads a scan's embedded text layer instead of OCRing the page, and 9 of the 15 scans arrived pre-OCR'd — so the pipeline was scoring *the digitiser's* OCR rather than its own. Adding `--force-ocr` with matched languages tripled the pass rate in an afternoon at no wall-clock cost (1,285 vs 1,220 pages/hr).

Two named defects account for almost all of the remaining failures and **neither has been attempted**. On the evidence that one correction tripled the rate, the honest reading is "40% and still climbing", not "40%, therefore no". This change attempts the two fixes and re-scores, so the scanned-legacy premise is decided on a number that reflects the engine rather than a configuration the pilot itself disproved.

## What Changes

- **Fix orientation handling — the top remaining recoverable defect and the one regression `--force-ocr` introduced.** Forcing full-page OCR discards the orientation handling the embedded layer carried, so rotated and mirrored regions become gibberish (`millers_falls` prose fell 1 → 0 even as its table rose 1 → 3). Tesseract OSD is the lever and currently fails with "Too few characters" on exactly those pages. Detect page/region rotation before OCR and correct it, rather than relying on OSD alone.
- **Validate embedded text layers before trusting them.** `do_ocr=True` does not override an existing text layer, and `lecroy_9450a_service` produced **420 pages of mojibake counted as a successful conversion**. Add a garbage-text check that scores an embedded layer's plausibility and forces OCR when it fails — so a corrupt layer can never again be emitted silently.
- **Make `--force-ocr` the default for scans**, conditional on the fixes above landing (it is currently opt-in and regresses rotated content when used blind).
- **Improve the scan detector.** Chars-per-page recognised only 5 of 15 scans because pre-OCR'd files present 1,000–3,000 extractable chars/page. The pilot already added a full-page-image ratio signal; promote the combined signal into the decision that drives forcing OCR, not just triage reporting.
- **Attempt scanned table structure**, the hard blocker — table fidelity barely moved under the force-OCR correction (47% → 53%) while readability went 40% → 80%. Rows merge, cells duplicate across columns, tables emerge as empty pipes. Prose from the *same* documents is often excellent.
- **Re-score the scanned cohort against the same rubric** and publish an updated pass rate, so the phase-2 go/no-go rests on measurement rather than on the pilot's superseded configuration.
- **Deliberate non-goals:** no re-litigating the licence exclusions (MinerU, Marker and Surya are out on weights/terms and that is not negotiable), no GPU adoption, no VLM conversion arm.

## Capabilities

### New Capabilities

- `manuals-ocr-quality`: the correctness guarantees the scanned-manual conversion path must hold — embedded-text-layer validation, orientation correction, scan detection driving OCR forcing, and the re-scoring contract that produces a comparable pass rate.

### Modified Capabilities

<!-- none — manuals-parser has no existing spec; the pilot shipped it as code without one -->

## Impact

- **Code**: `manuals-parser/convert.py` — the `_apply_docling_device` OCR-options block (`TesseractCliOcrOptions`, `force_full_page_ocr`), the triage/scan-detection path, and a new pre-OCR validation and orientation stage. Possibly `Dockerfile`/`Dockerfile.cpu` if orientation correction needs additional tooling or language packs (the pilot already added `jpn`).
- **Corpus**: re-runs against the pilot corpus, which lives on elm at `/logs+backup/manuals-pilot` (4.9 GB) — not committed, and pilot task 6.3 has not yet decided its fate, so **this change depends on that corpus still existing**.
- **Repos**: parser code is in this repo on `manuals-parser-pilot`; the report and rubric it must be scored against live in site-2017 (`openspec/changes/content-manuals-pilot/pilot/RUBRIC.md`, `pilot/results/RUBRIC_SCORES.md`). Re-scored results belong beside them.
- **Hardware**: CPU-only on elm, containers capped at 12 cores / 24 GB so conversion stays clear of page serving for 13 production sites. PEA is excluded (VRAM committed, 2-core Celeron host, gen-1 x1 risers).
- **Cost**: $0 external — local engines only. Wall-clock is the real cost: the corpus is 1,960 pages and the scanned cohort re-ran at 1,285 pages/hr.
- **Downstream**: the re-scored number decides whether the scanned-legacy premise is revived. It does **not** gate `content-model-hubs`, which was deliberately scoped to need no OCR at all.
