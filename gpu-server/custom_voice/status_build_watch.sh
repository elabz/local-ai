#!/bin/sh
set -eu

job_id=${1:-}
case "$job_id" in
  *[!a-zA-Z0-9._-]*|'') echo 'status_error=job_id_invalid'; exit 2 ;;
esac

root=${CUSTOM_VOICE_PRIVATE_ROOT:-/home/boss/local-ai/private}
log="$root/custom-voice-results/$job_id.watch.log"
if [ ! -f "$log" ]; then
  echo 'status_error=watch_not_found'
  exit 1
fi
tail -n "${CUSTOM_VOICE_STATUS_LINES:-10}" "$log"
