## ADDED Requirements

### Requirement: Kokoro serves built-in and approved custom voices

The HeartCode speech runtime SHALL preserve all existing built-in Kokoro voices and SHALL additionally discover and synthesize only healthy active custom voice registry entries.

#### Scenario: Custom pack is only staged
- **WHEN** a public client lists voices or requests synthesis
- **THEN** the staged voice is absent from discovery and rejected by the ordinary speech endpoint

#### Scenario: Custom pack is active and healthy
- **WHEN** a public client lists voices and then requests synthesis with its stable ID
- **THEN** the ID is discoverable and synthesis uses the registry's exact active artifact digest

### Requirement: Custom voice lifecycle does not degrade live speech

Building, staging, activating, rolling back, retiring, reconciling, or deleting custom voices SHALL NOT change the existing speech authentication boundary, supported delivery formats, `opus-40k` live profile, or availability of unrelated voices.

#### Scenario: Voice build runs during live calls
- **WHEN** Quick Chat and character calls synthesize speech while an offline voice build is queued or executing
- **THEN** existing calls remain within the accepted latency/error budget and keep their requested output profile
