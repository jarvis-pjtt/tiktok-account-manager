"""Paths and persistent settings for TikTok Account Manager."""
from __future__ import annotations

import json
import sys
import threading
from pathlib import Path
from typing import Any

# When packaged with PyInstaller, keep data next to the .exe instead of inside the bundle
if getattr(sys, "frozen", False):
    BASE_DIR = Path(sys.executable).resolve().parent
else:
    BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
PROFILES_DIR = DATA_DIR / "profiles"
SETTINGS_FILE = DATA_DIR / "settings.json"

for _d in (DATA_DIR, PROFILES_DIR):
    _d.mkdir(parents=True, exist_ok=True)

DEFAULT_SETTINGS: dict[str, Any] = {
    # --- appearance ---
    "appearance": "dark",             # dark | light
    # --- browser ---
    "chrome_channel": "chrome",       # chrome | msedge | "" (Playwright chromium)
    "headless": False,                # only used by the follower check; login always shows a window
    "window_width": 1280,
    "window_height": 900,
    # --- login ---
    "login_wait_minutes": 5,          # how long auto-login waits for OTP/captcha before handing over
    "home_url": "https://www.tiktok.com/tiktokstudio",   # page opened once the account is logged in
    # --- updates (GitHub Releases) ---
    "update_repo": "",                # "owner/repo" of the public repo holding the releases
    "auto_check_update": True,        # check once, a few seconds after start
    # --- selectors (editable if TikTok changes its layout) ---
    "selectors": {
        "profile_url": "https://www.tiktok.com/profile",
        "followers": "[data-e2e='followers-count']",
        "following": "[data-e2e='following-count']",
        "likes": "[data-e2e='likes-count']",
        "user_title": "[data-e2e='user-title']",
        "user_subtitle": "[data-e2e='user-subtitle']",
    },
}

# Keys left over from the older version of the app (download / split / caption / posting).
# Dropped on load so an old settings.json does not carry them forward.
_OBSOLETE_KEYS = {
    "download_quality", "segment_seconds", "vertical_916", "aspect_mode", "part_overlay",
    "min_last_segment", "max_parts", "output_res", "ffmpeg_path",
    "upload_timeout_sec", "post_confirm_timeout_sec", "type_delay_ms",
    "delay_value", "delay_unit", "run_mode", "distribute_mode", "retry_count",
    "visibility", "hd_upload",
    "auto_caption_from_link", "auto_caption_max_tags", "caption_source",
    "caption_hashtags", "caption_part_style",
    "anthropic_api_key", "ai_model", "ai_language", "ai_style",
}
_OBSOLETE_SELECTORS = {
    "upload_url", "file_input", "caption_editor", "post_button", "post_now_button",
    "success_markers", "upload_done_markers",
}


class Settings:
    """Thread-safe dict-like settings persisted to data/settings.json."""

    def __init__(self, path: Path = SETTINGS_FILE):
        self.path = path
        self._lock = threading.RLock()
        self._data: dict[str, Any] = json.loads(json.dumps(DEFAULT_SETTINGS))
        self.load()

    def load(self) -> None:
        with self._lock:
            if not self.path.exists():
                return
            try:
                saved = json.loads(self.path.read_text(encoding="utf-8"))
            except Exception:
                return
            saved = {k: v for k, v in saved.items() if k not in _OBSOLETE_KEYS}
            if isinstance(saved.get("selectors"), dict):
                saved["selectors"] = {k: v for k, v in saved["selectors"].items()
                                      if k not in _OBSOLETE_SELECTORS}
            self._merge(self._data, saved)

    @staticmethod
    def _merge(base: dict, extra: dict) -> None:
        for k, v in extra.items():
            if isinstance(v, dict) and isinstance(base.get(k), dict):
                Settings._merge(base[k], v)
            else:
                base[k] = v

    def save(self) -> None:
        with self._lock:
            self.path.write_text(json.dumps(self._data, ensure_ascii=False, indent=2), encoding="utf-8")

    def get(self, key: str, default: Any = None) -> Any:
        with self._lock:
            return self._data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        with self._lock:
            self._data[key] = value

    def update(self, values: dict[str, Any]) -> None:
        with self._lock:
            self._data.update(values)

    def selectors(self) -> dict[str, Any]:
        with self._lock:
            return json.loads(json.dumps(self._data.get("selectors", {})))

    def as_dict(self) -> dict[str, Any]:
        with self._lock:
            return json.loads(json.dumps(self._data))
