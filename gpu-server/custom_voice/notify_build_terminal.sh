#!/bin/sh
set -eu

job_id=${1:-}
case "$job_id" in
  *[!a-zA-Z0-9._-]*|'') echo 'notify_error=job_id_invalid'; exit 2 ;;
esac

private_root=${CUSTOM_VOICE_PRIVATE_ROOT:-/home/boss/local-ai/private}
webhook_file=${CUSTOM_VOICE_SLACK_ENV_FILE:-/home/boss/local-ai/gpu-server/.gpu-watchdog.env}
watch_log="$private_root/custom-voice-results/$job_id.watch.log"
marker="$private_root/custom-voice-results/$job_id.slack-notified"
interval=${CUSTOM_VOICE_NOTIFY_INTERVAL_SECONDS:-60}

if [ ! -f "$webhook_file" ]; then
  echo 'notify_error=webhook_not_configured'
  exit 1
fi
webhook=$(sed -n 's/^SLACK_WEBHOOK_URL=//p' "$webhook_file" | tail -n 1)
if [ -z "$webhook" ]; then
  echo 'notify_error=webhook_not_configured'
  exit 1
fi

while :; do
  if [ -f "$marker" ]; then
    echo 'notify_state=already_sent'
    exit 0
  fi
  if [ -f "$watch_log" ]; then
    line=$(tail -n 1 "$watch_log")
    reason=$(printf '%s\n' "$line" | sed -n 's/.* terminal_reason=\([^ ]*\).*/\1/p')
    if [ -n "$reason" ] && [ "$reason" != none ]; then
      if [ "$reason" = success ]; then
        outcome='completed successfully'
      else
        outcome="stopped with safe reason: $reason"
      fi
      payload=$(python3 -c 'import json,sys; print(json.dumps({"text": sys.argv[1]}))' \
        "Dima v2 custom-voice rerun on Pea $outcome. Job: $job_id")
      curl -fsS --max-time 15 -H 'Content-Type: application/json' --data-binary "$payload" "$webhook" >/dev/null
      umask 077
      : > "$marker"
      echo 'notify_state=sent'
      exit 0
    fi
  fi
  sleep "$interval"
done
