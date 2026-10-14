#!/usr/bin/env python3
import math
import random
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from compose_daemon import A4_300DPI, OUTER_MARGIN, TOP_MARGIN

LOGO_SOURCE = ROOT / "tmp" / "marchio_unipi_pant541-eps-converted-to.pdf.png"
UNIPI_BLUE = (0, 79, 159)
GRAY = (120, 124, 130)
FONTS = {
    "title": ("/System/Library/Fonts/Supplemental/Didot.ttc",
              "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf"),
    "serif": ("/System/Library/Fonts/Supplemental/Georgia.ttf",
              "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf"),
}


def font(kind, size):
    for path in FONTS[kind]:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default()


def spaced_text(draw, pos, text, fnt, fill, tracking):
    x, y = pos
    for ch in text:
        draw.text((x, y), ch, font=fnt, fill=fill)
        x += draw.textlength(ch, font=fnt) + tracking
    return x


def text_width(draw, text, fnt, tracking=0):
    return sum(draw.textlength(ch, font=fnt) for ch in text) + tracking * max(0, len(text) - 1)


def constellation(draw, region, rng, count=7):
    x0, y0, x1, y1 = region
    pts = [(rng.uniform(x0, x1), rng.uniform(y0, y1)) for _ in range(count)]
    pts.sort()
    for a, b in zip(pts, pts[1:]):
        draw.line([a, b], fill=UNIPI_BLUE, width=2)
    for x, y in pts:
        r = rng.uniform(4, 8)
        draw.ellipse([x - r, y - r, x + r, y + r], fill=UNIPI_BLUE)
    for x, y in rng.sample(pts, 2):
        s = rng.uniform(16, 26)
        draw.line([(x - s, y), (x + s, y)], fill=UNIPI_BLUE, width=2)
        draw.line([(x, y - s), (x, y + s)], fill=UNIPI_BLUE, width=2)


def build_logo():
    logo = Image.open(LOGO_SOURCE).convert("RGBA")
    px = logo.load()
    for y in range(logo.height):
        for x in range(logo.width):
            r, g, b, _ = px[x, y]
            if r > 235 and g > 235 and b > 235:
                px[x, y] = (r, g, b, 0)
    logo = logo.crop(logo.getbbox())
    width = 560
    return logo.resize((width, round(logo.height * width / logo.width)), Image.LANCZOS)


def main():
    page_w, page_h = A4_300DPI
    page = Image.new("RGB", (page_w, page_h), "white")
    draw = ImageDraw.Draw(page)
    rng = random.Random(20260915)

    logo = build_logo()
    page.paste(logo, (page_w - 120 - logo.width, 120), logo)

    title_f = font("title", 190)
    draw.text((OUTER_MARGIN, 92), "BRIGHT", font=title_f, fill=UNIPI_BLUE)
    sub_f = font("serif", 44)
    spaced_text(draw, (OUTER_MARGIN + 6, 350), "LA NOTTE DEI RICERCATORI", sub_f, GRAY, 14)

    constellation(draw, (950, 110, 1650, 400), rng)
    constellation(draw, (page_w - 900, page_h - 260, page_w - 420, page_h - 90), rng, count=5)
    constellation(draw, (420, page_h - 260, 900, page_h - 90), rng, count=5)

    box = (OUTER_MARGIN, TOP_MARGIN, page_w - OUTER_MARGIN, page_h - OUTER_MARGIN)
    draw.rectangle(box, outline=(185, 200, 220), width=3)
    cx = (box[0] + box[2]) / 2
    for corner in [(box[0], box[1]), (box[2], box[1]), (box[0], box[3]), (box[2], box[3])]:
        s = 34
        draw.line([(corner[0] - (s if corner[0] == box[0] else -s), corner[1]),
                   (corner[0] + (s if corner[0] == box[0] else -s), corner[1])], fill=UNIPI_BLUE, width=4)
        draw.line([(corner[0], corner[1] - (s if corner[1] == box[1] else -s)),
                   (corner[0], corner[1] + (s if corner[1] == box[1] else -s))], fill=UNIPI_BLUE, width=4)

    cap_f = font("serif", 36)
    caption = "UNIVERSITÀ DI PISA"
    cap_w = text_width(draw, caption, cap_f, 10)
    spaced_text(draw, (cx - cap_w / 2, page_h - 108), caption, cap_f, UNIPI_BLUE, 10)
    draw.line([(cx - cap_w / 2 - 220, page_h - 88), (cx - cap_w / 2 - 40, page_h - 88)], fill=GRAY, width=2)
    draw.line([(cx + cap_w / 2 + 40, page_h - 88), (cx + cap_w / 2 + 220, page_h - 88)], fill=GRAY, width=2)

    page.save(ROOT / "background.png")
    ink = sum(1 for p in page.convert("L").getdata() if p < 245) / (page_w * page_h)
    print(f"saved {ROOT / 'background.png'}, ink coverage {ink:.1%}")


if __name__ == "__main__":
    main()
