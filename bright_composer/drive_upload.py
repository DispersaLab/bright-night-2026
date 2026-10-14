import json
import logging
import re
from pathlib import Path

log = logging.getLogger("manga-daemon.drive")

SCOPES = ["https://www.googleapis.com/auth/drive"]
NAME_RE = re.compile(r"assembled_(\d+)\.png")

_state = None
_counter = 0


def enabled():
    return _state is not None


def _load_credentials(credentials_path):
    from google.auth.transport.requests import Request

    raw = json.loads(Path(credentials_path).read_text())
    if "installed" in raw or "web" in raw:
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow

        token_path = Path(credentials_path).parent / "token.json"
        creds = None
        if token_path.exists():
            creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except Exception:
                log.exception("stored token refresh failed, starting new consent flow")
                creds = None
        if not creds or not creds.valid:
            flow = InstalledAppFlow.from_client_secrets_file(credentials_path, SCOPES)
            creds = flow.run_local_server(port=0)
            token_path.write_text(creds.to_json(), encoding="utf-8")
            log.info("oauth token saved to %s", token_path)
        return creds
    from google.oauth2 import service_account

    return service_account.Credentials.from_service_account_file(credentials_path, scopes=SCOPES)


def init(credentials_path, folder_id):
    global _state, _counter
    from googleapiclient.discovery import build

    creds = _load_credentials(credentials_path)
    service = build("drive", "v3", credentials=creds, cache_discovery=False)
    about = service.about().get(fields="user").execute()
    _state = {"service": service, "folder_id": folder_id}

    page_token = None
    while True:
        resp = service.files().list(
            q=f"'{folder_id}' in parents and trashed = false",
            fields="nextPageToken, files(name)",
            pageSize=1000,
            pageToken=page_token,
        ).execute()
        for f in resp.get("files", []):
            m = NAME_RE.fullmatch(f["name"])
            if m:
                _counter = max(_counter, int(m.group(1)))
        page_token = resp.get("nextPageToken")
        if not page_token:
            break
    log.info("drive upload ready as %s, folder %s (next file: assembled_%d.png)",
             about["user"]["emailAddress"], folder_id, _counter + 1)


def upload(path):
    global _counter
    from googleapiclient.http import MediaFileUpload

    if _state is None:
        raise RuntimeError("drive upload not configured")
    _counter += 1
    filename = f"assembled_{_counter}.png"
    media = MediaFileUpload(str(path), mimetype="image/png", resumable=False)
    meta = {"name": filename, "parents": [_state["folder_id"]]}
    res = _state["service"].files().create(body=meta, media_body=media, fields="id, webViewLink").execute()
    log.info("uploaded %s -> %s", filename, res.get("webViewLink"))
    return res["id"]
