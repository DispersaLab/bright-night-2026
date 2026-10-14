#!/bin/bash
# Post-reboot verification. Read-only: starts nothing, changes nothing.
# Run this after the box comes back up. Exit 0 = everything survived.
cd /home/s.urso/Bright-2026-Comic-style-Storyteller
FAIL=0
ok()   { printf '  \033[32mPASS\033[0m  %s\n' "$1"; }
bad()  { printf '  \033[31mFAIL\033[0m  %s\n' "$1"; FAIL=1; }

echo "=== 1. Containers came back on their own ==="
for c in vllm_qwen_optimized comfyui_dgx sillytavern portainer; do
  s=$(docker inspect "$c" --format '{{.State.Status}}' 2>/dev/null || echo missing)
  [ "$s" = "running" ] && ok "$c is running" || bad "$c is '$s'"
done

echo "=== 2. Health ==="
for c in vllm_qwen_optimized comfyui_dgx sillytavern; do
  h=$(docker inspect "$c" --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' 2>/dev/null)
  [ "$h" = "healthy" ] && ok "$c healthy" || bad "$c health='$h'"
done

echo "=== 3. Endpoints ==="
check_ep() {
  code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 "$2")
  [ "$code" = "200" ] && ok "$1 -> 200" || bad "$1 -> $code"
}
check_ep "vLLM  /health"       http://localhost:8001/health
check_ep "Comfy /system_stats" http://localhost:8188/system_stats
check_ep "ST    /"             http://localhost:8010/

echo "=== 4. THE ACTUAL PROOF: rescued workflows survived ==="
# On the host
if [ -f comfyui/user/default/workflows/Alice.json ]; then
  ok "Alice.json present on host"
else
  bad "Alice.json MISSING on host"
fi
# And visible inside the recreated container, via the bind mount
if docker exec comfyui_dgx test -f /app/ComfyUI/user/default/workflows/Alice.json 2>/dev/null; then
  ok "Alice.json visible inside the container"
  h1=$(sha256sum comfyui/user/default/workflows/Alice.json | cut -d' ' -f1)
  h2=$(docker exec comfyui_dgx sha256sum /app/ComfyUI/user/default/workflows/Alice.json | cut -d' ' -f1)
  [ "$h1" = "$h2" ] && ok "checksums match ($h1)" || bad "checksum mismatch"
else
  bad "Alice.json NOT visible in container - the mount did not come back"
fi

echo "=== 5. No user-home paths in any mount ==="
if docker inspect vllm_qwen_optimized comfyui_dgx sillytavern \
     --format '{{range .Mounts}}{{.Source}}{{"\n"}}{{end}}' | grep -qE 'besozzi|Desktop'; then
  bad "a mount still points into a user home"
else
  ok "all mounts are inside the repo"
fi

echo
if [ $FAIL -eq 0 ]; then
  echo "### ALL CHECKS PASSED - the stack survived the reboot."
  echo "### It is now safe to run scripts/08-cleanup-originals.sh"
else
  echo "### SOMETHING FAILED - do NOT delete the originals yet."
fi
exit $FAIL
