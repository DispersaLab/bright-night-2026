# Bright Night 2026 — Comic-Style Storyteller

Local storytelling stack for an **NVIDIA DGX Spark** (GB10, Linux/arm64).
SillyTavern sends prompts to vLLM, ComfyUI renders four comic panels, and the
composer assembles them into an A4 page. Kokoro provides text-to-speech.

**DGX Spark is a requirement, not a suggested configuration.** The images,
GPU access and memory settings target its NVIDIA GPU and 128 GB of shared
CPU/GPU memory. Other computers are not supported by this Compose setup.

| Service | Purpose | Host port |
| --- | --- | --- |
| SillyTavern | Story interface; built from the `SillyTavern` submodule | 8010 |
| vLLM | Qwen text model | 8001 |
| ComfyUI | FLUX image generation | 8188 |
| Kokoro | Text-to-speech | 8880, localhost only |
| Composer | Four-panel A4 page assembly | none |

The uppercase `SillyTavern/` directory is application source. The lowercase
`sillytavern/` directory holds configuration, workflows and user data. Keep
both paths: they serve different purposes on the DGX Spark's Linux filesystem.

## Requirements

- NVIDIA DGX Spark with working NVIDIA drivers and NVIDIA Container Toolkit.
- Docker Engine with the Docker Compose plugin, Git and an internet connection
  for first-time image and model downloads.
- Disk space for the Qwen model, the 17 GB FLUX checkpoint and container images.
- Free ports 8001, 8010 and 8188, plus Docker subnet `172.23.0.0/16`.

The default vLLM memory reservation (`VLLM_GPU_MEM_UTIL=0.38`) leaves room
for ComfyUI in the Spark's shared memory. Increasing it can starve image
generation.

## Install on the DGX Spark

1. Clone the repository **with its submodule**, then create local settings:

   ```bash
   git clone --recurse-submodules https://github.com/DispersaLab/bright-night-2026.git
   cd bright-night-2026
   cp .env.example .env
   ```

   If the repository is already cloned, run `git submodule update --init`
   instead. The submodule must contain a Dockerfile before the build below.

2. Download the checkpoint used by the committed SillyTavern settings:

   ```bash
   mkdir -p comfyui/models/checkpoints
   curl -L --fail --retry 3 \
     -o comfyui/models/checkpoints/flux1-schnell-fp8.safetensors \
     https://huggingface.co/Comfy-Org/flux1-schnell/resolve/main/flux1-schnell-fp8.safetensors
   ```

   [Comfy-Org's model page](https://huggingface.co/Comfy-Org/flux1-schnell)
   documents this single-file ComfyUI checkpoint and its destination. Model
   weights are intentionally excluded from Git. vLLM downloads
   [Qwen/Qwen3.5-35B-A3B-FP8](https://huggingface.co/Qwen/Qwen3.5-35B-A3B-FP8)
   into `hf-cache/` on first start.

3. Start the stack from the repository root:

   ```bash
   docker compose -f docker-compose.yml -f compose.local.yml up -d --build
   docker compose -f docker-compose.yml -f compose.local.yml ps
   ```

   Open `http://localhost:8010` in a browser on the DGX Spark. The first
   startup builds ComfyUI, SillyTavern and the composer, downloads container
   images and model weights, and can take several minutes. SillyTavern waits
   for vLLM and ComfyUI to become healthy.

The base `docker-compose.yml` retains absolute path defaults for the existing
Portainer deployment. For a new local installation, copy `.env.example` and
**always use both Compose files** as above; `compose.local.yml` supplies the
build contexts for images produced from this repository.

## Configure and operate

Edit `.env` for local bind paths, published host ports and vLLM memory
settings. Internal service ports stay at 8001 (vLLM), 8010 (SillyTavern) and
8188 (ComfyUI). ComfyUI uses host networking, so its host port is fixed at
8188. `COMPOSER_PUSH_URL` is empty by default: assembled pages stay local.
Set it to a print receiver's upload URL only if one is in use.

```bash
docker compose -f docker-compose.yml -f compose.local.yml logs -f
docker compose -f docker-compose.yml -f compose.local.yml stop
docker compose -f docker-compose.yml -f compose.local.yml up -d
```

Generated panels are stored under `comfyui/output/`. Completed A4 pages are
stored in `bright_composer/bright/*_DONE/assembled.png`. SillyTavern chat
data lives under `sillytavern/data/`; chat logs are ignored by Git, while
selected settings, character cards and workflows are tracked. Saved ComfyUI
workflows live under `comfyui/user/`.

The committed image-generation settings use
`flux1-schnell-fp8.safetensors`. The optional `pony` profile needs
`ponyDiffusionV6XL_v6StartWithThisOne.safetensors` in
`comfyui/models/checkpoints/` and both LoRAs named in
`sillytavern/data/default-user/user/workflows/alice.json` under
`comfyui/models/loras/`. Once those files exist, use
`scripts/switch-image-model.py --status` or
`scripts/switch-image-model.py pony`. Hard-reload any open SillyTavern tab
after switching so its in-memory settings do not overwrite the change.

## Current limits

- The pinned `SillyTavern` submodule commit
  `f321b4b62b911c97ae60c2df81c6367c7f1f2fd7` was not found through
  the configured public upstream during preparation. A fresh
  `git clone --recurse-submodules` may fail until that reference is made
  available. The existing DGX Spark checkout has not been inspected.
- The ComfyUI Dockerfile pins the source revision, but its dependency
  installation has not been validated by a fresh DGX Spark rebuild. See
  `comfyui/build/Dockerfile` before replacing a working local image.
- No speech-to-text container is defined in this Compose stack. Microphone
  input needs separate SillyTavern/browser configuration.
- SillyTavern has no TLS or basic authentication in the committed config.
  Keep this stack on a trusted local network; do not expose ports 8001, 8010
  or 8188 to the Internet. If Docker cannot allocate `172.23.0.0/16`, change
  the subnet and gateway in `docker-compose.yml` and the gateway whitelist in
  `sillytavern/config/config.yaml` together.
