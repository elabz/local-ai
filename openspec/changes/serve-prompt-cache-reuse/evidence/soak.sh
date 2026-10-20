#!/usr/bin/env bash
# serve-prompt-cache-reuse 3.3: 24-hour soak of both chat routes at 8K.
#
# Rounds of append-only conversations (load-tests/prompt_cache_conversations.py)
# run on SFW and NSFW at the same time until DURATION has passed. Each round
# writes one bundle per route. Pacing stays well under the groups' LiteLLM
# limits (SFW 50k tpm, NSFW 38k tpm) so real traffic is not starved:
#   SFW  2 conversations at a time, 30 s think time (~3 turns/min, ~15k tpm)
#   NSFW 3 conversations at a time, 45 s think time (~3 turns/min, ~20k tpm);
#        three sessions keep the two-slot NSFW workers alternating.
#
# Usage (detached; the key is read from the environment, never logged):
#   LITELLM_KEY=sk-... nohup caffeinate -i bash soak.sh OUT_DIR > OUT_DIR/soak.log 2>&1 &
set -u
OUT=${1:?output directory}
DURATION=${DURATION:-86400}
HERE=$(cd "$(dirname "$0")" && pwd)
DRIVER="$HERE/../../../../load-tests/prompt_cache_conversations.py"
mkdir -p "$OUT"
start=$(date +%s)
echo "soak start $(date -u +%FT%TZ) duration=${DURATION}s"
round=0
while [ $(( $(date +%s) - start )) -lt "$DURATION" ]; do
  round=$((round + 1))
  seed="soak-$(date -u +%Y%m%d%H%M)-r$round"
  echo "round $round seed=$seed $(date -u +%FT%TZ)"
  python3 "$DRIVER" --model heartcode-chat-sfw --conversations 4 --parallel 2 --turns 40 \
    --think-seconds 30 --sample-seconds 30 --seed "$seed" \
    --output "$OUT/round-$round-sfw.json" > "$OUT/round-$round-sfw.log" 2>&1 &
  sfw=$!
  python3 "$DRIVER" --model heartcode-chat-nsfw --conversations 6 --parallel 3 --turns 40 \
    --think-seconds 45 --sample-seconds 30 --seed "$seed" \
    --output "$OUT/round-$round-nsfw.json" > "$OUT/round-$round-nsfw.log" 2>&1 &
  nsfw=$!
  wait $sfw; s=$?
  wait $nsfw; n=$?
  echo "round $round done sfw=$s nsfw=$n $(date -u +%FT%TZ)"
done
echo "soak end $(date -u +%FT%TZ) rounds=$round"
