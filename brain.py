#!/usr/bin/env python3
"""brain.py - the resident half of AirX Voice: the tree, Jev, the allowed actions, and the settings page.

"AirX Voice.ahk" starts it hidden (brain\\brain.exe when installed, pythonw brain.py from the repo) and talks
to it on 127.0.0.1 with a token. It reads directory names only, one level at a time, and writes nothing
but its own token, log and settings. Everything Windows-only lives in win.py, so tests run anywhere.

No fuzzy matching (Alex, 9/29). The tree is loaded in memory and Jev walks down it:
    what to do  ->  what kind (active job, live bid, Ops page, website, app, folder, open program or window)
                ->  the item (every one of that kind)
                ->  for a job or bid: the whole folder, a part of it, or its page in AirX Ops.
One Jev call answers the first levels at once; a part ("the submittals", "the BID Sheet") is a second
call over that folder's real subfolders and key files. The code only follows Jev's answers and opens
Jev's top pick (Alex, 9/29: no picker; the bar says what opened). Jev says it isn't a command, or Jev
is down: nothing happens and the bar says so. Jev is called directly with the key from Settings (Alex,
9/30), else the key already on this PC for the other AirX tools.

His websites, folders and apps are his settings (%APPDATA%\\AirX Voice\\settings.json), seeded on first run
from targets.json, which also holds the built-in AirX Ops pages. The Settings window is this same program
started with --settings (settings_app.py, a native window); it changes settings through /api/* below, so
the running helper is the only thing that writes settings.json.

    POST /cmd      body: what Wispr typed      -> reply lines (below)
    POST /refresh  (the bar opens)             -> reloads the tree while he talks
    POST /ping
    POST /api/get|save|jevkey|test             -> the Settings window's calls (JSON)

Reply: one instruction per line, tab-separated, so the .ahk needs no JSON parser:
    show\t<text for the bar>   activate\t<hwnd>
"""
import base64
import fnmatch
import hmac
import json
import os
import re
import secrets
import socket
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

if getattr(sys, "frozen", False):                            # brain\brain.exe: the app's files sit one level up
    HERE = os.path.dirname(os.path.dirname(sys.executable))
else:
    HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import jevcall  # noqa: E402
import layout as JL  # noqa: E402  the job-folder rules, copied from Claude/job_layout.py

STATE = os.path.join(os.environ.get("LOCALAPPDATA") or os.path.expanduser("~/.local/share"), "AirX Voice")
SETTINGS = os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~/.config"), "AirX Voice", "settings.json")
PORT = int(os.environ.get("AIRX_VOICE_PORT", "47823"))
JEV_TIMEOUT = 3.0                                            # a voice command never waits longer

ACTIVE, LIVE, PLACE = "active job", "live bid", "place"
NUM_RE = re.compile(r"^(.*?) - (\d{5})$")                     # "<Name> - <5-digit number>"
NONE = "none of these"
FILE_APPS = {".xlsx": ["excel.exe"], ".xlsm": ["excel.exe"], ".xls": ["excel.exe"], ".pdf": ["revu.exe"],
             ".docx": ["winword.exe"], ".doc": ["winword.exe"]}       # who shows a job's file, if no new window

HELP = ("Say: open <job or bid> | open the <job> submittals / plans / BID Sheet | open <job> in Ops | "
        "open procurement, bids, AI dispatch... (Ops pages) | open PlanHub, Gensco, QuickBooks... | "
        "open Revu, Excel... | open downloads, pricing... | switch to <app> | close all <app> windows | "
        "minimize everything | show desktop")

# The fixed top of the tree. The items below it are loaded from disk, targets.json and the open windows.
ACTIONS = {"open": "He wants something opened: a job or bid folder or part of one, an AirX Ops page, a website, an app, or a folder.",
           "switch": "He wants to go to an app that is already open (switch to, bring up, go back to).",
           "close": "He wants the windows of one app he named closed.",
           "minimize": "He wants every window minimized.",
           "desktop": "He wants to see the desktop.",
           "help": "He is asking for help: what he can say, which commands work, or what this can do.",
           "none": "Not a command at all (noise, a test, a sentence meant for someone else), or he asked to close every app at once without naming one."}
BRANCHES = {ACTIVE: "a won job AirX is building now (he may say 'job')",
            LIVE: "a bid AirX is estimating now (he may say 'bid')",
            "ops page": "a page or board of AirX Ops, the company's own web app (not a job or bid he named)",
            "site": "a website other than AirX Ops",
            "app": "a program on this computer (File Explorer only when he wants the app itself, not a folder)",
            PLACE: "one of these standard folders",
            "program": "a whole program he wants to switch to or close, every window of it ('close all Chrome', 'close Excel')",
            "window": "one particular open window he named by what is in it: a folder, a workbook, a web page, a chat"}
OPENS = (ACTIVE, LIVE, "ops page", "site", "app", PLACE)
FOLDERS = (ACTIVE, LIVE)
DEPTH = {"whole": "He wants the job or bid folder itself, or named no part of it.",
         "part": "He named a part of the job or bid: a subfolder or file such as plans, specs, addenda, quotes, submittals, "
                 "change orders, billing, contract, closeout, photos, the BID Sheet, the takeoff or the proposal."}
WHERE = {"pc": "The folder on this computer. Always this, unless the word Ops is in what he said.",
         "ops": "The job's page in AirX Ops. Only when he said the word Ops about it: 'in Ops', 'on Ops', 'the Ops page'."}
CONTEXT = ("Someone at AirX, an HVAC contractor, spoke a command into a voice bar on their PC. Dictation typed what it heard: "
           "unusual names often come out spelled by sound, even split into common words.")


def dirs(path):
    """Names of the folders directly under path. Never recursive, never a file read."""
    try:
        with os.scandir(path) as it:
            return [e.name for e in it if e.is_dir()]
    except OSError:
        return []


def files(path):
    try:
        with os.scandir(path) as it:
            return [e.name for e in it if e.is_file()]
    except OSError:
        return []


def load_folders(est, active):
    """[entry] for every active job and every live bid."""
    out = []
    for f in sorted(dirs(active)):
        m = NUM_RE.match(f)
        if m:
            out.append({"path": os.path.join(active, f), "folder": f, "tier": ACTIVE, "name": m[1], "number": m[2], "date": ""})
    for f in sorted(dirs(est)):
        if JL.JOB_RE.match(f):
            out.append({"path": os.path.join(est, f), "folder": f, "tier": LIVE, "name": f[6:], "number": "", "date": f[:5]})
    return out


def label(e):
    if e["tier"] == ACTIVE:
        return "%s (job %s)" % (e["name"], e["number"])
    if e["tier"] == LIVE:
        return "%s (bid %s)" % (e["name"], e["date"].replace(" ", "/"))
    return e["name"]


class Brain:
    def __init__(self, win, jev=None, est=None, active=None, targets=None, state=STATE, settings=SETTINGS):
        self.win, self.jev, self.state, self.settings_path = win, jev, state, settings
        self.targets = targets or json.load(open(os.path.join(HERE, "targets.json"), encoding="utf-8"))
        self.settings, self.settings_at = {}, 0
        self.load_settings()
        self.est = est or JL.estimating_root(self.settings.get("estimating_root", ""))
        self.active = active or os.path.join(os.path.dirname(self.est), "02 - Active Projects")
        self.folders, self.apps, self.apps_at = [], [], 0
        self._lock = threading.Lock()
        self.refresh()

    # -------------------------------------------------------------- settings (his lists, his keys)

    def roots(self):
        est = self.__dict__.get("est") or JL.estimating_root(self.settings.get("estimating_root", ""))
        ops = os.path.dirname(est) if est else ""
        return {"ops": ops, "airx": os.path.dirname(ops) if ops else "", "home": os.path.expanduser("~")}

    def seed(self):
        """First run: today's sites, folders and apps from targets.json become his own editable lists."""
        T, r = self.targets, self.roots()
        folders = []
        for name, p in T["places"].items():
            path = p["path"].format(**r) if (r["ops"] or "{ops}" not in p["path"]) else ""
            if path and os.path.isdir(path):
                folders.append({"name": name, "path": path, "say": p["say"]})
        return {"hotkey": "CapsLock", "wispr_key": "", "estimating_root": "", "jev_key": "",
                "sites": [{"name": n, "url": v["url"], "say": v["say"]} for n, v in T["sites"].items()],
                "folders": folders,
                "apps": [{"name": n, "say": v["say"], "exe": v["exe"]} for n, v in T["apps"].items()]}

    def load_settings(self):
        try:
            at = os.path.getmtime(self.settings_path)
        except OSError:
            at = 0
        if at and at == self.settings_at:
            return
        try:
            self.settings = json.load(open(self.settings_path, encoding="utf-8"))
        except (OSError, ValueError):
            self.settings = self.seed()
            self.save_settings(self.settings)
            at = os.path.getmtime(self.settings_path) if os.path.exists(self.settings_path) else 0
        self.settings_at = at

    def save_settings(self, d):
        os.makedirs(os.path.dirname(self.settings_path), exist_ok=True)
        tmp = self.settings_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(d, f, indent=1, ensure_ascii=False)
        os.replace(tmp, self.settings_path)
        self.settings = d
        self.settings_at = os.path.getmtime(self.settings_path)

    def jev_key(self):
        """(key, where it came from). The Settings key wins; else the key this PC already has."""
        k = unprotect(self.settings.get("jev_key", ""))
        if k:
            return k, "settings"
        k = jevcall.fallback_key()
        return (k, "this PC") if k else ("", "")

    # -------------------------------------------------------------- the tree

    def refresh(self):
        with self._lock:
            self.load_settings()
            self.folders = load_folders(self.est, self.active)
            if time.time() - self.apps_at > 600:                 # the Start menu list changes rarely
                try:
                    self.apps = self.win.start_apps()
                    self.apps_at = time.time()
                except Exception as e:
                    self.log({"err": "start apps: %s" % e})

    def refresh_async(self):
        threading.Thread(target=self.refresh, daemon=True).start()

    def app_id(self, name):
        """The Start menu AppID for a targets.json app: its exact name, else the shortest entry holding it."""
        lo = name.lower()
        hits = [a for a in self.apps if lo == a[0].lower()] or \
            sorted((a for a in self.apps if lo in a[0].lower()), key=lambda a: len(a[0]))
        return hits[0][1] if hits else None

    def tree(self):
        """{branch: {label: (criteria, action)}}, loaded fresh for each command."""
        T = self.targets
        t = {k: {} for k in OPENS + ("program", "window")}
        for e in self.folders:
            t[e["tier"]][label(e)] = ("The folder %s%s." % (e["folder"], (", bid due " + e["date"].replace(" ", "/")) if e["date"] else ""),
                                      {"do": "folder", "entry": e})
        base = T["ops"]["url"]
        for name, (path, about) in T["ops"]["pages"].items():
            t["ops page"][name] = ("AirX Ops %s: %s." % (name, about), {"do": "site", "name": "Ops " + name, "url": base + path})
        S = self.settings
        for s in S.get("sites", []):
            name = s["name"]
            t["site"][name] = ("The %s website. He may call it %s." % (name, ", ".join(s.get("say") or [name])),
                               {"do": "site", "name": name, "url": s["url"]})
        for a in S.get("apps", []):
            appid = self.app_id(a["name"])
            if appid:
                t["app"][a["name"]] = ("%s. He may call it %s." % (a["name"], ", ".join(a.get("say") or [a["name"]])),
                                       {"do": "app", "name": a["name"], "id": appid})
        for p in S.get("folders", []):
            if os.path.isdir(p["path"]):
                e = {"path": p["path"], "folder": os.path.basename(p["path"]), "tier": PLACE, "name": p["name"], "number": "", "date": ""}
                t[PLACE][p["name"]] = ("The %s folder. He may call it %s." % (p["name"], ", ".join(p.get("say") or [p["name"]])),
                                       {"do": "folder", "entry": e})
        try:
            running = sorted(set(x.lower() for x in self.win.open_apps()))
        except Exception:
            running = []
        known = set()
        for a in S.get("apps", []):
            name, exes = a["name"], [x.lower() for x in a.get("exe") or []]
            if not exes:
                continue
            known.update(exes)
            t["program"][name] = ("%s (%s). He may call it %s." % (name, "open now" if set(exes) & set(running) else "not open",
                                                                 ", ".join(a.get("say") or [name])), {"name": name, "exe": exes})
        for exe in running:
            if exe not in known:
                t["program"][exe] = ("The program %s, open now." % exe, {"name": exe[:-4] if exe.endswith(".exe") else exe, "exe": [exe]})
        try:
            wins = self.win.window_titles()
        except Exception:
            wins = []
        for hwnd, exe, title, path in wins:
            name = re.sub(r" - (File Explorer|Google Chrome|Microsoft Teams|Outlook|Excel|Word)$", "", title).strip() or exe
            lab, n = name[:70] + " window", 2
            while lab in t["window"]:
                lab, n = "%s window %d" % (name[:70], n), n + 1
            about = ("The File Explorer window showing the folder %s." % path) if path else \
                ("The open %s window titled '%s'." % (exe[:-4] if exe.endswith(".exe") else exe, title))
            t["window"][lab] = (about, {"name": name, "hwnd": hwnd})
        return t

    def parts(self, e):
        """{label: path} one level inside a job or bid: its subfolders and its key files (never recursive)."""
        out = {}
        for d in sorted(dirs(e["path"])):
            out[d] = os.path.join(e["path"], d)
        for f in sorted(files(e["path"])):
            if any(fnmatch.fnmatch(f, g) for g in JL.ROOT_FILES) and not f.startswith("~$"):
                out[f] = os.path.join(e["path"], f)
        return out

    # -------------------------------------------------------------- understanding (Jev walks the tree)

    def ask(self, state, qs):
        state = dict(context=CONTEXT, **state)
        try:
            if self.jev:                                         # tests hand in a scripted Jev
                return self.jev(state, qs, lane="voice", retries=1)
            return jevcall.decide(state, qs, self.jev_key()[0], JEV_TIMEOUT, os.path.join(self.state, "jev.jsonl"))
        except Exception:
            return None

    def understand(self, text):
        """-> {"verb", "how", "action" | "say"}. Pure: acts on nothing."""
        t = self.tree()
        qs = {"action": {"type": "choice", "criteria": ACTIONS},
              "depth": {"type": "choice", "criteria": DEPTH},
              "where": {"type": "choice", "criteria": WHERE}}
        for k, items in t.items():
            crit = {lab: c for lab, (c, _) in items.items()}
            crit[NONE] = "He did not name %s." % BRANCHES[k]
            qs[k] = {"type": "choice", "criteria": crit}
        ans = self.ask({"heard": text}, qs)
        if not ans:
            return {"verb": "unknown", "how": "no jev", "say": "Jev isn't answering, so nothing was opened: " + text}

        def probs(k, a=ans):
            q = a.get(k) or {}
            p = dict(q.get("probabilities") or {})
            if not p and q.get("choice"):
                p = {q["choice"]: float(q.get("confidence") or 0)}
            return p

        def top(k):
            p = probs(k)
            return max(p, key=p.get) if p else None

        pa = probs("action")
        chosen = top("action")                                     # only Jev's choice of action can act;
        allowed = {"open", "switch"} if chosen in ("open", "switch") else {chosen}   # open and switch are one
        leaves = []                                                # (score, [level confidences], verb, label, kind, action)
        for act, p1 in pa.items():
            if act not in allowed:
                continue
            if act in ("minimize", "desktop", "help", "none"):
                leaves.append((p1, [p1], act, act, None, {"do": act, "name": ""} if act in ("minimize", "desktop") else None))
            elif act == "open":
                p = p1 + pa.get("switch", 0)                      # "pull up" / "bring up": open or switch, same thing
                for kind in OPENS:
                    rivals = FOLDERS if kind in FOLDERS else OPENS   # a job only competes with the bids, and back
                    rest = min((probs(k).get(NONE, 0) for k in rivals if k != kind), default=1)
                    for lab, p3 in probs(kind).items():
                        if lab in t[kind] and p3 > probs(kind).get(NONE, 0):   # Jev says he named it
                            a = t[kind][lab][1]
                            if kind == "app" and lab in t["program"] and "open now" in t["program"][lab][0]:
                                a = dict(t["program"][lab][1], do="switch")   # already running: bring it forward
                            leaves.append((p * p3 * rest, [p, p3, rest], "open", lab, kind, a))
            elif act in ("switch", "close"):
                for kind in ("program", "window"):
                    for lab, p3 in probs(kind).items():
                        if lab in t[kind] and p3 > probs(kind).get(NONE, 0):
                            a = dict(t[kind][lab][1], do=act if kind == "program" else act + "_window")
                            leaves.append((p1 * p3, [p1, p3], act, lab, kind, a))
        leaves.sort(key=lambda x: -x[0])
        if not leaves:
            if chosen in ("close", "switch"):
                return {"verb": "unknown", "how": "jev %s: nothing open by that name" % chosen,
                        "say": "Nothing open by that name: " + text}
            return {"verb": "unknown", "how": "jev: nothing named", "say": "Didn't catch that: " + text}
        _, conf, verb, lab, kind, action = leaves[0]
        how = "jev %s %s (%s)" % (verb, lab, " > ".join("%.2f" % c for c in conf))
        if verb == "none":
            if "close" in text.lower():
                return {"verb": "refuse", "how": how, "say": "I only close the app you name, never everything. Try: close all Chrome"}
            return {"verb": "unknown", "how": how, "say": "Didn't catch that: " + text}
        if verb == "help":
            return {"verb": "help", "how": how, "say": HELP}
        if kind in FOLDERS:
            e = action["entry"]
            if top("where") == "ops":                            # "open <job> in Ops"
                base = self.targets["ops"]["url"]
                url = base + ("/jobs/" + e["number"] if kind == ACTIVE else "/bids")
                return {"verb": "open", "how": how + " > in Ops", "action": {"do": "site", "name": label(e) + " in Ops", "url": url}}
            if top("depth") == "part":                           # the second level: this folder's real parts
                parts = self.parts(e)
                crit = {k: ("The subfolder %s." % k) if os.path.isdir(v) else ("The file %s." % k) for k, v in parts.items()}
                crit[NONE] = "None of these is the part he named."
                sub = self.ask({"heard": text, "folder": e["folder"]}, {"part": {"type": "choice", "criteria": crit}})
                pp = probs("part", sub) if sub else {}
                best = max(pp, key=pp.get) if pp else NONE
                if best in parts:
                    child = dict(e, path=parts[best], folder=e["folder"] + "\\" + best, name=label(e) + " > " + best, tier="part")
                    return {"verb": "open", "how": how + " > %s %.2f" % (best, pp[best]), "action": {"do": "folder", "entry": child}}
                how += " > part not found"                        # open the folder itself and say so
        return {"verb": verb, "how": how, "action": action}

    # -------------------------------------------------------------- acting (the allowlist)

    def act(self, a):
        """-> reply lines. The only place anything happens; each branch is one allowed action.

        Whatever it opens comes to the front: Windows won't let a background program (this one, or the
        Explorer / Chrome / Excel it starts) take the foreground, so it waits for the new window and hands
        it back as `activate`, and the bar, which is in front, brings it forward (Alex, 9/30)."""
        w, do = self.win, a["do"]
        if do == "folder":
            e = a["entry"]
            hwnd = w.explorer_window(e["path"])
            if hwnd:
                return ["show\t" + label(e) + " is open", "activate\t%s" % hwnd]
            before = {h for h, _ in w.windows()}
            w.open_path(e["path"])
            if os.path.isdir(e["path"]):
                hwnd = w.wait_explorer(e["path"])
            else:                                                 # a file: whatever opens it (Excel, Revu, Word)
                ext = os.path.splitext(e["path"])[1].lower()
                hwnd = w.new_window(before, timeout=8.0) or w.top_window(FILE_APPS.get(ext, []))
            return ["show\tOpening " + label(e)] + (["activate\t%s" % hwnd] if hwnd else [])
        if do == "app":
            before = {h for h, _ in w.windows()}
            w.open_app(a["id"])
            hwnd = w.new_window(before, timeout=8.0)             # any new window: Store apps show theirs under another program
            return ["show\tOpening " + a["name"]] + (["activate\t%s" % hwnd] if hwnd else [])
        if do == "site":
            before = {h for h, _ in w.windows()}
            w.open_url(a["url"])
            hwnd = w.new_window(before, exes=["chrome.exe"], timeout=1.5) or w.top_window(["chrome.exe"])   # a new tab: Chrome's front window
            return ["show\tOpening " + a["name"]] + (["activate\t%s" % hwnd] if hwnd else [])
        if do == "switch":
            hwnd = w.top_window(a["exe"])
            return ["show\t" + a["name"], "activate\t%s" % hwnd] if hwnd else ["show\t%s isn't open" % a["name"]]
        if do == "close":
            n = w.close_windows(a["exe"])
            return ["show\tClosing %d %s window%s" % (n, a["name"], "" if n == 1 else "s") if n
                    else "show\tNo %s windows are open" % a["name"]]
        if do == "close_window":
            w.close_window(a["hwnd"])
            return ["show\tClosing " + a["name"]]
        if do == "switch_window":
            return ["show\t" + a["name"], "activate\t%s" % a["hwnd"]]
        if do == "minimize":
            w.minimize_all()
            return ["show\tMinimized"]
        if do == "desktop":
            w.toggle_desktop()
            return ["show\tDesktop"]
        raise ValueError("not an allowed action: %r" % do)

    def command(self, text, waited_ms=0):
        t0 = time.time()
        with self._lock:                                          # a rebuild started on key-down finishes first
            r = self.understand(text)
        if r.get("action"):
            lines = self.act(r["action"])
        else:
            lines = ["show\t" + r["say"]]
        a = r.get("action") or {}
        self.log({"heard": text, "action": r["verb"] if not a else a["do"], "target": target_of(a),
                  "how": r["how"],
                  "ms": waited_ms + int((time.time() - t0) * 1000)})
        return lines

    def log(self, rec):
        try:
            os.makedirs(self.state, exist_ok=True)
            with open(os.path.join(self.state, "log.jsonl"), "a", encoding="utf-8") as f:
                f.write(json.dumps(dict(ts=time.strftime("%Y-%m-%dT%H:%M:%S"), **rec), ensure_ascii=False) + "\n")
        except OSError:
            pass


def target_of(a):
    if not a:
        return None
    return a["entry"]["folder"] if a["do"] == "folder" else a.get("name")


def protect(key):
    """The Jev key encrypted to this Windows login (DPAPI), base64. Only this user on this PC can read it."""
    if not key:
        return ""
    import win32crypt
    return base64.b64encode(win32crypt.CryptProtectData(key.encode("utf-8"), "AirX Voice", None, None, None, 0)).decode("ascii")


def unprotect(blob):
    if not blob:
        return ""
    try:
        import win32crypt
        return win32crypt.CryptUnprotectData(base64.b64decode(blob), None, None, None, 0)[1].decode("utf-8")
    except Exception:
        return ""


def wispr_hands_free():
    """Wispr's own hands-free key ("popo" in its config, read, never written) as '162+32+91', or ''."""
    try:
        c = json.load(open(os.path.join(os.environ.get("APPDATA", ""), "Wispr Flow", "config.json"), encoding="utf-8"))
        return next((k for k, v in c["prefs"]["user"]["shortcuts"].items() if v == "popo"), "")
    except Exception:
        return ""


HOTKEY_RE = re.compile(r"^[\^!+#<>]*([A-Za-z0-9]|F\d{1,2}|CapsLock|ScrollLock|Pause|Insert|Home|End|PgUp|PgDn|AppsKey|"
                       r"RCtrl|RAlt|RShift|RWin|LCtrl|LAlt|LShift|LWin|Numpad\w+|Media_\w+|Browser_\w+|XButton[12]|[`\-=\[\];',./\\])$")
VKS_RE = re.compile(r"^\d{1,3}(\+\d{1,3})*$")


def clean_list(rows, fields):
    out = []
    for r in rows or []:
        row = {f: r.get(f) for f in fields}
        say = r.get("say")
        row["say"] = [x.strip() for x in (say.split(",") if isinstance(say, str) else (say or [])) if x.strip()]
        if "exe" in fields:
            exe = r.get("exe")
            row["exe"] = [x.strip() for x in (exe.split(",") if isinstance(exe, str) else (exe or [])) if x.strip()]
        if all((row.get(f) or "").strip() if isinstance(row.get(f), str) else row.get(f) is not None for f in fields if f not in ("say", "exe")):
            out.append(row)
    return out


def settings_view(brain):
    S = brain.settings
    key, where = brain.jev_key()
    return {"hotkey": S.get("hotkey", "CapsLock"), "wispr_key": S.get("wispr_key", ""), "wispr_auto": wispr_hands_free(),
            "wispr_installed": os.path.exists(os.path.join(os.environ.get("APPDATA", ""), "Wispr Flow", "config.json")),
            "estimating_root": S.get("estimating_root", ""), "estimating_auto": brain.est,
            "jev": where, "sites": S.get("sites", []), "folders": S.get("folders", []), "apps": S.get("apps", []),
            "ops_pages": list(brain.targets["ops"]["pages"]), "jobs": sum(1 for e in brain.folders if e["tier"] == ACTIVE),
            "bids": sum(1 for e in brain.folders if e["tier"] == LIVE), "log": os.path.join(brain.state, "log.jsonl")}


def settings_save(brain, d):
    S = dict(brain.settings)
    hk = (d.get("hotkey") or "CapsLock").strip()
    if not HOTKEY_RE.match(hk):
        return {"ok": False, "error": "That key can't be the hotkey: %s" % hk}
    wk = (d.get("wispr_key") or "").strip()
    if wk and not VKS_RE.match(wk):
        return {"ok": False, "error": "The Wispr key didn't read right: %s" % wk}
    est = (d.get("estimating_root") or "").strip()
    if est and not os.path.isdir(os.path.join(est, JL.MASTER)):
        return {"ok": False, "error": "That isn't the 01 - Estimating folder (no MASTER ESTIMATING FOLDER in it): %s" % est}
    S.update(hotkey=hk, wispr_key=wk, estimating_root=est,
             sites=[r for r in clean_list(d.get("sites"), ("name", "url")) if r["url"].startswith(("http://", "https://"))],
             folders=clean_list(d.get("folders"), ("name", "path")),
             apps=clean_list(d.get("apps"), ("name", "exe")))
    brain.save_settings(S)
    brain.refresh()
    return {"ok": True}


def settings_jev_key(brain, key):
    key = (key or "").strip()
    if key:
        probe = jevcall.decide({"heard": "open the bids"}, {"action": {"type": "choice", "criteria":
                               {"open": "He wants something opened.", "none": "Anything else."}}}, key, 8.0)
        if probe is None:
            return {"ok": False, "error": "Jev didn't accept that key (or couldn't be reached). Nothing was saved."}
    S = dict(brain.settings, jev_key=protect(key))
    brain.save_settings(S)
    return {"ok": True, "jev": brain.jev_key()[1]}


def describe(r):
    a = r.get("action")
    if not a:
        return r.get("say") or "Nothing."
    do, name = a["do"], target_of(a)
    verb = {"folder": "open the folder", "site": "open", "app": "open", "switch": "switch to", "close": "close every window of",
            "close_window": "close the window", "switch_window": "switch to the window", "minimize": "minimize everything",
            "desktop": "show the desktop"}.get(do, do)
    where = a.get("url") or (a.get("entry") or {}).get("path") or ""
    return ("Would %s %s" % (verb, name or "")).strip() + (" (%s)" % where if where else "")


# ------------------------------------------------------------------ the localhost server

class Server(ThreadingHTTPServer):
    """One helper per PC: the port is exclusive, so a second copy can't bind it and exits (on Windows the
    stock server shares the port, and 9/30 a second copy overwrote the token and ~60 piled up)."""
    allow_reuse_address = False
    daemon_threads = True

    def server_bind(self):
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        self.socket.bind(self.server_address)                      # skips HTTPServer's slow getfqdn()
        self.server_address = self.socket.getsockname()
        self.server_name, self.server_port = "127.0.0.1", self.server_address[1]


def serve(brain, token, port=PORT):
    class Handler(BaseHTTPRequestHandler):
        def reply(self, code, body, ctype):
            out = body if isinstance(body, bytes) else body.encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(out)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(out)

        def do_POST(self):
            if not hmac.compare_digest(self.headers.get("X-Token", ""), token):
                self.send_error(403)
                return
            body = self.rfile.read(int(self.headers.get("Content-Length") or 0)).decode("utf-8", "replace")
            if self.path.startswith("/api/"):
                try:
                    d = json.loads(body or "{}")
                    if self.path == "/api/get":
                        res = settings_view(brain)
                    elif self.path == "/api/save":
                        res = settings_save(brain, d)
                    elif self.path == "/api/jevkey":
                        res = settings_jev_key(brain, d.get("key"))
                    elif self.path == "/api/test":
                        res = {"say": describe(brain.understand(d.get("text", ""))) if d.get("text", "").strip() else ""}
                    else:
                        self.send_error(404)
                        return
                except Exception as e:
                    brain.log({"err": "settings %s: %s: %s" % (self.path, type(e).__name__, e)})
                    res = {"ok": False, "error": "Something went wrong; it's in the log"}
                self.reply(200, json.dumps(res, ensure_ascii=False), "application/json; charset=utf-8")
                return
            try:
                if self.path == "/cmd":
                    lines = brain.command(body.strip(), int(self.headers.get("X-Waited-Ms") or 0))
                elif self.path == "/refresh":
                    brain.refresh_async()
                    lines = ["ok"]
                elif self.path == "/ping":
                    lines = ["ok"]
                else:
                    self.send_error(404)
                    return
            except Exception as e:
                brain.log({"err": "%s: %s" % (type(e).__name__, e), "heard": body})
                lines = ["show\tSomething went wrong; it's in the log"]
            self.reply(200, "\n".join(lines), "text/plain; charset=utf-8")

        def log_message(self, *a):                                # pythonw has no console to write to
            pass

    return Server(("127.0.0.1", port), Handler)


def main():
    os.makedirs(STATE, exist_ok=True)
    if sys.stderr is None:                                        # pythonw: keep tracebacks somewhere
        sys.stderr = sys.stdout = open(os.path.join(STATE, "brain.err"), "a", encoding="utf-8")
    if "--settings" in sys.argv:                                  # the Settings window, its own process
        import settings_app
        settings_app.main(HERE, STATE, PORT)
        return
    probe = socket.socket()
    try:                                                          # another helper already has the port: leave
        probe.setsockopt(socket.SOL_SOCKET, getattr(socket, "SO_EXCLUSIVEADDRUSE", socket.SO_REUSEADDR), 1)
        probe.bind(("127.0.0.1", PORT))
    except OSError:
        return
    finally:
        probe.close()
    import win
    token = secrets.token_urlsafe(24)
    try:
        srv = serve(Brain(win), token)                            # binds before the token is written
    except OSError:
        return
    with open(os.path.join(STATE, "token"), "w", encoding="utf-8") as f:
        f.write(token)
    srv.serve_forever()


if __name__ == "__main__":
    main()
