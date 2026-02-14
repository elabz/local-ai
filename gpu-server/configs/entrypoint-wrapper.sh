#!/bin/bash
# Wrapper entrypoint for LocalAI image generation server
# - Installs diffusers backend from gallery if not already present
# - Fixes permissions on generated images (diffusers creates files with 600)

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

exec /entrypoint.sh "$@"
