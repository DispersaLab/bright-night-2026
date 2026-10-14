#!/usr/bin/env bash
# setup: run this on the machine where the project will live (e.g. the Spark)
set -e
cd "$(dirname "$0")"

if ! command -v python3 >/dev/null 2>&1; then
    echo "python3 not found"
    if command -v apt >/dev/null 2>&1; then
        echo "try: sudo apt install -y python3 python3-venv"
    fi
    exit 1
fi

if ! python3 -m venv .venv 2>/dev/null; then
    echo "failed to create .venv"
    if command -v apt >/dev/null 2>&1; then
        echo "try: sudo apt install -y python3-venv"
    fi
    exit 1
fi

.venv/bin/pip install --quiet --upgrade pip
if ! .venv/bin/pip install --quiet -r requirements.txt; then
    echo "pip install failed (no wheel / no build tools)"
    if command -v apt >/dev/null 2>&1; then
        echo "try: sudo apt install -y python3-dev libjpeg-dev zlib1g-dev"
        echo "or use the system package: sudo apt install -y python3-pil"
    fi
    exit 1
fi

.venv/bin/python -c "import PIL; print('Pillow', PIL.__version__, '- venv ready')"
