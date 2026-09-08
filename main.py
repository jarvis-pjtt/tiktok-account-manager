"""TikTok Account Manager - entry point.

Run:  python main.py
"""
from __future__ import annotations

import sys


def _check_deps() -> list[str]:
    missing = []
    for mod, pkg in (("playwright", "playwright"), ("requests", "requests")):
        try:
            __import__(mod)
        except ImportError:
            missing.append(pkg)
    return missing


def _setup_frozen_io() -> None:
    """Windowed (no console) builds have no stdout/stderr; send them to a log file."""
    if sys.stdout is not None and sys.stderr is not None:
        return
    from pathlib import Path

    base = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).parent
    log_dir = base / "data"
    log_dir.mkdir(parents=True, exist_ok=True)
    stream = open(log_dir / "app.log", "a", encoding="utf-8", buffering=1)
    if sys.stdout is None:
        sys.stdout = stream
    if sys.stderr is None:
        sys.stderr = stream


def main() -> int:
    _setup_frozen_io()
    if sys.version_info < (3, 10):
        print("ต้องใช้ Python 3.10 ขึ้นไป")
        return 1
    missing = _check_deps()
    if missing:
        print("ยังไม่ได้ติดตั้งแพ็กเกจ:", ", ".join(missing))
        print("รัน:  pip install -r requirements.txt")
        return 1
    from app.gui import run

    run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
