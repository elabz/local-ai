#!/bin/bash
# Wrapper entrypoint that ensures generated images are world-readable
# The diffusers library creates files with 600 permissions regardless of umask,
# so we use a background watcher to fix permissions immediately

umask 022

# Start a background process to watch for new files and fix permissions
(
  while true; do
    # Find files created in the last minute and fix permissions
    find /tmp/generated -type f -mmin -1 -exec chmod 644 {} \; 2>/dev/null
    find /tmp/generated -type d -exec chmod 755 {} \; 2>/dev/null
    sleep 1
  done
) &

exec /entrypoint.sh "$@"
