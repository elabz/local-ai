#!/bin/sh
# Generate the exact SPDX SBOM for one sealed artifact inside the pinned worker
# image (its installed distributions are what the SBOM inventories) and write
# it beside the artifact, where activation verifies it. Prints sbom.py's JSON
# line: {"sbom_sha256", "package_count", "unresolved_license_count"}.
set -eu
umask 077

: "${CUSTOM_VOICE_STABLE_ID:?set CUSTOM_VOICE_STABLE_ID}"
: "${CUSTOM_VOICE_VERSION:?set CUSTOM_VOICE_VERSION}"
: "${CUSTOM_VOICE_ARTIFACT_SHA256:?set CUSTOM_VOICE_ARTIFACT_SHA256}"
: "${CUSTOM_VOICE_PRIVATE_ROOT:?set CUSTOM_VOICE_PRIVATE_ROOT}"
: "${CUSTOM_VOICE_WORKER_IMAGE:?set CUSTOM_VOICE_WORKER_IMAGE}"
: "${CUSTOM_VOICE_WORKER_IMAGE_DIGEST:?set CUSTOM_VOICE_WORKER_IMAGE_DIGEST}"
: "${CUSTOM_VOICE_RUNTIME_IMAGE:?set CUSTOM_VOICE_RUNTIME_IMAGE}"

version_root="$CUSTOM_VOICE_PRIVATE_ROOT/custom-voice-artifacts/$CUSTOM_VOICE_STABLE_ID/$CUSTOM_VOICE_VERSION"
test -d "$version_root" && test ! -L "$version_root" || { echo '{"outcome":"failed","reason":"sbom_artifact_missing"}'; exit 2; }
test ! -e "$version_root/sbom.spdx.json" || { echo '{"outcome":"failed","reason":"sbom_exists"}'; exit 2; }

exec docker run --rm \
  --user "$(id -u):$(id -g)" \
  --network none --read-only --cap-drop ALL --security-opt no-new-privileges \
  --memory 1g --memory-swap 1g --pids-limit 64 \
  --tmpfs /tmp:rw,noexec,nosuid,nodev,size=64m \
  -v "$version_root:/artifact:rw" \
  --entrypoint python3 "$CUSTOM_VOICE_WORKER_IMAGE" /opt/custom-voice/sbom.py \
  --artifact-sha256 "$CUSTOM_VOICE_ARTIFACT_SHA256" \
  --worker-image-digest "$CUSTOM_VOICE_WORKER_IMAGE_DIGEST" \
  --runtime-image "$CUSTOM_VOICE_RUNTIME_IMAGE" \
  --output /artifact/sbom.spdx.json
