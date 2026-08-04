## ADDED Requirements

### Requirement: Embedded text layers are validated before use
The converter SHALL score the plausibility of a PDF's embedded text layer before extracting from it, and SHALL fall back to full-page OCR when that layer fails the check, so a corrupt layer is never emitted as a successful conversion.

`do_ocr=True` does not override an existing text layer. In the pilot this emitted 420 pages of mojibake from `lecroy_9450a_service` while reporting success.

#### Scenario: Corrupt embedded layer is rejected
- **WHEN** a PDF carries an embedded text layer that decodes to mojibake
- **THEN** the converter does not extract from that layer, runs OCR on the page instead, and records that the layer was rejected

#### Scenario: Sound embedded layer is used
- **WHEN** a born-digital PDF carries a well-formed embedded text layer
- **THEN** the converter extracts from that layer without forcing OCR

#### Scenario: Rejection is visible in the run record
- **WHEN** any page's embedded layer is rejected during a run
- **THEN** the per-manual metrics record the rejection, so a silent substitution cannot occur

### Requirement: Scan detection drives OCR forcing
The converter SHALL decide whether a document is a scan from a combined signal that includes both extractable characters per page and the share of pages that are a single page-sized image, and that decision SHALL drive whether OCR is forced.

Characters-per-page alone recognised only 5 of the pilot's 15 scans, because pre-OCR'd files present 1,000–3,000 chars/page and read as born-digital.

#### Scenario: Pre-OCR'd scan is detected
- **WHEN** a document's pages are predominantly single page-sized images while still exposing extractable characters
- **THEN** it is classified as a scan and OCR is forced

#### Scenario: Born-digital document is not forced
- **WHEN** a document is text-native and its pages are not page-sized images
- **THEN** it is not classified as a scan and OCR is not forced

#### Scenario: Both signals are recorded separately
- **WHEN** triage runs on any document
- **THEN** characters-per-page and full-page-image ratio are recorded as separate values

### Requirement: Orientation is corrected before OCR
The converter SHALL detect and correct rotated or mirrored page and region orientation before running OCR, and forcing OCR SHALL NOT reduce readability on documents whose orientation the embedded layer previously handled.

This is the one regression `--force-ocr` introduced: it discards the orientation handling the embedded layer carried, and Tesseract OSD currently fails with "Too few characters" on exactly the affected pages.

#### Scenario: Rotated page is corrected
- **WHEN** a scanned page is rotated relative to reading orientation
- **THEN** it is corrected before OCR and its text is extracted in reading order

#### Scenario: OSD failure does not silently pass through
- **WHEN** orientation detection cannot determine a page's orientation
- **THEN** the failure is recorded for that page rather than the page being OCR'd blind and reported as successful

#### Scenario: No readability regression from forcing OCR
- **WHEN** the scanned cohort is converted with OCR forced
- **THEN** no manual's readability score is lower than the same manual scored without forcing

### Requirement: Re-scoring is comparable to the pilot baseline
Re-scored results SHALL be produced against the same rubric, the same corpus and the same dimensions as the pilot, and SHALL report the scanned-cohort pass rate alongside the pilot's 13% (default) and 40% (force-OCR) figures.

An improvement measured against a different rubric or corpus subset is not evidence about the same question.

#### Scenario: Same rubric and corpus
- **WHEN** the scanned cohort is re-scored
- **THEN** it is scored on all five pilot dimensions against the same 15 scanned manuals

#### Scenario: Comparable figures published
- **WHEN** re-scored results are published
- **THEN** they state the new scanned pass rate beside the 13% and 40% baselines and identify which fixes were active

#### Scenario: Per-dimension movement is reported
- **WHEN** re-scored results are published
- **THEN** readability and table fidelity are reported separately, since the pilot's correction moved one and not the other
