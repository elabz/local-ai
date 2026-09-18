## ADDED Requirements

### Requirement: Capacity loss is alerted per model group

Monitoring SHALL alert when, for any model group over a 1-hour window, requests were received and zero completions succeeded, and SHALL alert on deployment cooldown events and on 429/503 rates above a configured threshold. Alerts SHALL name the model group and deployment and contain no request content.

#### Scenario: Only deployment in cooldown loop
- **WHEN** a model group's sole deployment cycles through cooldown so that no request succeeds for an hour
- **THEN** an alert names the group and deployment within that hour
