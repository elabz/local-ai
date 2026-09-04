## 1. Baseline and reproduction

- [ ] 1.1 Record secret-free baseline evidence for SFW backend restart counts, restart timestamps, watchdog reasons, LiteLLM downstream connection failures, and proxy 5xx responses.
- [ ] 1.2 Add a reproducible sustained-concurrency test that crosses at least five watchdog intervals and demonstrates the current false-restart behavior without storing prompts or responses.
- [ ] 1.3 Measure normal completion latency, health-probe latency while idle and busy, model startup time, and recovery time on the P104-100 backends.

## 2. Backend health semantics

- [ ] 2.1 Track bounded in-flight request state and expose `starting`, `ready`, `busy`, `degraded`, and `unavailable` with reason enums.
- [ ] 2.2 Change the watchdog so a live child serving inference is not restarted solely because HTTP health probes time out.
- [ ] 2.3 Preserve bounded restart recovery for child exit and verified stuck-child conditions, including restart backoff or a restart-rate circuit breaker.
- [ ] 2.4 Add unit tests for busy probe timeout, idle probe failure, child exit, stuck request, recovery, and restart-rate suppression.

## 3. Proxy resilience

- [ ] 3.1 Configure and test LiteLLM deployment cooldown for connection failures and model startup windows.
- [ ] 3.2 Verify retries choose another eligible backend rather than repeatedly selecting the same restarting deployment.
- [ ] 3.3 Define the bounded unavailable response when all deployments are withdrawn; prevent retry amplification.

## 4. Observability and operations

- [ ] 4.1 Export backend state, state reason, in-flight requests, watchdog probe failures, child exits, restart decisions, restart suppression, and recovery duration.
- [ ] 4.2 Add alerts for restart-rate regression and HeartCode proxy 5xx caused by downstream connection failures.
- [ ] 4.3 Document diagnosis, canary rollout, fault injection, rollback, and operator recovery without logging request content or credentials.

## 5. Acceptance and rollout

- [ ] 5.1 Run sustained concurrent inference on a canary for at least five watchdog intervals with zero watchdog restarts while successful requests continue.
- [ ] 5.2 Inject a genuine llama.cpp child failure and verify withdrawal, bounded restart, readiness recovery, and successful proxy traffic afterward.
- [ ] 5.3 Roll out to all SFW backends and compare restart and proxy-5xx rates with the baseline over an agreed observation window.
- [ ] 5.4 Run `openspec validate prevent-load-induced-gpu-restarts --strict` and attach aggregate, secret-free acceptance evidence.
