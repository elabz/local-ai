## ADDED Requirements

### Requirement: CI runs on GitHub-hosted runners without secrets or LAN access
The continuous-integration workflow SHALL run entirely on GitHub-hosted runners (`ubuntu-latest`) and MUST NOT require repository secrets, GHCR push permissions, or network access to the private LAN (`192.168.0.0/24`). A healthy repository state MUST produce a passing run.

#### Scenario: Push with a healthy repo passes
- **WHEN** a commit is pushed to `main` (or a PR is opened) touching tracked paths
- **THEN** all CI validation jobs complete successfully
- **AND** no job attempts to push an image to GHCR or SSH to a `192.168.0.x` host

#### Scenario: No package-permission failure
- **WHEN** the CI workflow runs
- **THEN** it does not fail with `denied: installation not allowed to Create organization package`
- **AND** each job declares least-privilege `permissions` (validation jobs use `contents: read`)

### Requirement: Compose stacks are validated
CI SHALL validate every Docker Compose stack in the repo by running `docker compose config` (parse/interpolate only) for `gpu-server`, `litellm`, `monitoring`, and `langfuse`.

#### Scenario: Invalid compose fails the build
- **WHEN** a `docker-compose.yml` contains a YAML or schema error (e.g. bad indentation, unknown key, undefined required variable)
- **THEN** the `compose-validate` job fails and blocks the merge

#### Scenario: Valid compose passes
- **WHEN** all compose files parse and interpolate cleanly
- **THEN** the `compose-validate` job succeeds without pulling or building images

### Requirement: LiteLLM config is validated
CI SHALL validate `litellm/config.yaml` (and `config-local.yaml`): the YAML MUST parse, `model_list` MUST be non-empty, every `model_name` MUST be unique, and every deployment's `litellm_params` MUST include an `api_base`.

#### Scenario: Duplicate or malformed model entry fails
- **WHEN** `config.yaml` has a duplicate `model_name`, a missing `api_base`, or invalid YAML
- **THEN** the `litellm-validate` job fails with a message identifying the offending entry

#### Scenario: Well-formed config passes
- **WHEN** `config.yaml` is well-formed and every deployment has a unique name and an `api_base`
- **THEN** the `litellm-validate` job succeeds

### Requirement: Python services are linted and byte-compiled
CI SHALL run `ruff check` and `python -m py_compile` over the FastAPI services under `gpu-server/`, `gpu-server/vision-embed/`, and `gpu-server/dino-embed/`.

#### Scenario: Syntax error or lint violation fails
- **WHEN** a `.py` file in a service directory has a syntax error or a lint error
- **THEN** the `python-lint` job fails and blocks the merge

### Requirement: GPU server image build is a path-filtered build-only check
CI SHALL build `gpu-server/Dockerfile` with `push: false` to catch build breakage, and this job MUST run only when `gpu-server/Dockerfile`, `gpu-server/requirements.txt`, or the wrapper `*.py` change — not for changes confined to `vision-embed/` or `dino-embed/`.

#### Scenario: Dockerfile change triggers a build-only check
- **WHEN** a commit changes `gpu-server/Dockerfile` or `gpu-server/requirements.txt`
- **THEN** the `gpu-build` job builds the image without pushing it
- **AND** a build failure blocks the merge

#### Scenario: Embed-only change skips the heavy build
- **WHEN** a commit only changes files under `gpu-server/vision-embed/` or `gpu-server/dino-embed/`
- **THEN** the `gpu-build` job is skipped (or short-circuits) and does not run the llama.cpp CUDA build

### Requirement: Actions are on supported, non-deprecated versions
CI SHALL use action versions that run on a supported Node.js runtime so runs do not emit Node 20 deprecation annotations.

#### Scenario: No deprecation annotation
- **WHEN** the workflow runs
- **THEN** GitHub does not annotate it with a "Node.js 20 actions are deprecated" warning
