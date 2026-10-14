# Task Brief: Consolidate and repair the Comic-Style Storyteller stack

## Context

Single-node deployment on an **NVIDIA DGX Spark** (GB10 Grace Blackwell, arm64,
128 GB unified LPDDR5x @ 273 GB/s, DGX OS / Ubuntu 24.04). Containers are managed
via **Portainer**. The stack is:

- **vLLM** serving `Qwen3.6-35B-A3B` (NVFP4) on port 8001
- **ComfyUI** for comic-panel image generation
- **SillyTavern** as the user-facing chat frontend, driving ComfyUI via its
  image-generation extension
- (Upstream) a microphone / Whisper STT feeding narration into SillyTavern

The files were laid out ad-hoc by a previous developer across two different user
home directories, including a `Desktop/` folder. Nothing is reproducible and one
critical data path is not persisted at all.

## Goal

1. Rescue data that is currently at risk of loss.
2. Consolidate everything into one git-tracked project directory.
3. Express the whole stack as a single `docker-compose.yml`.
4. Fix the vLLM runtime configuration (currently starves the rest of the box).
5. Guarantee the stack comes back cleanly after a full power cycle of the Spark.

---

## Current state (verified via `docker inspect`)

### vLLM container `vllm_qwen_optimized`

Entrypoint `["vllm","serve"]`, Cmd:

```
AEON-7/Qwen3.6-35B-A3B-heretic-NVFP4
--host=0.0.0.0 --port=8001
--tensor-parallel-size=1
--trust-remote-code
--kv-cache-dtype=fp8
--moe-backend=marlin
--gpu-memory-utilization=0.80
--max-model-len=262144
--max-num-seqs=8
--max-num-batched-tokens=8192
--enable-chunked-prefill
--async-scheduling
--enable-prefix-caching
--load-format=fastsafetensors
--reasoning-parser=qwen3
--tool-call-parser=qwen3_xml
--enable-auto-tool-choice
--mm-encoder-tp-mode=data
```

### Bind mounts currently in place

```
/home/v.besozzi/.cache/huggingface                      -> /root/.cache/huggingface
/home/s.urso/Bright-2026-Comic-style-Storyteller/SillyTavern/docker/data       -> /home/node/app/data
/home/s.urso/Bright-2026-Comic-style-Storyteller/SillyTavern/docker/plugins    -> /home/node/app/plugins
/home/s.urso/Bright-2026-Comic-style-Storyteller/SillyTavern/docker/extensions -> /home/node/app/public/scripts/extensions/third-party
/home/s.urso/Bright-2026-Comic-style-Storyteller/SillyTavern/docker/config     -> /home/node/app/config
/home/v.besozzi/Desktop/comfy_ui/data/models        -> /app/ComfyUI/models
/home/v.besozzi/Desktop/comfy_ui/data/custom_nodes  -> /app/ComfyUI/custom_nodes
/home/v.besozzi/Desktop/comfy_ui/data/output        -> /app/ComfyUI/output
/home/v.besozzi/Desktop/comfy_ui/data/input         -> /app/ComfyUI/input
```

---

## ⚠️ TASK 0 — DO THIS BEFORE ANYTHING ELSE

**`/app/ComfyUI/user` is NOT bind-mounted.** ComfyUI stores saved workflows in
`/app/ComfyUI/user/default/workflows/`. Those files exist only in the container's
writable layer and will be **permanently destroyed** by any `docker compose down`,
container recreation, or image pull.

Do not stop, recreate, prune, or redeploy any container until this is rescued.

```bash
# 1. Identify the ComfyUI container
docker ps --format '{{.Names}}\t{{.Image}}'

# 2. Inspect what's there
docker exec <comfy> ls -laR /app/ComfyUI/user/

# 3. Copy it out to the host
docker cp <comfy>:/app/ComfyUI/user ./RESCUE/comfyui_user

# 4. Verify the copy is non-empty and contains .json workflow files
find ./RESCUE/comfyui_user -name '*.json' | head -50
```

Also check the same container for other unmounted writable paths that may hold
state — at minimum `/app/ComfyUI/user`, and any `extra_model_paths.yaml` or
config written at runtime. Report what you find before proceeding.

Do the equivalent sanity check on the SillyTavern container: confirm that
`data/`, `config/`, `plugins/` and the third-party extensions dir are the only
stateful paths, and that nothing important lives elsewhere in its writable layer.

**Stop and report to the user after Task 0. Get explicit confirmation before
continuing to Task 1.**

---

## TASK 1 — Target directory structure

Consolidate into a single root. Suggested:

```
/opt/storyteller/
├── docker-compose.yml
├── .env
├── .env.example
├── .gitignore
├── README.md
├── comfyui/
│   ├── models/          # NOT in git (large binaries)
│   ├── custom_nodes/
│   ├── input/
│   ├── output/          # NOT in git (generated)
│   └── user/            # ← the rescued workflows; MUST be in git
├── sillytavern/
│   ├── config/
│   ├── data/            # see privacy note below
│   ├── plugins/
│   └── extensions/
└── hf-cache/            # NOT in git
```

Rules:

- Move, do not copy-and-leave-duplicates — but only after Task 0 is confirmed
  safe. Prefer `cp -a` first, verify, then remove originals in a separate step.
- Preserve ownership and permissions (`cp -a` / `rsync -aHAX`).
- Nothing may remain under any user's `~/Desktop` or home directory.
- Create a dedicated service account or group owning `/opt/storyteller`, so the
  stack does not depend on either `v.besozzi` or `s.urso` still existing.
- The HuggingFace cache is currently under `v.besozzi`. Move it — but note it may
  be tens of GB, so check free space and use `rsync` with progress.

### .gitignore must exclude

```
comfyui/models/
comfyui/output/
hf-cache/
.env
sillytavern/data/
**/secrets.json
**/*.safetensors
**/*.ckpt
**/*.gguf
```

### Privacy note

`sillytavern/data/` contains user chat logs and may contain personal data from
storytelling sessions. Do not commit it. Confirm with the user whether character
cards specifically should be tracked — those are configuration and probably
should be, but the chat history should not.

Check `sillytavern/config/config.yaml` and any `secrets.json` for API keys or
credentials before the first commit. If anything is found, report it and do not
commit it.

---

## TASK 2 — Verify architecture

The Spark is arm64. Any amd64 image will fail or run under slow emulation.

```bash
for c in $(docker ps -aq); do
  docker inspect $c --format '{{.Name}} {{.Config.Image}} {{.Architecture}}'
done
```

Report anything that is not `arm64` / `aarch64`. Also verify ComfyUI custom nodes
have working aarch64 wheels — check the ComfyUI startup log for import failures:

```bash
docker logs <comfy> 2>&1 | grep -iE 'error|failed|cannot import|traceback' | head -50
```

Custom nodes that fail to import are a likely cause of workflows that silently
misbehave. List any failures for the user.

---

## TASK 3 — Rewrite the vLLM configuration

The current args reserve ~102 GB of a 128 GB unified pool, starving ComfyUI on
the same memory bus. Apply these changes:

| Flag | Current | New | Why |
|---|---|---|---|
| `--max-model-len` | `262144` | `32768` | 262K KV cache is enormous and unnecessary for narration→panel conversion |
| `--gpu-memory-utilization` | `0.80` | `0.45` | Frees ~45 GB for ComfyUI; unified memory is shared |
| `--moe-backend` | `marlin` | *(remove)* | Marlin is an INT4 kernel path; weights are NVFP4, which Blackwell handles natively. Let vLLM choose. |
| `--mm-encoder-tp-mode` | `data` | *(see below)* | |

Keep unchanged: `--tensor-parallel-size=1`, `--kv-cache-dtype=fp8`,
`--reasoning-parser=qwen3`, `--enable-prefix-caching`, `--enable-chunked-prefill`,
`--async-scheduling`, `--load-format=fastsafetensors`, the tool-call flags.

**Vision encoder:** ask the user whether anything sends images *to* the model. If
not, replace `--mm-encoder-tp-mode=data` with `--language-model-only` to skip the
vision encoder and free memory. If they want the panel-consistency-check feature,
keep vision loaded.

**Model choice:** make the model ID an `.env` variable so it can be swapped
without editing compose:

```
VLLM_MODEL=AEON-7/Qwen3.6-35B-A3B-heretic-NVFP4
```

The user intends to A/B test this against stock `Qwen/Qwen3.6-35B-A3B` in NVFP4.
The "heretic" build is abliterated, which on a thinking model can damage the
`<think>` block structure that `--reasoning-parser=qwen3` depends on. Make the
swap a one-line change.

Benchmark before/after the `--moe-backend` removal and record results in the
README:

```bash
curl -s http://localhost:8001/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"model":"'"$VLLM_MODEL"'","messages":[{"role":"user","content":"Conta da 1 a 50."}],
       "max_tokens":512,"chat_template_kwargs":{"enable_thinking":false}}' \
  | python3 -c 'import sys,json; d=json.load(sys.stdin); print(d["usage"])'
```

---

## TASK 4 — docker-compose.yml

Write a single compose file at `/opt/storyteller/docker-compose.yml` covering
vLLM, ComfyUI and SillyTavern.

Requirements:

- **`restart: unless-stopped`** on every service — this is what survives reboot.
- All bind mounts use absolute paths under `/opt/storyteller`, or compose-relative
  paths. No user home directories.
- **Add the missing ComfyUI mount:** `./comfyui/user:/app/ComfyUI/user`
- GPU access via the nvidia runtime. On DGX OS this is typically:
  ```yaml
  deploy:
    resources:
      reservations:
        devices:
          - driver: nvidia
            count: all
            capabilities: [gpu]
  ```
  Verify what actually works on this box — check the existing containers'
  `HostConfig.Runtime` and `DeviceRequests` and match it.
- `shm_size` and `ipc: host` for vLLM as appropriate.
- Pin image tags explicitly. No `:latest` anywhere — an unpinned pull is how the
  workflows would have been lost.
- Put ports, model ID, and paths in `.env`; commit `.env.example`, not `.env`.
- Add healthchecks: vLLM on `/health`, ComfyUI on `/system_stats`, SillyTavern on
  its root path.
- **Startup ordering:** SillyTavern should `depends_on` both vLLM and ComfyUI with
  `condition: service_healthy`. Note in a comment that vLLM and ComfyUI contend
  for the same 273 GB/s memory bus, so their workloads should be serialized at the
  application level, not run concurrently.

---

## TASK 5 — Reboot survival

Verify, don't assume:

```bash
systemctl is-enabled docker          # must be 'enabled'
systemctl is-enabled portainer 2>/dev/null || docker inspect portainer --format '{{.HostConfig.RestartPolicy.Name}}'
```

Portainer itself must have a restart policy or the management UI won't come back.
Check whether `/opt/storyteller` is on a filesystem mounted at boot (it should be
the internal NVMe; confirm it's in `/etc/fstab` and not a removable/automounted
volume).

Then do a real test — with the user's permission and at a time they choose:

```bash
sudo reboot
# after boot:
docker ps --format '{{.Names}}\t{{.Status}}'
curl -sf http://localhost:8001/health && echo "vLLM OK"
```

Confirm the rescued ComfyUI workflows are still present after the reboot. That is
the actual proof the persistence fix worked.

---

## TASK 6 — Portainer integration

Once the compose file is committed to the git repo, redeploy the stack in
Portainer as a **Git-backed stack** (Stacks → Add stack → Repository) rather than
a pasted web-editor stack. This makes the repo the single source of truth and
removes the ability for anyone to make undocumented UI edits.

Remove or clearly rename the old ad-hoc stack/containers once the new one is
verified working. Do not delete anything until the new stack has survived a
reboot.

---

## TASK 7 — README

Write `/opt/storyteller/README.md` documenting:

- What the system does and how the four components connect
- Hardware constraints: 273 GB/s shared memory bus; why
  `--gpu-memory-utilization` is set low; why the two GPU workloads must not run
  concurrently
- How to start, stop, and update the stack
- How to swap the vLLM model via `.env`
- Where every piece of state lives, and which paths are git-tracked
- The recorded benchmark numbers from Task 3

---

## Constraints for the agent

- **Ask before any destructive operation.** No `docker compose down`, `docker
  system prune`, `docker rm`, `rm -rf`, or image pull without explicit approval.
- Task 0 is a hard gate. Report and wait.
- Work in git from the start: `git init` (or use the existing repo), commit after
  each task, so every step is revertible.
- Never commit model weights, the HF cache, `.env`, secrets, or chat logs.
- If a command's output is surprising or contradicts this brief, stop and report
  rather than improvising. The brief is based on one `docker inspect` snapshot and
  may be incomplete.
- Prefer `cp -a` then verify then delete, over `mv`, for anything irreplaceable.
