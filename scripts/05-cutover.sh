#!/bin/bash
# CUTOVER: replace the three ad-hoc containers with the repo's compose stack.
#
# DESTRUCTIVE: removes the existing containers. Their writable layers are lost.
# That is safe ONLY because:
#   - /app/ComfyUI/user was rescued and verified (sha256) -> comfyui/user/
#   - all other stateful paths are bind mounts, which survive
#
# Does NOT touch: any data in the repo, the originals in /home/v.besozzi,
# the ComfyUI image (tagged twice, so neither tag removal deletes it),
# or Portainer.
#
# ROLLBACK: the old compose files still exist at
#   /home/v.besozzi/Desktop/vllm/docker-compose.yaml
#   /home/v.besozzi/Desktop/comfy_ui/docker-compose.yml
#   ./SillyTavern/docker/docker-compose.yml
set -euo pipefail
cd /home/s.urso/Bright-2026-Comic-style-Storyteller

echo "### 1. Stop SillyTavern first - it writes chat data continuously"
docker stop sillytavern

echo "### 2. Re-sync its data now that writes have stopped"
# --delete so the copy is an exact mirror, not a union with stale files.
# Safe: the destination was created by us and holds no unique data.
rsync -a --no-owner --no-group --delete \
      SillyTavern/docker/data/ sillytavern/data/
rsync -a --no-owner --no-group \
      SillyTavern/docker/config/ sillytavern/config/
echo "    re-synced"

echo "### 3. Stop the GPU services"
docker stop vllm_qwen_optimized comfyui_dgx

echo "### 4. Snapshot the old container configs before removing them"
for c in vllm_qwen_optimized comfyui_dgx sillytavern; do
  docker inspect "$c" > "RESCUE/old-container-$c.json"
done
echo "    saved to RESCUE/old-container-*.json"

echo "### 5. Remove the old containers"
docker rm vllm_qwen_optimized comfyui_dgx sillytavern

echo "### 6. Bring up the new stack"
docker compose up -d

echo "### 7. Wait for health (vLLM cold start is ~5.5 min)"
for i in $(seq 1 40); do
  sleep 15
  s=$(docker compose ps --format '{{.Name}} {{.Status}}' 2>/dev/null)
  echo "--- $((i*15))s ---"; echo "$s"
  if echo "$s" | grep -q unhealthy; then echo "!! unhealthy - stopping wait"; break; fi
  if [ "$(echo "$s" | grep -c healthy)" -ge 2 ]; then echo "services healthy"; break; fi
done

echo "### 8. Verify the rescued workflow survived the recreation"
ls -la comfyui/user/default/workflows/
docker exec comfyui_dgx ls -la /app/ComfyUI/user/default/workflows/

echo "### 9. Endpoints"
curl -sf -o /dev/null -w 'vLLM  /health       -> %{http_code}\n' http://localhost:8001/health || echo "vLLM not ready"
curl -sf -o /dev/null -w 'Comfy /system_stats -> %{http_code}\n' http://localhost:8188/system_stats || echo "Comfy not ready"
curl -sf -o /dev/null -w 'ST    /             -> %{http_code}\n' http://localhost:8010/ || echo "ST not ready"

echo "### CUTOVER COMPLETE"
