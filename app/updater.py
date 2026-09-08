"""Self-update from GitHub Releases (public repo).

Flow: read the latest release json -> compare versions -> download the .zip asset -> unpack to
%TEMP% -> hand over to a small .bat that waits for this process to exit, copies the new files over
the install folder (never touching `data`), and starts the app again.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

import requests

from . import __version__

API_URL = "https://api.github.com/repos/{repo}/releases/latest"
TIMEOUT = 20
EXE_NAME = "TikTokAccountManager.exe"

# Waits for the app to close, copies the new build over it, restarts it, then deletes itself.
# /E (not /MIR) never deletes anything on the destination, so user data cannot be lost.
UPDATE_BAT = r"""@echo off
setlocal
set LOG=%TEMP%\tam_update.log
echo ---- update start %date% %time% >> "%LOG%"
:wait
tasklist /FI "PID eq {pid}" | find "{pid}" >nul 2>&1
if not errorlevel 1 (
  ping -n 2 127.0.0.1 >nul
  goto wait
)
robocopy "{src}" "{dst}" /E /R:2 /W:1 /XD "{dst}\data" >> "%LOG%" 2>&1
if errorlevel 8 echo ROBOCOPY FAILED >> "%LOG%"
echo ---- restart >> "%LOG%"
start "" "{exe}"
rmdir /s /q "{payload}" >nul 2>&1
del /q "{zip}" >nul 2>&1
(goto) 2>nul & del "%~f0"
"""


def parse_version(text: str | None) -> tuple[int, ...]:
    """'v1.2.3' / '1.2.3-beta' -> (1, 2, 3). Unparsable -> (0,)."""
    nums = re.findall(r"\d+", (text or "").split("+")[0])
    return tuple(int(n) for n in nums[:4]) or (0,)


def is_frozen() -> bool:
    """True when running from the built .exe (auto-update only makes sense there)."""
    return bool(getattr(sys, "frozen", False))


def install_dir() -> Path:
    return Path(sys.executable).resolve().parent if is_frozen() else Path(__file__).resolve().parent.parent


def check(repo: str) -> dict | None:
    """Return {version, url, notes, page, size} for a NEWER release, None when up to date."""
    repo = (repo or "").strip().strip("/")
    if "/" not in repo:
        raise ValueError("ยังไม่ได้ตั้งค่า GitHub repo (รูปแบบ owner/repo) ในหน้าตั้งค่า")
    resp = requests.get(API_URL.format(repo=repo), timeout=TIMEOUT,
                        headers={"Accept": "application/vnd.github+json"})
    if resp.status_code == 404:
        raise RuntimeError(f"ไม่พบ release ใน github.com/{repo} (ยังไม่ได้สร้าง release หรือรีโปเป็น private)")
    resp.raise_for_status()
    data = resp.json()
    zips = [a for a in data.get("assets", []) if str(a.get("name", "")).lower().endswith(".zip")]
    info = {
        "version": (data.get("tag_name") or data.get("name") or "").lstrip("vV").strip(),
        "notes": (data.get("body") or "").strip(),
        "page": data.get("html_url", f"https://github.com/{repo}/releases"),
        "url": zips[0]["browser_download_url"] if zips else "",
        "size": zips[0].get("size", 0) if zips else 0,
    }
    return info if parse_version(info["version"]) > parse_version(__version__) else None


def download(url: str, progress=None) -> Path:
    """Download the release zip to %TEMP%. *progress* gets (downloaded, total) in bytes."""
    dest = Path(tempfile.gettempdir()) / "tam_update.zip"
    with requests.get(url, stream=True, timeout=TIMEOUT) as resp:
        resp.raise_for_status()
        total = int(resp.headers.get("Content-Length") or 0)
        done = 0
        with open(dest, "wb") as fh:
            for chunk in resp.iter_content(chunk_size=256 * 1024):
                fh.write(chunk)
                done += len(chunk)
                if progress:
                    progress(done, total)
    return dest


def _payload_root(folder: Path) -> Path:
    """Zips may wrap everything in one folder; return the directory that holds the .exe."""
    if (folder / EXE_NAME).exists():
        return folder
    subdirs = [d for d in folder.iterdir() if d.is_dir()]
    if len(subdirs) == 1:
        return _payload_root(subdirs[0])
    return folder


def apply_and_restart(zip_path: Path) -> Path:
    """Unpack *zip_path* and start the external updater. The caller must exit right after."""
    if not is_frozen():
        raise RuntimeError("อัปเดตอัตโนมัติใช้ได้เฉพาะเวอร์ชัน .exe ที่บิ้วแล้ว "
                           "(ตอนรันด้วย python ให้ git pull เอา)")
    tmp = Path(tempfile.gettempdir())
    payload = tmp / "tam_update_payload"
    shutil.rmtree(payload, ignore_errors=True)
    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(payload)
    src = _payload_root(payload)
    if not (src / EXE_NAME).exists():
        raise RuntimeError(f"ไฟล์อัปเดตไม่ถูกต้อง — ไม่พบ {EXE_NAME} ใน zip")

    app_dir = install_dir()
    bat = tmp / "tam_update.bat"
    bat.write_text(UPDATE_BAT.format(pid=os.getpid(), src=src, dst=app_dir,
                                     exe=app_dir / EXE_NAME, payload=payload, zip=zip_path),
                   encoding="utf-8")
    subprocess.Popen(["cmd", "/c", str(bat)],
                     creationflags=subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS)
    return bat
