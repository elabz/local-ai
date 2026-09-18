## MODIFIED Requirements

### Requirement: The pilot uses multiple references reproducibly

The `kvoicewalk-multireference.v1` profile SHALL compute a normalized target
speaker centroid from every adaptation recording, SHALL exclude all development
and release-held-out recordings from construction, SHALL record the random seed
and pinned builder revision, and SHALL emit deterministic build metadata for
each walk. Candidate or checkpoint selection after construction SHALL use only a
separately authorized development set, and final release qualification SHALL use
untouched release-held-out recordings that were not used for construction,
tuning, or candidate selection.

#### Scenario: Pilot constructs a candidate
- **WHEN** a validated manifest contains adaptation, development, and release-held-out samples
- **THEN** all adaptation samples contribute to the target centroid, no development or release-held-out sample is opened during construction, and the result records its seed and input manifest digest

#### Scenario: Preserved candidates are compared
- **WHEN** completed artifacts or integrity-valid checkpoints are ranked after construction
- **THEN** only the separate development set informs candidate selection and release-held-out inputs remain unopened for the future release gate
