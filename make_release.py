"""Build the .exe and pack the release zip.

Run:  python make_release.py      (or double-click build.bat)

Produces:
  dist/TikTokAccountManager/                 - the app folder, copy it anywhere
  dist/TikTokAccountManager-v<ver>.zip       - upload this to the GitHub Release (tag v<ver>)
"""
from __future__ import annotations

import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
NAME = "TikTokAccountManager"
DIST = ROOT / "dist" / NAME


def version() -> str:
    text = (ROOT / "app" / "__init__.py").read_text(encoding="utf-8")
    m = re.search(r'__version__\s*=\s*["\']([^"\']+)', text)
    if not m:
        sys.exit("อ่านเลขเวอร์ชันจาก app/__init__.py ไม่ได้")
    return m.group(1)


def run(args: list[str]) -> None:
    print(">", " ".join(args), flush=True)
    if subprocess.call(args) != 0:
        sys.exit("คำสั่งล้มเหลว: " + " ".join(args))


def build() -> None:
    run([sys.executable, "-m", "pip", "install", "-q", "pyinstaller"])
    run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onedir", "--windowed",
         "--name", NAME, "--collect-all", "playwright",
         "--hidden-import", "PIL._tkinter_finder", "main.py"])
    if not (DIST / f"{NAME}.exe").exists():
        sys.exit("บิ้วไม่สำเร็จ — ไม่พบ .exe")
    shutil.copy(ROOT / "README.md", DIST / "README.md")


def pack(ver: str) -> Path:
    """Zip the build without `data` (the updater must never ship or overwrite user data)."""
    out = ROOT / "dist" / f"{NAME}-v{ver}.zip"
    out.unlink(missing_ok=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(DIST.rglob("*")):
            rel = path.relative_to(DIST)
            if rel.parts and rel.parts[0] == "data":
                continue
            if path.is_file():
                zf.write(path, rel)
    return out


def main() -> None:
    ver = version()
    print(f"=== building {NAME} v{ver} ===", flush=True)
    build()
    zip_path = pack(ver)
    size = zip_path.stat().st_size / 1048576
    print("\nBUILD OK")
    print(f"  โปรแกรม : {DIST / (NAME + '.exe')}")
    print(f"  ไฟล์อัปโหลดขึ้น GitHub Release : {zip_path}  ({size:.0f} MB, tag = v{ver})")


if __name__ == "__main__":
    main()
