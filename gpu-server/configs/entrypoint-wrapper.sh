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
(
  echo "[warmup] Waiting for LocalAI to be ready..."
  for i in $(seq 1 120); do
    if curl -sf http://localhost:8080/readyz > /dev/null 2>&1; then
      echo "[warmup] LocalAI ready after ${i}s, sending warmup request..."
      curl -sf --max-time 300 http://localhost:8080/v1/images/generations \
        -H "Content-Type: application/json" \
        -d '{"model":"heartcode-image","prompt":"warmup","size":"512x512"}' > /dev/null 2>&1
      echo "[warmup] Model loaded into VRAM, ready for requests."
      break
    fi
    sleep 1
  done
) &

exec /entrypoint.sh "$@"
