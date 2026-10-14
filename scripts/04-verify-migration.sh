#!/bin/bash
# Verify every copied tree byte-for-byte against its source using rsync
# --checksum in dry-run mode. ANY output line for a tree means a mismatch.
# Nothing is written or deleted.
set -u
SRC_COMFY=/home/v.besozzi/Desktop/comfy_ui
SRC_HF=/home/v.besozzi/.cache/huggingface
REPO=/home/s.urso/Bright-2026-Comic-style-Storyteller
ST=$REPO/SillyTavern/docker
FAIL=0

check() { # name src dst
  printf '%-22s ' "$1"
  out=$(rsync -rlptDn --checksum --itemize-changes --no-owner --no-group "$2" "$3" 2>&1)
  if [ -z "$out" ]; then echo "OK (identical)"; else
    echo "MISMATCH:"; echo "$out" | head -10; FAIL=1
  fi
}

check "comfyui/models"   "$SRC_COMFY/data/models/"       "$REPO/comfyui/models/"
check "comfyui/custom_nodes" "$SRC_COMFY/data/custom_nodes/" "$REPO/comfyui/custom_nodes/"
check "comfyui/input"    "$SRC_COMFY/data/input/"        "$REPO/comfyui/input/"
check "comfyui/output"   "$SRC_COMFY/data/output/"       "$REPO/comfyui/output/"
check "comfyui/user"     "$REPO/RESCUE/comfyui_user/"    "$REPO/comfyui/user/"
for d in config data plugins extensions; do
  check "sillytavern/$d"  "$ST/$d/" "$REPO/sillytavern/$d/"
done
check "hf-cache"         "$SRC_HF/"                      "$REPO/hf-cache/"

echo
echo "### independent check: the rescued workflow"
sha256sum "$REPO/comfyui/user/default/workflows/Alice.json"
docker exec comfyui_dgx sha256sum /app/ComfyUI/user/default/workflows/Alice.json

echo
[ $FAIL -eq 0 ] && echo "### ALL TREES VERIFIED IDENTICAL" || echo "### !!! MISMATCHES FOUND - DO NOT DELETE ORIGINALS !!!"
exit $FAIL
