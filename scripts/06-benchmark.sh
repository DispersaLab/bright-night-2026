#!/bin/bash
# Benchmark the running vLLM. Same prompt/params as the baseline in
# RESCUE/benchmark-before.txt so the two are directly comparable.
# Read-only: issues chat completions, changes nothing.
set -u
cd /home/s.urso/Bright-2026-Comic-style-Storyteller
[ -f .env ] && . ./.env
M="${VLLM_MODEL:-AEON-7/Qwen3.6-35B-A3B-heretic-NVFP4}"
P="${VLLM_PORT:-8001}"
LABEL="${1:-after}"
OUT="RESCUE/benchmark-${LABEL}.txt"

{
echo "# vLLM benchmark (${LABEL})"
echo "# date: $(date -Is)"
echo "# model: $M"
echo "# args: $(docker inspect vllm_qwen_optimized --format '{{join .Config.Cmd " "}}' 2>/dev/null)"
echo "# host mem: $(free -g | awk '/Mem:/{print $3"G used / "$2"G total, "$7"G available"}')"
echo

TOT=0
for i in 1 2 3; do
  S=$(date +%s.%N)
  R=$(curl -s "http://localhost:$P/v1/chat/completions" -H 'Content-Type: application/json' \
    -d '{"model":"'"$M"'","messages":[{"role":"user","content":"Conta da 1 a 50."}],"max_tokens":512,"temperature":0,"chat_template_kwargs":{"enable_thinking":false}}')
  E=$(date +%s.%N)
  W=$(echo "$E - $S" | bc)
  C=$(echo "$R" | python3 -c 'import sys,json;print(json.load(sys.stdin)["usage"]["completion_tokens"])' 2>/dev/null || echo 0)
  if [ "$C" -gt 0 ] 2>/dev/null; then
    TS=$(echo "scale=2; $C / $W" | bc)
    echo "run $i: ${C} tokens in ${W}s = ${TS} tok/s"
    TOT=$(echo "$TOT + $TS" | bc)
  else
    echo "run $i: FAILED"; echo "$R" | head -3
  fi
done
echo
echo "mean: $(echo "scale=2; $TOT / 3" | bc) tok/s"
echo
echo "# vLLM KV cache allocation this boot:"
docker logs vllm_qwen_optimized 2>&1 | grep -E 'Available KV cache memory|GPU KV cache size|Model loading took' | tail -5
} | tee "$OUT"

echo
echo "written to $OUT"
