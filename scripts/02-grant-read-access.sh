#!/bin/bash
# Grant s.urso READ access to v.besozzi's stack data. No data is moved,
# copied or deleted here. Reversal instructions printed at the end.
set -u
B=/home/v.besozzi

echo "### BEFORE"
stat -c '%A %U:%G %n' "$B" "$B/.cache" "$B/.cache/huggingface" "$B/Desktop" "$B/Desktop/comfy_ui" 2>&1

# Traversal (--x) only: lets s.urso pass THROUGH these dirs.
# It does NOT permit listing their contents.
chmod o+x "$B"
[ -d "$B/.cache" ] && chmod o+x "$B/.cache"

# The HF cache and comfy data may be 0700 internally; grant a read ACL
# scoped to s.urso specifically rather than opening them to all users.
if command -v setfacl >/dev/null 2>&1; then
  setfacl -R -m u:s.urso:rX "$B/.cache/huggingface" 2>&1 && echo "ACL set on huggingface"
  setfacl -R -m u:s.urso:rX "$B/Desktop/comfy_ui"   2>&1 && echo "ACL set on comfy_ui"
  setfacl -R -m u:s.urso:rX "$B/Desktop/vllm"       2>&1 && echo "ACL set on vllm"
else
  echo "!! setfacl not available - falling back to chmod o+rX"
  chmod -R o+rX "$B/.cache/huggingface" "$B/Desktop/comfy_ui" "$B/Desktop/vllm"
fi

echo; echo "### AFTER"
stat -c '%A %U:%G %n' "$B" "$B/.cache" "$B/.cache/huggingface" "$B/Desktop/comfy_ui" 2>&1

echo; echo "### VERIFY (running as s.urso)"
sudo -u s.urso bash -c '
  for p in /home/v.besozzi/.cache/huggingface \
           /home/v.besozzi/Desktop/comfy_ui/Dockerfile \
           /home/v.besozzi/Desktop/comfy_ui/data/models \
           /home/v.besozzi/Desktop/vllm ; do
    if [ -r "$p" ]; then echo "  READABLE   $p"; else echo "  BLOCKED    $p"; fi
  done
  echo "  du huggingface: $(du -sh /home/v.besozzi/.cache/huggingface 2>&1 | cut -f1)"
'

echo; echo "### TO REVERSE LATER:"
echo "  sudo chmod o-x $B"
echo "  sudo setfacl -R -x u:s.urso $B/.cache/huggingface $B/Desktop/comfy_ui $B/Desktop/vllm"
