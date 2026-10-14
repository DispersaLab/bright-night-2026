# Comic-Style Storyteller

A single-node storytelling stack for the **NVIDIA DGX Spark** (GB10 Grace
Blackwell, arm64, 128 GB unified LPDDR5x @ 273 GB/s, DGX OS / Ubuntu 24.04).

You narrate into a microphone; Whisper transcribes; SillyTavern drives a local
LLM to turn the narration into a story and into image prompts; ComfyUI renders
those prompts as comic panels.

```
┌─────────────┐   narration    ┌─────────────┐   panel prompt   ┌──────────┐
│ Whisper STT │ ─────────────► │ SillyTavern │ ───────────────► │ ComfyUI  │
└─────────────┘                │    :8010    │ ◄─────────────── │  :8188   │
                               └──────┬──────┘   comic panel    └──────────┘
                                      │ chat completions
                                      ▼
                                ┌──────────┐
                                │   vLLM   │  Qwen3.5-35B-A3B (FP8)  
                                │  :8001   │
                                └──────────┘
```

| Service | Port | Image |
|---|---|---|
| vLLM | 8001 | `vllm/vllm-openai` 0.26.0 (digest-pinned) |
| ComfyUI | 8188 | `storyteller-comfyui:0.29.0` (locally built) |
| SillyTavern | 8010 | `ghcr.io/sillytavern/sillytavern` 1.18.0 (digest-pinned) |
| Portainer | 9443 | `portainer/portainer-ce:sts` (managed separately) |

---

## ⚠ The hardware constraint that drives every tuning decision

**There is no separate VRAM.** The GB10 has *one* pool of 128 GB unified
LPDDR5x on a single **273 GB/s** bus, shared by the CPU, vLLM and ComfyUI.

Two consequences:

**1. Memory is zero-sum.** The original configuration ran vLLM at
`--gpu-memory-utilization=0.80`, reserving ~97 GB of 121.6 GiB usable and
leaving the box with about 9 GB free. ComfyUI had to fight for what was left.
The current setting is `0.38`:

| | Original | Now |
|---|---|---|
| `--gpu-memory-utilization` | 0.80 → ~97.3 GiB | **0.38 → ~46.2 GiB** |
| `--max-model-len` | 262144 | **32768** |
| Model weights | 21.88 GiB | 21.88 GiB |
| KV cache | 68.66 GiB (6.82 M tokens) | ~26 GiB (~2.6 M tokens) |
| Freed for ComfyUI | — | **~42.6 GiB** |

The old KV cache was oversized even for its own settings: `262144 × 8 seqs` =
2.10 M tokens is the most the scheduler could ever use, against 6.82 M
allocated. At the current settings the requirement is `32768 × 8` = **262 K
tokens**, so ~2.6 M still leaves roughly 10× headroom. ComfyUI's SDXL working
set is ~6.6 GB staged, which now fits comfortably.

**2. Bandwidth is zero-sum too, and compose cannot fix that.**
`depends_on` orders *startup*. It does nothing about *runtime*. An LLM
generation and an SDXL diffusion running at the same moment contend for the
same 273 GB/s, and both get slower — this is a bandwidth problem, not a
capacity one, so it persists even when there is plenty of free memory.

**Serializing the two workloads has to happen at the application level.**
SillyTavern should finish streaming a response *before* triggering panel
generation, rather than overlapping them.

---

## Quick start

```bash
cp .env.example .env      # then edit if needed
docker compose up -d
docker compose ps
```

vLLM takes roughly **5.5 minutes** to become healthy from cold (223 s to load
weights + 117 s engine init), which is why its healthcheck has a 600 s
`start_period`. SillyTavern waits for both vLLM and ComfyUI to report healthy
before it starts.

| Task | Command |
|---|---|
| Start | `docker compose up -d` |
| Stop | `docker compose stop` |
| Stop + remove containers | `docker compose down` (safe — all state is bind-mounted) |
| Logs | `docker compose logs -f vllm` |
| Restart one service | `docker compose restart comfyui` |
| Update after editing `.env` | `docker compose up -d` |
| Health | `curl -sf localhost:8001/health && echo OK` |

### Swapping the LLM

One line in `.env`:

```bash
VLLM_MODEL=Qwen/Qwen3.5-35B-A3B-FP8               # current (native FP8)
VLLM_MODEL=AEON-7/Qwen3.6-35B-A3B-heretic-NVFP4   # abliterated
VLLM_MODEL=nvidia/Qwen3.6-35B-A3B-NVFP4           # stock NVFP4
```

then `docker compose up -d vllm`. **All three are already in `hf-cache/`**, so
none requires a download.

> **Do not use the unquantized `Qwen/Qwen3.5-35B-A3B`.** It is 71.9 GB of BF16
> weights and needs `VLLM_GPU_MEM_UTIL` raised from 0.38 to roughly 0.66, which
> reverses the headroom deliberately left for ComfyUI on the shared memory bus.
> The FP8 build is 37.5 GB and fits at 0.38.

> The "heretic" build is abliterated. On a thinking model that can damage the
> `<think>` block structure which `--reasoning-parser=qwen3` depends on. If
> reasoning-parser errors appear after a swap, suspect this first.

### Swapping the image model

Two image-generation profiles are installed side by side. Switching flips the
ComfyUI workflow, the checkpoint, the sampler settings, the prompt prefix **and**
the image-guidance block inside `Galileo.png`, because the two models want
fundamentally different prompt languages.

```bash
scripts/switch-image-model.py --status   # which profile is live
scripts/switch-image-model.py flux       # FLUX.1-schnell, natural language
scripts/switch-image-model.py pony       # ponyDiffusionV6XL, Danbooru tags
```

| | `pony` | `flux` |
|---|---|---|
| checkpoint | ponyDiffusionV6XL (6.5 GB) | FLUX.1-schnell fp8 (17 GB) |
| workflow | `alice.json` | `flux.json` |
| prompt language | Danbooru tags | natural-language prose |
| steps / cfg | 35 / 5 | 4 / 1 |
| warm render | ~30 s | ~13 s |
| negative prompt | active | **inert** (cfg 1.0) |
| style LoRAs | two, at strength 1.0 | none |

Nothing is deleted by a switch: both checkpoints and both workflows stay on
disk, and `pony -> flux -> pony` restores `Galileo.png` byte-for-byte (verified
by sha256). Each switch also drops timestamped copies of `settings.json` and
`Galileo.png` into `backups/image-model-switch/`, which is gitignored.

The profiles themselves live in `config/image-model-profiles.json`. The `pony`
profile was generated from the live configuration, so it is an exact record of
the pre-FLUX state.

**Hard-reload any open SillyTavern tab after switching.** A stale tab holds the
old settings in memory and will write them back over `settings.json`.

### Changing the character

The active character is **Galileo Galilei** — a `redivivo` who knows four
centuries have passed, speaks a measured seventeenth-century Italian and
addresses the visitor as `voi`. He replaced Cortana on 2026-08-31. Cortana's
card is still on disk and still tracked; nothing was deleted.

Cards are not edited by hand. The content lives in readable, diffable JSON and
the PNG is built from it:

```bash
scripts/build-character-card.py \
  --content        config/galileo-card.json \
  --template       sillytavern/data/default-user/characters/Cortana.png \
  --avatar         assets/galileo-placeholder.png \
  --out            sillytavern/data/default-user/characters/Galileo.png \
  --world-template sillytavern/data/default-user/worlds/Unipi_Lore.json \
  --world-out      sillytavern/data/default-user/worlds/Galileo_Lore.json
```

`--template` supplies the *schema*, not the content: a v2/v3 card carries a
large amount of boilerplate that SillyTavern expects, so the builder clones an
existing card and substitutes fields rather than re-declaring the format. It
resets the per-instance fields it must not inherit — `chat` in particular, which
would otherwise point Galileo at Cortana's chat log — and refuses to write a
card with any other template text left in it.

> **The English image-guidance block at the end of `system_prompt` is copied
> verbatim from the template and is never authored from the content file.**
> Rewording it is not a cosmetic change: an attempt on 2026-08-31 to restate it
> in prose took tool calling from 12/12 to 0/12, and a careful rewrite still only
> reached 3/8. The working text describes a *parameter value*; anything phrased
> as an instruction to *write* competes with the tool call and wins. The builder
> asserts the block survives byte-identical.

Both tEXt chunks — `chara` (v2) and `ccv3` (v3) — are written and verified
identical apart from the spec fields. SillyTavern prefers `ccv3` and silently
falls back to `chara`, so a card whose chunks disagree behaves differently
depending on which reader you ask.

**A character change is a measurable change, not a cosmetic one.** The first
Galileo card scored **11/16** tool calls where Cortana scores 16/16 on the same
harness and the same sampling settings. Two revisions recovered it:

| card revision | tool calls | what changed |
|---|---|---|
| v1 | 11/16 (69%) | style blocks sat *between* Fase 3 and the guidance block |
| v2 | 14/16 (88%) | style moved above Fase 1, restoring Cortana's layout |
| v3 | 23/24 (96%) | Fase 3 and the function call declared inseparable |
| v3, full pipeline | 24/24 | 12 personas x 2, images rendered |
| Cortana (control) | 16/16 | same harness, same session |

The lesson generalises: **what sits between `Fase 3:` and the guidance block
matters more than what it says.** v1 put ~900 characters of register and
anachronism instruction there; moving that text above `Fase 1:` — leaving 550
characters between Fase 3 and the block, against Cortana's 551 — recovered most
of the loss on its own. Pooled over v3, the rate is 47/48 (98%).

Register was never the problem: all three revisions produced `voi` in 16/16 and
24/24 replies, with no `tu` and no English prompt text in the visible narration.

The lorebook is generated from the same file, as both the embedded
`character_book` and the standalone `worlds/Galileo_Lore.json`. It has six
entries: the university, his role as storyteller, the frog on the Sapienza
door, the image engine, the 1633 trial, and his discoveries. The last two are
new — they are the questions a science-festival crowd actually asks, and
without them he improvises.

### Enabling vision

Nothing currently sends images *to* the model, so vLLM runs with
`--language-model-only`, which disables multimodal input. To add
panel-consistency checking (feeding rendered panels back to the model), remove
that flag in `docker-compose.yml` and restore `--mm-encoder-tp-mode=data`.

---

## Portainer

The stack is deployed as a **Git-backed stack**, so this repository is the
single source of truth and nobody can make undocumented edits in the web
editor.

**Stacks → Add stack → Repository:**

| Field | Value |
|---|---|
| Repository URL | `https://github.com/SaulUrso/-Bright-2026-Comic-style-Storyteller` |
| Reference | `refs/heads/main` |
| Compose path | `docker-compose.yml` |
| Automatic updates | optional; polling re-pulls on new commits |

No environment variables need to be set in the Portainer UI.
`docker-compose.yml` carries defaults for every one (`${VAR:-default}`), so it
deploys correctly with no `.env` — which matters because `.env` is gitignored
and Portainer never sees it.

> **Why the bind mounts are absolute.** Portainer clones the repo into its own
> volume (`/data/compose/<id>`) and resolves compose-relative paths against
> *that* clone. Since `hf-cache/` and `comfyui/models/` are gitignored, relative
> paths would resolve to empty directories and the stack would start with no
> model weights. Absolute paths are required here, not a stylistic choice.

> **The ComfyUI image is built locally and is not in any registry.** The
> compose file has no `build:` section on purpose: Portainer has only
> `docker.sock` and its own volume mounted, so it cannot read a build context
> from the host, and a build triggered from a Portainer stack would fail with a
> confusing error. The image must already exist on the host — which it does,
> tagged `storyteller-comfyui:0.29.0`.
>
> To rebuild it (on the host, not through Portainer):
>
> ```bash
> docker build -t storyteller-comfyui:0.29.0 comfyui/build/
> ```
>
> Read the CAVEAT in `comfyui/build/Dockerfile` first — those pins have never
> been validated by an actual rebuild, and this image cannot be re-pulled if
> lost. **Do not prune images on this host.**

Portainer itself is managed separately (`restart=always`, its own named
volume) and is deliberately *not* part of this stack — a stack cannot
reliably redeploy the container that is redeploying it.

---

## Where state lives

Everything is inside this repository. No path depends on any user's home
directory.

| Path | Contents | In git? |
|---|---|---|
| `comfyui/user/` | **Saved workflows** | ✅ **yes** |
| `comfyui/models/` | SDXL checkpoints, LoRAs (7.4 GB) | ❌ too large |
| `comfyui/output/` | Generated panels | ❌ regenerated |
| `comfyui/input/`, `custom_nodes/` | Inputs, custom nodes (empty) | ✅ yes |
| `comfyui/build/` | Dockerfile + frozen deps | ✅ yes |
| `sillytavern/config/` | `config.yaml` | ✅ yes |
| `sillytavern/data/.../characters/Galileo.png` | **Active** character card | ✅ yes |
| `sillytavern/data/.../characters/Cortana.png` | Previous card, kept as a fallback | ✅ yes |
| `config/galileo-card.json` | Card content, in diffable form | ✅ yes |
| `sillytavern/data/.../worlds/*.json` | Lorebooks | ✅ yes |
| `sillytavern/data/` (everything else) | **Chat logs, personal data** | ❌ **never** |
| `hf-cache/` | Model weights (44 GB) | ❌ too large |
| `assets/vrm/` | VRM avatar for Extension-VRM | ✅ yes |
| `.env` | Local config | ❌ secrets |

`comfyui/user/` being tracked is the whole point of the rescue described below.

---

## History: what was wrong and what was done

The stack was laid out ad-hoc across two user home directories, including a
`Desktop/` folder, and was managed as three unrelated Portainer stacks.

**`/app/ComfyUI/user` was not bind-mounted.** Saved workflows existed *only* in
the ComfyUI container's writable layer. Any `docker compose down`, container
recreation or image pull would have destroyed them permanently. They were
rescued with `docker cp` (verified by sha256) and the mount was added.

Also fixed:

- **The ComfyUI image could not be rebuilt.** It is locally built with no
  registry origin, and its Dockerfile pinned nothing — it cloned ComfyUI HEAD
  and installed unpinned dependencies, so a rebuild would produce a different
  image. Recovered into `comfyui/build/` and pinned to the exact commit that
  was running (`9cf9133`, v0.29.0). See the CAVEAT in that Dockerfile.
- **vLLM ran `privileged: true`**, which GPU access does not require. Removed.
- **Paths referenced `~` and two different user homes.** All now repo-relative.
- **Images were all `:latest`.** Now digest-pinned.
- **Chat logs sat inside the vendored SillyTavern git submodule.** Moved out to
  `sillytavern/` and excluded from git.

### Known issues, not yet fixed
- ~~**Prompt prefix dominates the style.**~~ **Root-caused and resolved by the
  model switch 2026-08-31.** It was not really the text prefix: `alice.json`
  chains two style LoRAs at full strength 1.0 (`Abstract Painting`,
  `perfection style`), and `abstractionism` / `perfection style` in
  `prompt_prefix` are their *trigger words*. A fixed-seed three-way test showed
  the current prefix producing pure abstract paint with no subject at all;
  dropping the trigger words recovered the subject but still overrode "night".
  The `flux` profile has no LoRAs and renders the full scene, Leaning Tower
  included.

- ~~**SillyTavern sends malformed JSON to ComfyUI.**~~ **Diagnosed and closed
  2026-08-30.** Line 55 is the `%prompt%` line of the workflow, and the JSON
  string closed after exactly 170 characters — the length of `prompt_prefix` —
  so an unescaped `"` was terminating it at the prefix boundary. The signature
  was reproduced exactly against live ComfyUI. It is no longer reachable:
  SillyTavern substitutes with `JSON.stringify()` and `processReply()` deletes
  quotes before that anyway.
- ~~**Garbage image prompts.**~~ **Fixed 2026-08-30.** The Cortana card's
  system prompt contained a literal `Struttura della Tool Call` JSON block that
  told the model to *write* the tool call instead of invoking it. Removing it
  took image generation from 3/6 to 5/6 proper tool calls with 0/6 leaks.
- ~~**The model sometimes skips the image entirely.**~~ **Diagnosed and fixed
  2026-08-31. It was never 1 in 6 — it was 57%.** The cause was
  `freq_pen_openai=1.25` / `pres_pen_openai=1.49` in `settings.json`. A tool
  call is a fixed, formulaic token sequence; penalties that high make those
  tokens too expensive to emit, so the model narrates its intent
  ("Generazione immagine avviata...") and stops. Measured over n=30 per arm:
  **17/30 misses with the penalties, 0/30 without** (95% CI 39-73% vs 0-11%,
  non-overlapping). Both penalties are now 0. The earlier "1 in 6" figure and
  an apparently clean 6/6 test were both artifacts of a harness that did not
  send the penalties at all.
- **Content safety is not yet settled.** On the `pony` profile the negative
  prompt still contains no NSFW terms, and `rating_safe` alone is not enough
  for ponyDiffusionV6XL. On the `flux` profile the negative prompt is
  structurally **inert** — FLUX.1-schnell is guidance-distilled and runs at
  cfg 1.0, where classifier-free guidance discards the negative branch
  entirely. FLUX's filtered training set makes explicit output far less likely,
  but neither profile has a hard backstop. If a bad frame on a projector is
  unacceptable, gate the display: either an operator approves each image, or a
  classifier node blocks it. **Decision pending on a measured rate.**
- **SillyTavern's whitelist is keyed on the Docker gateway IP.** Moving to a
  single compose project changed the gateway and SillyTavern started returning
  403. The compose network subnet is now pinned to `172.23.0.0/16` so the
  gateway stays `172.23.0.1`, and that address is whitelisted in
  `sillytavern/config/config.yaml`. `whitelistDockerHosts: true` is set but did
  not catch it. If you ever change the subnet, update the whitelist too.
- **SillyTavern's healthcheck must use `127.0.0.1`, not `localhost`.** The
  container's `/etc/hosts` maps `localhost` to both `127.0.0.1` and `::1`,
  wget tries IPv6 first, and SillyTavern binds IPv4 only (`0.0.0.0:8010`). With
  `localhost` the check fails permanently with "Connection refused" while the
  service is perfectly healthy. vLLM and ComfyUI are unaffected because curl
  falls back to IPv4.
- **Driver version gap.** The ComfyUI container logs `This container was built
  for NVIDIA Driver Release 610.43 or later`; the host runs 580.126.09. It
  works through the CUDA compatibility layer.
- **The stack lives under `/home/s.urso/`.** A dedicated service account
  owning `/opt/storyteller` would be more robust, since the stack currently
  depends on that home directory continuing to exist. This was a deliberate
  trade for keeping all material inside one git repo.

---

## Scripts

| Script | Purpose |
|---|---|
| `build-character-card.py` | Build a card PNG + lorebook from JSON content |
| `switch-image-model.py` | Flip between the `pony` and `flux` profiles |
| `story-batch.py` | Drive full story sessions and save every image for review |
