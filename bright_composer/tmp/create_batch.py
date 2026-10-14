#!/usr/bin/env python3
import argparse
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SOURCE = ROOT / "tmp" / "IMG_5535.JPG"
DEFAULT_TARGET = ROOT / "bright"
NUMBER_OPACITY = 70
FONT_CANDIDATES = (
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
    "/System/Library/Fonts/SFNS.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
)


def load_font(size):
    for path in FONT_CANDIDATES:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default()


def stamp_number(img, number, opacity):
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    font = load_font(min(img.size) // 5)
    text = str(number)
    x0, y0, x1, y1 = draw.textbbox((0, 0), text, font=font)
    margin = min(img.size) // 25
    pos = (img.width - (x1 - x0) - margin - x0, img.height - (y1 - y0) - margin - y0)
    draw.text(pos, text, font=font, fill=(255, 255, 255, opacity))
    return Image.alpha_composite(img, overlay)


def main():
    ap = argparse.ArgumentParser(description="Create a timestamped folder with 4 PNG copies of a photo")
    ap.add_argument("source", nargs="?", default=str(DEFAULT_SOURCE), help="image to copy (default: tmp/IMG_5535.JPG)")
    ap.add_argument("--out", default=str(DEFAULT_TARGET), help="parent folder for the new timestamped folder")
    ap.add_argument("--opacity", type=int, default=NUMBER_OPACITY, help="number opacity 0-255")
    args = ap.parse_args()

    src = Path(args.source)
    if not src.exists():
        print(f"error: {src} not found")
        return 1

    folder = Path(args.out) / datetime.now().strftime("%Y%m%d-%H%M%S")
    folder.mkdir(parents=True, exist_ok=True)
    img = Image.open(src).convert("RGBA")
    for number, name in enumerate(("1.png", "2.png", "3.png", "4.png"), start=1):
        stamp_number(img, number, args.opacity).convert("RGB").save(folder / name)
        print(f"created {folder / name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
