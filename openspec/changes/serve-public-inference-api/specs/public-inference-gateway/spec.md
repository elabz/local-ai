## ADDED Requirements

### Requirement: OpenAI-format sampler fields reach llama.cpp
The chat wrapper SHALL forward `stop` (a string or a list of strings), `seed`,
`presence_penalty`, `frequency_penalty` and `repetition_penalty` to llama.cpp
on both streaming and non-streaming chat completions, in addition to
`temperature`, `top_p`, `top_k`, `min_p`, `repeat_penalty` and `max_tokens`.
`repetition_penalty` SHALL be sent as `repeat_penalty`, and an explicit
`repeat_penalty` SHALL take precedence. Fields the client did not send SHALL
NOT be sent.

#### Scenario: Stop string honoured
- **WHEN** a chat request through the proxy sets `stop: ["7"]` and asks for the numbers 1 to 12
- **THEN** the generation stops before emitting 7

#### Scenario: Penalties reach the slot
- **WHEN** a chat request sets `presence_penalty`, `frequency_penalty` and `repetition_penalty`
- **THEN** llama.cpp's `/slots` for the serving slot reports those values (`repetition_penalty` as `repeat_penalty`)

### Requirement: Public API keys are identified by HeartCode's marker
The proxy SHALL treat a request as public API traffic exactly when its virtual
key's metadata contains `heartcode_key_name`. All other traffic SHALL pass the
public guard unchanged.

#### Scenario: First-party request is not bounded
- **WHEN** a key without the marker sends 101 messages and `temperature: 9`
- **THEN** the guard neither rejects nor modifies the request

### Requirement: Public request size is bounded
For public chat requests the proxy SHALL reject more than 100 messages, or any
message whose text content exceeds 32 KiB measured in UTF-8 bytes, with HTTP
413 before the request reaches a model.

#### Scenario: Too many messages
- **WHEN** a public key sends 101 messages
- **THEN** the response is HTTP 413 naming the limit

### Requirement: Public samplers are bounded
For public chat requests the proxy SHALL clamp `temperature` to [0, 2],
`top_p` and `min_p` to [0, 1], `top_k` to [0, 200], repetition penalties to
[0.5, 2], presence and frequency penalties to [-2, 2], and `max_tokens` to
[1, the configured ceiling], SHALL apply the `max_tokens` ceiling when the
client sends none, SHALL force `n` to 1, and SHALL reject a non-numeric or
non-finite sampler value with HTTP 400.

#### Scenario: Overshooting preset is clamped
- **WHEN** a public key sends `temperature: 7` and `max_tokens: 900` with a ceiling of 64
- **THEN** the serving slot runs at temperature 2.0 and at most 64 tokens

### Requirement: Public generations are admitted per model group
The proxy SHALL admit at most the configured number of public generations per
chat model group at once (default 1), counting an alias against the group it
resolves to, and SHALL answer the next public request for that group with
HTTP 429 and a `Retry-After` header. An admitted slot SHALL be released when
the request completes, fails, or its stream ends or is abandoned, and SHALL
expire if never released.

#### Scenario: Second public generation while one streams
- **WHEN** a public stream is in flight on `heartcode-chat-sfw` and a public key requests `heartcode-chat`
- **THEN** the second request receives HTTP 429 with `Retry-After`

#### Scenario: First-party capacity preserved
- **WHEN** the public allowance for a group is in use
- **THEN** first-party requests to that group are still admitted by the guard
