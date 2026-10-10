# Design — serve-public-inference-api

## Where the bounds live

The public hostname (SushiBastion, HeartCode task 1.4) can cap body size, but
it cannot see which key a request uses or how many public generations are in
flight. LiteLLM can: it authenticates the key, and a `CustomLogger` pre-call
hook sees the parsed body and the key's metadata. So size, sampler and
concurrency bounds live in one callback, and SushiBastion adds only a coarse
body-size cap in front.

Bounds are per public key *group*, identified by the `heartcode_key_name`
metadata HeartCode writes at creation. HeartCode's own backend key, rediska and
health checks carry no such marker, so first-party chat is never clamped or
admitted against the public allowance.

## Admission, not a team

LiteLLM teams were the obvious tool for a shared ceiling. Measured on 1.81.9: a
team with `max_parallel_requests: 1` admitted three concurrent requests from
one of its keys; only key-level limits produced headers. The guard therefore
counts public generations itself, in process, keyed by `litellm_call_id`.
That is exact because the proxy runs a single worker. A slot is released on
success (non-stream), on failure, or when the stream iterator ends or is
closed; anything that slips every hook expires after 300 s, above the 240 s
request timeout. Verified against the pinned image with a local proxy: a
second request while a stream runs gets 429 with `Retry-After: 5` (also via
the `heartcode-chat` alias), and the slot frees when the stream ends or its
client disconnects (on generation end upstream, which is when the GPU slot is
actually free).

## Clamp, don't refuse, samplers

SillyTavern presets routinely overshoot (temperature 4, top_k 0/large).
Clamping into `SAMPLER_BOUNDS` gives the user a working request; only a
non-numeric or non-finite value is a 400. `max_tokens` gets a ceiling even when
unsent, because the deployment default (512) is not a ceiling and a public
request should not hold a slot for thousands of tokens.

## Default allowance

One public generation per chat model group. With three SFW and two NSFW slots,
that reserves two SFW and one NSFW for first-party chat. Raise
`PUBLIC_API_PARALLEL` only with capacity evidence (`scale-chat-concurrency`).
