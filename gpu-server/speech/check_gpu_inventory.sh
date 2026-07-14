#!/usr/bin/env bash
set -euo pipefail

expected_uuid="${SPEECH_GPU_UUID:-GPU-f417c539-26db-94e9-4c8f-c5a775291988}"
expected_index="${SPEECH_GPU_PHYSICAL_INDEX_ZERO_BASED:-6}"
display_slot="${SPEECH_GPU_DISPLAY_SLOT_ONE_BASED:-7}"

actual_index="$({ nvidia-smi --query-gpu=index,uuid --format=csv,noheader,nounits || true; } \
  | awk -F ', *' -v uuid="$expected_uuid" '$2 == uuid { print $1; exit }')"

if [[ -z "$actual_index" ]]; then
  echo "speech GPU UUID not discovered: $expected_uuid" >&2
  exit 2
fi

printf 'speech_gpu_uuid=%s physical_index_zero_based=%s display_slot_one_based=%s\n' \
  "$expected_uuid" "$actual_index" "$display_slot"

if [[ "$actual_index" != "$expected_index" ]]; then
  echo "speech GPU inventory mismatch: expected physical index $expected_index, discovered $actual_index" >&2
  exit 1
fi
