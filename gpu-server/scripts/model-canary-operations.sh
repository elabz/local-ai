#!/usr/bin/env bash
set -euo pipefail

compose=(docker compose --env-file .env --env-file models.generated.env)
canary=(docker compose -f docker-compose.model-canaries.yml)

case "${1:-}" in
  start-sfw)
    docker stop qwen3-canary-gpu5 pea-embed-5 >/dev/null 2>&1 || true
    "${canary[@]}" up -d sfw-model-canary
    ;;
  restore-sfw)
    "${canary[@]}" stop sfw-model-canary || true
    "${canary[@]}" rm -f sfw-model-canary || true
    "${compose[@]}" up -d embedding-server-5
    ;;
  start-nsfw)
    "${compose[@]}" stop gpu-server-6 dino-embed-2
    "${canary[@]}" up -d nsfw-model-canary
    ;;
  restore-nsfw)
    "${canary[@]}" stop nsfw-model-canary || true
    "${canary[@]}" rm -f nsfw-model-canary || true
    "${compose[@]}" up -d gpu-server-6 dino-embed-2
    ;;
  status)
    docker ps --format '{{.Names}}\t{{.Status}}' | \
      grep -E 'pea-(sfw|nsfw)-model-canary|pea-gpu-4|pea-embed-4|pea-embed-5|pea-gpu-6|pea-embed-dino-[12]' || true
    ;;
  *)
    echo "usage: $0 {start-sfw|restore-sfw|start-nsfw|restore-nsfw|status}" >&2
    exit 2
    ;;
esac
