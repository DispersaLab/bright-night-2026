# Next workstream — model behaviour and the ComfyUI format problem

Written 2026-08-30, at the end of the infrastructure consolidation. The stack
is running and healthy; everything below is about *behaviour*, not plumbing.

> **Note on scope.** The user said these items are "documented also in
> `CLAUDE_CODE_BRIEF.md`". They are not — that brief covers Tasks 0–7, all
> infrastructure. The nearest passage is lines 221–224 (the abliteration /
> `<think>` warning). Confirm whether a newer brief exists before assuming
> requirements.

---

## 1. Instruction-following

Not yet investigated. No baseline exists.

The obvious first question is whether the abliterated model is the cause. The
served model is `AEON-7/Qwen3.6-35B-A3B-heretic-NVFP4`; abliteration removes
refusal behaviour but can degrade instruction adherence generally.

**The A/B test costs nothing but a restart** — the stock model is already in
`hf-cache/`:

```bash
# in .env
VLLM_MODEL=nvidia/Qwen3.6-35B-A3B-NVFP4
docker compose up -d vllm        # ~5 min cold start
```

Build a fixed prompt set first so "before" and "after" are comparable.
`scripts/06-benchmark.sh` measures throughput only, not quality — it is not
the right tool for this.

## 2. Is SillyTavern parsing model output correctly?

vLLM runs with:

- `--reasoning-parser=qwen3` — extracts `<think>` blocks
- `--tool-call-parser=qwen3_xml` + `--enable-auto-tool-choice`

**The prime suspect is documented in the brief itself (lines 221–224):** the
"heretic" build is abliterated, and on a thinking model that can damage the
`<think>` block structure the reasoning parser depends on. If `<think>` tags
are malformed or missing, vLLM's parser may emit reasoning as ordinary content
— which SillyTavern would then render as story text.

Worth checking, in order:

1. Call `/v1/chat/completions` directly with thinking **enabled** and inspect
   the raw JSON — specifically whether `reasoning_content` is populated and
   whether `content` is clean.
2. Compare against the stock model to see whether abliteration is the cause.
3. Only then look at SillyTavern's own rendering settings.

Doing (1) before (3) matters: if vLLM is mis-parsing, no SillyTavern setting
will fix it.

## 3. The ComfyUI format problem

**This is the strongest lead of the three, because there is already hard
evidence.** Before the cutover, the ComfyUI log showed repeated errors on
requests from SillyTavern's container IP:

```
ERROR Error handling request from 172.20.0.2
Traceback (most recent call last):
  File "/app/ComfyUI/server.py", line 98, in deprecation_warning
json.decoder.JSONDecodeError: Expecting ',' delimiter: line 55 column 187 (char 1117)
```

Note it appeared at char 1117 and 1119 across occurrences — so the payload
varies slightly, consistent with generated content being interpolated into a
workflow template and breaking it. **An unescaped quote or newline in a
generated prompt string is the most likely cause.**

### What has already been ruled out

- **Not connectivity.** Verified 2026-08-30 that SillyTavern reaches ComfyUI
  at `http://172.17.0.1:8188/system_stats` and vLLM at `:8001/health` from
  inside its container, after the network consolidation.
- **Not custom nodes.** `custom_nodes/` is empty.
- **Not architecture.** All images are `arm64`; no emulation.

### Caveat on the evidence

The original ComfyUI container was removed during the cutover, so **its logs
are gone**. Only the signature above survives (quoted here and in the README).
The error will need to be reproduced.

### Reproducing it

1. `docker logs -f comfyui_dgx` in one terminal.
2. Trigger an image generation from SillyTavern.
3. Capture the full traceback — this time save it to a file.

The saved workflow is `comfyui/user/default/workflows/Alice.json` (11 nodes),
which is what SillyTavern's image-generation extension drives. Comparing the
JSON SillyTavern actually POSTs against that template is the direct path to
the answer.

---

## State this work starts from

- Stack live and healthy on one compose project (`storyteller`).
- vLLM: `util 0.45`, `max-model-len 32768`, no `moe-backend`,
  `--language-model-only` (nothing sends images *to* the model yet).
- **Reboot test deferred indefinitely** — do not delete the ~51.5 GB of
  originals under `/home/v.besozzi` until it passes. See README.
- Portainer Git-backed stack: to be created by the user in the UI, named
  `storyteller`.
