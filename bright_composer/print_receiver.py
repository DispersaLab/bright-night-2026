#!/usr/bin/env python3
"""Run this on the printing laptop: receives composed pages and (optionally) prints them.

    python3 print_receiver.py --dir ~/prints

Opens a window showing the pages in the folder: arrow buttons / Left-Right keys
to browse, a thumbnail strip to jump to any page, and a Print button.
While the window is open it also receives pages pushed over HTTP from the Spark
(compose_daemon.py) and serves the same view at http://localhost:8000.

GUI needs tkinter and Pillow (headless fallback if missing):
    sudo apt install python3-tk python3-pil     # Ubuntu
"""
import argparse
import json
import os
import re
import smtplib
import socket
import subprocess
import tempfile
import threading
import time
from email.message import EmailMessage
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

try:
    from PIL import Image
    PIL_OK = True
except ImportError:
    PIL_OK = False

try:
    import tkinter as tk
    from tkinter import ttk
    from PIL import ImageTk
    GUI_OK = True
    GUI_ERR = None
except Exception as e:
    GUI_OK = False
    GUI_ERR = e

IMAGE_EXTS = {".png", ".jpg", ".jpeg"}

DEFAULT_EMAIL_MSG = ("Ciao! Ecco il fumetto che hai generato alla BRIGHT Night 2026.\n\n"
                     "Grazie per aver partecipato!\n\n"
                     "DispersaLab @ Dipartimento di Informatica, Università di Pisa")

# theme: BRIGHT (#004494) + Università di Pisa (navy #1A315D, accent #225DD7)
NAVY = "#1A315D"
NAVY_HI = "#24406F"
BLUE = "#225DD7"
BLUE_HI = "#1B49AE"
BRIGHT_BLUE = "#004494"
BG = "#EEF1F5"
PANEL = "#FFFFFF"
STRIP_BG = "#E4E9F0"
FG = "#1F2937"
MUTED = "#6B7280"
DIM = "#C3CBD6"
BORDER = "#D5DBE3"
HDR_TXT = "#C9D4EA"
OK = "#2E9E5B"
ERR = "#C0392B"
OK_HDR = "#6FE3A0"
ERR_HDR = "#FF9E96"

PAGE = """<!doctype html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>BRIGHT — Comic-style Storyteller</title>
<style>
  body { margin:0; font-family:system-ui,sans-serif; background:#EEF1F5; color:#1F2937;
         display:flex; flex-direction:column; height:100vh; }
  header { display:flex; align-items:center; gap:14px; padding:10px 18px;
           background:#1A315D; color:#fff; }
  h1 { font-size:17px; margin:0; font-weight:800; letter-spacing:.5px; }
  h1 small { display:block; font-size:11px; font-weight:400; color:#C9D4EA; }
  .slash { width:10px; height:34px; border-left:2px solid #225DD7;
           transform:skewX(-14deg); margin-right:2px; }
  button { background:#225DD7; color:#fff; border:0; border-radius:6px;
           padding:9px 22px; font-size:14px; font-weight:700; cursor:pointer; }
  button:disabled { opacity:.45; cursor:default; }
  .inkwrap { display:flex; align-items:center; }
  .inkwrap input { accent-color:#225DD7; width:110px; }
  .qbtn { color:#FFD167; cursor:pointer; font-size:12px; font-weight:700; }
  #status { font-size:12px; color:#C9D4EA; min-width:150px; text-align:right; }
  #name { font-size:12px; color:#C9D4EA; flex:1; text-align:right;
          overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
  main { flex:1; overflow:auto; display:flex; align-items:center;
         justify-content:center; padding:14px; }
  img { max-width:100%; max-height:100%; background:#fff; border-radius:4px;
        box-shadow:0 4px 18px rgba(26,49,93,.25); }
  #empty { color:#6B7280; font-size:14px; }
</style>
</head>
<body>
<header>
  <div class="slash"></div>
  <h1>BRIGHT<small>Università di Pisa · Comic-style Storyteller</small></h1>
  <span class="inkwrap"><input type="range" id="ink" min="30" max="100"
        value="100" title="Ink level — lower saves toner"></span>
  <button id="email">Email</button>
  <button id="print">Print</button>
  <span id="queue" class="qbtn" hidden></span>
  <span id="status">waiting for pages…</span>
  <span id="name"></span>
</header>
<main><img id="img" hidden><div id="empty">waiting for the first page…</div></main>
<script>
let current = null, busy = false, defaultTo = "__EMAIL_TO__", defaultMsg = "__EMAIL_MSG__";
const $ = id => document.getElementById(id);

function setStatus(t) { $('status').textContent = t; }

async function poll() {
  try {
    const r = await fetch('/latest');
    if (!r.ok) return;
    const name = r.headers.get('X-Filename');
    if (name && name !== current) {
      current = name;
      $('img').src = '/latest?ts=' + Date.now();
      $('img').hidden = false;
      $('empty').hidden = true;
      $('name').textContent = name;
    }
    if (!busy) setStatus('ready');
    fetch('/queue').then(r => r.text()).then(n => {
      n = parseInt(n, 10) || 0;
      $('queue').hidden = n === 0;
      $('queue').textContent = 'queued: ' + n;
    }).catch(() => {});
  } catch { setStatus('receiver offline'); }
}

$('queue').onclick = async () => {
  const r = await fetch('/queue/retry', {method: 'POST'});
  setStatus(await r.text());
};

$('print').onclick = () => send('/print', 'print');
$('email').onclick = () => send('/email', 'email');

async function send(url, what) {
  if (!current) return;
  const body = {name: current};
  if (what === 'print') body.ink = parseInt($('ink').value, 10);
  if (what === 'email') {
    const to = prompt('Send page to:', defaultTo);
    if (!to) return;
    const m = prompt('Greeting message:', defaultMsg);
    if (m === null) return;
    body.to = to;
    body.msg = m;
  }
  const btn = $(what);
  btn.disabled = true; busy = true; setStatus('sending ' + what + '…');
  try {
    const r = await fetch(url, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({name: current})
    });
    setStatus(r.ok ? await r.text() : 'failed: ' + await r.text());
  } catch (e) { setStatus('error: ' + e); }
  btn.disabled = false; busy = false;
}

poll();
setInterval(poll, 3000);
</script>
</body>
</html>
"""


def local_ips():
    ips = set()
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ips.add(s.getsockname()[0])
        s.close()
    except OSError:
        pass
    for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
        ip = info[4][0]
        if not ip.startswith("127."):
            ips.add(ip)
    return sorted(ips) or ["127.0.0.1"]


def list_images(save_dir):
    files = [p for p in save_dir.iterdir()
             if p.is_file() and p.suffix.lower() in IMAGE_EXTS]
    files.sort(key=natkey)
    return files


def natkey(p):
    return [int(t) if t.isdigit() else t.lower()
            for t in re.split(r"(\d+)", p.name)]


def latest_image(save_dir):
    files = [p for p in save_dir.iterdir()
             if p.is_file() and p.suffix.lower() in IMAGE_EXTS]
    return max(files, key=lambda p: p.stat().st_mtime) if files else None


def send_to_printer(path, printer=None, ink=100):
    tmp = None
    if ink < 100 and PIL_OK:
        factor = max(0.3, ink / 100.0)
        lut = [255 - int((255 - v) * factor) for v in range(256)]
        img = Image.open(path).convert("L").point(lut)
        tmp = Path(tempfile.gettempdir()) / f"print_ink{ink}_{path.stem}.png"
        img.save(tmp)
        path = tmp
    cmd = ["lpr", "-o", "media=a4", "-o", "fit-to-page"]
    if printer:
        cmd += ["-P", printer]
    cmd.append(str(path))
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if tmp is not None:
        tmp.unlink(missing_ok=True)
    if proc.returncode != 0:
        raise RuntimeError((proc.stderr or proc.stdout or "lpr failed").strip())


def send_by_email(path, cfg, body=""):
    subtype = "jpeg" if path.suffix.lower() in {".jpg", ".jpeg"} else "png"
    msg = EmailMessage()
    msg["From"] = cfg["user"]
    msg["To"] = cfg["to"]
    msg["Subject"] = "Il tuo fumetto della notte dei ricercatori! - BRIGHT NIGHT 2026"
    msg.set_content((body or cfg.get("msg") or DEFAULT_EMAIL_MSG) + "\n")
    msg.add_attachment(path.read_bytes(), maintype="image", subtype=subtype,
                       filename="bright-comic-page.png")
    if cfg["port"] == 465:
        with smtplib.SMTP_SSL(cfg["host"], cfg["port"], timeout=60) as s:
            s.login(cfg["user"], cfg["pass"])
            s.send_message(msg)
    else:
        with smtplib.SMTP(cfg["host"], cfg["port"], timeout=60) as s:
            s.starttls()
            s.login(cfg["user"], cfg["pass"])
            s.send_message(msg)


class EmailLog:
    """Append-only history of email attempts, kept in <script dir>/logs/."""

    def __init__(self, base_dir=None):
        base = Path(base_dir) if base_dir else Path(__file__).resolve().parent
        self.dir = base / "logs"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.path = self.dir / "email_log.jsonl"

    def new_id(self):
        return f"{time.time():.3f}".replace(".", "")

    def record(self, eid, to, file, status, detail=""):
        try:
            with self.path.open("a") as fh:
                fh.write(json.dumps(
                    {"id": eid, "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
                     "to": to, "file": str(file), "status": status,
                     "detail": detail}) + "\n")
        except Exception:
            pass

    def rows(self):
        """Newest-first list; for each email id the latest event wins."""
        state, order = {}, []
        try:
            lines = self.path.read_text().splitlines()
        except Exception:
            return []
        for line in lines:
            try:
                ev = json.loads(line)
            except Exception:
                continue
            eid = ev.get("id")
            if eid not in state:
                order.append(eid)
                state[eid] = ev
            else:
                state[eid].update({k: ev[k] for k in ("ts", "status", "detail")
                                   if k in ev})
        return [state[e] for e in reversed(order)]


class EmailQueue:
    """Persists failed emails and retries them in the background."""
    MAX_TRIES = 10
    RETRY_S = 20

    def __init__(self, save_dir, cfg, log):
        self.dir = Path(save_dir) / "email_queue"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.cfg = cfg
        self.log = log
        self.lock = threading.Lock()

    def _entries(self):
        items = []
        for p in sorted(self.dir.glob("*.json")):
            try:
                items.append((p, json.loads(p.read_text())))
            except Exception:
                pass
        return items

    def count(self):
        with self.lock:
            return len(self._entries())

    def enqueue(self, path, to, msg=""):
        with self.lock:
            entry = {"to": to, "msg": msg, "file": str(path),
                     "ts": time.strftime("%Y-%m-%d %H:%M:%S"), "tries": 0}
            stamp = f"{time.time():.3f}".replace(".", "")
            (self.dir / f"{stamp}.json").write_text(json.dumps(entry, indent=1))
            self.log.record(stamp, to, Path(path).name, "queued")
            print(f"email to {to} queued ({path.name})")
            return len(self._entries())

    def try_send_all(self):
        sent = failed = 0
        with self.lock:
            for jpath, entry in self._entries():
                if entry.get("tries", 0) >= self.MAX_TRIES:
                    failed += 1
                    continue
                path = Path(entry.get("file", ""))
                if not path.is_file():
                    jpath.unlink(missing_ok=True)
                    continue
                entry["tries"] = entry.get("tries", 0) + 1
                try:
                    send_by_email(path, {**self.cfg, "to": entry["to"]},
                                  entry.get("msg", ""))
                except Exception:
                    jpath.write_text(json.dumps(entry))
                    if entry["tries"] >= self.MAX_TRIES:
                        self.log.record(jpath.stem, entry["to"], path.name,
                                        "failed",
                                        f"gave up after {self.MAX_TRIES} tries")
                    failed += 1
                    continue
                jpath.unlink(missing_ok=True)
                sent += 1
                self.log.record(jpath.stem, entry["to"], path.name, "sent")
                print(f"queued email sent to {entry['to']} ({path.name})")
        return sent, failed

    def start(self):
        def loop():
            while True:
                time.sleep(self.RETRY_S)
                try:
                    if self.count():
                        self.try_send_all()
                except Exception:
                    pass
        threading.Thread(target=loop, daemon=True).start()


def make_handler(save_dir, do_print, printer, email_cfg=None, mailq=None):
    class Handler(BaseHTTPRequestHandler):
        def _reply(self, code, body, ctype="text/plain; charset=utf-8"):
            data = body.encode() if isinstance(body, str) else body
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _print_file(self, out, ink=100):
            send_to_printer(out, printer, ink)
            print(f"printed {out.name} (ink {ink}%)")

        def do_POST(self):
            if self.path == "/upload":
                name = os.path.basename(self.headers.get("X-Filename", "assembled.png"))
                length = int(self.headers.get("Content-Length", 0))
                out = save_dir / name
                tmp = out.with_suffix(out.suffix + ".part")
                tmp.write_bytes(self.rfile.read(length))
                os.replace(tmp, out)
                self._reply(200, "ok")
                print(f"received {name} -> {out}")
                if do_print:
                    try:
                        self._print_file(out)
                    except Exception as e:
                        print(f"print error for {name}: {e}")
            elif self.path == "/print":
                try:
                    length = int(self.headers.get("Content-Length", 0))
                    req = json.loads(self.rfile.read(length) or b"{}")
                    name = os.path.basename(str(req.get("name", "")))
                    ink = int(req.get("ink", 100))
                    ink = max(30, min(100, ink))
                    out = save_dir / name
                    if not name or not out.is_file():
                        self._reply(404, "no such image")
                        return
                    self._print_file(out, ink)
                    self._reply(200, "sent to printer")
                except Exception as e:
                    self._reply(500, str(e))
            elif self.path == "/email":
                if not email_cfg:
                    self._reply(400, "email not configured")
                    return
                try:
                    length = int(self.headers.get("Content-Length", 0))
                    req = json.loads(self.rfile.read(length) or b"{}")
                    name = os.path.basename(str(req.get("name", "")))
                    to = str(req.get("to", "").strip() or email_cfg.get("to", ""))
                    body = str(req.get("msg", "").strip() or
                               email_cfg.get("msg", DEFAULT_EMAIL_MSG))
                    out = save_dir / name
                    if not name or not out.is_file():
                        self._reply(404, "no such image")
                        return
                    if "@" not in to:
                        self._reply(400, "no valid recipient")
                        return
                    try:
                        send_by_email(out, {**email_cfg, "to": to}, body)
                        if mailq:
                            mailq.log.record(mailq.log.new_id(), to, name,
                                             "sent")
                        self._reply(200, f"email sent to {to}")
                    except Exception:
                        if mailq:
                            n = mailq.enqueue(out, to, body)
                            self._reply(202, f"no connection — queued "
                                             f"({n} pending, auto-retry on)")
                        else:
                            raise
                except Exception as e:
                    self._reply(500, str(e))
            elif self.path == "/queue/retry":
                if not mailq:
                    self._reply(400, "email not configured")
                    return
                sent, failed = mailq.try_send_all()
                self._reply(200, f"sent {sent}, pending {failed}")
            else:
                self.send_error(404)

        def do_GET(self):
            path = self.path.split("?", 1)[0]
            if path == "/health":
                self._reply(200, "ok")
            elif path == "/":
                default_to = email_cfg["to"] if email_cfg else ""
                default_msg = (email_cfg.get("msg", DEFAULT_EMAIL_MSG)
                               if email_cfg else DEFAULT_EMAIL_MSG)
                esc = lambda s: s.replace("\\", "\\\\").replace('"', '\\"')
                page = (PAGE.replace("__EMAIL_TO__", esc(default_to))
                            .replace("__EMAIL_MSG__", esc(default_msg)))
                self._reply(200, page, "text/html; charset=utf-8")
            elif path == "/latest":
                latest = latest_image(save_dir)
                if latest is None:
                    self.send_error(404, "no images yet")
                    return
                ctype = ("image/jpeg" if latest.suffix.lower() in {".jpg", ".jpeg"}
                         else "image/png")
                body = latest.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("X-Filename", latest.name)
                self.end_headers()
                self.wfile.write(body)
            elif path == "/queue":
                self._reply(200, str(mailq.count() if mailq else 0))
            else:
                self.send_error(404)

        def log_message(self, fmt, *args):
            pass

    return Handler


def pick_font(root, candidates):
    try:
        from tkinter import font as tkfont
        fams = set(tkfont.families(root))
        for c in candidates:
            if c in fams:
                return c
    except Exception:
        pass
    return "Helvetica"


class Viewer:
    POLL_MS = 2000
    THUMB = 100

    def __init__(self, root, save_dir, printer, email_cfg=None, mailq=None,
                 email_log=None):
        self.root, self.save_dir, self.printer = root, save_dir, printer
        self.email_cfg = email_cfg
        self.mailq = mailq
        self.email_log = email_log
        self.files = []
        self.idx = 0          # 0 == waiting slot when the list is empty
        self._photo = None
        self._thumbs = {}          # index -> [PhotoImage, frame]
        self._render_job = None
        self.printing = False
        self.emailing = False
        self.ink_default = 100

        family = pick_font(root, ["Titillium Web", "Titillium", "Inter",
                                  "Helvetica Neue"])
        self.family = family

        style = ttk.Style()
        style.theme_use("clam")
        style.configure("Accent.TButton", background=BLUE, foreground="#fff",
                        font=(family, 13, "bold"), borderwidth=0,
                        focusthickness=0, padding=(22, 9))
        style.map("Accent.TButton",
                  background=[("disabled", "#5A6C99"), ("active", BLUE_HI)],
                  foreground=[("disabled", "#C7D1E8")])
        style.configure("Ghost.TButton", background="#FFFFFF", foreground=NAVY,
                        font=(family, 13, "bold"), borderwidth=0,
                        focusthickness=0, padding=(18, 9))
        style.map("Ghost.TButton",
                  background=[("disabled", "#8E9BC0"), ("active", "#E8EDF7")],
                  foreground=[("disabled", "#DDE3F0")])

        root.title("BRIGHT — Comic-style Storyteller")
        root.configure(bg=BG)
        root.minsize(760, 560)
        sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
        root.geometry(f"{int(sw * 0.44)}x{int(sh * 0.84)}")

        top = tk.Frame(root, bg=NAVY)
        top.pack(fill=tk.X, side=tk.TOP)
        tk.Label(top, text="BRIGHT", fg="#FFFFFF", bg=NAVY,
                 font=(family, 21, "bold")).pack(side=tk.LEFT, padx=(18, 4),
                                                 pady=(8, 0))
        slash = tk.Canvas(top, width=16, height=44, bg=NAVY,
                          highlightthickness=0)
        slash.create_line(11, 3, 3, 41, fill=BLUE, width=2)
        slash.create_line(16, 3, 8, 41, fill=BRIGHT_BLUE, width=2)
        slash.pack(side=tk.LEFT, padx=(2, 10), pady=(6, 0))
        tk.Label(top, text="Università di Pisa\nComic-style Storyteller",
                 fg=HDR_TXT, bg=NAVY, justify=tk.LEFT,
                 font=(family, 10)).pack(side=tk.LEFT, pady=(6, 4))
        self.status = tk.Label(top, text="", fg=HDR_TXT, bg=NAVY,
                               font=(family, 11))
        self.status.pack(side=tk.RIGHT, padx=12)
        self.print_btn = ttk.Button(top, text="Print", style="Accent.TButton",
                                    command=self.on_print, state=tk.DISABLED)
        self.print_btn.pack(side=tk.RIGHT, padx=6, pady=10)
        if email_cfg:
            self.email_btn = ttk.Button(top, text="Email",
                                        style="Ghost.TButton",
                                        command=self.on_email, state=tk.DISABLED)
            self.email_btn.pack(side=tk.RIGHT, padx=6, pady=10)
        else:
            self.email_btn = None
        self.counter = tk.Label(top, text="", fg="#FFFFFF", bg=NAVY,
                                font=(family, 12, "bold"))
        self.counter.pack(side=tk.RIGHT, padx=8)
        if mailq:
            self.queue_lbl = tk.Label(top, text="", fg="#FFD166", bg=NAVY,
                                      font=(family, 11, "bold"), cursor="hand2")
            self.queue_lbl.pack(side=tk.RIGHT, padx=4)
            self.queue_lbl.bind("<Button-1>", lambda e: self._retry_queue())
        else:
            self.queue_lbl = None

        nb = ttk.Notebook(root)
        nb.pack(fill=tk.BOTH, expand=True)
        pages_tab = tk.Frame(nb, bg=BG)
        nb.add(pages_tab, text="  Pages  ")
        log_tab = tk.Frame(nb, bg=BG)
        nb.add(log_tab, text="  Email log  ")
        self.nb = nb

        strip_wrap = tk.Frame(pages_tab, bg=STRIP_BG)
        strip_wrap.pack(fill=tk.X, side=tk.BOTTOM)
        self.hbar = tk.Scrollbar(strip_wrap, orient=tk.HORIZONTAL,
                                 command=self._strip_xview, takefocus=0,
                                 elementborderwidth=-1, width=8)
        self.hbar.pack(fill=tk.X, side=tk.BOTTOM)
        self.strip = tk.Canvas(strip_wrap, bg=STRIP_BG, highlightthickness=0,
                               height=self.THUMB + 24)
        self.strip.pack(fill=tk.X)
        self.strip.configure(xscrollcommand=self.hbar.set)
        self.inner = tk.Frame(self.strip, bg=STRIP_BG)
        self._strip_win = self.strip.create_window(0, 0, window=self.inner,
                                                   anchor="nw")
        self.inner.bind("<Configure>", self._strip_resized)
        self.strip.bind("<Configure>", self._strip_canvas_resized)

        self.img_lbl = tk.Label(pages_tab, bg=BG, fg=MUTED, font=(family, 14),
                                text="waiting for the first page…")
        self.img_lbl.pack(fill=tk.BOTH, expand=True)
        self.img_lbl.bind("<Configure>", lambda e: self._reschedule_render())

        self.prev = self._nav_button("\u2039", self._prev)
        self.next = self._nav_button("\u203a", self._next)
        self.prev.place(in_=self.img_lbl, relx=0.0, rely=0.5, anchor="w",
                        x=10, width=52, height=96)
        self.next.place(in_=self.img_lbl, relx=1.0, rely=0.5, anchor="e",
                        x=-10, width=52, height=96)

        self._build_log_tab(log_tab, family)
        nb.bind("<<NotebookTabChanged>>", lambda e: self._refresh_log())

        root.bind("<Left>", lambda e: self._prev())
        root.bind("<Right>", lambda e: self._next())
        root.bind("p", lambda e: self.on_print())
        root.bind("e", lambda e: self.on_email())

        self._poll()

    def _build_log_tab(self, log_tab, family):
        wrap = tk.Frame(log_tab, bg=BG)
        wrap.pack(fill=tk.BOTH, expand=True, padx=12, pady=(12, 4))
        cols = ("ts", "to", "file", "status")
        self.log_tree = ttk.Treeview(wrap, columns=cols, show="headings",
                                     selectmode="browse")
        for cid, text, w in (("ts", "Time", 150), ("to", "To", 220),
                             ("file", "Page", 170), ("status", "Status", 220)):
            self.log_tree.heading(cid, text=text)
            self.log_tree.column(cid, width=w, anchor=tk.W)
        ysb = ttk.Scrollbar(wrap, orient=tk.VERTICAL, command=self.log_tree.yview)
        self.log_tree.configure(yscrollcommand=ysb.set)
        self.log_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        ysb.pack(side=tk.RIGHT, fill=tk.Y)
        self.log_tree.tag_configure("sent", foreground=OK)
        self.log_tree.tag_configure("queued", foreground="#B8860B")
        self.log_tree.tag_configure("failed", foreground=ERR)

        bar = tk.Frame(log_tab, bg=BG)
        bar.pack(fill=tk.X, padx=12, pady=(4, 10))
        self.pending_lbl = tk.Label(bar, text="", fg=MUTED, bg=BG,
                                    font=(family, 11))
        self.pending_lbl.pack(side=tk.LEFT)
        if not self.email_cfg:
            tk.Label(bar, text="email not configured — start with --smtp-* "
                               "options to enable sending",
                     fg=MUTED, bg=BG, font=(family, 11)).pack(side=tk.LEFT,
                                                              padx=12)
        self.retry_all_btn = ttk.Button(bar, text="Deliver all pending",
                                        style="Accent.TButton",
                                        command=self._retry_queue,
                                        state=tk.DISABLED)
        self.retry_all_btn.pack(side=tk.RIGHT)

    def _refresh_log(self):
        if getattr(self, "log_tree", None) is None:
            return
        self.log_tree.delete(*self.log_tree.get_children())
        for row in self.email_log.rows():
            status = row.get("status", "?")
            detail = row.get("detail") or ""
            text = f"{status} — {detail}" if detail else status
            tag = status if status in ("sent", "queued", "failed") else ""
            self.log_tree.insert("", tk.END,
                                 values=(row.get("ts", ""), row.get("to", ""),
                                         row.get("file", ""), text),
                                 tags=(tag,) if tag else ())
        pending = self.mailq.count() if self.mailq else 0
        self.pending_lbl.config(text=f"{pending} not delivered" if pending
                                else "nothing pending")
        if self.mailq:
            self.retry_all_btn.config(state="normal" if pending
                                      else "disabled")

    # ---------- navigation ----------

    def _nav_button(self, glyph, cmd):
        b = tk.Label(self.root, text=glyph, font=("Helvetica", 42, "bold"),
                     fg=DIM, bg=BG, cursor="hand2")
        b._on = False
        b.bind("<Button-1>", lambda e: cmd())
        b.bind("<Enter>", lambda e: b.config(fg=BLUE) if b._on else None)
        b.bind("<Leave>", lambda e: b.config(fg=NAVY if b._on else DIM))
        return b

    def _set_arrow(self, btn, on):
        btn._on = on
        btn.config(fg=NAVY if on else DIM)

    def _prev(self):
        if self.idx > 0:
            self._goto(self.idx - 1)

    def _next(self):
        if self.idx < len(self.files):
            self._goto(self.idx + 1)

    def _goto(self, i):
        if not self.files:
            self.idx = 0
        else:
            self.idx = max(0, min(i, len(self.files)))
        self.render()
        self._update_hud()
        self._highlight_thumb()

    def _update_hud(self):
        n = len(self.files)
        waiting = self.idx >= n
        if waiting:
            self.counter.config(text="next page")
        else:
            self.counter.config(text=f"{self.idx + 1} / {n}" if n else "")
        self.print_btn.config(state="normal" if n and not waiting
                              and not self.printing else "disabled")
        if self.email_btn is not None:
            self.email_btn.config(state="normal" if n and not waiting
                                  and not self.emailing else "disabled")
        self._set_arrow(self.prev, self.idx > 0)
        self._set_arrow(self.next, self.idx < n)

    # ---------- main image ----------

    def _reschedule_render(self):
        if self._render_job is not None:
            self.root.after_cancel(self._render_job)
        self._render_job = self.root.after(150, self.render)

    def render(self):
        self._render_job = None
        if not self.files or self.idx >= len(self.files):
            self.img_lbl.config(image="", text="waiting for the next page…")
            self._photo = None
            return
        w, h = self.img_lbl.winfo_width(), self.img_lbl.winfo_height()
        if w < 60 or h < 60:
            return
        try:
            img = Image.open(self.files[self.idx])
            img.thumbnail((max(60, w - 140), max(60, h - 24)))
            self._photo = ImageTk.PhotoImage(img)
            self.img_lbl.config(image=self._photo, text="")
        except Exception:
            pass  # file mid-write or unreadable; retry on next poll

    # ---------- thumbnail strip ----------

    def _strip_xview(self, *args):
        self.strip.xview(*args)

    def _strip_resized(self, _e):
        self.strip.configure(scrollregion=self.strip.bbox("all"))

    def _strip_canvas_resized(self, e):
        self.strip.itemconfigure(self._strip_win, width=e.width)

    def _build_strip(self):
        self.inner.destroy()
        self.inner = tk.Frame(self.strip, bg=STRIP_BG)
        self._strip_win = self.strip.create_window(0, 0, window=self.inner,
                                                   anchor="nw")
        self.inner.bind("<Configure>", self._strip_resized)
        self._thumbs = {}
        for i, p in enumerate(self.files):
            try:
                img = Image.open(p)
                img.thumbnail((self.THUMB, self.THUMB))
                ph = ImageTk.PhotoImage(img)
            except Exception:
                continue
            fr = tk.Frame(self.inner, bg=PANEL, highlightthickness=2,
                          highlightbackground=BORDER)
            lbl = tk.Label(fr, image=ph, bg=PANEL, cursor="hand2")
            lbl.pack(padx=3, pady=3)
            for w in (fr, lbl):
                w.bind("<Button-1>", lambda e, i=i: self._goto(i))
            fr.grid(row=0, column=i, padx=4, pady=8)
            self._thumbs[i] = (ph, fr)
        slot = tk.Frame(self.inner, bg="#EDF0F4", highlightthickness=2,
                        highlightbackground=BORDER)
        lbl = tk.Label(slot, text="next\npage", fg=MUTED, bg="#EDF0F4",
                       font=("Helvetica", 11, "bold"), cursor="hand2")
        lbl.pack(padx=3, pady=3, ipadx=30, ipady=34)
        for w in (slot, lbl):
            w.bind("<Button-1>", lambda e, i=len(self.files): self._goto(i))
        slot.grid(row=0, column=len(self.files), padx=4, pady=8)
        self._thumbs[len(self.files)] = (None, slot)

    def _highlight_thumb(self):
        for i, (_, fr) in self._thumbs.items():
            fr.config(highlightbackground=BLUE if i == self.idx else BORDER)
        if self.idx in self._thumbs:
            fr = self._thumbs[self.idx][1]
            self.strip.update_idletasks()
            x = fr.winfo_x() + 20
            left = self.strip.canvasx(0)
            right = self.strip.canvasx(self.strip.winfo_width())
            if x < left or x > right - 60:
                span = self.inner.winfo_width() - self.strip.winfo_width()
                frac = x / span if span > 0 else 0.0
                self.strip.xview_moveto(min(1.0, max(0.0, frac)))

    # ---------- folder polling ----------

    def _poll(self):
        try:
            files = list_images(self.save_dir)
            if [p.name for p in files] != [p.name for p in self.files]:
                was_latest = self.idx >= len(self.files) - 1
                had_none = not self.files
                self.files = files
                self._build_strip()
                if had_none or was_latest:
                    self._goto(len(files) - 1)
                else:
                    self.idx = min(self.idx, len(files) - 1)
                    self._update_hud()
            else:
                self._update_hud()
        except Exception:
            pass
        if self.queue_lbl is not None:
            q = self.mailq.count()
            self.queue_lbl.config(text=f"queued: {q}" if q else "")
        self._refresh_log()
        self.root.after(self.POLL_MS, self._poll)

    # ---------- printing ----------

    def _set_status(self, text, color=HDR_TXT):
        self.status.config(text=text, fg=color)

    def on_print(self):
        if not self.files or self.idx >= len(self.files) or self.printing:
            return
        ink = self._ask_quality()
        if ink is None:
            return
        self.printing = True
        self.print_btn.config(state="disabled")
        self._set_status(f"sending to printer (ink {ink}%)…")
        threading.Thread(target=self._print_worker, args=(ink,),
                         daemon=True).start()

    def _ask_quality(self):
        dlg = tk.Toplevel(self.root)
        dlg.title("Print quality")
        dlg.configure(bg=NAVY)
        dlg.transient(self.root)
        dlg.resizable(False, False)
        dlg.grab_set()
        tk.Label(dlg, text="Ink level — lower saves toner", fg="#FFFFFF",
                 bg=NAVY, font=(self.family, 12, "bold")).pack(padx=24,
                                                                pady=(18, 2))
        var = tk.IntVar(value=self.ink_default)
        desc = tk.Label(dlg, text="", fg=HDR_TXT, bg=NAVY,
                        font=(self.family, 10))

        def describe(v):
            v = int(v)
            if v >= 100:
                return "Full quality"
            if v >= 75:
                return "Light saving"
            if v >= 50:
                return "Strong saving"
            return "Maximum saving (faint)"

        scale = tk.Scale(dlg, from_=30, to=100, orient=tk.HORIZONTAL,
                         variable=var, length=280, showvalue=True,
                         command=lambda v: desc.config(text=describe(v)),
                         bg=NAVY, fg="#FFFFFF", troughcolor=NAVY_HI,
                         activebackground=BLUE, highlightthickness=0,
                         font=(self.family, 10))
        scale.pack(padx=24, pady=(4, 2))
        desc.pack(pady=(0, 10))
        btns = tk.Frame(dlg, bg=NAVY)
        btns.pack(pady=(0, 16))
        result = {}

        def ok(_e=None):
            result["ink"] = var.get()
            dlg.destroy()

        ttk.Button(btns, text="Print", style="Accent.TButton",
                   command=ok).pack(side=tk.LEFT, padx=6)
        ttk.Button(btns, text="Cancel",
                   command=dlg.destroy).pack(side=tk.LEFT, padx=6)
        dlg.bind("<Return>", ok)
        dlg.bind("<Escape>", lambda e: dlg.destroy())
        scale.focus_set()
        dlg.wait_window()
        return result.get("ink")

    def _print_worker(self, ink):
        ok = True
        try:
            send_to_printer(self.files[self.idx], self.printer, ink)
            self.ink_default = ink
            msg, color = "sent to printer", OK_HDR
        except Exception as e:
            ok = False
            msg, color = f"failed: {e}", ERR_HDR
        self.root.after(0, self._print_done, ok, msg, color)

    def _print_done(self, ok, msg, color):
        self._set_status(msg, color)
        self.printing = False
        if ok:
            self._goto(len(self.files))   # slide to the waiting slot
        elif self.files and self.idx < len(self.files):
            self.print_btn.config(state="normal")

    def on_email(self):
        if self.email_btn is None or not self.files \
                or self.idx >= len(self.files) or self.emailing:
            return
        to, msg = self._ask_email()
        if not to:
            return
        self.emailing = True
        self.email_btn.config(state="disabled")
        self._set_status(f"sending email to {to}…")
        threading.Thread(target=self._email_worker, args=(to, msg),
                         daemon=True).start()

    def _ask_email(self):
        dlg = tk.Toplevel(self.root)
        dlg.title("Send page by email")
        dlg.configure(bg=NAVY)
        dlg.transient(self.root)
        dlg.resizable(False, False)
        dlg.grab_set()
        tk.Label(dlg, text="Send this page to:", fg="#FFFFFF", bg=NAVY,
                 font=(self.family, 12, "bold")).pack(padx=24, pady=(18, 6))
        var = tk.StringVar(value=self.email_cfg.get("to", ""))
        ent = tk.Entry(dlg, textvariable=var, width=34,
                       font=(self.family, 12), justify=tk.CENTER)
        ent.pack(padx=24, pady=(0, 12), ipady=4)
        tk.Label(dlg, text="Greeting message:", fg=HDR_TXT, bg=NAVY,
                 font=(self.family, 10)).pack(padx=24, pady=(0, 4))
        mvar = tk.StringVar(value=self.email_cfg.get(
            "msg", DEFAULT_EMAIL_MSG))
        ment = tk.Entry(dlg, textvariable=mvar, width=44,
                        font=(self.family, 11))
        ment.pack(padx=24, pady=(0, 14), ipady=4)
        btns = tk.Frame(dlg, bg=NAVY)
        btns.pack(pady=(0, 16))
        result = {}

        def ok(_e=None):
            result["to"] = var.get().strip()
            result["msg"] = mvar.get().strip()
            dlg.destroy()

        ttk.Button(btns, text="Send", style="Accent.TButton",
                   command=ok).pack(side=tk.LEFT, padx=6)
        ttk.Button(btns, text="Cancel",
                   command=dlg.destroy).pack(side=tk.LEFT, padx=6)
        ent.bind("<Return>", ok)
        ment.bind("<Return>", ok)
        dlg.bind("<Escape>", lambda e: dlg.destroy())
        ent.focus_set()
        ent.selection_range(0, tk.END)
        dlg.wait_window()
        to = result.get("to", "")
        if "@" not in to:
            return None, ""
        return to, result.get("msg", "")

    def _email_worker(self, to, msg):
        ok = True
        try:
            send_by_email(self.files[self.idx], {**self.email_cfg, "to": to},
                          msg)
            self.email_cfg["to"] = to
            self.email_cfg["msg"] = msg or DEFAULT_EMAIL_MSG
            if self.email_log is not None:
                self.email_log.record(self.email_log.new_id(), to,
                                      self.files[self.idx].name, "sent")
            msg_ok, color = f"email sent to {to}", OK_HDR
        except Exception as e:
            if self.mailq is not None:
                self.mailq.enqueue(self.files[self.idx], to, msg)
                msg_ok = "no connection — email queued, auto-retry on"
                color = "#FFD166"
            else:
                ok = False
                msg_ok, color = f"failed: {e}", ERR_HDR
        self.root.after(0, self._email_done, ok, msg_ok, color)

    def _retry_queue(self):
        if self.mailq is None or not self.mailq.count():
            return
        self._set_status("retrying queued email…")
        threading.Thread(target=self._retry_worker, daemon=True).start()

    def _retry_worker(self):
        sent, failed = self.mailq.try_send_all()
        if failed:
            msg, color = f"queue: {sent} sent, {failed} still pending", "#FFD166"
        else:
            msg, color = f"queue: {sent} sent", OK_HDR
        self.root.after(0, self._queue_done, msg, color)

    def _queue_done(self, msg, color):
        self._set_status(msg, color)
        self._refresh_log()

    def _email_done(self, ok, msg, color):
        self._set_status(msg, color)
        self.emailing = False
        if ok:
            self._goto(len(self.files))   # slide to the waiting slot
        else:
            self._update_hud()


def load_smtp_password():
    """App password from p.txt next to this script (one line, no quotes)."""
    try:
        return (Path(__file__).resolve().parent / "p.txt").read_text().strip()
    except Exception:
        return None


def main():
    ap = argparse.ArgumentParser(description="Receiver for composed manga pages")
    ap.add_argument("--dir", default="prints", help="folder where received images are saved")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--print", action="store_true", help="also send received images to the printer via lpr")
    ap.add_argument("--printer", help="printer name passed to lpr -P (default: system default printer)")
    ap.add_argument("--email-to", help="default recipient for the Email button")
    ap.add_argument("--email-message", default=os.environ.get("EMAIL_MESSAGE"),
                    help="greeting text in the email body "
                         "(or env EMAIL_MESSAGE)")
    ap.add_argument("--smtp-host", default=os.environ.get("SMTP_HOST"),
                    help="SMTP server (or env SMTP_HOST), e.g. smtp.gmail.com")
    ap.add_argument("--smtp-port", type=int,
                    default=int(os.environ.get("SMTP_PORT", "587")),
                    help="SMTP port: 587 STARTTLS or 465 SSL")
    ap.add_argument("--smtp-user", default=os.environ.get("SMTP_USER"),
                    help="SMTP login (or env SMTP_USER)")
    ap.add_argument("--smtp-pass", default=os.environ.get("SMTP_PASS"),
                    help="SMTP password / app password (or env SMTP_PASS)")
    ap.add_argument("--no-gui", action="store_true", help="run headless (no window, web UI only)")
    args = ap.parse_args()

    email_to = args.email_to or os.environ.get("EMAIL_TO")
    email_msg = args.email_message or DEFAULT_EMAIL_MSG
    smtp_pass = args.smtp_pass or load_smtp_password()
    email_cfg = None
    if args.smtp_host and args.smtp_user and smtp_pass:
        email_cfg = {"to": email_to or "", "msg": email_msg,
                     "host": args.smtp_host,
                     "port": args.smtp_port, "user": args.smtp_user,
                     "pass": smtp_pass}
    elif email_to or args.smtp_host or args.smtp_user or smtp_pass:
        print("email partially configured -> Email button disabled "
              "(need --smtp-host, --smtp-user, --smtp-pass)")
    if email_cfg:
        print(f"email enabled: {email_cfg['user']} "
              f"(default recipient: {email_cfg['to'] or 'asked each time'})")

    save_dir = Path(args.dir).expanduser()
    save_dir.mkdir(parents=True, exist_ok=True)

    email_log = EmailLog()
    mailq = EmailQueue(save_dir, email_cfg, email_log) if email_cfg else None
    print(f"email log: {email_log.path}")
    if mailq:
        mailq.start()
        if mailq.count():
            print(f"{mailq.count()} queued email(s) will be retried")

    server = ThreadingHTTPServer(
        ("0.0.0.0", args.port),
        make_handler(save_dir, args.print, args.printer, email_cfg, mailq))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    print(f"listening on port {args.port}, saving to {save_dir}")
    print(f"  -> web UI: http://localhost:{args.port}")
    for ip in local_ips():
        print(f"  -> spark should use: --push-url http://{ip}:{args.port}/upload")

    if args.no_gui or not GUI_OK:
        if not args.no_gui:
            print(f"GUI unavailable ({GUI_ERR}) -> headless mode. Fixes: "
                  "'sudo apt install python3-tk python3-pil', and run it from the "
                  "laptop's desktop, not over SSH (or 'ssh -X').")
        try:
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            pass
        return

    root = tk.Tk()
    Viewer(root, save_dir, args.printer, email_cfg, mailq, email_log)
    try:
        root.mainloop()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
