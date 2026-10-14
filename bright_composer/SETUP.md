# bright_composer — Spark to Printer-laptop setup

Direct Ethernet link, no internet required.

```
[Spark: compose_daemon.py] --ethernet--> [Ubuntu laptop: print_receiver.py --> printer]
```

The daemon composes an A4 page, saves it as `assembled_N.png`, and pushes it over HTTP
to the laptop. If the laptop is off/unreachable, pages queue on the Spark in `outbox/`
and are delivered in order when the link comes back. Nothing is lost.

Use these fixed IPs:

| Machine | IP |
|---|---|
| Ubuntu laptop (Ethernet) | `192.168.77.1` |
| Spark (Ethernet) | `192.168.77.2` |

---

## 1. Ubuntu laptop (one-time)

### 1.1 Fixed IP on the Ethernet port

Plug the cable, then (GUI way):

- Settings → Network → click the gear on **Wired** → **IPv4** tab
- IPv4 Method: **Manual**
- Address: `192.168.77.1` — Netmask: `255.255.255.0` — Gateway: leave empty
- Apply, then toggle Wired off/on

Or from the terminal:

```bash
nmcli con show                      # note the wired connection name, e.g. "Wired connection 1"
nmcli con modify "Wired connection 1" ipv4.method manual ipv4.addresses 192.168.77.1/24
nmcli con up "Wired connection 1"
```

### 1.2 Printer

- Settings → Printers → make sure your printer is added and can print a test page
- If `lpr` is missing: `sudo apt install cups-client`

### 1.3 Copy the receiver script

Copy `print_receiver.py` (from this project) to the laptop, e.g. to `~/`:
```bash
mkdir -p ~/printer_server
cp print_receiver.py ~/printer_server/
```

### 1.4 Firewall (only if ufw is active)

```bash
sudo ufw status                 # if "active":
sudo ufw allow 8000/tcp
```

### 1.5 Keep the laptop awake while receiving

Settings → Power → **Automatic Suspend** → off (on battery too).

### 1.6 Run the receiver

One-time install for the GUI (uses Ubuntu's system python3):

```bash
sudo apt install python3-tk python3-pil
```

Then:

```bash
cd ~/printer_server
python3 print_receiver.py --dir ~/prints
```

- Opens a window showing the latest page in `~/prints/` (auto-updates, Print button)
- Print asks for an ink level (slider, 30-100%): lower = lighter grayscale copy
  sent to the printer, to save toner/ink; saved files stay untouched
- `--print` also auto-prints each received page (A4, fit to page)
- `--printer <name>` targets a specific printer instead of the default one
- Without tkinter it falls back to headless mode (receiver + web UI only)
- It prints the URL to use on the Spark at startup (here: `http://192.168.77.1:8000/upload`)

### 1.7 Web UI (fallback)

The same view is served at `http://localhost:8000` while the receiver runs —
handy from another device, or on a machine without tkinter.

### 1.8 Email option (optional)

Adds an **Email** button: clicking it asks for the recipient address (pre-filled
with the last one used) and sends the page you're viewing as an attachment.

**Recommended — launcher script + environment variables:**

```bash
# 1. Set credentials only in your local shell/session:
export SMTP_USER=you@gmail.com
export SMTP_PASS='<app-password>'

# 2. start the app:
./start.sh
```

`start.sh` contains no account-specific values. Credentials stay in the
environment and are not stored in the repository.

**Or run the command directly:**

```bash
python3 print_receiver.py --dir ~/prints --printer <name> \
    --smtp-host smtp.gmail.com --smtp-port 587 \
    --smtp-user you@gmail.com --smtp-pass <app-password>
```

- Only the SMTP credentials are required; `--email-to someone@example.com`
  optionally sets the default recipient shown in the dialog
- Password precedence: `--smtp-pass` → env `SMTP_PASS` → local `p.txt` fallback
- `--email-message "text"` sets the greeting used in the email body
  (also editable in the send dialog; env `EMAIL_MESSAGE`)
- Emails have a clean subject ("La tua pagina a fumetti — BRIGHT"), the
  attachment is named `bright-comic-page.png`, and the page number/filename
  is never shown to the recipient
- Gmail: enable 2FA, then create an App Password (myaccount.google.com → Security)
- SMTP credentials can also come from env vars: `SMTP_HOST`, `SMTP_PORT`,
  `SMTP_USER`, `SMTP_PASS`, `EMAIL_TO`
- If sending fails (no internet), the email is stored in `~/prints/email_queue/`
  and retried automatically every 20 s; the app shows a "queued: N" badge
  (click it to retry immediately). Entries give up after 10 attempts.
- The **Email log** tab shows every email attempt (time, recipient, page,
  status) and has a *Deliver all pending* button; history is kept in
  `logs/email_log.jsonl` next to the script and survives restarts
- Without these options the button is simply not shown; printing is unaffected

---

## 2. Spark (one-time)

### 2.1 Fixed IP on the Ethernet port

```bash
ip link                                # find the port name, usually eth0 or end0
sudo nmcli con add type ethernet con-name laptop ifname eth0 \
     ipv4.method manual ipv4.addresses 192.168.77.2/24
sudo nmcli con up laptop
```

### 2.2 Copy the updated project to the Spark

Replace the old `bright_composer` folder with the current one
(at least: `compose_daemon.py`, `background.png`, `bright/`, `setup_venv.sh`).

If the Spark has no internet, only Pillow is needed:

```bash
bash setup_venv.sh                     # full install (needs internet)
# or, offline:
# .venv/bin/pip install pillow
```

### 2.3 Test the link

With the laptop running the receiver:

```bash
ping -c3 192.168.77.1
curl http://192.168.77.1:8000/health   # should print: ok
```

---

## 3. Everyday use

**Laptop** (each session, or set up as a service later):
```bash
cd ~/printer_server
python3 print_receiver.py --dir ~/prints --print
```

**Spark:**
```bash
cd bright_composer
.venv/bin/python compose_daemon.py --path bright --time 5 \
    --push-url http://192.168.77.1:8000/upload
```

**End-to-end test:** rename an already-composed batch back and watch it print:
```bash
mv bright/20260915-151236_DONE bright/20260915-151236
```

---

## Troubleshooting

| Symptom | Check |
|---|---|
| `ping` fails | Cable seated? `ip a` on both — do the ports show `192.168.77.x`? |
| ping ok, `/health` times out | Receiver running? `sudo ufw status` on laptop |
| Receiver gets file, nothing prints | Default printer set? `lpstat -p -d`. Try `lpr -o media=a4 -o fit-to-page ~/prints/assembled_1.png` manually |
| `lpr: Error - no default destination` | Set a default printer (`lpoptions -d <name>`) or pass `--printer <name>` to the receiver |
| Spark log: `push target unreachable` | Normal when laptop is off — files queue in `outbox/` and go out on the next scan |
| Wrong numbering on laptop | Numbering follows the Spark's `outbox/seq.txt`; check for old outbox files |

Optional Google Drive mode (needs internet) is still available:
```bash
.venv/bin/python compose_daemon.py --drive-credentials <local-credentials.json> --drive-folder <FOLDER_ID>
```
