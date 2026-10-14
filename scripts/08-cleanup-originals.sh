#!/bin/bash
# FINAL CLEANUP - removes the originals from /home/v.besozzi.
#
# ⚠ DESTRUCTIVE AND IRREVERSIBLE. Deletes ~51.5 GB.
#
# Run ONLY after scripts/07-verify-after-reboot.sh has passed. This script
# re-verifies every tree byte-for-byte immediately before deleting anything and
# aborts on the first mismatch, so a stale or partial copy cannot cause loss.
#
# Requires root (the files belong to v.besozzi):
#     sudo ./scripts/08-cleanup-originals.sh
#
# Add --yes to skip the confirmation prompt.
set -uo pipefail

REPO=/home/s.urso/Bright-2026-Comic-style-Storyteller
SRC_COMFY=/home/v.besozzi/Desktop/comfy_ui
SRC_HF=/home/v.besozzi/.cache/huggingface

[ "$(id -u)" -eq 0 ] || { echo "must run as root (sudo)"; exit 1; }

echo "### Re-verifying every tree before deleting anything"
verify() {
  printf '  %-22s ' "$1"
  out=$(rsync -rlptDn --checksum --itemize-changes --no-owner --no-group "$2" "$3" 2>&1)
  if [ -z "$out" ]; then echo "identical"; return 0; fi
  echo "MISMATCH"; echo "$out" | head -5; return 1
}

verify "comfyui/models"       "$SRC_COMFY/data/models/"       "$REPO/comfyui/models/"       || exit 1
verify "comfyui/custom_nodes" "$SRC_COMFY/data/custom_nodes/" "$REPO/comfyui/custom_nodes/" || exit 1
verify "comfyui/input"        "$SRC_COMFY/data/input/"        "$REPO/comfyui/input/"        || exit 1
verify "comfyui/output"       "$SRC_COMFY/data/output/"       "$REPO/comfyui/output/"       || exit 1
verify "hf-cache"             "$SRC_HF/"                      "$REPO/hf-cache/"             || exit 1

# The VRM asset lives alongside the build context, not under data/.
for f in "$SRC_COMFY"/*.vrm.glb; do
  [ -e "$f" ] || continue
  b=$(basename "$f")
  if cmp -s "$f" "$REPO/assets/vrm/$b"; then
    echo "  vrm asset            identical"
  else
    echo "  vrm asset            MISMATCH - aborting"; exit 1
  fi
done

echo "### All trees verified identical to the copies in the repo."

# Confirm no container still references the old paths.
echo "### Checking no running container still mounts these paths"
if docker ps -q | xargs -r docker inspect --format '{{range .Mounts}}{{.Source}}{{"\n"}}{{end}}' \
     | grep -qE 'besozzi|Desktop'; then
  echo "!! A running container still mounts a path under /home/v.besozzi."
  echo "!! Aborting - fix the stack before deleting."
  exit 1
fi
echo "  none - safe"

if [ "${1:-}" != "--yes" ]; then
  echo
  echo "About to permanently delete:"
  echo "    $SRC_HF                 (~44 G)"
  echo "    $SRC_COMFY/data         (~7.4 G)"
  echo "    $SRC_COMFY/*.vrm.glb    (~16 M)"
  echo
  printf 'Type DELETE to proceed: '
  read -r a
  [ "$a" = "DELETE" ] || { echo "aborted"; exit 1; }
fi

echo "### Deleting"
rm -rf "$SRC_HF"
rm -rf "$SRC_COMFY/data"
rm -f  "$SRC_COMFY"/*.vrm.glb
echo "  done"

echo
echo "### Kept deliberately (tiny, and they are the rollback path):"
echo "    $SRC_COMFY/Dockerfile"
echo "    $SRC_COMFY/docker-compose.yml"
echo "    /home/v.besozzi/Desktop/vllm/docker-compose.yaml"
echo "  Both are already copied into the repo. Delete them by hand once you are"
echo "  confident you will not need to roll back."
echo
echo "### Now revoke the read access that was granted for the migration:"
echo "    sudo chmod o-x /home/v.besozzi"
echo "    sudo setfacl -R -x u:s.urso /home/v.besozzi/Desktop/comfy_ui /home/v.besozzi/Desktop/vllm"
echo
df -h "$REPO" | tail -1
