#!/usr/bin/env bash
set -euo pipefail

# The canary knobs live in .env, which docker compose reads for interpolation
# but the shell does not. Import the ones this script branches on, so a value
# set in .env cannot silently fall back to the GPU 5 default and stop the wrong
# co-tenant.
if [ -f .env ]; then
  for key in SFW_CANARY_GPU_UUID SFW_CANARY_DISPLACE; do
    if [ -z "${!key:-}" ]; then
      value=$(sed -n "s/^${key}=//p" .env | tail -1)
      [ -n "$value" ] && export "$key=$value"
    fi
  done
fi

compose=(docker compose --env-file .env --env-file models.generated.env)
canary=(docker compose -f docker-compose.model-canaries.yml)

case "${1:-}" in
  start-sfw)
    # Free the card the canary is pinned to. By default that is GPU 5 and its
    # co-tenants; set SFW_CANARY_DISPLACE (with SFW_CANARY_GPU_UUID) to pin the
    # canary to another card, as GPU 5 is quarantined for the >7.6 GiB
    # generation-corruption fault recorded on 2026-09-04.
    if [ -n "${SFW_CANARY_DISPLACE:-}" ]; then
      # shellcheck disable=SC2086
      "${compose[@]}" stop ${SFW_CANARY_DISPLACE}
    else
      docker stop qwen3-canary-gpu5 pea-embed-5 >/dev/null 2>&1 || true
    fi
    "${canary[@]}" up -d sfw-model-canary
    ;;
  restore-sfw)
    "${canary[@]}" stop sfw-model-canary || true
    "${canary[@]}" rm -f sfw-model-canary || true
    # shellcheck disable=SC2086
    "${compose[@]}" up -d ${SFW_CANARY_DISPLACE:-embedding-server-5}
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
