# ComfyUI for DGX Spark (GB10 Grace Blackwell, aarch64)
#
# The pins below were extracted from the original DGX Spark container.
#
# CAVEAT: this pins ComfyUI and torchaudio to exact commits, but ComfyUI's own
# requirements.txt still uses version ranges, so a rebuild is close to but not
# byte-identical with the running image. Diff a rebuild against
# requirements-frozen.txt to see what moved. Until a rebuild has actually been
# tested, treat the running image as the source of truth and do not prune it.
#
#   ComfyUI  v0.29.0  @ 9cf91339b708a245762fa38ffeec9702b381e0db
#   torch    2.13.0a0+9186a08b2c.nv26.07   (from the base image, do not reinstall)
#
FROM nvcr.io/nvidia/pytorch:26.07-py3

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y \
    git \
    wget \
    libgl1 \
    libglib2.0-0 \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Pinned to the exact commit running in production. The original had no pin,
# which meant every rebuild silently produced a different ComfyUI.
ARG COMFYUI_COMMIT=9cf91339b708a245762fa38ffeec9702b381e0db
RUN git clone https://github.com/comfyanonymous/ComfyUI.git && \
    cd ComfyUI && \
    git checkout ${COMFYUI_COMMIT}

WORKDIR /app/ComfyUI

# The NGC base image ships tuned aarch64 builds of torch/torchvision/xformers.
# Strip them from requirements.txt so pip cannot replace them with wheels that
# are wrong for GB10.
RUN sed -i -E '/^(torch|torchvision|torchaudio|xformers)([>=~]|$)/d' requirements.txt

# requirements-frozen.txt records the exact package set of the image that was
# running in production, for diffing a rebuild against it. It is not applied
# automatically: it contains file:// torch entries from the base image, and
# wiring it in has not been tested with a real rebuild.
RUN pip install --no-cache-dir --no-build-isolation --no-deps \
        git+https://github.com/pytorch/audio.git@c0cbdb9 && \
    pip install --no-cache-dir -r requirements.txt

# ComfyUI stores saved workflows in /app/ComfyUI/user. This MUST be bind-mounted
# or every workflow is destroyed on container recreation. See docker-compose.yml.
VOLUME ["/app/ComfyUI/user"]

EXPOSE 8188

CMD ["python", "main.py", "--listen", "0.0.0.0", "--enable-cors-header", "*"]
