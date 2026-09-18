## ADDED Requirements

### Requirement: CI runs the gpu-server unit tests
The CI workflow SHALL run the `gpu-server/tests` unit suite (excluding `tests/integration`) on every push and pull request, on GitHub-hosted runners without LAN access, and the job SHALL fail when any test fails or errors during collection.

#### Scenario: A test regression blocks the build
- **WHEN** a commit changes `gpu-server/metrics.py` so that a test stub no longer matches it and a test fails
- **THEN** the unit-test job reports failure for that commit

#### Scenario: Collection errors are failures
- **WHEN** a test module cannot be imported because of a missing dependency
- **THEN** the unit-test job fails instead of skipping the module silently

### Requirement: Test dependencies are pinned
Test dependencies SHALL be installed from a pinned requirements file committed to the repo, so a clean CI install resolves the same versions every run.

#### Scenario: Upstream release does not change the result
- **WHEN** a new FastAPI or pydantic version is published upstream
- **THEN** the CI unit-test job still installs the pinned versions and its result is unchanged
