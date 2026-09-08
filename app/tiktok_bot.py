"""Playwright automation for TikTok: open a profile's Chrome, log in, read account stats."""
from __future__ import annotations

import json
import re
import time
from datetime import datetime
from typing import Callable

from .config import Settings
from .profiles import Profile

LogFn = Callable[[str], None]

LOGIN_EMAIL_URL = "https://www.tiktok.com/login/phone-or-email/email"


class NotLoggedIn(Exception):
    pass


def short_error(exc: BaseException, limit: int = 300) -> str:
    """First line of an exception message (Playwright errors carry a long call log)."""
    text = str(exc).strip() or exc.__class__.__name__
    first = text.splitlines()[0].strip()
    if "Opening in existing browser session" in text:
        first = "Chrome ของโปรไฟล์นี้เปิดอยู่แล้ว (เปิดซ้ำไม่ได้) — ปิดหน้าต่างเดิมก่อน"
    return first[:limit]


class Cancelled(Exception):
    pass


def _num(text: str) -> int:
    """'1.2M' -> 1200000, '12.5K' -> 12500, '1,234' -> 1234."""
    if text is None:
        return 0
    if isinstance(text, (int, float)):
        return int(text)
    t = str(text).strip().upper().replace(",", "")
    m = re.match(r"([\d.]+)\s*([KMB]?)", t)
    if not m:
        return 0
    val = float(m.group(1))
    mult = {"": 1, "K": 1_000, "M": 1_000_000, "B": 1_000_000_000}[m.group(2)]
    return int(val * mult)


class TikTokBrowser:
    """One Chrome window bound to a profile's persistent user-data-dir."""

    def __init__(self, profile: Profile, settings: Settings, log: LogFn | None = None,
                 headless: bool | None = None, stop_flag: Callable[[], bool] | None = None):
        self.profile = profile
        self.settings = settings
        self.sel = settings.selectors()
        self.log = log or (lambda m: None)
        self.headless = settings.get("headless", False) if headless is None else headless
        self.stop_flag = stop_flag or (lambda: False)
        self._pw = None
        self.context = None

    # ------------------------------------------------------------------ lifecycle
    def __enter__(self):
        self.open()
        return self

    def __exit__(self, *exc):
        self.close()

    def open(self):
        from playwright.sync_api import sync_playwright

        self._pw = sync_playwright().start()
        channel = self.settings.get("chrome_channel", "chrome") or None
        args = [
            f"--window-size={self.settings.get('window_width', 1280)},{self.settings.get('window_height', 900)}",
            "--disable-blink-features=AutomationControlled",
            "--no-first-run",
            "--no-default-browser-check",
        ]
        kwargs = dict(
            user_data_dir=str(self.profile.user_data_dir),
            headless=self.headless,
            viewport=None,
            no_viewport=True,
            locale="th-TH",
            args=args,
            # Playwright disables extensions by default; drop those switches so extensions can be
            # installed from the Chrome Web Store (they stay in this profile) and actually run.
            ignore_default_args=["--enable-automation", "--disable-extensions",
                                 "--disable-component-extensions-with-background-pages"],
            timeout=120_000,
        )
        try:
            self.context = self._pw.chromium.launch_persistent_context(channel=channel, **kwargs) if channel \
                else self._pw.chromium.launch_persistent_context(**kwargs)
        except Exception as exc:
            if "Opening in existing browser session" in str(exc) or not channel:
                raise
            self.log(f"เปิด Chrome ({channel}) ไม่ได้: {short_error(exc)} — ลองใช้ Chromium ของ Playwright")
            self.context = self._pw.chromium.launch_persistent_context(**kwargs)
        self.context.set_default_timeout(30_000)

    def close(self):
        try:
            if self.context:
                self.context.close()
        except Exception:
            pass
        try:
            if self._pw:
                self._pw.stop()
        except Exception:
            pass
        self.context = None
        self._pw = None

    @property
    def is_open(self) -> bool:
        try:
            return self.context is not None and len(self.context.pages) > 0
        except Exception:
            return False

    def is_alive(self) -> bool:
        """True while the window is still open AND the browser still answers.

        `context.pages` alone is not enough: after Chrome is closed by the user it can keep
        reporting a stale page, so a cheap round-trip is used to confirm the connection.
        """
        try:
            if self.context is None or not self.context.pages:
                return False
            self.context.cookies("https://www.tiktok.com")   # raises once Chrome is gone
            return True
        except Exception:
            return False

    def page(self):
        pages = self.context.pages
        return pages[0] if pages else self.context.new_page()

    # ------------------------------------------------------------------ helpers
    def _check_stop(self):
        if self.stop_flag():
            raise Cancelled("หยุดโดยผู้ใช้")

    def _sleep(self, seconds: float):
        end = time.time() + seconds
        while time.time() < end:
            self._check_stop()
            time.sleep(min(0.5, max(0.0, end - time.time())))

    def _first(self, page, selectors: list[str] | str, timeout: float = 0):
        """Return the first visible locator among *selectors* (or None)."""
        if isinstance(selectors, str):
            selectors = [selectors]
        deadline = time.time() + timeout
        while True:
            for s in selectors:
                try:
                    loc = page.locator(s).first
                    if loc.count() and loc.is_visible():
                        return loc
                except Exception:
                    continue
            if time.time() >= deadline:
                return None
            self._sleep(0.5)

    def has_session(self) -> bool:
        try:
            cookies = self.context.cookies("https://www.tiktok.com")
        except Exception:
            return False
        return any(c.get("name") == "sessionid" and c.get("value") for c in cookies)

    # ------------------------------------------------------------------ login
    def open_login(self):
        page = self.page()
        page.goto("https://www.tiktok.com/login", wait_until="domcontentloaded")

    def _login_challenge(self, page) -> str:
        """Detect the login speed bumps: 'captcha', 'verify' (choose a method), 'code' (enter code), or ''."""
        if self._first(page, ["#captcha_container", ".captcha-verify-container", "[class*='captcha']",
                              "iframe[src*='captcha']"]) is not None:
            return "captcha"
        # code-entry screen (a 6-digit field is already visible)
        if self._first(page, ["input[name='verificationCode']", "input[placeholder*='รหัสยืนยัน']",
                              "input[placeholder*='verification' i]", "input[placeholder*='code' i]:not([type='password'])",
                              "input[maxlength='6']", "text=/enter.*verification code/i", "text=/กรอกรหัสยืนยัน/",
                              "text=/ป้อนรหัส/"]) is not None:
            return "code"
        # method chooser ("verify it's you" -> pick email)
        if self._first(page, ["text=/ตรวจสอบยืนยันว่าเป็นคุณ/", "text=/ยืนยันตัวตน/",
                              "text=/verify (that )?it.?s you/i", "text=/verify your identity/i"]) is not None:
            return "verify"
        return ""

    def _click_email_verify_option(self, page) -> bool:
        """On the 'verify it's you' chooser, click the e-mail method card."""
        try:
            marked = page.evaluate(
                """() => {
                    const snap = document.evaluate(
                        "//*[normalize-space(text())='อีเมล' or normalize-space(text())='Email']",
                        document, null, XPathResult.ORDERED_NODE_SNAPSHOT_TYPE, null);
                    for (let i = 0; i < snap.snapshotLength; i++) {
                        let el = snap.snapshotItem(i);
                        for (let n = el, d = 0; n && d < 6; n = n.parentElement, d++) {
                            const t = (n.innerText || '');
                            if (t.includes('@') || n.getAttribute('role') === 'button'
                                || getComputedStyle(n).cursor === 'pointer') {
                                n.setAttribute('data-ttsm-verify', '1');
                                return true;
                            }
                        }
                    }
                    return false;
                }"""
            )
        except Exception:
            marked = False
        target = None
        if marked:
            target = self._first(page, ["[data-ttsm-verify='1']"], timeout=2)
        if target is None:
            target = self._first(page, ["div[role='button']:has-text('อีเมล')", "text=/^อีเมล$/", "text=/^Email$/"], timeout=2)
        if target is None:
            return False
        try:
            target.click()
            self._sleep(1.5)
            self.log("เลือกวิธียืนยันแบบอีเมลแล้ว")
            return True
        except Exception:
            return False

    def login_with_password(self, email: str, password: str, wait_minutes: float = 5.0) -> bool:
        """Fill TikTok's email/password form. CAPTCHA or verification codes are left to the user (we wait)."""
        page = self.page()
        self.log("เปิดหน้าล็อกอินด้วยอีเมล...")
        page.goto(LOGIN_EMAIL_URL, wait_until="domcontentloaded")
        user_box = self._first(page, ["input[name='username']", "input[type='text'][placeholder*='อีเมล']",
                                      "input[type='text'][placeholder*='mail' i]"], timeout=30)
        if user_box is None:
            # older layout: choose "Use phone / email / username" then "Log in with email or username"
            for sel in ["a[href*='phone-or-email']", "text=/ใช้โทรศัพท์.*อีเมล/", "text=/Use phone.*email/i"]:
                loc = self._first(page, [sel], timeout=3)
                if loc is not None:
                    loc.click()
                    break
            for sel in ["a[href*='/email']", "text=/เข้าสู่ระบบด้วยอีเมล/", "text=/Log in with email/i"]:
                loc = self._first(page, [sel], timeout=3)
                if loc is not None:
                    loc.click()
                    break
            user_box = self._first(page, ["input[name='username']"], timeout=20)
        if user_box is None:
            raise RuntimeError("ไม่พบช่องกรอกอีเมลในหน้าล็อกอิน (หน้าเว็บอาจเปลี่ยน)")
        pass_box = self._first(page, ["input[type='password']"], timeout=10)
        if pass_box is None:
            raise RuntimeError("ไม่พบช่องกรอกรหัสผ่าน")

        user_box.click()
        page.keyboard.press("Control+A")
        user_box.type(email, delay=25)
        pass_box.click()
        page.keyboard.press("Control+A")
        pass_box.type(password, delay=25)
        self._sleep(0.5)
        since_ts = time.time()
        btn = self._first(page, ["button[data-e2e='login-button']", "button[type='submit']"], timeout=5)
        if btn is not None:
            btn.click()
        else:
            page.keyboard.press("Enter")
        self.log("ส่งข้อมูลล็อกอินแล้ว รอผล...")

        deadline = time.time() + wait_minutes * 60
        warned = ""
        otp_done = False
        while time.time() < deadline:
            self._check_stop()
            if self.has_session():
                self.log("ล็อกอินสำเร็จ ✓")
                return True
            try:
                if not self.context.pages:
                    return False
                kind = self._login_challenge(page)
            except Exception:
                kind = ""
            if kind == "verify":
                # always click the e-mail method - helps both auto-OTP and manual entry
                if self._click_email_verify_option(page):
                    self._sleep(2)
                    continue
            if kind == "code" and not otp_done and self.profile.has_mail_otp:
                if self._auto_fill_otp(page, since_ts):
                    otp_done = True
                    self._sleep(2)
                    continue
            if kind and kind != warned:
                warned = kind
                if kind == "captcha":
                    self.log("⚠ TikTok ขอให้ยืนยัน CAPTCHA — โปรดแก้ในหน้าต่าง Chrome (โปรแกรมจะรอ)")
                elif kind in ("code", "verify") and self.profile.has_mail_otp:
                    self.log("⚠ TikTok ขอรหัสยืนยันทางอีเมล — กำลังจัดการอัตโนมัติ")
                elif kind in ("code", "verify"):
                    self.log("⚠ TikTok ขอรหัสยืนยันทางอีเมล — โปรดกรอกในหน้าต่าง Chrome (โปรแกรมจะรอ)")
            err = self._first(page, ["text=/รหัสผ่านไม่ถูกต้อง|บัญชีไม่ถูกต้อง|ไม่พบบัญชี/",
                                     "text=/incorrect|doesn't match|not found|too many attempts/i"])
            if err is not None:
                try:
                    msg = (err.text_content() or "").strip()[:120]
                except Exception:
                    msg = "อีเมลหรือรหัสผ่านไม่ถูกต้อง"
                raise RuntimeError(f"ล็อกอินไม่ผ่าน: {msg}")
            time.sleep(2)
        return False

    def _auto_fill_otp(self, page, since_ts: float) -> bool:
        """Read the 6-digit code from the linked mailbox and type it into the verification field."""
        code_input = self._first(page, ["input[placeholder*='6']", "input[maxlength='6']",
                                        "input[name='verificationCode']", "input[name='code']",
                                        "input[placeholder*='รหัส']"], timeout=3)
        if code_input is None:
            return False
        self.log("กำลังอ่านรหัส OTP จากอีเมล...")
        try:
            from .mail_otp import read_otp

            code = read_otp(self.profile.mail_email, self.profile.get_mail_token(), self.profile.mail_client_id,
                            since_ts, timeout=120, log=self.log)
        except Exception as exc:
            self.log(f"อ่าน OTP ไม่สำเร็จ: {short_error(exc)} — กรอกเองในหน้าต่าง Chrome")
            return False
        if not code:
            self.log("ไม่พบรหัส OTP ในอีเมล — กรอกเองในหน้าต่าง Chrome")
            return False
        code_input.click()
        page.keyboard.press("Control+A")
        code_input.type(code, delay=80)
        self._sleep(0.5)
        nxt = self._first(page, ["button:has-text('ถัดไป')", "button:has-text('Next')",
                                 "button[type='submit']", "button[data-e2e='login-button']"], timeout=3)
        if nxt is not None:
            try:
                nxt.click()
            except Exception:
                page.keyboard.press("Enter")
        self.log(f"กรอกรหัส OTP {code} แล้ว")
        return True

    def ensure_logged_in(self, wait_minutes: float = 5.0) -> bool:
        """True when a session exists; tries the stored email/password first when it does not."""
        if self.has_session():
            return True
        if self.profile.has_credentials:
            self.log("ไม่มี session — ล็อกอินด้วยอีเมล/รหัสผ่านที่บันทึกไว้")
            return self.login_with_password(self.profile.email, self.profile.get_password(), wait_minutes)
        return False

    def wait_until_closed(self, on_login: Callable[[], None] | None = None, poll: float = 2.0,
                          login_retries: int = 3):
        """Block until the user closes the window. Calls on_login once a session cookie appears."""
        attempts_left = login_retries if on_login else 0
        next_try = 0.0
        while True:
            if not self.is_alive():
                return
            if attempts_left > 0 and time.time() >= next_try and self.has_session():
                if next_try == 0.0:
                    next_try = time.time() + 6      # let TikTok finish its post-login redirect first
                    continue
                attempts_left -= 1
                try:
                    on_login()
                    attempts_left = 0
                except Exception as exc:
                    self.log(f"อ่านข้อมูลโปรไฟล์ไม่สำเร็จ: {short_error(exc)}"
                             + (" — จะลองใหม่อีกครั้ง" if attempts_left else ""))
                    next_try = time.time() + 10
            time.sleep(poll)

    # ------------------------------------------------------------------ profile stats
    def _account_info(self, page) -> dict:
        """TikTok's own account endpoint (uses the session cookies) -> username / user_id / nickname."""
        try:
            resp = page.request.get(
                "https://www.tiktok.com/passport/web/account/info/?aid=1459&app_language=en", timeout=15000)
            data = (resp.json() or {}).get("data") or {}
            if data.get("username"):
                return {
                    "username": data["username"],
                    "nickname": data.get("screen_name", "") or "",
                    "user_id": str(data.get("user_id_str") or data.get("user_id") or ""),
                }
        except Exception:
            pass
        return {}

    @staticmethod
    def _username_from_url(url: str) -> str:
        if "/@" not in url:
            return ""
        return url.split("/@", 1)[1].split("?")[0].split("/")[0].strip()

    def _find_username(self, page) -> tuple[str, dict]:
        info = self._account_info(page)
        if info.get("username"):
            return info["username"], info
        # fallback 1: /profile redirects to /@username
        try:
            page.goto(self.sel.get("profile_url", "https://www.tiktok.com/profile"), wait_until="domcontentloaded")
            deadline = time.time() + 20
            while time.time() < deadline:
                name = self._username_from_url(page.url)
                if name:
                    return name, {}
                if "/login" in page.url:
                    break
                self._sleep(0.5)
        except Exception:
            pass
        # fallback 2: the "Profile" link in the side navigation
        try:
            if "tiktok.com" not in page.url or "/login" in page.url:
                page.goto("https://www.tiktok.com/", wait_until="domcontentloaded")
            for sel in ("[data-e2e='nav-profile']", "a[href*='/@']:has-text('Profile')", "a[href*='/@']:has-text('โปรไฟล์')"):
                loc = page.locator(sel).first
                if loc.count():
                    name = self._username_from_url(loc.get_attribute("href") or "")
                    if name:
                        return name, {}
        except Exception:
            pass
        return "", {}

    def fetch_profile_stats(self) -> dict:
        """Read the logged-in account's username and stats (opens its own tab, leaves the user's tab alone)."""
        if not self.has_session():
            raise NotLoggedIn("โปรไฟล์นี้ยังไม่ได้ล็อกอิน TikTok")
        page = self.context.new_page()
        try:
            return self._fetch_profile_stats(page)
        finally:
            try:
                if len(self.context.pages) > 1:
                    page.close()
            except Exception:
                pass

    def _fetch_profile_stats(self, page) -> dict:
        username, info = self._find_username(page)
        if not username:
            raise NotLoggedIn("หาชื่อบัญชีไม่พบ (อาจยังล็อกอินไม่เสร็จ หรือ TikTok ขอยืนยันตัวตน)")
        stats: dict = {"username": username, **info}
        if self._username_from_url(page.url) != username:
            last_exc: Exception | None = None
            for attempt in range(3):
                try:
                    page.goto(f"https://www.tiktok.com/@{username}", wait_until="domcontentloaded")
                    last_exc = None
                    break
                except Exception as exc:          # TikTok sometimes answers with an error code (bot check)
                    last_exc = exc
                    self._sleep(3.0 * (attempt + 1))
            if last_exc is not None:
                if info:
                    self.log(f"เปิดหน้าโปรไฟล์ไม่ได้ ({short_error(last_exc)}) — ได้เฉพาะชื่อบัญชี ยอดผู้ติดตามจะอัปเดตครั้งถัดไป")
                    stats["partial"] = True
                    return stats
                raise
        self._sleep(1.0)

        # 1) structured data embedded by TikTok (most reliable)
        try:
            raw = page.locator("#__UNIVERSAL_DATA_FOR_REHYDRATION__").text_content(timeout=5000)
            data = json.loads(raw or "{}")
            user_info = data.get("__DEFAULT_SCOPE__", {}).get("webapp.user-detail", {}).get("userInfo", {})
            user = user_info.get("user", {}) or {}
            st = user_info.get("stats", {}) or {}
            if user:
                stats.update({
                    "username": user.get("uniqueId") or username,
                    "nickname": user.get("nickname", ""),
                    "user_id": str(user.get("id", "")),
                    "followers": _num(st.get("followerCount")),
                    "following": _num(st.get("followingCount")),
                    "likes": _num(st.get("heartCount") or st.get("heart")),
                    "videos": _num(st.get("videoCount")),
                })
                return stats
        except Exception:
            pass

        # 2) fall back to visible counters
        page.wait_for_selector(self.sel.get("followers", "[data-e2e='followers-count']"), timeout=20000)
        for key, sel_key in (("followers", "followers"), ("following", "following"), ("likes", "likes")):
            try:
                stats[key] = _num(page.locator(self.sel[sel_key]).first.text_content(timeout=3000))
            except Exception:
                stats[key] = 0
        if not stats.get("nickname"):
            try:
                stats["nickname"] = (page.locator(self.sel["user_subtitle"]).first.text_content(timeout=3000) or "").strip()
            except Exception:
                stats["nickname"] = ""
        return stats

    def update_profile_stats(self) -> Profile:
        stats = self.fetch_profile_stats()
        p = self.profile
        p.username = stats.get("username", p.username)
        p.nickname = stats.get("nickname", p.nickname)
        p.user_id = stats.get("user_id", p.user_id)
        p.followers = stats.get("followers", p.followers)
        p.following = stats.get("following", p.following)
        p.likes = stats.get("likes", p.likes)
        p.videos = stats.get("videos", p.videos)
        p.logged_in = True
        if not stats.get("partial"):
            p.last_checked = datetime.now().strftime("%Y-%m-%d %H:%M")
        p.save()
        return p


def check_profile_once(profile: Profile, settings: Settings, log: LogFn | None = None) -> Profile:
    """Open the profile's browser, refresh follower stats, close it."""
    with TikTokBrowser(profile, settings, log=log) as bot:
        return bot.update_profile_stats()
