## ADDED Requirements

### Requirement: Deployed stacks use digest-pinned images

Every registry image referenced by a deployed compose stack (`gpu-server`, `litellm`, `langfuse`) SHALL be pinned by content digest (`@sha256:`). Locally built images SHALL be exempt by an explicit allowlist. CI SHALL fail when a registry image lacks a digest.

#### Scenario: Floating tag introduced
- **WHEN** a compose file references a registry image by tag only
- **THEN** the `compose-validate` job fails and names the stack and image

#### Scenario: Locally built image
- **WHEN** a compose file references an image whose name matches the local-build allowlist
- **THEN** the check accepts it without a digest

#### Scenario: All pinned
- **WHEN** every registry image carries a digest
- **THEN** the check exits zero

### Requirement: Dependency pins are refreshed by reviewed pull requests

Container image digests, GitHub Actions versions and the unit-test Python requirements SHALL be refreshed through automated pull requests on a fixed cadence, grouped per stack, and SHALL NOT change on a host without passing CI and the qualification recorded next to the pin.

#### Scenario: Scheduled refresh
- **WHEN** the scheduled dependency check finds a newer digest or version
- **THEN** it opens one pull request per stack that CI validates before merge

#### Scenario: Pin needing qualification
- **WHEN** the bumped image is one whose pin comment names an extra test (for example the LiteLLM routing test or an image-generation smoke test)
- **THEN** the pull request carries a label marking it as needing that qualification before merge
