#!/usr/bin/env bash
# Scheduled wrapper around controlled_probe.sh (spec `heartcode-speech-runtime`,
# "GPU execution is verifiable"). Cron entry on PEA, as boss:
#
#   0 */12 * * * /home/boss/local-ai/gpu-server/speech/run_controlled_probe.sh
#
# Why scheduled: SpeechControlledProbeCorrelationMissing fires when the newest
# evidence file is over 24h old, but the probe was only ever run by hand at
# deploy time (OPERATIONS.md step 6). The metric went stale on 2026-09-04 and
# the alert fired continuously from then on. Twice a day keeps a comfortable
# margin under the 24h window.
#
# Secrets come from .speech-probe.env (gitignored, mode 600) next to the repo's
# other env files; see .speech-probe.env.example. Nothing here writes user
# content: the probe sends one fixed audio file and one fixed phrase.
set -euo pipefail

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
gpu_server="$repo_root/gpu-server"
env_file=${SPEECH_PROBE_ENV_FILE:-$gpu_server/.speech-probe.env}
log_file=${SPEECH_PROBE_LOG:-$gpu_server/speech/evidence/probe-runs.log}
keep=${SPEECH_PROBE_KEEP:-30}

log() { printf '%s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*" >> "$log_file"; }

if [ ! -r "$env_file" ]; then
  log "FAIL env file $env_file is missing or unreadable"
  exit 1
fi
set -a
# shellcheck disable=SC1090
. "$env_file"
set +a

export LITELLM_URL=${LITELLM_URL:-http://192.168.70.152:4000}
export SPEECH_DIRECT_URL=${SPEECH_DIRECT_URL:-http://192.168.70.144:8201}
export PROMETHEUS_URL=${PROMETHEUS_URL:-http://localhost:9099}
export EVIDENCE_DIR=${EVIDENCE_DIR:-$gpu_server/speech/evidence}

if output=$("$gpu_server/speech/controlled_probe.sh" 2>&1); then
  log "OK ${output##*$'\n'}"
  status=0
else
  status=$?
  # The probe prints no user content; its output is statuses and file paths.
  log "FAIL exit=$status ${output//$'\n'/ | }"
fi

# Bound the evidence directory: the metric only reads the newest file, and the
# meter bind-mounts this directory read-only.
# shellcheck disable=SC2012  # probe filenames are generated, no spaces/newlines
ls -t "$EVIDENCE_DIR"/speech-probe-*.json 2>/dev/null | tail -n +$((keep + 1)) | while read -r old; do
  rm -f "$old"
done

exit "$status"
