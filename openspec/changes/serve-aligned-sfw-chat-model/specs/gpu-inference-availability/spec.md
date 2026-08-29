# gpu-inference-availability — Delta

## ADDED Requirements

### Requirement: The SFW chat pool serves a model that declines explicit content

Because the calling application performs no content filtering of its own, the weight loaded by the `heartcode-chat-sfw` pool is an access control rather than only a quality choice. The pool SHALL serve a model measured to decline explicit sexual content under the calling application's production system prompt, and the NSFW pool SHALL serve a model that does not refuse it for authorized callers. Refusal SHALL be measured with the deployed immersion prompt, an in-character persona, the caller's tone contract for an unauthorized user, and the production sampler — never from a bare prompt, which has been measured to produce the opposite verdict for the same weight. The measurement SHALL be taken before the weight is promoted into the pool, and repeated whenever the pool's occupant changes.

#### Scenario: Candidate measured before promotion
- **WHEN** a new weight is proposed for the SFW pool
- **THEN** it is loaded on a canary slot and measured in role first, and it is promoted only if it declines

#### Scenario: Bare-prompt result is not accepted as evidence
- **WHEN** a candidate's refusal behaviour is evidenced only by a probe without the production system prompt
- **THEN** the evidence is rejected and the in-role measurement is required, because the deployed immersion prompt has been measured to override a model's alignment

#### Scenario: Occupant changes
- **WHEN** the SFW pool's loaded weight is replaced or rolled back
- **THEN** refusal behaviour is re-measured on the production route and recorded before the route is relied upon

#### Scenario: NSFW pool is not made to refuse
- **WHEN** the NSFW pool's occupant is measured under an authorized caller's conditions
- **THEN** it does not decline, and a candidate that refuses is rejected for that pool

### Requirement: Pool occupancy changes preserve throughput and are reversible

A change of pool occupant SHALL record generated-token throughput measured cold and warm as separate figures, because prompt-cache reuse makes a single repeated-prompt measurement report generation speed only. The previous weight SHALL remain on disk so the change can be reversed, and the proxy SHALL be updated by targeted edit of the affected model entries rather than by replacing its configuration file, which carries live entries absent from this repository.

#### Scenario: Throughput recorded on both paths
- **WHEN** a candidate's throughput is measured
- **THEN** the first run of a series is recorded as the cold figure and later runs as warm, and both are reported

#### Scenario: Proxy updated without collateral loss
- **WHEN** the proxy is pointed at a new weight
- **THEN** only the affected model entries are edited in place, and canary, speech, and tuning entries survive the change

#### Scenario: Rollback available
- **WHEN** a promoted weight must be withdrawn
- **THEN** the previous weight is still present on disk and can be restored by reversing the path and proxy changes
