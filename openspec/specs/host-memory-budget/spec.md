# host-memory-budget Specification

## Purpose
PEA's container memory is bounded and adds up: chat workers cap llama.cpp's host-RAM prompt cache, every default-started container has a memory limit, the limits fit in physical RAM minus an OS reserve, and CI enforces it. Established by `bound-llama-host-prompt-cache` after two host OOM kills on 2026-09-18 (synced from that change while its acceptance tasks were still open).
## Requirements
### Requirement: Chat workers bound their host prompt cache
Every chat worker SHALL start `llama-server` with an explicit `--cache-ram` value taken from the `CACHE_RAM` setting. The value SHALL be a positive number of MiB: neither `0` (which may disable `--cache-reuse`) nor `-1` (unlimited). A worker SHALL NOT rely on llama.cpp's built-in default.

#### Scenario: Worker command line carries the bound
- **WHEN** any `pea-gpu-N` container is running
- **THEN** its `llama-server` command line contains `--cache-ram <CACHE_RAM>` with a positive value

#### Scenario: Memory plateaus under sustained distinct sessions
- **WHEN** a worker serves at least 30 distinct multi-turn sessions
- **THEN** its `llama-server` resident memory levels off at no more than its baseline plus `CACHE_RAM` plus 256 MiB, and stays below the container's `mem_limit`

### Requirement: Prompt-cache reuse keeps its latency benefit
The chosen `CACHE_RAM` SHALL keep repeated-prompt time-to-first-token (client-measured wall time of a one-token completion, which includes restoring cached state), measured directly against a worker, within 10% of the value measured with llama.cpp's previous 8,192 MiB default, for two alternating active sessions.

#### Scenario: Returning conversation is restored from the host cache
- **WHEN** two conversations alternate on one worker, so each return evicts the other from the slot
- **THEN** the median TTFT of returning turns at the chosen `CACHE_RAM` is within 10% of the median at 8,192 MiB

### Requirement: Every PEA container has a memory limit
Every service in `gpu-server/docker-compose.yml` SHALL declare `mem_limit`, and SHALL declare `memswap_limit` no lower than `mem_limit` and at most 512 MiB above it. All chat workers SHALL share one memory configuration.

#### Scenario: A service without a limit is rejected
- **WHEN** a service is added to the PEA compose file without `mem_limit`
- **THEN** the memory-budget check fails and names the service

#### Scenario: Chat workers are uniform
- **WHEN** the resolved compose configuration is inspected
- **THEN** `gpu-server-1` through `gpu-server-6` have identical `mem_limit` and `memswap_limit`

### Requirement: Container limits fit in physical RAM
The sum of `mem_limit` across all PEA compose services SHALL NOT exceed the host RAM minus the OS reserve declared in the compose file's `x-host-memory` block. CI SHALL fail when it does.

#### Scenario: Adding a worker over budget fails CI
- **WHEN** a commit adds a service, or raises a limit, so that the sum exceeds `host_ram_mib − os_reserve_mib`
- **THEN** the CI job running the memory-budget check fails and prints the per-service totals

### Requirement: No host OOM kills under sustained load
Under a sustained load run on both chat routes, the PEA kernel SHALL NOT kill `llama-server` for host out-of-memory, and host available memory SHALL stay above 4 GiB.

#### Scenario: Sustained load on both routes
- **WHEN** a load run of at least two hours drives both `heartcode-chat-sfw` and `heartcode-chat-nsfw`
- **THEN** `journalctl -k` for the run's window has no `Out of memory: Killed process` entry for `llama-server`, and sampled `MemAvailable` never drops below 4 GiB
