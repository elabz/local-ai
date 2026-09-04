#!/bin/sh
set -eu

: "${CUSTOM_VOICE_JOB_ID:?set CUSTOM_VOICE_JOB_ID}"
: "${CUSTOM_VOICE_WORKER_IMAGE:?set CUSTOM_VOICE_WORKER_IMAGE}"
: "${CUSTOM_VOICE_WORKER_IMAGE_DIGEST:?set CUSTOM_VOICE_WORKER_IMAGE_DIGEST}"
: "${CUSTOM_VOICE_PRIVATE_ROOT:?set CUSTOM_VOICE_PRIVATE_ROOT}"

case "$CUSTOM_VOICE_JOB_ID" in
  *[!a-zA-Z0-9._-]*|'') echo '{"outcome":"failed","reason":"job_id_invalid"}'; exit 2 ;;
esac
case "$CUSTOM_VOICE_WORKER_IMAGE_DIGEST" in
  *[!0-9a-f]*|'') echo '{"outcome":"failed","reason":"worker_image_digest_invalid"}'; exit 2 ;;
esac
if [ "${#CUSTOM_VOICE_WORKER_IMAGE_DIGEST}" -ne 64 ]; then
  echo '{"outcome":"failed","reason":"worker_image_digest_invalid"}'
  exit 2
fi

actual_image_digest=$(docker image inspect --format '{{.Id}}' "$CUSTOM_VOICE_WORKER_IMAGE" 2>/dev/null || true)
actual_image_digest=${actual_image_digest#sha256:}
if [ "$actual_image_digest" != "$CUSTOM_VOICE_WORKER_IMAGE_DIGEST" ]; then
  echo '{"outcome":"failed","reason":"worker_image_digest_mismatch"}'
  exit 2
fi

for directory in \
  custom-voice-intake \
  custom-voice-workspaces \
  custom-voice-results \
  custom-voice-cache \
  custom-voice-locks
do
  path="$CUSTOM_VOICE_PRIVATE_ROOT/$directory"
  if [ ! -d "$path" ] || [ -L "$path" ]; then
    echo '{"outcome":"failed","reason":"private_root_invalid"}'
    exit 2
  fi
done

if [ "${CUSTOM_VOICE_PREFLIGHT_ONLY:-0}" = "1" ]; then
  printf '{"outcome":"ready","job_id":"%s","worker_image_digest":"%s"}\n' \
    "$CUSTOM_VOICE_JOB_ID" "$actual_image_digest"
  exit 0
fi

exec docker run --rm \
  --name "custom-voice-build-$CUSTOM_VOICE_JOB_ID" \
  --user "$(id -u):$(id -g)" \
  --runtime nvidia \
  --cpus 2 \
  --memory 4g \
  --memory-swap 4g \
  --pids-limit 256 \
  --read-only \
  --cap-drop ALL \
  --security-opt no-new-privileges \
  --stop-timeout 30 \
  --network gpu-server_gpu-network \
  --tmpfs /tmp:rw,noexec,nosuid,nodev,size=1g \
  -e NVIDIA_VISIBLE_DEVICES=GPU-f417c539-26db-94e9-4c8f-c5a775291988 \
  -e HOME=/data/custom-voice-cache \
  -e CUSTOM_VOICE_GPU_LOCK=/data/custom-voice-locks/speech-gpu.lock \
  -e CUSTOM_VOICE_LIVE_HEALTH_URL=http://speech-tts:8880/health \
  -e CUSTOM_VOICE_LIVE_ACTIVITY_URL=http://speech-meter:8080/internal/activity \
  -e CUSTOM_VOICE_WORKER_IMAGE_DIGEST="$CUSTOM_VOICE_WORKER_IMAGE_DIGEST" \
  -v "$CUSTOM_VOICE_PRIVATE_ROOT/custom-voice-intake:/data/custom-voice-intake:ro" \
  -v "$CUSTOM_VOICE_PRIVATE_ROOT/custom-voice-workspaces:/data/custom-voice-workspaces:rw" \
  -v "$CUSTOM_VOICE_PRIVATE_ROOT/custom-voice-results:/data/custom-voice-results:rw" \
  -v "$CUSTOM_VOICE_PRIVATE_ROOT/custom-voice-cache:/data/custom-voice-cache:rw" \
  -v "$CUSTOM_VOICE_PRIVATE_ROOT/custom-voice-locks:/data/custom-voice-locks:rw" \
  "$CUSTOM_VOICE_WORKER_IMAGE" \
  --plan "/data/custom-voice-workspaces/$CUSTOM_VOICE_JOB_ID/build-plan.json" \
  --workspace "/data/custom-voice-workspaces/$CUSTOM_VOICE_JOB_ID" \
  --output "/data/custom-voice-results/$CUSTOM_VOICE_JOB_ID"
