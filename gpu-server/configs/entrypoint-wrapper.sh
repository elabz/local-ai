#!/bin/bash
# Wrapper entrypoint for LocalAI image generation server
# - Installs diffusers backend from gallery if not already present
# - Fixes permissions on generated images (diffusers creates files with 600)
# - Warmup: loads model into VRAM so first real request isn't slow

umask 022

# Install diffusers backend if not already installed
# Backend is persisted in /backends volume across restarts
if [ ! -d "/backends/cuda12-diffusers" ]; then
  echo "Installing cuda12-diffusers backend from gallery..."
  /local-ai backends install localai@cuda12-diffusers
  echo "Backend installation complete."
else
  echo "cuda12-diffusers backend already installed."
fi

# Start a background process to watch for new files and fix permissions
(
  while true; do
    find /tmp/generated -type f -mmin -1 -exec chmod 644 {} \; 2>/dev/null
    find /tmp/generated -type d -exec chmod 755 {} \; 2>/dev/null
    sleep 1
  done
) &

# Warmup: wait for LocalAI to be ready, then fire a dummy generation
# to load the model into VRAM. Runs in background so it doesn't block startup.
#
# Success means an image came back, not an HTTP 200: when the diffusers backend
# misses LocalAI's gRPC start deadline, LocalAI still answers 200 with no image.
# That happened on the 2026-10-10 reboot, when every container loaded at once on
# Pea's 2 cores. The model stayed unloaded, and the first avatar request paid
# the ~45 s load (97 s cold vs 52 s warm). So retry until a generation succeeds.
# A loaded model costs nothing at idle: the card sits in P8 at ~9 W either way.
(
  echo "[warmup] Waiting for LocalAI to be ready..."
  until curl -sf http://localhost:8080/readyz > /dev/null 2>&1; do sleep 2; done
  for attempt in $(seq 1 20); do
    echo "[warmup] attempt ${attempt}: sending warmup generation..."
    if curl -s --max-time 600 http://localhost:8080/v1/images/generations \
        -H "Content-Type: application/json" \
        -d '{"model":"heartcode-image","prompt":"warmup","size":"512x512"}' \
        | grep -q '"url":"http'; then
      echo "[warmup] Model loaded into VRAM, ready for requests."
      exit 0
    fi
    echo "[warmup] no image returned (backend not up yet); retrying in 30s"
    sleep 30
  done
  echo "[warmup] gave up after 20 attempts; the first real request will load the model"
) &

exec /entrypoint.sh "$@"
