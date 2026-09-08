"""Read a TikTok verification code (OTP) from an Outlook/Hotmail mailbox.

Supports the common `email|password|refresh_token|client_id` account format: the refresh_token + client_id
are exchanged for a Microsoft access token, then the mailbox is read over IMAP (XOAUTH2). The mail password is
not needed for this and is kept only for reference / manual login.
"""
from __future__ import annotations

import email
import imaplib
import re
import time
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Callable

import requests

IMAP_HOST = "outlook.office365.com"
TOKEN_AUTHORITIES = [
    "https://login.microsoftonline.com/common/oauth2/v2.0/token",
    "https://login.microsoftonline.com/consumers/oauth2/v2.0/token",
]
IMAP_SCOPE = "offline_access https://outlook.office.com/IMAP.AccessAsUser.All"
FOLDERS = ["INBOX", "Junk"]
CODE_RE = re.compile(r"(?<!\d)(\d{6})(?!\d)")
LogFn = Callable[[str], None]


def parse_account_line(line: str) -> dict:
    """'email|pass|refresh_token|client_id' -> dict. Extra fields tolerated."""
    parts = [p.strip() for p in line.split("|")]
    parts += [""] * (4 - len(parts))
    return {"email": parts[0], "password": parts[1], "refresh_token": parts[2], "client_id": parts[3]}


def get_access_token(refresh_token: str, client_id: str) -> str:
    if not (refresh_token and client_id):
        raise RuntimeError("ไม่มี refresh_token / client_id สำหรับอ่านอีเมล")
    last = ""
    for url in TOKEN_AUTHORITIES:
        data = {
            "client_id": client_id,
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "scope": IMAP_SCOPE,
        }
        try:
            r = requests.post(url, data=data, timeout=25)
            j = r.json()
        except Exception as exc:
            last = str(exc)
            continue
        if "access_token" in j:
            return j["access_token"]
        last = j.get("error_description", j.get("error", str(j)))
    raise RuntimeError(f"ขอ access token ไม่สำเร็จ: {str(last)[:160]}")


def _imap_connect(email_addr: str, access_token: str) -> imaplib.IMAP4_SSL:
    auth = f"user={email_addr}\x01auth=Bearer {access_token}\x01\x01"
    m = imaplib.IMAP4_SSL(IMAP_HOST)
    m.authenticate("XOAUTH2", lambda _: auth.encode())
    return m


def _body_text(msg: email.message.Message) -> str:
    chunks = []
    if msg.is_multipart():
        for part in msg.walk():
            ctype = part.get_content_type()
            if ctype in ("text/plain", "text/html"):
                try:
                    chunks.append(part.get_payload(decode=True).decode(part.get_content_charset() or "utf-8", "replace"))
                except Exception:
                    continue
    else:
        try:
            chunks.append(msg.get_payload(decode=True).decode(msg.get_content_charset() or "utf-8", "replace"))
        except Exception:
            pass
    text = " ".join(chunks)
    return re.sub(r"<[^>]+>", " ", text)   # strip HTML tags so codes in markup are still found


def _looks_like_tiktok(msg: email.message.Message, text: str) -> bool:
    hay = f"{msg.get('From','')} {msg.get('Subject','')} {text}".lower()
    return "tiktok" in hay or "verification" in hay or "รหัสยืนยัน" in hay or "ยืนยัน" in hay


def _scan_folder(m: imaplib.IMAP4_SSL, folder: str, not_before: datetime) -> tuple[str, datetime] | None:
    try:
        status, _ = m.select(folder, readonly=True)
        if status != "OK":
            return None
    except Exception:
        return None
    try:
        typ, data = m.search(None, "ALL")
    except Exception:
        return None
    ids = data[0].split()[-20:]
    best: tuple[str, datetime] | None = None
    for i in reversed(ids):
        try:
            typ, md = m.fetch(i, "(RFC822)")
            raw = md[0][1]
        except Exception:
            continue
        msg = email.message_from_bytes(raw)
        try:
            when = parsedate_to_datetime(msg.get("Date"))
            if when.tzinfo is None:
                when = when.replace(tzinfo=timezone.utc)
        except Exception:
            when = datetime.now(timezone.utc)
        if when < not_before:
            continue
        text = _body_text(msg)
        if not _looks_like_tiktok(msg, text):
            continue
        subject = msg.get("Subject", "")
        codes = CODE_RE.findall(f"{subject} {text}")
        if codes:
            if best is None or when > best[1]:
                best = (codes[0], when)
    return best


def read_otp(email_addr: str, refresh_token: str, client_id: str, since_ts: float,
             timeout: float = 120.0, log: LogFn | None = None) -> str:
    """Poll the mailbox until a TikTok 6-digit code newer than *since_ts* appears (or timeout)."""
    log = log or (lambda m: None)
    not_before = datetime.fromtimestamp(since_ts, tz=timezone.utc) - timedelta(seconds=120)
    token = get_access_token(refresh_token, client_id)
    deadline = time.time() + timeout
    while time.time() < deadline:
        best: tuple[str, datetime] | None = None
        try:
            m = _imap_connect(email_addr, token)
        except Exception as exc:
            log(f"เชื่อมต่ออีเมลไม่สำเร็จ: {str(exc)[:120]}")
            time.sleep(5)
            continue
        try:
            for folder in FOLDERS:
                hit = _scan_folder(m, folder, not_before)
                if hit and (best is None or hit[1] > best[1]):
                    best = hit
        finally:
            try:
                m.logout()
            except Exception:
                pass
        if best:
            return best[0]
        log("ยังไม่พบอีเมล OTP กำลังรอ...")
        time.sleep(5)
    return ""
