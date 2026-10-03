"""settings_app.py - the AirX Voice Settings window: a native Windows window, no browser (Alex, 9/30).

Started from the tray as `brain.exe --settings` (or `pythonw brain.py --settings` from the repo). It changes
nothing on disk itself: it reads and saves through the running helper's /api/* calls with the helper's
token, so the helper stays the only writer of settings.json and picks every change up at once.
"""
import json
import os
import tkinter as tk
import urllib.request
from tkinter import filedialog, messagebox, ttk

TITLE = "AirX Voice Settings"
MODS = {"Control_L": 162, "Control_R": 163, "Shift_L": 160, "Shift_R": 161, "Alt_L": 164, "Alt_R": 165, "Win_L": 91, "Win_R": 92}
VK_NAMES = {72: "H", 160: "Shift", 161: "Right Shift", 162: "Ctrl", 163: "Right Ctrl", 164: "Alt", 165: "Right Alt", 91: "Win",
            92: "Right Win", 32: "Space", 13: "Enter", 9: "Tab", 27: "Esc", 20: "Caps Lock"}
HOTKEY_VK = {20: "CapsLock", 145: "ScrollLock", 19: "Pause", 45: "Insert", 36: "Home", 35: "End", 33: "PgUp", 34: "PgDn", 93: "AppsKey"}
HOTKEY_SIDE = {"Control_R": "RCtrl", "Alt_R": "RAlt", "Shift_R": "RShift", "Win_R": "RWin"}
SCALE = 1.0                                                   # screen pixels per 96-dpi pixel, set at start


def px(n):
    return int(n * SCALE)


NICE = {"CapsLock": "Caps Lock", "ScrollLock": "Scroll Lock", "PgUp": "Page Up", "PgDn": "Page Down", "AppsKey": "Menu key",
        "RCtrl": "Right Ctrl", "RAlt": "Right Alt", "RShift": "Right Shift", "RWin": "Right Win"}


def hotkey_label(h):
    h = h or "CapsLock"
    i = 0
    while i < len(h) and h[i] in "^!+#<>":
        i += 1
    mods = [w for c, w in (("^", "Ctrl"), ("!", "Alt"), ("+", "Shift"), ("#", "Win")) if c in h[:i]]
    k = h[i:]
    return "+".join(mods + [NICE.get(k, k.upper() if len(k) == 1 else k)])


def vk_label(v):
    out = []
    for n in [int(x) for x in (v or "").split("+") if x]:
        out.append(VK_NAMES.get(n) or (chr(n) if 65 <= n <= 90 or 48 <= n <= 57 else "F%d" % (n - 111) if 112 <= n <= 135 else "key %d" % n))
    return "+".join(out)


class Api:
    def __init__(self, state, port):
        self.state, self.port = state, port

    def __call__(self, path, body=None, timeout=15):
        token = open(os.path.join(self.state, "token"), encoding="utf-8").read().strip()
        req = urllib.request.Request("http://127.0.0.1:%d%s" % (self.port, path), data=json.dumps(body or {}).encode("utf-8"),
                                     headers={"X-Token": token, "Content-Type": "application/json"})
        return json.load(urllib.request.urlopen(req, timeout=timeout))


class Rows:
    """One tab's list (websites, folders or apps): a table with Add, Edit and Remove."""

    def __init__(self, app, parent, key, cols, hint, browse=False):
        self.app, self.key, self.cols, self.browse = app, key, cols, browse
        ttk.Label(parent, text=hint, foreground="#5d6778", wraplength=px(820)).pack(anchor="w", padx=12, pady=(10, 6))
        box = ttk.Frame(parent)
        box.pack(fill="both", expand=True, padx=12)
        self.tree = ttk.Treeview(box, columns=[c for c, _, _ in cols], show="headings", selectmode="browse")
        for c, head, width in cols:
            self.tree.heading(c, text=head)
            self.tree.column(c, width=px(width), anchor="w")
        sb = ttk.Scrollbar(box, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.tree.bind("<Double-1>", lambda e: self.edit())
        bar = ttk.Frame(parent)
        bar.pack(fill="x", padx=12, pady=8)
        ttk.Button(bar, text="Add…", command=self.add).pack(side="left")
        ttk.Button(bar, text="Edit…", command=self.edit).pack(side="left", padx=6)
        ttk.Button(bar, text="Remove", command=self.remove).pack(side="left")

    def rows(self):
        return self.app.S[self.key]

    def show(self):
        self.tree.delete(*self.tree.get_children())
        for i, r in enumerate(self.rows()):
            self.tree.insert("", "end", iid=str(i), values=[", ".join(r.get(c) or []) if isinstance(r.get(c), list) else r.get(c, "")
                                                             for c, _, _ in self.cols])

    def picked(self):
        sel = self.tree.selection()
        return int(sel[0]) if sel else None

    def add(self):
        r = {c: "" for c, _, _ in self.cols}
        if self.browse:
            path = filedialog.askdirectory(parent=self.app.root, title="Pick a folder")
            if not path:
                return
            r.update(path=os.path.normpath(path), name=os.path.basename(path))
        if self.dialog(r, "Add"):
            self.rows().append(r)
            self.app.changed()
            self.show()

    def edit(self):
        i = self.picked()
        if i is None:
            return
        r = dict(self.rows()[i])
        if self.dialog(r, "Edit"):
            self.rows()[i] = r
            self.app.changed()
            self.show()

    def remove(self):
        i = self.picked()
        if i is not None and messagebox.askyesno(TITLE, "Remove %s?" % (self.rows()[i].get("name") or "this"), parent=self.app.root):
            del self.rows()[i]
            self.app.changed()
            self.show()

    def dialog(self, r, verb):
        d = tk.Toplevel(self.app.root)
        d.title("%s %s" % (verb, self.key[:-1]))
        d.transient(self.app.root)
        d.resizable(False, False)
        vars_ = {}
        f = ttk.Frame(d, padding=14)
        f.pack(fill="both")
        for n, (c, head, _) in enumerate(self.cols):
            ttk.Label(f, text=head).grid(row=n, column=0, sticky="w", pady=4, padx=(0, 10))
            v = tk.StringVar(value=", ".join(r[c]) if isinstance(r.get(c), list) else r.get(c, ""))
            e = ttk.Entry(f, textvariable=v, width=60)
            e.grid(row=n, column=1, sticky="we", pady=4)
            if n == 0:
                e.focus_set()
            if c == "path":
                ttk.Button(f, text="Browse…", command=lambda v=v: v.set(os.path.normpath(filedialog.askdirectory(
                    parent=d, initialdir=v.get() or None, title="Pick a folder") or v.get()))).grid(row=n, column=2, padx=(6, 0))
            vars_[c] = v
        ttk.Label(f, text='"You call it": what you might say, separated by commas.', foreground="#5d6778").grid(
            row=len(self.cols), column=1, sticky="w", pady=(2, 8))
        ok = {"v": False}

        def done():
            for c, v in vars_.items():
                r[c] = v.get().strip()
            if not r.get("name"):
                messagebox.showwarning(TITLE, "Give it a name.", parent=d)
                return
            ok["v"] = True
            d.destroy()
        b = ttk.Frame(f)
        b.grid(row=len(self.cols) + 1, column=0, columnspan=3, sticky="e")
        ttk.Button(b, text="OK", command=done, default="active").pack(side="left", padx=6)
        ttk.Button(b, text="Cancel", command=d.destroy).pack(side="left")
        d.bind("<Return>", lambda e: done())
        d.bind("<Escape>", lambda e: d.destroy())
        d.grab_set()
        self.app.root.wait_window(d)
        return ok["v"]


class App:
    def __init__(self, here, state, port):
        self.api = Api(state, port)
        self.dirty = False
        global SCALE
        self.root = root = tk.Tk()
        SCALE = max(1.0, root.winfo_fpixels("1i") / 96.0)
        root.title(TITLE)
        try:
            root.iconbitmap(os.path.join(here, "icon.ico"))
        except tk.TclError:
            pass
        st = ttk.Style()
        if "vista" in st.theme_names():
            st.theme_use("vista")
        root.option_add("*Font", ("Segoe UI", 10))
        st.configure(".", font=("Segoe UI", 10))
        st.configure("Treeview", rowheight=px(24))
        st.configure("Head.TLabel", font=("Segoe UI", 15, "bold"))
        st.configure("Key.TLabel", font=("Segoe UI", 10, "bold"), padding=(10, 3), relief="groove")
        root.geometry("%dx%d" % (px(940), px(660)))
        root.minsize(px(720), px(520))

        top = ttk.Frame(root, padding=(14, 10, 14, 0))
        top.pack(fill="x")
        ttk.Label(top, text="AirX Voice", style="Head.TLabel").pack(anchor="w")
        ttk.Label(top, text="Press your key, talk, press it again. Wispr types what you said into the bar and AirX Voice does it.",
                  foreground="#5d6778").pack(anchor="w")

        nb = ttk.Notebook(root)
        nb.pack(fill="both", expand=True, padx=10, pady=10)
        self.general(nb)
        self.sites = Rows(self, self.tab(nb, "Websites"), "sites", [("name", "Name", 180), ("url", "Address", 360), ("say", "You call it", 260)],
                          "Websites you want to open by voice. Jev reads \"You call it\"; nothing has to match exactly.")
        self.folders = Rows(self, self.tab(nb, "Folders"), "folders", [("name", "Name", 180), ("path", "Folder", 420), ("say", "You call it", 200)],
                            "Folders you want to open by voice. Jobs and bids are built in, so they don't go here.", browse=True)
        self.apps = Rows(self, self.tab(nb, "Apps"), "apps", [("name", "Name (as in the Start menu)", 220), ("say", "You call it", 300),
                                                                 ("exe", "Program file (to close or switch to it)", 260)],
                         "Apps you want to open, close or switch to by voice.")
        self.trytab(nb)

        bottom = ttk.Frame(root, padding=(12, 0, 12, 12))
        bottom.pack(fill="x")
        self.status = ttk.Label(bottom, text="")
        self.status.pack(side="left")
        ttk.Button(bottom, text="Close", command=self.close).pack(side="right")
        ttk.Button(bottom, text="Save", command=self.save, default="active").pack(side="right", padx=6)
        root.protocol("WM_DELETE_WINDOW", self.close)
        self.load()

    def tab(self, nb, name):
        f = ttk.Frame(nb)
        nb.add(f, text=name)
        return f

    # ---------------------------------------------------------------- General

    def general(self, nb):
        g = self.tab(nb, "General")
        keys = ttk.LabelFrame(g, text="Keys", padding=12)
        keys.pack(fill="x", padx=12, pady=(12, 6))
        ttk.Label(keys, text="Your key").grid(row=0, column=0, sticky="w", padx=(0, 12))
        self.hk = ttk.Label(keys, text="", style="Key.TLabel")
        self.hk.grid(row=0, column=1, sticky="w")
        ttk.Button(keys, text="Change…", command=self.pick_hotkey).grid(row=0, column=2, padx=8)
        ttk.Label(keys, text="Opens the bar and starts Wispr; press it again when you're done. Esc cancels.",
                  foreground="#5d6778").grid(row=0, column=3, sticky="w")
        ttk.Label(keys, text="Wispr's hands-free key").grid(row=1, column=0, sticky="w", padx=(0, 12), pady=(10, 0))
        self.wk = ttk.Label(keys, text="", style="Key.TLabel")
        self.wk.grid(row=1, column=1, sticky="w", pady=(10, 0))
        wb = ttk.Frame(keys)
        wb.grid(row=1, column=2, columnspan=2, sticky="w", pady=(10, 0))
        ttk.Button(wb, text="Change…", command=self.pick_wispr).pack(side="left", padx=8)
        ttk.Button(wb, text="Use Wispr's own", command=self.wispr_auto).pack(side="left")
        self.wk_note = ttk.Label(wb, text="", foreground="#5d6778")
        self.wk_note.pack(side="left", padx=8)

        jev = ttk.LabelFrame(g, text="Jev key", padding=12)
        jev.pack(fill="x", padx=12, pady=6)
        ttk.Label(jev, text="AirX Voice asks Jev directly. A key you save here is checked with Jev first, kept encrypted "
                            "to your Windows login, and never shown again.", foreground="#5d6778", wraplength=px(820)).pack(anchor="w")
        self.jev_status = ttk.Label(jev, text="")
        self.jev_status.pack(anchor="w", pady=6)
        row = ttk.Frame(jev)
        row.pack(fill="x")
        self.jev_entry = ttk.Entry(row, show="•", width=48)
        self.jev_entry.pack(side="left")
        ttk.Button(row, text="Save key", command=self.save_jev).pack(side="left", padx=6)
        self.jev_clear = ttk.Button(row, text="Remove saved key", command=lambda: self.save_jev(clear=True))
        self.jev_clear.pack(side="left")

        est = ttk.LabelFrame(g, text="Estimating folder", padding=12)
        est.pack(fill="x", padx=12, pady=6)
        self.est_note = ttk.Label(est, text="", foreground="#5d6778", wraplength=px(820))
        self.est_note.pack(anchor="w")
        row = ttk.Frame(est)
        row.pack(fill="x", pady=(6, 0))
        self.est = tk.StringVar()
        ttk.Entry(row, textvariable=self.est, width=80).pack(side="left", fill="x", expand=True)
        ttk.Button(row, text="Browse…", command=self.pick_est).pack(side="left", padx=6)
        self.est.trace_add("write", lambda *a: self.changed())

    def trytab(self, nb):
        t = self.tab(nb, "Try it")
        ttk.Label(t, text="Type what you'd say. It shows what would happen and opens nothing. It uses your saved settings.",
                  foreground="#5d6778").pack(anchor="w", padx=12, pady=(12, 6))
        row = ttk.Frame(t)
        row.pack(fill="x", padx=12)
        self.try_text = ttk.Entry(row, width=70)
        self.try_text.pack(side="left", fill="x", expand=True)
        self.try_text.bind("<Return>", lambda e: self.try_it())
        ttk.Button(row, text="Try", command=self.try_it).pack(side="left", padx=6)
        self.try_out = ttk.Label(t, text="", wraplength=px(840))
        self.try_out.pack(anchor="w", padx=12, pady=10)
        ttk.Separator(t).pack(fill="x", padx=12, pady=6)
        self.builtin = ttk.Label(t, text="", foreground="#5d6778", wraplength=px(840), justify="left")
        self.builtin.pack(anchor="w", padx=12, pady=6)

    # ---------------------------------------------------------------- data

    def load(self):
        try:
            self.S = self.api("/api/get")
        except Exception as e:
            messagebox.showerror(TITLE, "AirX Voice isn't answering (%s).\n\nStart it from the Start menu and try again." % e)
            self.root.destroy()
            return
        self.hk.configure(text=hotkey_label(self.S["hotkey"]))
        self.show_wispr()
        self.show_jev(self.S["jev"])
        self.est.set(self.S.get("estimating_root") or "")
        self.est_note.configure(text="Blank: found by itself%s." % ((": " + self.S["estimating_auto"]) if self.S.get("estimating_auto") else
                                                                  " (not found on this PC; pick the 01 - Estimating folder)"))
        for r in (self.sites, self.folders, self.apps):
            r.show()
        self.builtin.configure(text=("Built in, nothing to set up: every active job (%d now) and live bid (%d now), their parts "
                                     "(\"the <job> submittals\", \"the BID Sheet\"), \"<job> in Ops\", closing and switching "
                                     "windows, minimize everything, show desktop, and these AirX Ops pages: %s.")
                               % (self.S["jobs"], self.S["bids"], ", ".join(self.S["ops_pages"])))
        self.dirty = False
        self.status.configure(text="")

    def changed(self):
        self.dirty = True
        self.status.configure(text="Not saved yet", foreground="#5d6778")

    def save(self):
        body = {k: self.S.get(k) for k in ("hotkey", "wispr_key", "sites", "folders", "apps")}
        body["estimating_root"] = self.est.get().strip()
        try:
            x = self.api("/api/save", body)
        except Exception as e:
            x = {"ok": False, "error": "AirX Voice isn't answering (%s)" % e}
        if x.get("ok"):
            self.load()
            self.status.configure(text="Saved. AirX Voice is using it now.", foreground="#1f7a3d")
            return True
        self.status.configure(text=x.get("error", "Not saved"), foreground="#b3261e")
        return False

    def close(self):
        if self.dirty:
            a = messagebox.askyesnocancel(TITLE, "Save your changes?", parent=self.root)
            if a is None or (a and not self.save()):
                return
        self.root.destroy()

    # ---------------------------------------------------------------- keys

    def show_wispr(self):
        self.wk.configure(text=vk_label(self.S.get("wispr_key") or self.S.get("wispr_auto") or ("" if self.S.get("wispr_installed") else "91+72"))
                          or "Ctrl+Win+Space")
        self.wk_note.configure(text="Your own setting." if self.S.get("wispr_key") else
                               "Read from Wispr's settings, so it follows Wispr." if self.S.get("wispr_auto") else
                               "Wispr's default." if self.S.get("wispr_installed") else
                               "No Wispr on this PC: Windows voice typing (Win+H) does the listening.")

    def wispr_auto(self):
        self.S["wispr_key"] = ""
        self.show_wispr()
        self.changed()

    def capture(self, title, on_key, on_release=None):
        d = tk.Toplevel(self.root)
        d.title(title)
        d.transient(self.root)
        d.resizable(False, False)
        msg = ttk.Label(d, text=title, padding=24, font=("Segoe UI", 12, "bold"))
        msg.pack()
        ttk.Button(d, text="Cancel", command=d.destroy).pack(pady=(0, 14))
        d.bind("<KeyPress>", lambda e: on_key(e, d, msg))
        if on_release:
            d.bind("<KeyRelease>", lambda e: on_release(e, d, msg))
        d.grab_set()
        d.focus_force()
        self.root.wait_window(d)

    def pick_hotkey(self):
        def key(e, d, msg):
            if e.keysym in ("Control_L", "Shift_L", "Alt_L", "Win_L"):
                return "break"                                   # wait for the real key
            vk = e.keycode
            name = HOTKEY_SIDE.get(e.keysym) or HOTKEY_VK.get(vk) or ("F%d" % (vk - 111) if 112 <= vk <= 135 else "") or \
                (chr(vk).lower() if 65 <= vk <= 90 else chr(vk) if 48 <= vk <= 57 else "Numpad%d" % (vk - 96) if 96 <= vk <= 105 else "")
            if not name:
                msg.configure(text="That key can't be used. Press another.")
                return "break"
            mods = ("^" if e.state & 0x4 and name != "RCtrl" else "") + ("!" if e.state & 0x20000 and name != "RAlt" else "") + \
                ("+" if e.state & 0x1 and name != "RShift" else "")
            if not mods and len(name) == 1:
                msg.configure(text="A letter alone would fire while you type.\nHold Ctrl or Alt with it.")
                return "break"
            self.S["hotkey"] = mods + name
            self.hk.configure(text=hotkey_label(self.S["hotkey"]))
            self.changed()
            d.destroy()
            return "break"
        self.capture("Press the key you want to use", key)

    def pick_wispr(self):
        held, combo = set(), []

        def down(e, d, msg):
            vk = MODS.get(e.keysym, e.keycode)
            held.add(vk)
            if vk not in combo:
                combo.append(vk)
            msg.configure(text=vk_label("+".join(map(str, combo))))
            return "break"

        def up(e, d, msg):
            held.discard(MODS.get(e.keysym, e.keycode))
            if not held and combo:
                self.S["wispr_key"] = "+".join(map(str, combo))
                self.show_wispr()
                self.changed()
                d.destroy()
            return "break"
        self.capture("Press Wispr's hands-free keys together", down, up)

    def pick_est(self):
        p = filedialog.askdirectory(parent=self.root, initialdir=self.est.get() or self.S.get("estimating_auto") or None,
                                    title="Pick the 01 - Estimating folder")
        if p:
            self.est.set(os.path.normpath(p))

    # ---------------------------------------------------------------- Jev

    def show_jev(self, where):
        if where == "settings":
            self.jev_status.configure(text="Using the key saved here.", foreground="#1f7a3d")
        elif where == "this PC":
            self.jev_status.configure(text="Using the Jev key this PC already has for the other AirX tools.", foreground="#1f7a3d")
        else:
            self.jev_status.configure(text="No key. Commands won't work until you save one.", foreground="#b3261e")
        self.jev_clear.state(["!disabled"] if where == "settings" else ["disabled"])

    def save_jev(self, clear=False):
        key = "" if clear else self.jev_entry.get().strip()
        if not clear and not key:
            return
        self.jev_status.configure(text="Checking the key with Jev…", foreground="#5d6778")
        self.root.update_idletasks()
        try:
            x = self.api("/api/jevkey", {"key": key}, timeout=20)
        except Exception as e:
            x = {"ok": False, "error": "AirX Voice isn't answering (%s)" % e}
        self.jev_entry.delete(0, "end")
        if x.get("ok"):
            self.show_jev(x.get("jev"))
        else:
            self.jev_status.configure(text=x.get("error", "Not saved"), foreground="#b3261e")

    # ---------------------------------------------------------------- Try it

    def try_it(self):
        text = self.try_text.get().strip()
        if not text:
            return
        if self.dirty:
            self.try_out.configure(text="Save first, so the test uses your changes.", foreground="#b3261e")
            return
        self.try_out.configure(text="Asking Jev…", foreground="#5d6778")
        self.root.update_idletasks()
        try:
            x = self.api("/api/test", {"text": text})
            self.try_out.configure(text=x.get("say", ""), foreground="")
        except Exception as e:
            self.try_out.configure(text="AirX Voice isn't answering (%s)" % e, foreground="#b3261e")


def main(here, state, port):
    import ctypes
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)          # sharp text on scaled screens
    except Exception:
        pass
    app = App(here, state, port)
    try:
        app.root.mainloop()
    except tk.TclError:
        pass
