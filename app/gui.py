"""Desktop GUI for TikTok Account Manager (tkinter/ttk, flat WinForms-style dark theme).

Account list on the left, control panel for the selected account on the right, action bar at the bottom.
"""
from __future__ import annotations

import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import messagebox, ttk

from . import __version__
from .config import SETTINGS_FILE, Settings
from .profiles import ProfileManager
from .theme import (C, FONT, FONT_B, FONT_MONO, FlatButton, FlatMenu, bordered, checkbox, entry,
                    frame, label, set_readonly_text, style_ttk, textbox, use_theme)
from .tiktok_bot import TikTokBrowser, short_error

GROUP_IID = "grp:default"
MASK = "••••••••"


def open_folder(path: Path):
    path = Path(path)
    path.mkdir(parents=True, exist_ok=True)
    if sys.platform == "win32":
        os.startfile(str(path))  # type: ignore[attr-defined]
    else:
        subprocess.Popen(["xdg-open", str(path)])


def popup(master, anchor, items: list[tuple[str, object] | None]):
    """Drop a menu right under *anchor*. A None entry draws a separator."""
    FlatMenu(master, items).post(anchor.winfo_rootx(), anchor.winfo_rooty() + anchor.winfo_height())


def center_on(window, master=None, width: int | None = None, height: int | None = None):
    """Place *window* over *master* (or on screen when master is None), kept inside the desktop."""
    window.update_idletasks()
    w = width or window.winfo_width() or window.winfo_reqwidth()
    h = height or window.winfo_height() or window.winfo_reqheight()
    if master is not None and master.winfo_ismapped():
        x = master.winfo_rootx() + (master.winfo_width() - w) // 2
        y = master.winfo_rooty() + (master.winfo_height() - h) // 3
    else:
        x = (window.winfo_screenwidth() - w) // 2
        y = (window.winfo_screenheight() - h) // 3
    x = max(0, min(x, window.winfo_screenwidth() - w))
    y = max(0, min(y, window.winfo_screenheight() - h - 40))
    window.geometry(f"{w}x{h}+{x}+{y}")


class Dialog(tk.Toplevel):
    """Modal window using the flat palette, centred over its parent."""

    def __init__(self, master, title: str, width: int, height: int, resizable: bool = False):
        super().__init__(master, bg=C["bg"])
        self.withdraw()                       # position first, then show — avoids the top-left flash
        self.title(title)
        self.resizable(resizable, resizable)
        self.transient(master)
        self.result = None
        center_on(self, master, width, height)
        self.after_idle(self._show)           # runs once the subclass has finished building

    def _show(self):
        self.deiconify()
        try:
            self.grab_set()                   # only works on a mapped window
        except tk.TclError:
            pass
        self.lift()
        self.focus_set()


class NameDialog(Dialog):
    """Single-line prompt (new account / rename)."""

    def __init__(self, master, title: str, prompt: str, value: str = ""):
        super().__init__(master, title, 400, 140)
        self.columnconfigure(0, weight=1)
        label(self, prompt, bg=C["bg"]).grid(row=0, column=0, sticky="w", padx=14, pady=(16, 4))
        self.entry = entry(self)
        self.entry.insert(0, value)
        self.entry.grid(row=1, column=0, sticky="ew", padx=14, ipady=3)
        self.entry.bind("<Return>", lambda e: self._ok())
        bar = frame(self, bg=C["bg"])
        bar.grid(row=2, column=0, sticky="e", padx=12, pady=14)
        FlatButton(bar, "ตกลง", self._ok, w=86, bg=C["accent"], hover=C["accent_hover"]).pack(side="right", padx=3)
        FlatButton(bar, "ยกเลิก", self.destroy, w=86).pack(side="right", padx=3)
        self.after(100, self.entry.focus_set)

    def _ok(self):
        self.result = self.entry.get().strip()
        self.destroy()


class CredentialsDialog(Dialog):
    """TikTok login + the mailbox that receives its OTP.

    Result: dict(email, password, mail_email, mail_pass, mail_token, mail_client_id) or None.
    An all-empty dict means 'clear'.
    """

    def __init__(self, master, profile):
        super().__init__(master, f"ล็อกอิน TikTok — {profile.name}", 580, 400)
        self.columnconfigure(0, weight=1)

        s1 = frame(self, bg=C["panel"])
        s1.grid(row=0, column=0, sticky="ew", padx=10, pady=(10, 6))
        s1.columnconfigure(1, weight=1)
        label(s1, "① บัญชี TikTok (ใช้ล็อกอิน)", bold=True).grid(row=0, column=0, columnspan=2, sticky="w", padx=8, pady=(8, 4))
        label(s1, "อีเมล / ชื่อผู้ใช้:").grid(row=1, column=0, sticky="w", padx=8, pady=4)
        self.email = entry(s1)
        self.email.insert(0, profile.email)
        self.email.grid(row=1, column=1, sticky="ew", padx=8, pady=4, ipady=3)
        label(s1, "รหัสผ่าน TikTok:").grid(row=2, column=0, sticky="w", padx=8, pady=(4, 10))
        self.password = entry(s1, show="•")
        self.password.grid(row=2, column=1, sticky="ew", padx=8, pady=(4, 10), ipady=3)

        s2 = frame(self, bg=C["panel"])
        s2.grid(row=1, column=0, sticky="ew", padx=10, pady=6)
        s2.columnconfigure(0, weight=1)
        label(s2, "② อีเมลรับ OTP (Outlook/Hotmail)", bold=True).grid(row=0, column=0, sticky="w", padx=8, pady=(8, 2))
        label(s2, "วางทั้งบรรทัด:  email|pass|refresh_token|client_id", dim=True).grid(row=1, column=0, sticky="w", padx=8)
        self.mail_combo = entry(s2)
        self.mail_combo.grid(row=2, column=0, sticky="ew", padx=8, pady=4, ipady=3)
        row = frame(s2, bg=C["panel"])
        row.grid(row=3, column=0, sticky="ew", padx=8, pady=(2, 10))
        FlatButton(row, "แยกข้อมูล ▾", self._parse_mail, w=100, h=22).pack(side="left")
        self.mail_status = label(row, "", dim=True)
        self.mail_status.pack(side="left", padx=8)
        if profile.mail_email:
            self.mail_combo.insert(0, f"{profile.mail_email}|••••|••••|{profile.mail_client_id}")
            self.mail_status.configure(text=f"บันทึกไว้: {profile.mail_email}")
        self._mail = {
            "email": profile.mail_email,
            "password": "",
            "refresh_token": "keep" if profile.mail_token_enc else "",
            "client_id": profile.mail_client_id,
        }

        self.show_var = tk.BooleanVar(value=False)
        cb = checkbox(self, "แสดงรหัสผ่าน", self.show_var,
                      lambda: self.password.configure(show="" if self.show_var.get() else "•"))
        cb.configure(bg=C["bg"], activebackground=C["bg"])
        cb.grid(row=2, column=0, sticky="w", padx=12, pady=2)
        label(self, "รหัสผ่าน/refresh_token เข้ารหัสด้วย Windows DPAPI • บัญชี ② ใช้อ่าน OTP อัตโนมัติ\n"
                    "ถ้าเจอ CAPTCHA ต้องกดเองในหน้าต่าง Chrome", dim=True, bg=C["bg"], justify="left"
              ).grid(row=3, column=0, sticky="w", padx=12, pady=4)
        bar = frame(self, bg=C["bg"])
        bar.grid(row=4, column=0, sticky="e", padx=10, pady=10)
        FlatButton(bar, "บันทึก + ล็อกอิน", self._ok, w=126, bg=C["accent"], hover=C["accent_hover"]).pack(side="right", padx=3)
        FlatButton(bar, "ยกเลิก", self.destroy, w=86).pack(side="right", padx=3)
        FlatButton(bar, "ลบทั้งหมด", self._clear, w=86, bg=C["danger"], hover=C["danger_hover"]).pack(side="right", padx=3)
        self.email.focus_set()

    def _parse_mail(self):
        line = self.mail_combo.get().strip()
        if "|" not in line or "••" in line:
            return
        from .mail_otp import parse_account_line

        self._mail = parse_account_line(line)
        self.mail_status.configure(text=f"อ่านแล้ว: {self._mail['email']}"
                                   + ("  ✓ พร้อมอ่าน OTP" if self._mail["refresh_token"] and self._mail["client_id"] else "  (ไม่มี token)"))

    def _ok(self):
        self._parse_mail()
        self.result = {
            "email": self.email.get().strip(),
            "password": self.password.get(),
            "mail_email": self._mail.get("email", ""),
            "mail_pass": "" if self._mail.get("password") in ("", None) else self._mail["password"],
            "mail_token": "" if self._mail.get("refresh_token") in ("", None) else self._mail["refresh_token"],
            "mail_client_id": self._mail.get("client_id", ""),
        }
        self.destroy()

    def _clear(self):
        self.result = {"email": "", "password": "", "mail_email": "", "mail_pass": "", "mail_token": "", "mail_client_id": ""}
        self.destroy()


class SettingsDialog(Dialog):
    ROWS = [
        ("chrome_channel", "เบราว์เซอร์ (chrome / msedge / ว่าง=Chromium):"),
        ("window_width", "ความกว้างหน้าต่าง Chrome:"),
        ("window_height", "ความสูงหน้าต่าง Chrome:"),
        ("login_wait_minutes", "รอล็อกอินอัตโนมัติสูงสุด (นาที):"),
        ("home_url", "หน้าที่เปิดหลังล็อกอิน:"),
        ("update_repo", "GitHub repo สำหรับอัปเดต (owner/repo):"),
    ]

    def __init__(self, master, settings: Settings, log):
        super().__init__(master, "ตั้งค่า", 600, 360)
        self.settings, self.log = settings, log
        self.columnconfigure(1, weight=1)
        self.widgets: dict[str, tk.Entry] = {}
        for r, (key, text) in enumerate(self.ROWS):
            label(self, text, bg=C["bg"]).grid(row=r, column=0, sticky="w", padx=12, pady=5)
            e = entry(self)
            e.insert(0, str(settings.get(key, "")))
            e.grid(row=r, column=1, sticky="ew", padx=12, pady=5, ipady=3)
            self.widgets[key] = e
        r = len(self.ROWS)
        self.headless_var = tk.BooleanVar(value=bool(settings.get("headless", False)))
        cb = checkbox(self, "ซ่อนหน้าต่าง Chrome ตอนเช็คสถานะบัญชี (headless)", self.headless_var)
        cb.configure(bg=C["bg"], activebackground=C["bg"])
        cb.grid(row=r, column=0, columnspan=2, sticky="w", padx=10, pady=(6, 0))
        self.autoupd_var = tk.BooleanVar(value=bool(settings.get("auto_check_update", True)))
        cb2 = checkbox(self, "ตรวจหาเวอร์ชันใหม่อัตโนมัติตอนเปิดโปรแกรม", self.autoupd_var)
        cb2.configure(bg=C["bg"], activebackground=C["bg"])
        cb2.grid(row=r + 1, column=0, columnspan=2, sticky="w", padx=10, pady=(0, 4))
        r += 1
        bar = frame(self, bg=C["bg"])
        bar.grid(row=r + 1, column=0, columnspan=2, sticky="ew", padx=10, pady=10)
        FlatButton(bar, "แก้ selectors", lambda: os.startfile(str(SETTINGS_FILE)), w=110).pack(side="left", padx=3)  # type: ignore[attr-defined]
        FlatButton(bar, "โฟลเดอร์ข้อมูล", lambda: open_folder(SETTINGS_FILE.parent), w=110).pack(side="left", padx=3)
        FlatButton(bar, "บันทึก", self._save, w=90, bg=C["accent"], hover=C["accent_hover"]).pack(side="right", padx=3)
        label(self, "โปรไฟล์ Chrome ของแต่ละบัญชีเก็บที่ data/profiles/<ชื่อ>/chrome", dim=True, bg=C["bg"]
              ).grid(row=r + 2, column=0, columnspan=2, sticky="w", padx=12)

    def _save(self):
        values = {}
        for key, w in self.widgets.items():
            val = w.get().strip()
            if key in ("window_width", "window_height"):
                try:
                    val = int(float(val))
                except ValueError:
                    val = self.settings.get(key)
            elif key == "login_wait_minutes":
                try:
                    val = float(val)
                except ValueError:
                    val = self.settings.get(key)
            values[key] = val
        values["headless"] = self.headless_var.get()
        values["auto_check_update"] = self.autoupd_var.get()
        self.settings.update(values)
        self.settings.save()
        self.log("บันทึกการตั้งค่าแล้ว")
        self.destroy()


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.settings = Settings()
        use_theme(self.settings.get("appearance", "dark"))
        self.title(f"TikTok Account Manager v{__version__}")
        self.minsize(880, 520)
        center_on(self, None, 980, 600)
        self.configure(bg=C["bg"])

        self.pm = ProfileManager()
        self._login_bots: dict[str, TikTokBrowser] = {}
        self._busy_profiles: set[str] = set()
        self._log_q: queue.Queue[str] = queue.Queue()
        self._ui_q: queue.Queue = queue.Queue()     # UI work handed from worker threads to the main loop
        self.hide_var = tk.BooleanVar(value=False)
        self._log_visible = True

        style_ttk(self)
        self._build()
        self.after(200, self._drain_log)
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.log(f"พร้อมใช้งาน v{__version__} — {len(self.pm.names())} บัญชี")
        if self.settings.get("auto_check_update", True):
            self.after(3000, lambda: self.check_update(manual=False))

    # ------------------------------------------------------------------ infra
    def log(self, msg: str):
        self._log_q.put(f"[{datetime.now():%H:%M:%S}] {msg}")

    def _ui(self, fn):
        """Queue *fn* to run on the main thread (Tkinter must only be touched there)."""
        self._ui_q.put(fn)

    def _drain_log(self):
        try:
            while True:
                line = self._log_q.get_nowait()
                self.log_box.configure(state="normal")
                self.log_box.insert("end", line + "\n")
                self.log_box.see("end")
                self.log_box.configure(state="disabled")
        except queue.Empty:
            pass
        for _ in range(50):                       # run queued UI work from worker threads
            try:
                fn = self._ui_q.get_nowait()
            except queue.Empty:
                break
            try:
                fn()
            except Exception as exc:
                self.log(f"UI error: {exc}")
        self.after(200, self._drain_log)

    def _bg(self, fn, *args, name: str = "worker"):
        t = threading.Thread(target=fn, args=args, daemon=True, name=name)
        t.start()
        return t

    def _on_close(self):
        if self._login_bots and not messagebox.askyesno(
                "ยืนยัน", "ยังมีหน้าต่าง Chrome เปิดอยู่ ต้องการปิดโปรแกรมหรือไม่?"):
            return
        for bot in list(self._login_bots.values()):
            bot.close()
        self.destroy()

    # ------------------------------------------------------------------ updates
    def check_update(self, manual: bool = False):
        repo = (self.settings.get("update_repo") or "").strip()
        if not repo:
            if manual:
                messagebox.showinfo("อัปเดต", "ยังไม่ได้ตั้งค่า GitHub repo\n\n"
                                              "ไปที่ ตั้งค่า → 'GitHub repo สำหรับอัปเดต' แล้วใส่ owner/repo")
            return
        self._bg(self._update_check_worker, repo, manual, name="update-check")

    def _update_check_worker(self, repo: str, manual: bool):
        from . import updater

        try:
            info = updater.check(repo)
        except Exception as exc:
            self.log(f"ตรวจหาอัปเดตไม่สำเร็จ: {short_error(exc)}")
            if manual:
                self._ui(lambda: messagebox.showerror("อัปเดต", short_error(exc)))
            return
        if info is None:
            self.log(f"ใช้เวอร์ชันล่าสุดอยู่แล้ว (v{__version__})")
            if manual:
                self._ui(lambda: messagebox.showinfo("อัปเดต", f"ใช้เวอร์ชันล่าสุดอยู่แล้ว (v{__version__})"))
            return
        self.log(f"พบเวอร์ชันใหม่: v{info['version']} (ตอนนี้ v{__version__})")
        self._ui(lambda: self._offer_update(info))

    def _offer_update(self, info: dict):
        from . import updater

        notes = info["notes"][:400] + ("..." if len(info["notes"]) > 400 else "")
        size = f"\nขนาด {info['size'] / 1048576:.0f} MB" if info.get("size") else ""
        if not updater.is_frozen():
            messagebox.showinfo("มีเวอร์ชันใหม่", f"เวอร์ชันใหม่ v{info['version']} (ตอนนี้ v{__version__})\n\n"
                                                 f"{notes}\n\nตอนนี้รันจากซอร์สโค้ด อัปเดตอัตโนมัติใช้ได้เฉพาะเวอร์ชัน .exe\n"
                                                 f"โหลดเองที่: {info['page']}")
            return
        if self._login_bots:
            messagebox.showwarning("อัปเดต", "ปิดหน้าต่าง Chrome ของทุกบัญชีก่อนอัปเดต")
            return
        if not info["url"]:
            messagebox.showinfo("อัปเดต", f"release นี้ไม่มีไฟล์ .zip แนบมา\nเปิดดูเองที่: {info['page']}")
            return
        if messagebox.askyesno("มีเวอร์ชันใหม่",
                               f"เวอร์ชันใหม่ v{info['version']} (ตอนนี้ v{__version__}){size}\n\n{notes}\n\n"
                               "ดาวน์โหลดและอัปเดตเลยไหม? (โปรแกรมจะปิดแล้วเปิดใหม่เอง)"):
            self._bg(self._update_apply_worker, info, name="update-apply")

    def _update_apply_worker(self, info: dict):
        from . import updater

        try:
            self.log(f"กำลังดาวน์โหลด v{info['version']}...")
            last = [0]

            def progress(done, total):
                pct = int(done * 100 / total) if total else 0
                if pct >= last[0] + 20:                     # log every 20%
                    last[0] = pct
                    self.log(f"ดาวน์โหลด {pct}%")

            zip_path = updater.download(info["url"], progress=progress)
            self.log("ดาวน์โหลดเสร็จ กำลังติดตั้ง — โปรแกรมจะปิดแล้วเปิดใหม่เอง")
            updater.apply_and_restart(zip_path)
        except Exception as exc:
            self.log(f"อัปเดตไม่สำเร็จ: {short_error(exc)}")
            self._ui(lambda: messagebox.showerror("อัปเดตไม่สำเร็จ", short_error(exc)))
            return
        self._ui(self._quit_for_update)

    def _quit_for_update(self):
        for bot in list(self._login_bots.values()):
            bot.close()
        self.destroy()

    def _home_url(self) -> str:
        return (self.settings.get("home_url") or "https://www.tiktok.com/tiktokstudio").strip()

    def _wait_minutes(self) -> float:
        try:
            return max(0.5, float(self.settings.get("login_wait_minutes", 5) or 5))
        except (TypeError, ValueError):
            return 5.0

    # ------------------------------------------------------------------ layout
    def _build(self):
        self.configure(bg=C["bg"])
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)

        body = frame(self, bg=C["bg"])
        body.grid(row=0, column=0, sticky="nsew", padx=8, pady=(8, 4))
        body.columnconfigure(0, weight=1)
        body.rowconfigure(0, weight=1)

        self._build_list(body)
        self._build_panel(body)
        self._build_action_bar()
        self._build_log()
        self.refresh_profiles()

    # --- left: account list -------------------------------------------
    def _build_list(self, parent):
        box = bordered(parent)
        box.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        box.columnconfigure(0, weight=1)
        box.rowconfigure(0, weight=1)

        cols = [("alias", "Alias", 110), ("followers", "ผู้ติดตาม", 80),
                ("status", "สถานะ", 120), ("note", "Description", 180)]
        self.tree = ttk.Treeview(box, columns=[c[0] for c in cols], show="tree headings",
                                 selectmode="extended", style="RAM.Treeview")
        self.tree.heading("#0", text="Username", anchor="w")
        self.tree.column("#0", width=190, minwidth=120, stretch=False)
        for cid, title, width in cols:
            self.tree.heading(cid, text=title, anchor="w")
            self.tree.column(cid, width=width, minwidth=50, anchor="w", stretch=(cid == "note"))
        vsb = ttk.Scrollbar(box, orient="vertical", command=self.tree.yview, style="RAM.Vertical.TScrollbar")
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.grid(row=0, column=0, sticky="nsew", padx=(1, 0), pady=1)
        vsb.grid(row=0, column=1, sticky="ns", pady=1, padx=(0, 1))
        self.tree.tag_configure("group", foreground=C["group"])
        self.tree.tag_configure("st_open", foreground="#4da3ff")
        self.tree.tag_configure("st_busy", foreground="#e0a33a")
        self.tree.tag_configure("st_in", foreground=C["fg"])
        self.tree.tag_configure("st_out", foreground=C["dim"])
        self.tree.bind("<<TreeviewSelect>>", lambda e: self._sync_panel())
        self.tree.bind("<Double-1>", self._on_double_click)
        self.tree.bind("<Button-3>", self._on_right_click)

    # --- right: selected-account panel --------------------------------
    def _build_panel(self, parent):
        panel = frame(parent, bg=C["bg"], width=300)
        panel.grid(row=0, column=1, sticky="nsew")
        panel.grid_propagate(False)
        panel.columnconfigure(0, weight=1)

        head = frame(panel, bg=C["bg"])
        head.grid(row=0, column=0, sticky="ew", pady=(0, 2))
        label(head, "บัญชีที่เลือก", dim=True, bg=C["bg"]).pack(side="left")
        FlatButton(head, "⟳", self.refresh_profiles, w=26, h=22).pack(side="right")

        self.sel_name = label(panel, "—", bold=True, bg=C["bg"], anchor="w")
        self.sel_name.grid(row=1, column=0, sticky="ew")

        info = frame(panel, bg=C["bg"])
        info.grid(row=2, column=0, sticky="ew", pady=(2, 4))
        info.columnconfigure(0, weight=3)
        info.columnconfigure(1, weight=2)
        label(info, "ไอดี TikTok", dim=True, bg=C["bg"]).grid(row=0, column=0, sticky="w")
        label(info, "ผู้ติดตาม", dim=True, bg=C["bg"]).grid(row=0, column=1, sticky="w", padx=(4, 0))
        self.sel_user = entry(info, readonly=True)          # display only
        self.sel_user.grid(row=1, column=0, sticky="ew", ipady=2)
        self.sel_followers = entry(info, readonly=True)     # display only
        self.sel_followers.grid(row=1, column=1, sticky="ew", padx=(4, 0), ipady=2)

        row = frame(panel, bg=C["bg"])
        row.grid(row=3, column=0, sticky="ew", pady=4)
        row.columnconfigure(0, weight=1)
        FlatButton(row, "เปิดบัญชี", self.open_profile_browser, h=26,
                   bg=C["accent"], hover=C["accent_hover"]).grid(row=0, column=0, sticky="ew")
        FlatButton(row, "ล็อกอินอัตโนมัติ", self.auto_login, w=110, h=26,
                   bg=C["purple"], hover=C["purple_hover"]).grid(row=0, column=1, sticky="ew", padx=(4, 0))

        arow = frame(panel, bg=C["bg"])
        arow.grid(row=4, column=0, sticky="ew", pady=(6, 2))
        arow.columnconfigure(0, weight=1)
        label(arow, "อีเมลที่ใช้ล็อกอิน", dim=True, bg=C["bg"]).grid(row=0, column=0, sticky="w")
        self.email_entry = entry(arow, readonly=True)      # display only (แก้ผ่านปุ่ม 'อีเมล/รหัส')
        self.email_entry.grid(row=1, column=0, sticky="ew", ipady=2)
        FlatButton(arow, "อีเมล/รหัส", self.set_credentials, w=92).grid(row=1, column=1, padx=(4, 0))

        brow = frame(panel, bg=C["bg"])
        brow.grid(row=5, column=0, sticky="ew", pady=(6, 2))
        brow.columnconfigure(0, weight=1)
        label(brow, "Alias (ชื่อเล่นที่เราตั้งเอง)", dim=True, bg=C["bg"]).grid(row=0, column=0, sticky="w")
        self.alias_entry = entry(brow)
        self.alias_entry.grid(row=1, column=0, sticky="ew", ipady=2)
        FlatButton(brow, "Set Alias", self.set_alias, w=92).grid(row=1, column=1, padx=(4, 0))

        label(panel, "Description", dim=True, bg=C["bg"], anchor="w").grid(row=6, column=0, sticky="ew", pady=(6, 1))
        panel.rowconfigure(7, weight=1)
        self.note_box = textbox(panel, height=6)
        self.note_box.grid(row=7, column=0, sticky="nsew")

        r1 = frame(panel, bg=C["bg"])
        r1.grid(row=8, column=0, sticky="ew", pady=(4, 2))
        r1.columnconfigure((0, 1), weight=1, uniform="p")
        FlatButton(r1, "Set Description", self.set_note).grid(row=0, column=0, sticky="ew", padx=(0, 2))
        self.util_btn = FlatButton(r1, "Account Utilities", self.account_utilities_menu)
        self.util_btn.grid(row=0, column=1, sticky="ew", padx=(2, 0))

        r2 = frame(panel, bg=C["bg"])
        r2.grid(row=9, column=0, sticky="ew")
        r2.columnconfigure((0, 1), weight=1, uniform="p")
        FlatButton(r2, "Edit Theme", self.toggle_theme).grid(row=0, column=0, sticky="ew", padx=(0, 2))
        FlatButton(r2, "ตั้งค่าโปรแกรม", self.open_settings).grid(row=0, column=1, sticky="ew", padx=(2, 0))

    # --- bottom: action bar -------------------------------------------
    def _build_action_bar(self):
        bar = frame(self, bg=C["bg"])
        bar.grid(row=1, column=0, sticky="ew", padx=8, pady=(0, 4))
        self.add_btn = FlatButton(bar, "เพิ่มบัญชี  ▾", self.add_account_menu, w=110)
        self.add_btn.pack(side="left")
        FlatButton(bar, "ลบ", self.delete_profile, w=80, bg=C["danger"], hover=C["danger_hover"]).pack(side="left", padx=4)
        cb = checkbox(bar, "ซ่อนไอดี", self.hide_var, self.refresh_profiles)
        cb.configure(bg=C["bg"], activebackground=C["bg"])
        cb.pack(side="left", padx=8)
        self.more_btn = FlatButton(bar, "⋯", self.more_menu, w=32)
        self.more_btn.pack(side="left", padx=(8, 0))
        self.log_btn = FlatButton(bar, "ซ่อน Log", self.toggle_log, w=90)
        self.log_btn.pack(side="right")

    def _build_log(self):
        self.logf = bordered(self)
        self.logf.grid(row=2, column=0, sticky="nsew", padx=8, pady=(0, 8))
        self.logf.columnconfigure(0, weight=1)
        self.logf.rowconfigure(0, weight=1)
        self.rowconfigure(2, weight=0, minsize=130)
        self.log_box = tk.Text(self.logf, height=6, bg=C["list"], fg=C["fg"], font=FONT_MONO, relief="flat",
                               bd=0, highlightthickness=0, insertbackground=C["fg"], state="disabled",
                               padx=5, pady=3, wrap="none")
        self.log_box.grid(row=0, column=0, sticky="nsew", padx=1, pady=1)
        vsb = ttk.Scrollbar(self.logf, orient="vertical", command=self.log_box.yview, style="RAM.Vertical.TScrollbar")
        self.log_box.configure(yscrollcommand=vsb.set)
        vsb.grid(row=0, column=1, sticky="ns", padx=(0, 1), pady=1)
        self.log_box.bind("<Button-3>", lambda e: popup(self, self.log_btn, [("ล้าง Log", self.clear_log)]))

    def clear_log(self):
        self.log_box.configure(state="normal")
        self.log_box.delete("1.0", "end")
        self.log_box.configure(state="disabled")

    def toggle_log(self):
        self._log_visible = not self._log_visible
        if self._log_visible:
            self.logf.grid()
            self.rowconfigure(2, minsize=130)
            self.log_btn.set_text("ซ่อน Log")
        else:
            self.logf.grid_remove()
            self.rowconfigure(2, minsize=0)
            self.log_btn.set_text("แสดง Log")

    def toggle_theme(self):
        mode = "light" if self.settings.get("appearance", "dark") == "dark" else "dark"
        self.settings.set("appearance", mode)
        self.settings.save()
        old_log = self.log_box.get("1.0", "end").rstrip()
        use_theme(mode)
        style_ttk(self)
        for child in self.winfo_children():
            child.destroy()
        self._build()
        if old_log:
            self.log_box.configure(state="normal")
            self.log_box.insert("1.0", old_log + "\n")
            self.log_box.see("end")
            self.log_box.configure(state="disabled")

    def open_settings(self):
        dlg = SettingsDialog(self, self.settings, self.log)
        self.wait_window(dlg)

    # ================================================================== list
    def refresh_profiles(self):
        selected = set(self._selected_profiles(require=False))
        for iid in self.tree.get_children(""):
            self.tree.delete(iid)
        self.tree.insert("", "end", iid=GROUP_IID, text="Default", open=True, tags=("group",))
        hide = self.hide_var.get()
        for p in self.pm.list():
            if p.name in self._login_bots:
                status, tag = "● เปิด Chrome อยู่", "st_open"
            elif p.name in self._busy_profiles:
                status, tag = "● กำลังทำงาน", "st_busy"
            elif p.logged_in:
                status, tag = "● ล็อกอินแล้ว", "st_in"
            else:
                status, tag = "○ ยังไม่ล็อกอิน", "st_out"
            self.tree.insert(GROUP_IID, "end", iid=p.name, text=f"  {MASK if hide else p.name}", tags=(tag,),
                             values=(p.alias or "", f"{p.followers:,}", status,
                                     (p.note or "").replace("\n", " ")[:80]))
        for name in selected:
            if self.tree.exists(name):
                self.tree.selection_add(name)
        self._sync_panel()

    def _selected_profiles(self, require: bool = True) -> list[str]:
        sel = [i for i in self.tree.selection() if i != GROUP_IID]
        if not sel and require:
            messagebox.showinfo("เลือกบัญชี", "กรุณาเลือกบัญชีในรายการก่อน")
        return sel

    def _current(self):
        sel = self._selected_profiles(require=False)
        return self.pm.get(sel[0]) if sel else None

    def _sync_panel(self):
        p = self._current()
        hide = self.hide_var.get()
        self.sel_name.configure(text=(MASK if hide else p.name) if p else "—")
        for widget, value in ((self.sel_user, f"@{p.username}" if p and p.username else ""),
                              (self.email_entry, p.email if p else "")):
            set_readonly_text(widget, MASK if (hide and value) else value)
        set_readonly_text(self.sel_followers, f"{p.followers:,}" if p else "")
        self.alias_entry.delete(0, "end")
        self.alias_entry.insert(0, p.alias if p else "")
        self.note_box.delete("1.0", "end")
        if p:
            self.note_box.insert("1.0", p.note)

    def _on_double_click(self, event):
        iid = self.tree.identify_row(event.y)
        if iid and iid != GROUP_IID:
            self.open_profile_browser()

    def _on_right_click(self, event):
        iid = self.tree.identify_row(event.y)
        if iid and iid != GROUP_IID:
            if iid not in self.tree.selection():
                self.tree.selection_set(iid)
            self._sync_panel()
        FlatMenu(self, [
            ("เปิดบัญชี (Chrome)", self.open_profile_browser),
            ("ล็อกอินอัตโนมัติ", self.auto_login),
            ("อีเมล/รหัสผ่าน...", self.set_credentials),
            None,
            ("เปลี่ยนชื่อ...", self.rename_profile),
            ("เช็คสถานะ/ผู้ติดตาม", lambda: self.check_followers(False)),
            ("คัดลอกข้อมูล", self.copy_profile_info),
            ("เปิดโฟลเดอร์", self.open_profile_folder),
            None,
            ("ลบบัญชี", self.delete_profile),
        ]).post(event.x_root, event.y_root)

    # ================================================================== menus
    def add_account_menu(self):
        popup(self, self.add_btn, [
            ("สร้างบัญชีใหม่ (ล็อกอินเองใน Chrome)", self.create_profile),
            ("สร้าง + ตั้งอีเมล/รหัสผ่าน", self.create_profile_with_credentials),
        ])

    def more_menu(self):
        """Program-wide tools (per-account tools live in Account Utilities)."""
        popup(self, self.more_btn, [
            ("เช็คสถานะทุกบัญชี", lambda: self.check_followers(True)),
            ("ล้างสถานะค้าง (ทุกบัญชี)", self.clear_stuck_status),
            None,
            ("ตรวจหาเวอร์ชันใหม่", lambda: self.check_update(manual=True)),
            None,
            ("เปิดโฟลเดอร์ข้อมูล", lambda: open_folder(self.pm.root)),
            ("ล้าง Log", self.clear_log),
        ])

    def account_utilities_menu(self):
        popup(self, self.util_btn, [
            ("เช็คสถานะ/ผู้ติดตาม", lambda: self.check_followers(False)),
            ("คัดลอกข้อมูลบัญชี", self.copy_profile_info),
            ("เปิดโฟลเดอร์โปรไฟล์", self.open_profile_folder),
            ("เปลี่ยนชื่อบัญชี...", self.rename_profile),
            None,
            ("ลบบัญชี", self.delete_profile),
        ])

    # ================================================================== accounts
    def _ask_name(self, title: str, prompt: str, value: str = "") -> str | None:
        dlg = NameDialog(self, title, prompt, value)
        self.wait_window(dlg)
        return dlg.result or None

    def create_profile(self, then_credentials: bool = False):
        name = self._ask_name("สร้างบัญชีใหม่", "ชื่อบัญชี (ใช้เรียกในโปรแกรม):")
        if not name:
            return None
        try:
            p = self.pm.create(name)
        except FileExistsError as exc:
            messagebox.showerror("สร้างไม่ได้", str(exc))
            return None
        self.log(f"สร้างบัญชี '{p.name}' แล้ว — กด 'เปิดบัญชี' เพื่อล็อกอิน TikTok")
        self.refresh_profiles()
        self.tree.selection_set(p.name)
        self._sync_panel()
        if then_credentials:
            self.set_credentials()
        return p

    def create_profile_with_credentials(self):
        self.create_profile(then_credentials=True)

    def rename_profile(self):
        names = self._selected_profiles()
        if not names:
            return
        old = names[0]
        if old in self._login_bots or old in self._busy_profiles:
            messagebox.showwarning("เปลี่ยนชื่อไม่ได้", "ปิด Chrome ของบัญชีนั้นก่อน")
            return
        new = self._ask_name("เปลี่ยนชื่อบัญชี", "ชื่อใหม่:", old)
        if not new or new == old:
            return
        try:
            p = self.pm.rename(old, new)
        except (FileExistsError, OSError) as exc:
            messagebox.showerror("เปลี่ยนชื่อไม่ได้", str(exc))
            return
        self.log(f"เปลี่ยนชื่อ '{old}' → '{p.name}' แล้ว")
        self.refresh_profiles()

    def set_alias(self):
        p = self._current()
        if p is None:
            messagebox.showinfo("เลือกบัญชี", "กรุณาเลือกบัญชีในรายการก่อน")
            return
        p.alias = self.alias_entry.get().strip()
        p.save()
        self.log(f"[{p.name}] ตั้ง alias = {p.alias or '(ว่าง)'}")
        self.refresh_profiles()

    def set_note(self):
        p = self._current()
        if p is None:
            messagebox.showinfo("เลือกบัญชี", "กรุณาเลือกบัญชีในรายการก่อน")
            return
        p.note = self.note_box.get("1.0", "end").strip()
        p.save()
        self.log(f"[{p.name}] บันทึก description แล้ว")
        self.refresh_profiles()

    # --- open account (Chrome window) ---------------------------------
    def open_profile_browser(self):
        names = self._selected_profiles()
        for name in names:
            if name in self._login_bots or name in self._busy_profiles:
                self.log(f"[{name}] Chrome ของบัญชีนี้เปิดอยู่แล้ว (หรือกำลังเปิด) "
                         "— ถ้าปิดหน้าต่างไปแล้ว ให้กด 'ล้างสถานะค้าง' ในเมนู ⋯")
                continue
            self._busy_profiles.add(name)          # reserve immediately so a second click cannot relaunch
            self.refresh_profiles()
            self._bg(self._login_worker, name, name=f"login-{name}")

    def _login_worker(self, name: str):
        profile = self.pm.get(name)
        if profile is None:
            self._busy_profiles.discard(name)
            return
        bot = TikTokBrowser(profile, self.settings, log=lambda m: self.log(f"[{name}] {m}"), headless=False)
        try:
            self.log(f"[{name}] กำลังเปิด Chrome...")
            bot.open()
            self._login_bots[name] = bot
            self._busy_profiles.discard(name)
            self._ui(self.refresh_profiles)
            home = self._home_url()
            if bot.has_session():
                # already logged in: just hand the window over. No stats refresh here — that opens a
                # second tab on the profile page, which is not what "open account" should do.
                self.log(f"[{name}] ล็อกอินอยู่แล้ว เปิด {home}")
                bot.page().goto(home, wait_until="domcontentloaded")
                bot.wait_until_closed()
            else:
                self.log(f"[{name}] ล็อกอิน TikTok ในหน้าต่าง Chrome ที่เปิดขึ้น แล้วปิดหน้าต่างเมื่อเสร็จ")
                bot.open_login()

                def on_login():
                    # first login for this profile: read the username/followers once (uses a temporary
                    # tab that closes itself), then leave the window on the home page
                    self.log(f"[{name}] ตรวจพบการล็อกอิน กำลังอ่านข้อมูลบัญชี (เปิดแท็บชั่วคราวแล้วปิดเอง)...")
                    p = bot.update_profile_stats()
                    self.log(f"[{name}] @{p.username} ผู้ติดตาม {p.followers:,}")
                    self._ui(self.refresh_profiles)
                    try:
                        bot.page().goto(home, wait_until="domcontentloaded")
                    except Exception as exc:
                        self.log(f"[{name}] เปิดหน้า {home} ไม่สำเร็จ: {short_error(exc)}")

                bot.wait_until_closed(on_login=on_login)
        except Exception as exc:
            self.log(f"[{name}] ❌ {short_error(exc)}")
        finally:
            # release the slot BEFORE closing: a slow/hanging close() must never leave the
            # account stuck on "เปิด Chrome อยู่"
            self._login_bots.pop(name, None)
            self._busy_profiles.discard(name)
            self._ui(self.refresh_profiles)
            self.log(f"[{name}] ปิด Chrome แล้ว")
            try:
                bot.close()
            except Exception:
                pass

    # --- credentials + auto login -------------------------------------
    def set_credentials(self):
        names = self._selected_profiles()
        if not names:
            return
        profile = self.pm.get(names[0])
        if profile is None:
            return
        dlg = CredentialsDialog(self, profile)
        self.wait_window(dlg)
        if dlg.result is None:
            return
        r = dlg.result
        password = r["password"] or (profile.get_password() if profile.has_credentials else "")
        profile.set_tiktok(r["email"], password)
        # "keep" sentinel = the field was left untouched, so keep the stored mailbox token
        mail_token = profile.get_mail_token() if r["mail_token"] == "keep" else r["mail_token"]
        profile.set_mailbox(r["mail_email"], r["mail_pass"], mail_token, r["mail_client_id"])
        profile.save()
        parts = []
        if profile.has_credentials:
            parts.append("บัญชี TikTok")
        if profile.has_mail_otp:
            parts.append(f"อ่าน OTP จาก {profile.mail_email}")
        self.log(f"[{profile.name}] " + ("บันทึก: " + " + ".join(parts) if parts else "ลบข้อมูลล็อกอินแล้ว"))
        self.refresh_profiles()
        if profile.has_credentials:           # saved a usable login -> log in right away
            self.log(f"[{profile.name}] เริ่มล็อกอินอัตโนมัติทันที...")
            self.auto_login([profile.name])

    def auto_login(self, names: list[str] | None = None):
        names = self._selected_profiles() if names is None else names
        for name in names:
            profile = self.pm.get(name)
            if profile is None:
                continue
            if not profile.has_credentials:
                self.log(f"[{name}] ยังไม่ได้ตั้งอีเมล/รหัสผ่าน (กดปุ่ม 'อีเมล/รหัส' ก่อน)")
                continue
            if name in self._login_bots or name in self._busy_profiles:
                self.log(f"[{name}] Chrome ของบัญชีนี้เปิดอยู่แล้ว")
                continue
            self._busy_profiles.add(name)
            self.refresh_profiles()
            self._bg(self._auto_login_worker, name, name=f"autologin-{name}")

    def _auto_login_worker(self, name: str):
        profile = self.pm.get(name)
        if profile is None:
            self._busy_profiles.discard(name)
            return
        bot = TikTokBrowser(profile, self.settings, log=lambda m: self.log(f"[{name}] {m}"), headless=False)
        try:
            self.log(f"[{name}] กำลังเปิด Chrome...")
            bot.open()
            self._login_bots[name] = bot
            self._busy_profiles.discard(name)
            self._ui(self.refresh_profiles)
            if bot.has_session():
                self.log(f"[{name}] มี session อยู่แล้ว ไม่ต้องล็อกอินใหม่")
                ok = True
            else:
                ok = bot.login_with_password(profile.email, profile.get_password(), wait_minutes=self._wait_minutes())
            if ok:
                p = bot.update_profile_stats()
                self.log(f"[{name}] ✅ @{p.username} ผู้ติดตาม {p.followers:,} — ปิด Chrome")
            else:
                self.log(f"[{name}] ยังล็อกอินไม่สำเร็จ — ทำต่อในหน้าต่าง Chrome ได้เลย แล้วปิดหน้าต่างเมื่อเสร็จ")

                def on_login():
                    p = bot.update_profile_stats()
                    self.log(f"[{name}] ✅ @{p.username} ผู้ติดตาม {p.followers:,}")
                    self._ui(self.refresh_profiles)

                bot.wait_until_closed(on_login=on_login)
        except Exception as exc:
            self.log(f"[{name}] ❌ {short_error(exc)}")
        finally:
            self._login_bots.pop(name, None)
            self._busy_profiles.discard(name)
            self._ui(self.refresh_profiles)
            try:
                bot.close()
            except Exception:
                pass

    # --- account info --------------------------------------------------
    def check_followers(self, all_profiles: bool):
        names = self.pm.names() if all_profiles else self._selected_profiles()
        if not names:
            return
        self._bg(self._check_worker, names, name="check-followers")

    def _check_worker(self, names: list[str]):
        for name in names:
            if name in self._login_bots or name in self._busy_profiles:
                self.log(f"[{name}] ข้าม — Chrome ของบัญชีนี้เปิดอยู่")
                continue
            profile = self.pm.get(name)
            if profile is None:
                continue
            self._busy_profiles.add(name)
            self._ui(self.refresh_profiles)
            try:
                self.log(f"[{name}] กำลังเช็คสถานะบัญชี...")
                with TikTokBrowser(profile, self.settings, log=lambda m, n=name: self.log(f"[{n}] {m}")) as bot:
                    p = bot.update_profile_stats()
                self.log(f"[{name}] ✅ @{p.username} ผู้ติดตาม {p.followers:,} | กำลังติดตาม {p.following:,} | ถูกใจ {p.likes:,}")
            except Exception as exc:
                self.log(f"[{name}] ❌ {short_error(exc)}")
                profile.logged_in = False
                profile.save()
            finally:
                self._busy_profiles.discard(name)
                self._ui(self.refresh_profiles)

    def copy_profile_info(self):
        names = self._selected_profiles()
        if not names:
            return
        texts = [self.pm.get(n).copy_text() for n in names if self.pm.get(n)]
        self.clipboard_clear()
        self.clipboard_append("\n\n".join(texts))
        self.update()
        self.log(f"คัดลอกข้อมูล {len(names)} บัญชีไปยังคลิปบอร์ดแล้ว")

    def open_profile_folder(self):
        names = self._selected_profiles(require=False)
        open_folder(self.pm.get(names[0]).path if names else self.pm.root)

    def clear_stuck_status(self):
        """Escape hatch: free accounts whose Chrome is gone but whose status is still stuck."""
        names = self._selected_profiles(require=False) or (list(self._login_bots) + list(self._busy_profiles))
        cleared = []
        for name in dict.fromkeys(names):
            bot = self._login_bots.pop(name, None)
            was_busy = name in self._busy_profiles
            self._busy_profiles.discard(name)
            if bot is None and not was_busy:
                continue
            if bot is not None:
                self._bg(lambda b=bot: b.close(), name=f"close-{name}")   # may block; do it off the UI thread
            cleared.append(name)
        self.refresh_profiles()
        if cleared:
            self.log("ล้างสถานะค้างแล้ว: " + ", ".join(cleared)
                     + " — ถ้าเปิดใหม่แล้วขึ้นว่า Chrome เปิดอยู่ ให้ปิด chrome.exe ใน Task Manager ก่อน")
        else:
            self.log("ไม่มีสถานะค้างให้ล้าง")

    def delete_profile(self):
        names = self._selected_profiles()
        if not names:
            return
        if any(n in self._login_bots or n in self._busy_profiles for n in names):
            messagebox.showwarning("ลบไม่ได้", "ปิด Chrome ของบัญชีนั้นก่อน")
            return
        if not messagebox.askyesno("ยืนยันการลบ", f"ลบบัญชี {', '.join(names)} ?\n(ข้อมูลล็อกอินใน Chrome จะถูกลบด้วย)"):
            return
        for n in names:
            self.pm.delete(n)
            self.log(f"ลบบัญชี '{n}' แล้ว")
        self.refresh_profiles()


def run():
    app = App()
    app.mainloop()
