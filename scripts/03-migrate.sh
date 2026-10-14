#!/bin/bash
# Copy all stack data into the repo. COPIES ONLY - deletes nothing.
# Originals are left untouched for a separate, explicitly-approved cleanup step.
set -euo pipefail

REPO=/home/s.urso/Bright-2026-Comic-style-Storyteller
SRC_COMFY=/home/v.besozzi/Desktop/comfy_ui
SRC_HF=/home/v.besozzi/.cache/huggingface
SRC_ST=$REPO/SillyTavern/docker

# -a minus owner/group: we run as s.urso and cannot chown. All three containers
# run as root, so host ownership does not affect them. ACLs are deliberately NOT
# copied (-A omitted) so the temporary u:s.urso grant is not baked into the repo.
RS=(rsync -a --no-owner --no-group --info=progress2 --human-readable)

echo "### free space before"; df -h "$REPO" | tail -1

mkdir -p "$REPO"/{comfyui,sillytavern,assets/vrm,hf-cache}

echo; echo "### 1/8 comfyui/models  (7.4G)"
"${RS[@]}" "$SRC_COMFY/data/models/"       "$REPO/comfyui/models/"
echo "### 2/8 comfyui/custom_nodes"
"${RS[@]}" "$SRC_COMFY/data/custom_nodes/" "$REPO/comfyui/custom_nodes/"
echo "### 3/8 comfyui/input"
"${RS[@]}" "$SRC_COMFY/data/input/"        "$REPO/comfyui/input/"
echo "### 4/8 comfyui/output"
"${RS[@]}" "$SRC_COMFY/data/output/"       "$REPO/comfyui/output/"

echo "### 5/8 comfyui/user  <- THE RESCUED WORKFLOWS"
"${RS[@]}" "$REPO/RESCUE/comfyui_user/"    "$REPO/comfyui/user/"

echo "### 6/8 VRM asset (pairs with SillyTavern Extension-VRM)"
"${RS[@]}" "$SRC_COMFY"/*.vrm.glb          "$REPO/assets/vrm/"

echo "### 7/8 sillytavern/{config,data,plugins,extensions}  (263M)"
for d in config data plugins extensions; do
  "${RS[@]}" "$SRC_ST/$d/" "$REPO/sillytavern/$d/"
done

echo "### 8/8 hf-cache  (44G - this is the slow one)"
"${RS[@]}" "$SRC_HF/" "$REPO/hf-cache/"

echo; echo "### free space after"; df -h "$REPO" | tail -1
echo "### DONE COPYING - originals untouched"
