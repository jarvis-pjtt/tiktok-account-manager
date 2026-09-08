"""Chrome profile management (one persistent user-data-dir per TikTok account)."""
from __future__ import annotations

import json
import re
import shutil
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path

from .config import PROFILES_DIR

META_FILE = "profile.json"


@dataclass
class Profile:
    name: str
    path: Path
    alias: str = ""                   # free-text label shown in the account list
    username: str = ""
    nickname: str = ""
    user_id: str = ""
    followers: int = 0
    following: int = 0
    likes: int = 0
    videos: int = 0
    last_checked: str = ""
    logged_in: bool = False
    note: str = ""
    # --- TikTok login ---
    email: str = ""                   # TikTok login (email or username)
    password_enc: str = ""            # encrypted TikTok password (Windows DPAPI)
    # --- OTP mailbox (a separate Outlook/Hotmail account that receives TikTok's codes) ---
    mail_email: str = ""              # mailbox address (IMAP user)
    mail_pass_enc: str = ""           # encrypted mailbox password (kept for reference)
    mail_token_enc: str = ""          # encrypted Outlook/Hotmail refresh_token (used to read OTP)
    mail_client_id: str = ""          # Microsoft OAuth client id that goes with the refresh token
    extra: dict = field(default_factory=dict)

    # --- TikTok credentials ------------------------------------------
    def set_tiktok(self, email: str, password: str) -> None:
        from .secure import protect

        self.email = email.strip()
        self.password_enc = protect(password) if password else ""

    def get_password(self) -> str:
        from .secure import unprotect

        return unprotect(self.password_enc)

    # --- OTP mailbox credentials -------------------------------------
    def set_mailbox(self, mail_email: str, mail_pass: str = "", mail_token: str = "", mail_client_id: str = "") -> None:
        from .secure import protect

        self.mail_email = mail_email.strip()
        self.mail_pass_enc = protect(mail_pass) if mail_pass else ""
        self.mail_token_enc = protect(mail_token) if mail_token else ""
        self.mail_client_id = mail_client_id.strip()

    def get_mail_token(self) -> str:
        from .secure import unprotect

        return unprotect(self.mail_token_enc)

    @property
    def has_credentials(self) -> bool:
        return bool(self.email and self.password_enc)

    @property
    def has_mail_otp(self) -> bool:
        return bool(self.mail_email and self.mail_token_enc and self.mail_client_id)

    @property
    def user_data_dir(self) -> Path:
        return self.path / "chrome"

    @property
    def profile_url(self) -> str:
        return f"https://www.tiktok.com/@{self.username}" if self.username else ""

    def to_meta(self) -> dict:
        d = asdict(self)
        d.pop("path", None)
        return d

    def save(self) -> None:
        self.path.mkdir(parents=True, exist_ok=True)
        (self.path / META_FILE).write_text(
            json.dumps(self.to_meta(), ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def copy_text(self) -> str:
        """Text placed on clipboard by the 'copy account info' button."""
        lines = [
            f"โปรไฟล์: {self.name}" + (f" ({self.alias})" if self.alias else ""),
            f"ไอดี (username): @{self.username}" if self.username else "ไอดี (username): -",
            f"ชื่อแสดง: {self.nickname or '-'}",
            f"User ID: {self.user_id or '-'}",
            f"ผู้ติดตาม: {self.followers:,}",
            f"กำลังติดตาม: {self.following:,}",
            f"ถูกใจ: {self.likes:,}",
            f"วิดีโอ: {self.videos:,}",
            f"ลิงก์: {self.profile_url or '-'}",
            f"เช็คล่าสุด: {self.last_checked or '-'}",
        ]
        return "\n".join(lines)


class ProfileManager:
    def __init__(self, root: Path = PROFILES_DIR):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _safe_name(name: str) -> str:
        name = re.sub(r"[^\w\-. ก-๙]+", "_", name.strip())
        return name[:50] or f"profile_{int(time.time())}"

    def list(self) -> list[Profile]:
        result = []
        for d in sorted(self.root.iterdir()):
            if d.is_dir():
                result.append(self._load(d))
        return result

    def names(self) -> list[str]:
        return [p.name for p in self.list()]

    def _load(self, d: Path) -> Profile:
        meta_path = d / META_FILE
        meta = {}
        if meta_path.exists():
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
            except Exception:
                meta = {}
        meta.pop("name", None)
        known = {k: v for k, v in meta.items() if k in Profile.__dataclass_fields__}
        return Profile(name=d.name, path=d, **known)

    def get(self, name: str) -> Profile | None:
        d = self.root / name
        return self._load(d) if d.is_dir() else None

    def create(self, name: str) -> Profile:
        safe = self._safe_name(name)
        d = self.root / safe
        if d.exists():
            raise FileExistsError(f"มีโปรไฟล์ชื่อ '{safe}' อยู่แล้ว")
        p = Profile(name=safe, path=d)
        p.user_data_dir.mkdir(parents=True, exist_ok=True)
        p.save()
        return p

    def delete(self, name: str) -> None:
        d = self.root / name
        if d.is_dir():
            shutil.rmtree(d, ignore_errors=True)

    def rename(self, old: str, new: str) -> Profile:
        safe = self._safe_name(new)
        src, dst = self.root / old, self.root / safe
        if dst.exists():
            raise FileExistsError(f"มีโปรไฟล์ชื่อ '{safe}' อยู่แล้ว")
        src.rename(dst)
        return self._load(dst)
