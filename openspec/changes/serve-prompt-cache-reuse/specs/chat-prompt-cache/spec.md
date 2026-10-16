## ADDED Requirements

### Requirement: Chat routing keeps a session on one replica when the pool allows
For chat model groups routed `least-busy`, a request carrying a session id SHALL be sent to the replica chosen by rendezvous hashing of that id over the healthy deployments with the lowest in-flight count. A request without a session id SHALL be sent to one of those deployments chosen uniformly at random. A deployment with more in-flight requests than another healthy deployment SHALL NOT be chosen because of a session id.

#### Scenario: Idle pool, same session
- **WHEN** two consecutive requests carry the same session id and every healthy replica is idle
- **THEN** both are served by the same replica

#### Scenario: Preferred replica busy
- **WHEN** the replica a session hashes to has a request in flight and another healthy replica is idle
- **THEN** the request goes to the idle replica

#### Scenario: Replica leaves the pool
- **WHEN** a replica becomes unhealthy
- **THEN** only sessions that hashed to it move, and sessions that hashed elsewhere keep their replica

#### Scenario: No session id
- **WHEN** requests carry no session id and every replica is idle
- **THEN** they spread across the replicas as they do today

### Requirement: Prompt reuse is visible to consumers
A chat completion served by a Pea worker through LiteLLM SHALL report to the client how many prompt tokens were reused from the cache, on both streamed and non-streamed responses. The figure SHALL be `usage.prompt_tokens_details.cached_tokens` or llama.cpp's `timings.cache_n`.

#### Scenario: Streamed completion
- **WHEN** a consumer streams a chat completion from `heartcode-chat-sfw` or `heartcode-chat-nsfw`
- **THEN** the response carries the number of cached prompt tokens

### Requirement: 8K prompts are qualified on the chat routes
Before a consumer's default context is raised to 8192 tokens, both chat routes SHALL be shown to serve multi-turn conversations whose prompts reach 8192 tokens minus the consumer's response buffer, through LiteLLM, meeting all of:
- zero failed requests and zero `llama-server` exits;
- at least 300 MiB of free VRAM per card;
- resident memory below the container's `mem_limit` with the host prompt cache full;
- the same result over a 24-hour soak.

The result SHALL be recorded as evidence.

#### Scenario: Qualification passes
- **WHEN** the 8K runs and the soak complete with no failures, no exits, and the headroom held
- **THEN** the evidence records the pass and the consumer may raise its default

#### Scenario: Qualification fails
- **WHEN** any run ends in an OOM kill, an exit or exhausted headroom
- **THEN** the consumer's default stays at 4096 and the failure and its cause are recorded

### Requirement: The host prompt cache is sized for the qualified prompt size
Each chat route's `CACHE_RAM` SHALL be chosen by measuring returning-conversation time-to-first-token at the qualified prompt size, with two to four sessions alternating on one worker. The value SHALL be the smallest that keeps the benefit, and SHALL fit within `host-memory-budget`.

#### Scenario: Value chosen from measurement
- **WHEN** `CACHE_RAM` is changed for a chat route
- **THEN** the evidence shows the alternating-session TTFT at the old and new values, and the memory-budget check passes

### Requirement: Checkpoint flags change only after isolated measurement
`--checkpoint-min-step` and `--swa-full` SHALL NOT be changed on the chat fleet until they are measured on a single worker, for host and GPU memory and for reuse after a mid-prompt change, and the measurement shows a benefit within budget.

#### Scenario: Flag rolled out
- **WHEN** either flag is set on the chat fleet
- **THEN** evidence from a single-worker measurement precedes it
