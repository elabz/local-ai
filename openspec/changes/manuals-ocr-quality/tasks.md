# manuals-ocr-quality — tasks

## 1. Preconditions

- [ ] 1.1 Confirm the pilot corpus still exists on elm at `/logs+backup/manuals-pilot` (4.9 GB) — **this blocks every other task**; site-2017 pilot task 6.3 ("archive/delete corpus PDFs") is still open and this is the only copy
- [ ] 1.2 Agree the pass-rate threshold that would revive the scanned-legacy premise, and record it — before the re-score, so the bar is not chosen after seeing the result
- [ ] 1.3 Re-establish the containment used by the pilot (12 cores / 24 GB cap) so re-runs stay clear of page serving for 13 production sites

## 2. Embedded text layer validation

- [ ] 2.1 Implement a plausibility check that scores an embedded text layer before extraction and forces OCR when it fails
- [ ] 2.2 Record layer rejection in the per-manual metrics JSON so a silent substitution is impossible
- [ ] 2.3 Verify against `lecroy_9450a_service` — the known 420-page mojibake case that previously counted as a successful conversion
- [ ] 2.4 Verify a born-digital manual with a sound layer is still extracted without forcing OCR (no throughput regression on the 4,204 pages/hr cohort)

## 3. Scan detection

- [ ] 3.1 Promote the combined signal (chars-per-page **and** full-page-image ratio) from triage reporting into the decision that drives OCR forcing
- [ ] 3.2 Verify it detects the 9 pre-OCR'd scans that chars-per-page alone missed (pilot recognised 5 of 15)
- [ ] 3.3 Keep both signals recorded separately in metrics

## 4. Orientation correction

- [ ] 4.1 Detect page/region rotation from rendered page imagery ahead of OCR, using OSD as a signal where it succeeds rather than as the sole decision (OSD currently fails "Too few characters" on exactly the pages that need it)
- [ ] 4.2 Correct detected rotation before OCR runs
- [ ] 4.3 Record orientation-detection failures per page instead of OCR'ing blind and reporting success
- [ ] 4.4 Verify against `millers_falls_mitre_box` — the known regression case where forcing OCR took prose 1 → 0 while the table went 1 → 3
- [ ] 4.5 Prove the no-regression scenario across the whole scanned cohort: no manual's readability scores lower with forcing than without

## 5. Make forcing the default

- [ ] 5.1 Flip `force_full_page_ocr` to default-on for documents detected as scans — **only after 4.5 passes**; doing it earlier ships a known regression
- [ ] 5.2 Keep an explicit override for the born-digital path and confirm it is unaffected

## 6. Table structure (measured attempt)

- [ ] 6.1 Establish the current per-manual table-fidelity baseline on the corrected run (47% → 53% is where the pilot left it)
- [ ] 6.2 Try cell-matching parameters and rasterisation scale ahead of table detection (`images_scale` is currently 2.0), measuring each independently
- [ ] 6.3 Try pre-segmenting ruled tables before handing regions to the table model
- [ ] 6.4 Record the outcome honestly, including a negative — **"scanned table fidelity does not clear the bar on licence-clean engines without a GPU" is a legitimate finding** that settles phase 2 the other way

## 7. Re-score

- [ ] 7.1 Re-run all 15 scanned manuals with the fixes active
- [ ] 7.2 Score against the identical rubric and dimensions used by the pilot (`pilot/RUBRIC.md` in site-2017) — the instrument must not move or the comparison is meaningless
- [ ] 7.3 Publish the new pass rate beside the 13% (default) and 40% (force-OCR) baselines, stating which fixes were active
- [ ] 7.4 Report readability and table fidelity separately — the pilot's correction moved one and not the other, and a blended number would hide that again
- [ ] 7.5 Write results beside the pilot's existing results in site-2017 rather than in this repo

## 8. Close out

- [ ] 8.1 Record the outcome and the decision it drives (revive scanned-legacy, or close it) in memory
- [ ] 8.2 If the CPU attempt fails on tables, state plainly that the never-run PaddleOCR comparison becomes the deciding evidence and that it reopens the deferred GPU trade
- [ ] 8.3 Merge `manuals-parser-pilot` and this branch, since the parser has never landed on `main`
