#!/usr/bin/env bash
set -euo pipefail

: "${AUDIO_FILE:?set AUDIO_FILE to a non-sensitive WAV used only for this probe}"
: "${LITELLM_URL:?set LITELLM_URL, for example http://192.168.0.152:4000}"
: "${LITELLM_API_KEY:?set LITELLM_API_KEY}"
: "${LITELLM_ADMIN_KEY:?set LITELLM_ADMIN_KEY for the accounting verification API}"
: "${SPEECH_DIRECT_URL:?set SPEECH_DIRECT_URL, for example http://192.168.0.144:8201}"
: "${SPEECH_DIRECT_API_KEY:?set SPEECH_DIRECT_API_KEY}"
PROMETHEUS_URL=${PROMETHEUS_URL:-http://localhost:9099}
EXPECTED_GPU_UUID=${EXPECTED_GPU_UUID:-GPU-f417c539-26db-94e9-4c8f-c5a775291988}
EVIDENCE_DIR=${EVIDENCE_DIR:-./speech/evidence}
SPEECH_TTS_ENCODING_PROFILE=${SPEECH_TTS_ENCODING_PROFILE:-opus-40k}
mkdir -p "$EVIDENCE_DIR"

request_id="speech-probe-$(date -u +%Y%m%dT%H%M%SZ)-$RANDOM"
call_id="controlled-$RANDOM"
turn_id="turn-1"
started=$(date -u +%Y-%m-%dT%H:%M:%SZ)
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT

prom() { curl -fsS --get "$PROMETHEUS_URL/api/v1/query" --data-urlencode "query=$1"; }
before=$(prom 'sum(speech_requests_total)' | jq -r '.data.result[0].value[1] // "0"')
util_before=$(prom "speech_gpu_utilization_percent{gpu_uuid=\"$EXPECTED_GPU_UUID\"}" | jq -r '.data.result[0].value[1] // "0"')

stt_status=$(curl -sS -D "$tmp/stt.headers" -o "$tmp/stt.json" -w '%{http_code}' "$LITELLM_URL/v1/audio/transcriptions" \
  -H "Authorization: Bearer $LITELLM_API_KEY" -H "X-Speech-Request-ID: $request_id-stt" \
  -H "X-Call-ID: $call_id" -H "X-Turn-ID: $turn_id" \
  -F model=heartcode-stt -F "file=@$AUDIO_FILE")
tts_status=$(curl -sS -o "$tmp/tts.audio" -w '%{http_code}' "$SPEECH_DIRECT_URL/v1/audio/speech" \
  -H "Authorization: Bearer $SPEECH_DIRECT_API_KEY" -H 'Content-Type: application/json' \
  -H "X-Speech-Request-ID: $request_id-tts" -H "X-Call-ID: $call_id" -H "X-Turn-ID: $turn_id" \
  --data "{\"model\":\"kokoro\",\"voice\":\"af_heart\",\"input\":\"Controlled operations probe.\",\"response_format\":\"opus\",\"encoding_profile\":\"$SPEECH_TTS_ENCODING_PROFILE\"}")
tts_magic=$(od -An -N4 -tx1 "$tmp/tts.audio" | tr -d ' \n')
after=$before
for _ in 1 2 3 4 5 6; do
  after=$(prom 'sum(speech_requests_total)' | jq -r '.data.result[0].value[1] // "0"')
  awk "BEGIN { exit !($after > $before) }" && break
  sleep 5
done
gpu=$(prom "speech_gpu_inventory_info{gpu_uuid=\"$EXPECTED_GPU_UUID\"}")
memory=$(prom "sum(speech_gpu_process_memory_bytes{gpu_uuid=\"$EXPECTED_GPU_UUID\"})" | jq -r '.data.result[0].value[1] // "0"')
util_after=$(prom "speech_gpu_utilization_percent{gpu_uuid=\"$EXPECTED_GPU_UUID\"}" | jq -r '.data.result[0].value[1] // "0"')
log_hits=$(docker logs --since "$started" pea-speech-meter 2>&1 | grep -c "$request_id" || true)
litellm_call_id=$(awk -F': ' 'tolower($1)=="x-litellm-call-id" {gsub("\\r", "", $2); print $2}' "$tmp/stt.headers" | tail -1)
accounting_hits=0
for _ in 1 2 3 4 5 6; do
  accounting_hits=$(curl -fsS --get "$LITELLM_URL/spend/logs" -H "Authorization: Bearer $LITELLM_ADMIN_KEY" \
    --data-urlencode "request_id=$litellm_call_id" --data-urlencode "summarize=false" | jq 'if type=="array" then length else 0 end' 2>/dev/null || echo 0)
  [ "$accounting_hits" -ge 1 ] && break
  sleep 5
done

jq -n --arg timestamp "$started" --arg request_id "$request_id" --arg call_id "$call_id" \
  --arg stt_status "$stt_status" --arg tts_status "$tts_status" --arg before "$before" --arg after "$after" \
  --arg memory "$memory" --arg util_before "$util_before" --arg util_after "$util_after" \
  --arg litellm_call_id "$litellm_call_id" --arg tts_profile "$SPEECH_TTS_ENCODING_PROFILE" --arg tts_magic "$tts_magic" --argjson log_hits "$log_hits" --argjson accounting_hits "$accounting_hits" --argjson gpu "$gpu" \
  '{timestamp:$timestamp,request_id:$request_id,call_id:$call_id,litellm_call_id:$litellm_call_id,status:{stt:($stt_status|tonumber),tts:($tts_status|tonumber)},tts:{encoding_profile:$tts_profile,ogg_signature_valid:($tts_magic=="4f676753")},correlation:{meter_log_hits:$log_hits,accounting_rows:$accounting_hits},metrics:{requests_before:($before|tonumber),requests_after:($after|tonumber),gpu_memory_bytes:($memory|tonumber),gpu_utilization_before:($util_before|tonumber),gpu_utilization_after:($util_after|tonumber)},gpu_query:$gpu}' \
  > "$EVIDENCE_DIR/$request_id.json"

jq -e '.status.stt < 300 and .status.tts < 300 and .tts.ogg_signature_valid and .correlation.meter_log_hits >= 2 and .correlation.accounting_rows >= 1 and .metrics.requests_after > .metrics.requests_before and .metrics.gpu_memory_bytes > 0 and (.gpu_query.data.result|length) > 0' "$EVIDENCE_DIR/$request_id.json" >/dev/null
echo "controlled speech probe passed; sanitized evidence: $EVIDENCE_DIR/$request_id.json"
