#!/usr/bin/env python3
import argparse
import logging
import math
import random
import shutil
import signal
import sys
import time
import urllib.request
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw

import drive_upload

ROOT = Path(__file__).resolve().parent
BRIGHT_DIR = ROOT / "bright"
OUTPUT_NAME = "assembled.png"
PUSH_OUTBOX = ROOT / "outbox"

A4_300DPI = (2480, 3508)
OUTER_MARGIN = 150
TOP_MARGIN = 460
BACKGROUND_CANDIDATES = ("background.png", "background.jpg", "a4_pattern.png", "a4_pattern.jpg")
POLL_INTERVAL = 5.0
DONE_SUFFIX = "_DONE"

COL_SPLIT_TOP = (0.52, 0.58)
COL_SPLIT_BOTTOM = (0.44, 0.50)
ROW_SPLIT_LEFT = (0.42, 0.48)
ROW_SPLIT_RIGHT = (0.57, 0.66)
GUTTER = 70
PANEL_INK = 14

PANEL_CELLS = {
    "1": (1, 0),
    "2": (0, 0),
    "3": (1, 1),
    "4": (0, 1),
}

log = logging.getLogger("manga-daemon")


def find_background(override):
    if override:
        p = Path(override)
        return p if p.exists() else None
    for name in BACKGROUND_CANDIDATES:
        p = ROOT / name
        if p.exists():
            return p
    return None


def make_base(bg_path):
    if bg_path:
        base = Image.open(bg_path).convert("RGB")
        if base.size != A4_300DPI:
            base = base.resize(A4_300DPI, Image.LANCZOS)
        return base
    return Image.new("RGB", A4_300DPI, "white")


def fit_cover(img, box_w, box_h):
    scale = max(box_w / img.width, box_h / img.height)
    new_w = round(img.width * scale)
    new_h = round(img.height * scale)
    img = img.resize((new_w, new_h), Image.LANCZOS)
    left = (new_w - box_w) // 2
    top = (new_h - box_h) // 2
    return img.crop((left, top, left + box_w, top + box_h))


def page_layout(rng):
    page_w, page_h = A4_300DPI
    x0, y0 = OUTER_MARGIN, TOP_MARGIN
    x3, y3 = page_w - OUTER_MARGIN, page_h - OUTER_MARGIN
    cx_top = x0 + (x3 - x0) * rng.uniform(*COL_SPLIT_TOP)
    cx_bot = x0 + (x3 - x0) * rng.uniform(*COL_SPLIT_BOTTOM)
    yl = y0 + (y3 - y0) * rng.uniform(*ROW_SPLIT_LEFT)
    yr = y0 + (y3 - y0) * rng.uniform(*ROW_SPLIT_RIGHT)

    def divider_x(y):
        return cx_top + (cx_bot - cx_top) * (y - y0) / (y3 - y0)

    p_top, p_bot = (cx_top, y0), (cx_bot, y3)
    ql, qr = (divider_x(yl), yl), (divider_x(yr), yr)
    polygons = {
        "1": [(x3, y0), p_top, qr, (x3, yr)],
        "2": [(x0, y0), p_top, ql, (x0, yl)],
        "3": [(x3, y3), p_bot, qr, (x3, yr)],
        "4": [(x0, y3), p_bot, ql, (x0, yl)],
    }
    seams = [[p_top, p_bot], [(x0, yl), ql], [qr, (x3, yr)]]
    box = (x0, y0, x3, y3)
    return polygons, seams, box


def line_intersection(p1, p2, p3, p4):
    den = (p1[0] - p2[0]) * (p3[1] - p4[1]) - (p1[1] - p2[1]) * (p3[0] - p4[0])
    if abs(den) < 1e-9:
        return ((p2[0] + p3[0]) / 2, (p2[1] + p3[1]) / 2)
    t = ((p1[0] - p3[0]) * (p3[1] - p4[1]) - (p1[1] - p3[1]) * (p3[0] - p4[0])) / den
    return (p1[0] + t * (p2[0] - p1[0]), p1[1] + t * (p2[1] - p1[1]))


def inset_polygon(points, r):
    pts = list(points)
    n = len(pts)
    area = sum(pts[i][0] * pts[(i + 1) % n][1] - pts[(i + 1) % n][0] * pts[i][1] for i in range(n))
    if area < 0:
        pts.reverse()
    lines = []
    for i in range(n):
        ax, ay = pts[i]
        bx, by = pts[(i + 1) % n]
        dx, dy = bx - ax, by - ay
        length = math.hypot(dx, dy) or 1.0
        nx, ny = -dy / length, dx / length
        lines.append(((ax + nx * r, ay + ny * r), (bx + nx * r, by + ny * r)))
    return [line_intersection(lines[i - 1][0], lines[i - 1][1], lines[i][0], lines[i][1])
            for i in range(n)]


def paste_panel(page, photo, poly):
    xs = [p[0] for p in poly]
    ys = [p[1] for p in poly]
    bx0, by0 = math.ceil(min(xs)), math.ceil(min(ys))
    bx1, by1 = math.floor(max(xs)), math.floor(max(ys))
    tile = fit_cover(photo, bx1 - bx0, by1 - by0)
    mask = Image.new("L", (bx1 - bx0, by1 - by0), 0)
    ImageDraw.Draw(mask).polygon([(x - bx0, y - by0) for x, y in poly], fill=255)
    page.paste(tile, (bx0, by0), mask)


def stroke(page, lines, width, color, box):
    layer = Image.new("L", page.size, 0)
    draw = ImageDraw.Draw(layer)
    for line in lines:
        draw.line(line, fill=255, width=width, joint="curve")
    clip = Image.new("L", page.size, 0)
    ImageDraw.Draw(clip).rectangle(box, fill=255)
    page.paste(Image.new("RGB", page.size, color), (0, 0), ImageChops.multiply(layer, clip))


def compose_page(folder, bg_path):
    rng = random.Random(folder.name)
    polygons, _, box = page_layout(rng)

    page = make_base(bg_path)
    frames = []
    for num, poly in polygons.items():
        panel = inset_polygon(poly, GUTTER / 2)
        photo = Image.open(folder / f"{num}.png").convert("RGB")
        paste_panel(page, photo, panel)
        frames.append(inset_polygon(panel, PANEL_INK / 2))
    stroke(page, [f + [f[0]] for f in frames], PANEL_INK, (10, 10, 10), box)

    out = folder / OUTPUT_NAME
    page.save(out)
    return out


def has_all_panels(folder):
    # Publishers rename a staging directory only after all four files are closed.
    # Verify the PNGs as a defensive guard for manually-created batches.
    try:
        if not all((folder / f"{num}.png").is_file() for num in PANEL_CELLS):
            return False
        for num in PANEL_CELLS:
            with Image.open(folder / f"{num}.png") as image:
                image.verify()
        return True
    except (OSError, SyntaxError):
        return False


def done_target(folder):
    target = folder.with_name(folder.name + DONE_SUFFIX)
    counter = 2
    while target.exists():
        target = folder.with_name(f"{folder.name}{DONE_SUFFIX}_{counter}")
        counter += 1
    return target


def queue_for_push(src_path):
    PUSH_OUTBOX.mkdir(exist_ok=True)
    seq_file = PUSH_OUTBOX / "seq.txt"
    n = 1
    if seq_file.exists():
        try:
            n = int(seq_file.read_text().strip()) + 1
        except ValueError:
            n = 1
    dest = PUSH_OUTBOX / f"assembled_{n}.png"
    shutil.copy2(src_path, dest)
    seq_file.write_text(str(n))
    return dest


def flush_outbox(push_url):
    sent = 0
    for f in sorted(PUSH_OUTBOX.glob("assembled_*.png")):
        try:
            req = urllib.request.Request(
                push_url,
                data=f.read_bytes(),
                headers={"Content-Type": "image/png", "X-Filename": f.name},
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                if resp.status != 200:
                    raise RuntimeError(f"receiver answered {resp.status}")
            f.unlink()
            sent += 1
            log.info("pushed %s", f.name)
        except Exception as exc:
            log.warning("push target unreachable (%s), will retry next scan", exc)
            break
    return sent


def scan_once(bg_path, watch_dir, push_url=None):
    processed = 0
    folders = [p for p in watch_dir.iterdir()
               if p.is_dir() and not p.name.endswith(DONE_SUFFIX) and not p.name.endswith(".staging")]
    for folder in sorted(folders):
        if not has_all_panels(folder):
            log.warning("skipping %s: incomplete or invalid 4-panel batch", folder.name)
            continue
        try:
            out = compose_page(folder, bg_path)
            target = done_target(folder)
            folder.rename(target)
            processed += 1
            try:
                shown = out.relative_to(ROOT)
            except ValueError:
                shown = out
            log.info("composed %s, folder renamed to %s", shown, target.name)
            if drive_upload.enabled():
                try:
                    drive_upload.upload(target / OUTPUT_NAME)
                except Exception:
                    log.exception("drive upload failed for %s", target.name)
            if push_url:
                queue_for_push(target / OUTPUT_NAME)
                flush_outbox(push_url)
        except Exception:
            log.exception("failed to compose %s", folder)
    return processed


def main():
    ap = argparse.ArgumentParser(description="Manga page compositor daemon")
    ap.add_argument("--once", action="store_true", help="run a single scan and exit")
    ap.add_argument("--background", default=None, help="path to A4 background/pattern file")
    ap.add_argument("--path", default=str(BRIGHT_DIR), help="folder to monitor for panel batches")
    ap.add_argument("--time", type=float, default=POLL_INTERVAL, help="seconds between scans")
    ap.add_argument("--drive-credentials", default=None, help="path to Google service account JSON key")
    ap.add_argument("--drive-folder", default=None, help="Google Drive folder ID that receives composed pages")
    ap.add_argument("--push-url", default=None, help="HTTP endpoint that receives composed pages (e.g. http://192.168.1.50:8000/upload)")
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    watch_dir = Path(args.path)
    if not watch_dir.is_dir():
        log.error("missing folder %s", watch_dir)
        return 1
    log.info("watching %s every %ss", watch_dir, args.time)

    bg = find_background(args.background)
    log.info("background: %s", bg or "plain white")

    if args.drive_credentials and args.drive_folder:
        drive_upload.init(args.drive_credentials, args.drive_folder)
    elif args.drive_credentials or args.drive_folder:
        log.warning("--drive-credentials and --drive-folder are both required; drive upload disabled")

    stop = {"flag": False}

    def handle(signum, frame):
        log.info("signal %s received, shutting down", signum)
        stop["flag"] = True

    signal.signal(signal.SIGINT, handle)
    signal.signal(signal.SIGTERM, handle)

    while not stop["flag"]:
        processed = scan_once(bg, watch_dir, push_url=args.push_url)
        if processed:
            log.info("processed %d page(s)", processed)
        if args.push_url:
            flush_outbox(args.push_url)
        if args.once:
            break
        time.sleep(args.time)
    return 0


if __name__ == "__main__":
    sys.exit(main())
