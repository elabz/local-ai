#!/bin/sh
set -eu

: "${CUSTOM_VOICE_JOB_ID:?set CUSTOM_VOICE_JOB_ID}"
: "${CUSTOM_VOICE_PRIVATE_ROOT:?set CUSTOM_VOICE_PRIVATE_ROOT}"

case "$CUSTOM_VOICE_JOB_ID" in
  *[!a-zA-Z0-9._-]*|'') echo 'watch_error=job_id_invalid'; exit 2 ;;
esac

interval=${CUSTOM_VOICE_WATCH_INTERVAL_SECONDS:-60}
case "$interval" in *[!0-9]*|'') echo 'watch_error=interval_invalid'; exit 2 ;; esac
if [ "$interval" -lt 10 ] || [ "$interval" -gt 3600 ]; then
  echo 'watch_error=interval_invalid'
  exit 2
fi

container="custom-voice-build-$CUSTOM_VOICE_JOB_ID"
output="$CUSTOM_VOICE_PRIVATE_ROOT/custom-voice-results/$CUSTOM_VOICE_JOB_ID"
launch_log="$CUSTOM_VOICE_PRIVATE_ROOT/custom-voice-results/$CUSTOM_VOICE_JOB_ID.launch.log"

while :; do
  timestamp=$(date -u +%Y-%m-%dT%H:%M:%SZ)
  if docker ps --format '{{.Names}}' | grep -qx "$container"; then
    worker_state=running
    resources=$(docker stats --no-stream --format 'cpu={{.CPUPerc}} memory={{.MemUsage}}' "$container" 2>/dev/null || echo 'cpu=unavailable memory=unavailable')
  else
    worker_state=stopped
    resources='cpu=stopped memory=stopped'
  fi

  checkpoint=absent
  checkpoint_size=0
  checkpoint_mtime=0
  for candidate in "$output/checkpoint.v2.json" "$output/checkpoint.pt"; do
    if [ -f "$candidate" ]; then
      checkpoint=present
      checkpoint_size=$(stat -c %s "$candidate")
      checkpoint_mtime=$(stat -c %Y "$candidate")
      break
    fi
  done
  [ -f "$output/result.json" ] && result=present || result=absent
  [ -f "$output/artifact.pt" ] && artifact=present || artifact=absent
  if docker exec pea-speech-tts python3 -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8880/health',timeout=5)" >/dev/null 2>&1; then
    tts_health=healthy
  else
    tts_health=unhealthy
  fi

  terminal_reason=none
  if [ "$worker_state" = stopped ]; then
    if [ "$result" = present ] && [ "$artifact" = present ]; then
      terminal_reason=success
    elif [ -f "$launch_log" ]; then
      terminal_reason=$(grep -Eo 'worker_timeout|worker_cancelled|gpu_[a-z_]+|live_health_[a-z_]+|[a-z_]+_failed' "$launch_log" | tail -n 1 || true)
      [ -n "$terminal_reason" ] || terminal_reason=unknown_failure
    else
      terminal_reason=unknown_failure
    fi
  fi

  printf 'utc=%s worker=%s checkpoint=%s checkpoint_size=%s checkpoint_mtime=%s result=%s artifact=%s %s tts_health=%s terminal_reason=%s\n' \
    "$timestamp" "$worker_state" "$checkpoint" "$checkpoint_size" "$checkpoint_mtime" \
    "$result" "$artifact" "$resources" "$tts_health" "$terminal_reason"

  if [ "$worker_state" = stopped ]; then
    break
  fi
  sleep "$interval"
done
