#!/bin/sh
set -eu
umask 077

: "${CUSTOM_VOICE_JOB_ID:?set CUSTOM_VOICE_JOB_ID}"
: "${CUSTOM_VOICE_STABLE_ID:?set CUSTOM_VOICE_STABLE_ID}"
: "${CUSTOM_VOICE_VERSION:?set CUSTOM_VOICE_VERSION}"
: "${CUSTOM_VOICE_PRIVATE_ROOT:?set CUSTOM_VOICE_PRIVATE_ROOT}"
: "${CUSTOM_VOICE_WORKER_IMAGE:?set CUSTOM_VOICE_WORKER_IMAGE}"
: "${CUSTOM_VOICE_COMPAT_IMAGE:?set CUSTOM_VOICE_COMPAT_IMAGE}"
CUSTOM_VOICE_MIN_SIMILARITY=${CUSTOM_VOICE_MIN_SIMILARITY:-0.65}

result_root="$CUSTOM_VOICE_PRIVATE_ROOT/custom-voice-results/$CUSTOM_VOICE_JOB_ID"
workspace="$CUSTOM_VOICE_PRIVATE_ROOT/custom-voice-workspaces/$CUSTOM_VOICE_JOB_ID"
artifact_store="$CUSTOM_VOICE_PRIVATE_ROOT/custom-voice-artifacts"
preview_root="$CUSTOM_VOICE_PRIVATE_ROOT/custom-voice-previews"

for required in "$result_root/artifact.pt" "$result_root/result.json" "$workspace/build-plan.json"; do
  test -f "$required" && test ! -L "$required" || { echo '{"outcome":"failed","reason":"postbuild_input_missing"}'; exit 2; }
done
for output in "$result_root/compatibility.json" "$result_root/evaluation.json"; do
  test ! -e "$output" || { echo '{"outcome":"failed","reason":"postbuild_result_exists"}'; exit 2; }
done
mkdir -p "$artifact_store" "$preview_root"
chmod 700 "$artifact_store" "$preview_root"

python3 -m custom_voice.artifact \
  --artifact "$result_root/artifact.pt" \
  --build-result "$result_root/result.json" \
  --store "$artifact_store" \
  --stable-voice-id "$CUSTOM_VOICE_STABLE_ID" \
  --version "$CUSTOM_VOICE_VERSION" \
  --language a

version_root="$artifact_store/$CUSTOM_VOICE_STABLE_ID/$CUSTOM_VOICE_VERSION"
artifact_sha256=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["artifact"]["sha256"])' "$version_root/manifest.json")
sealed_artifact="$version_root/$artifact_sha256.pt"

docker run --rm \
  --user "$(id -u):$(id -g)" \
  --runtime nvidia \
  -e NVIDIA_VISIBLE_DEVICES=GPU-f417c539-26db-94e9-4c8f-c5a775291988 \
  --network none --read-only --cap-drop ALL --security-opt no-new-privileges \
  --memory 3g --memory-swap 3g --pids-limit 128 \
  --tmpfs /tmp:rw,noexec,nosuid,nodev,size=512m \
  -v "$version_root:/artifact:ro" \
  "$CUSTOM_VOICE_COMPAT_IMAGE" \
  --artifact "/artifact/$artifact_sha256.pt" --sha256 "$artifact_sha256" --language a \
  >"$result_root/compatibility.json"
chmod 600 "$result_root/compatibility.json"

docker run --rm \
  --user "$(id -u):$(id -g)" \
  --runtime nvidia \
  -e NVIDIA_VISIBLE_DEVICES=GPU-f417c539-26db-94e9-4c8f-c5a775291988 \
  --network gpu-server_gpu-network --read-only --cap-drop ALL --security-opt no-new-privileges \
  --memory 4g --memory-swap 4g --pids-limit 256 \
  --tmpfs /tmp:rw,noexec,nosuid,nodev,size=1g \
  -v "$version_root:/artifact:ro" \
  -v "$workspace:/workspace:ro" \
  -v "$preview_root:/previews:rw" \
  -v "$result_root:/reports:rw" \
  --entrypoint python3 "$CUSTOM_VOICE_WORKER_IMAGE" /opt/custom-voice/evaluator.py \
  --artifact "/artifact/$artifact_sha256.pt" --sha256 "$artifact_sha256" \
  --plan /workspace/build-plan.json --workspace /workspace \
  --preview-root /previews --asr-url http://speech-stt:8000/v1/audio/transcriptions \
  --min-similarity "$CUSTOM_VOICE_MIN_SIMILARITY" \
  --output /reports/evaluation.json

printf '{"outcome":"succeeded","artifact_sha256":"%s"}\n' "$artifact_sha256"
