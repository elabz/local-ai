## ADDED Requirements

### Requirement: A single manifest is the source of truth for models and tenancy
`gpu-server/models.yaml` SHALL be the authoritative declaration of every served model and its placement. Each entry MUST specify an `api_name`, a `kind` (`chat` | `text-embed` | `vision-embed` | `visual-embed` | `image`), one or more `deployments` (each a GPU/slot index + port), and a model `source` (GGUF filename or HF repo). Optional fields include `aliases` and routing knobs (e.g. `rpm`).

#### Scenario: Changing a model is a one-file edit
- **WHEN** a maintainer changes the `source` (or GPU/port) of a model entry in `models.yaml` and regenerates
- **THEN** the chat env (`models.generated.env`), the LiteLLM `model_list`, and the download list all reflect the change
- **AND** no other file needs to be hand-edited for a model swap that keeps the same service kind

#### Scenario: Manifest covers all served model kinds
- **WHEN** the manifest is read
- **THEN** it enumerates the chat, text-embed, vision-embed, visual-embed, and image deployments that exist in the running topology

### Requirement: A generator renders the derived config from the manifest
`gpu-server/scripts/render-config.py` SHALL read `models.yaml` and render: (1) `gpu-server/models.generated.env` (the `GPU_N_MODEL_PATH/TYPE/NAME` values; kept separate from the gitignored, secret-bearing `gpu-server/.env`), (2) `litellm/config.yaml` by merging hand-maintained `litellm/config.base.yaml` with a manifest-derived `model_list` (plus `model_rate_limits` and `model_group_alias`), and (3) `gpu-server/models.download.tsv` consumed by `scripts/download-models.sh`. The generator MUST be deterministic (same manifest → same output) and depend only on the Python stdlib plus `PyYAML`.

#### Scenario: Deterministic render
- **WHEN** the generator runs twice on the same `models.yaml`
- **THEN** it produces byte-identical output both times

#### Scenario: Router settings are preserved
- **WHEN** the generator renders `litellm/config.yaml`
- **THEN** the `router_settings`, `general_settings`, and `litellm_settings` from `config.base.yaml` are preserved unchanged
- **AND** only the `model_list` section is derived from the manifest

#### Scenario: Backend api_base is derived from tenancy
- **WHEN** a model entry declares a deployment on a given port
- **THEN** the generated `model_list` routes that `api_name` to `http://192.168.0.144:<port>`

### Requirement: The manifest is schema-validated
CI SHALL reject a `models.yaml` that violates structural rules: `kind` outside the allowed set, a GPU index outside 1-8, colliding ports across deployments, a duplicate `api_name`, or a chat deployment whose `source` does not resolve to a downloadable model.

#### Scenario: Port collision fails validation
- **WHEN** two deployments in `models.yaml` declare the same port
- **THEN** the `model-manifest-validate` job fails identifying the colliding port

#### Scenario: Unknown kind fails validation
- **WHEN** an entry uses a `kind` not in the allowed set
- **THEN** validation fails identifying the offending entry

### Requirement: CI fails when generated files drift from the manifest
Generated files (`gpu-server/models.generated.env`, `litellm/config.yaml`, `gpu-server/models.download.tsv`) SHALL be committed, and CI SHALL re-render them and compare against the committed versions. Any difference MUST fail the build. (The gitignored, secret-bearing `gpu-server/.env` is hand-maintained and not drift-checked.)

#### Scenario: Hand-edited config is caught
- **WHEN** someone edits `litellm/config.yaml` directly without updating `models.yaml`
- **THEN** the regenerate-and-diff check fails, instructing the maintainer to edit `models.yaml` and regenerate

#### Scenario: In-sync repo passes
- **WHEN** the committed generated files match a fresh render of `models.yaml`
- **THEN** the drift check passes

### Requirement: Deploy applies manifest-derived config
The deploy workflow SHALL apply the manifest-derived config — the rendered `litellm/config.yaml` to Prod and the rendered `.env` / download list to PEA — using the same validated-then-health-checked flow as other deploys. It MAY either run the generator on the runner or rely on the committed generated files pulled via git.

#### Scenario: Manifest change rolls out via deploy
- **WHEN** a `models.yaml` change is merged and the deploy workflow runs
- **THEN** the rendered LiteLLM config is applied to Prod and the rendered `models.generated.env` to PEA
- **AND** the existing post-deploy health checks gate success
