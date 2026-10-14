#!/bin/bash
# READ-ONLY recon of /home/v.besozzi. Writes nothing, deletes nothing.
# Output is captured so Claude can plan the migration.
set -u
OUT=/home/s.urso/Bright-2026-Comic-style-Storyteller/RESCUE/besozzi-recon.txt
{
  echo "### comfy_ui build context (top level)"
  ls -la /home/v.besozzi/Desktop/comfy_ui/

  echo; echo "### Dockerfile(s) found"
  find /home/v.besozzi/Desktop/comfy_ui -maxdepth 2 -iname 'Dockerfile*' -o -maxdepth 2 -iname '*.yml' -o -maxdepth 2 -iname '*.yaml' -o -maxdepth 2 -iname '*.txt' -o -maxdepth 2 -iname '*.sh' 2>/dev/null

  echo; echo "### docker-compose.yml contents"
  cat /home/v.besozzi/Desktop/comfy_ui/docker-compose.yml 2>&1

  echo; echo "### Dockerfile contents"
  cat /home/v.besozzi/Desktop/comfy_ui/Dockerfile 2>&1

  echo; echo "### sizes to migrate"
  du -sh /home/v.besozzi/.cache/huggingface \
         /home/v.besozzi/Desktop/comfy_ui/data/models \
         /home/v.besozzi/Desktop/comfy_ui/data/custom_nodes \
         /home/v.besozzi/Desktop/comfy_ui/data/input \
         /home/v.besozzi/Desktop/comfy_ui/data/output 2>&1

  echo; echo "### anything else under Desktop?"
  ls -la /home/v.besozzi/Desktop/ 2>&1

  echo; echo "### ownership/uids"
  id v.besozzi 2>&1; id deepspace 2>&1; id s.urso 2>&1
} > "$OUT" 2>&1
chown s.urso:s.urso "$OUT"
echo "Wrote $OUT ($(wc -l < "$OUT") lines)"
