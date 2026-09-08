"""Flat WinForms-style widgets and palette for the tkinter/ttk UI.

Plain tkinter is used on purpose: its widgets are square and 1px-bordered, which is what the
classic account-manager look needs. Buttons are hand-built (a bordered Frame + Label) because
tk.Button cannot draw a flat border with custom hover colours on Windows.
"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

FONT = ("Segoe UI", 9)
FONT_B = ("Segoe UI", 9, "bold")
FONT_MONO = ("Consolas", 9)

DARK = {
    "bg": "#1f1f1f", "panel": "#252526", "list": "#191919", "head": "#2b2b2b",
    "btn": "#2d2d2d", "btn_hover": "#3a3a3a", "btn_down": "#484848",
    "border": "#4a4a4a", "fg": "#e8e8e8", "dim": "#9a9a9a", "entry": "#232323",
    "accent": "#0e639c", "accent_hover": "#1177bb",
    "danger": "#8b1e1e", "danger_hover": "#a82a2a",
    "purple": "#5b2d82", "purple_hover": "#6f3a9e",
    "group": "#6f9fd8",
}
LIGHT = {
    "bg": "#f0f0f0", "panel": "#f5f5f5", "list": "#ffffff", "head": "#e6e6e6",
    "btn": "#e1e1e1", "btn_hover": "#d3d3d3", "btn_down": "#c2c2c2",
    "border": "#adadad", "fg": "#1a1a1a", "dim": "#5f5f5f", "entry": "#ffffff",
    "accent": "#0078d7", "accent_hover": "#1a88e0",
    "danger": "#c42b1c", "danger_hover": "#d13b2c",
    "purple": "#7b3fa0", "purple_hover": "#8d4cb5",
    "group": "#1f5fa8",
}
C = dict(DARK)          # active palette (mutated by use_theme)


def use_theme(mode: str) -> None:
    C.clear()
    C.update(LIGHT if mode == "light" else DARK)


def style_ttk(root) -> None:
    st = ttk.Style(root)
    st.theme_use("clam")
    st.configure("RAM.Treeview", background=C["list"], fieldbackground=C["list"], foreground=C["fg"],
                 rowheight=22, font=FONT, borderwidth=0, relief="flat")
    st.configure("RAM.Treeview.Heading", background=C["head"], foreground=C["fg"], font=FONT,
                 relief="flat", borderwidth=1, padding=(4, 3))
    st.map("RAM.Treeview.Heading", background=[("active", C["btn_hover"])])
    st.map("RAM.Treeview", background=[("selected", C["accent"])], foreground=[("selected", "#ffffff")])
    st.configure("RAM.Vertical.TScrollbar", background=C["btn"], troughcolor=C["list"],
                 bordercolor=C["border"], arrowcolor=C["fg"], darkcolor=C["btn"], lightcolor=C["btn"])
    st.map("RAM.Vertical.TScrollbar", background=[("active", C["btn_hover"])])


class FlatButton(tk.Frame):
    """1px-bordered rectangular button with hover/press colours."""

    def __init__(self, master, text: str, command=None, w: int | None = None, h: int = 24,
                 bg: str | None = None, hover: str | None = None, fg: str | None = None,
                 font=FONT, anchor: str = "center", padx: int = 8):
        super().__init__(master, bg=C["border"], bd=0, highlightthickness=0, height=h)
        self._bg = bg or C["btn"]
        self._hover = hover or (C["btn_hover"] if bg is None else _lighten(bg))
        self._down = C["btn_down"] if bg is None else self._hover
        self.command = command
        self.enabled = True
        self.label = tk.Label(self, text=text, bg=self._bg, fg=fg or C["fg"], font=font,
                              anchor=anchor, padx=padx, cursor="hand2")
        self.label.pack(fill="both", expand=True, padx=1, pady=1)
        if w:
            self.configure(width=w)
        self.pack_propagate(False)
        self.grid_propagate(False)
        for widget in (self, self.label):
            widget.bind("<Enter>", self._on_enter)
            widget.bind("<Leave>", self._on_leave)
            widget.bind("<ButtonPress-1>", self._on_press)
            widget.bind("<ButtonRelease-1>", self._on_release)

    def _on_enter(self, _=None):
        if self.enabled:
            self.label.configure(bg=self._hover)

    def _on_leave(self, _=None):
        if self.enabled:
            self.label.configure(bg=self._bg)

    def _on_press(self, _=None):
        if self.enabled:
            self.label.configure(bg=self._down)

    def _on_release(self, event=None):
        if not self.enabled:
            return
        self.label.configure(bg=self._hover)
        if self.command and event is not None:
            x, y = event.x_root - self.winfo_rootx(), event.y_root - self.winfo_rooty()
            if 0 <= x <= self.winfo_width() and 0 <= y <= self.winfo_height():
                self.command()

    def set_text(self, text: str):
        self.label.configure(text=text)


def _lighten(color: str, amount: int = 22) -> str:
    r, g, b = (int(color[i:i + 2], 16) for i in (1, 3, 5))
    return "#%02x%02x%02x" % tuple(min(255, v + amount) for v in (r, g, b))


def entry(master, width: int | None = None, show: str | None = None, readonly: bool = False, **kw) -> tk.Entry:
    """A flat entry. `readonly=True` = display only: text can be selected and copied, not edited."""
    e = tk.Entry(master, bg=C["entry"], fg=C["fg"], font=FONT, relief="flat", bd=0,
                 highlightthickness=1, highlightbackground=C["border"], highlightcolor=C["accent"],
                 insertbackground=C["fg"], disabledbackground=C["entry"], disabledforeground=C["dim"],
                 readonlybackground=C["bg"], **kw)
    if width:
        e.configure(width=width)
    if show:
        e.configure(show=show)
    if readonly:
        e.configure(state="readonly", fg=C["dim"], cursor="arrow", highlightcolor=C["border"])
    return e


def set_readonly_text(e: tk.Entry, text: str) -> None:
    """Replace the contents of a readonly entry."""
    state = e.cget("state")
    e.configure(state="normal")
    e.delete(0, "end")
    e.insert(0, text)
    e.configure(state=state)


def label(master, text: str, dim: bool = False, bold: bool = False, bg: str | None = None, **kw) -> tk.Label:
    return tk.Label(master, text=text, bg=bg or C["panel"], fg=C["dim"] if dim else C["fg"],
                    font=FONT_B if bold else FONT, **kw)


def frame(master, bg: str | None = None, **kw) -> tk.Frame:
    return tk.Frame(master, bg=bg or C["panel"], bd=0, highlightthickness=0, **kw)


def bordered(master, **kw) -> tk.Frame:
    """A 1px-bordered container (pack children with padx=1, pady=1)."""
    return tk.Frame(master, bg=C["border"], bd=0, highlightthickness=0, **kw)


def textbox(master, height: int = 6, **kw) -> tk.Text:
    return tk.Text(master, height=height, bg=C["entry"], fg=C["fg"], font=FONT, relief="flat", bd=0,
                   highlightthickness=1, highlightbackground=C["border"], highlightcolor=C["accent"],
                   insertbackground=C["fg"], wrap="word", padx=4, pady=3, **kw)


def checkbox(master, text: str, variable, command=None) -> tk.Checkbutton:
    return tk.Checkbutton(master, text=text, variable=variable, command=command, font=FONT,
                          bg=C["panel"], fg=C["fg"], activebackground=C["panel"], activeforeground=C["fg"],
                          selectcolor=C["entry"], relief="flat", bd=0, highlightthickness=0,
                          anchor="w", cursor="hand2")


class FlatMenu(tk.Toplevel):
    """Dark dropdown built from labels.

    tk.Menu ignores -background on Windows (it always paints the system menu colours), so the menu
    is drawn as a borderless Toplevel instead.
    """

    def __init__(self, master, items: list[tuple[str, object] | None]):
        super().__init__(master, bg=C["border"])
        self.withdraw()
        self.overrideredirect(True)
        self.attributes("-topmost", True)
        inner = tk.Frame(self, bg=C["head"], bd=0, highlightthickness=0)
        inner.pack(fill="both", expand=True, padx=1, pady=1)
        for item in items:
            if item is None:
                tk.Frame(inner, bg=C["border"], height=1, bd=0).pack(fill="x", pady=3)
                continue
            text, command = item
            row = tk.Label(inner, text=text, bg=C["head"], fg=C["fg"], font=FONT,
                           anchor="w", padx=16, pady=4, cursor="hand2")
            row.pack(fill="x")
            row.bind("<Enter>", lambda e, w=row: w.configure(bg=C["accent"], fg="#ffffff"))
            row.bind("<Leave>", lambda e, w=row: w.configure(bg=C["head"], fg=C["fg"]))
            row.bind("<ButtonRelease-1>", lambda e, c=command: self._activate(c))
        self.bind("<Escape>", lambda e: self.close())
        self.bind("<Button-1>", self._maybe_close)
        self.bind("<FocusOut>", lambda e: self.close())

    def post(self, x: int, y: int) -> "FlatMenu":
        self.update_idletasks()
        w, h = self.winfo_reqwidth(), self.winfo_reqheight()
        x = max(0, min(x, self.winfo_screenwidth() - w))
        y = max(0, min(y, self.winfo_screenheight() - h - 40))
        self.geometry(f"{w}x{h}+{x}+{y}")
        self.deiconify()
        self.lift()
        try:
            self.grab_set()          # clicks elsewhere in the app are routed here so we can close
        except tk.TclError:
            pass
        self.focus_set()
        return self

    def _maybe_close(self, event):
        if not (0 <= event.x <= self.winfo_width() and 0 <= event.y <= self.winfo_height()):
            self.close()

    def _activate(self, command):
        self.close()
        if command:
            command()

    def close(self):
        try:
            self.grab_release()
        except tk.TclError:
            pass
        self.destroy()
