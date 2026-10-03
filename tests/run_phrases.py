#!/usr/bin/env python3
"""run_phrases.py - airx-voice's tests.

    python tests/run_phrases.py         offline: the tree walk with a scripted Jev (no network, no Windows)
    python tests/run_phrases.py --live  on the PC: tests/phrases.jsonl against the real folders and live Jev,
                                        acting on nothing (the Windows calls that change anything are stubbed)

The live cases name real folders, so they change as bids go out and jobs close: fix the line, not the brain.
"""
import json
import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import brain  # noqa: E402

ACTS = {"open_path", "open_app", "open_url", "close_windows", "close_window", "minimize_all", "toggle_desktop"}


class FakeWin:
    def start_apps(self):
        return [("Bluebeam Revu", "Revu"), ("Outlook", "olk"), ("Excel", "xl"), ("Word", "wd"), ("Google Chrome", "Chrome"),
                ("File Explorer", "fe"), ("Microsoft Teams", "teams"), ("Claude", "claude")]

    def open_apps(self):
        return ["chrome.exe", "explorer.exe", "olk.exe", "whatsapp.exe"]

    def windows(self):
        return []

    def window_titles(self):
        return [(11, "explorer.exe", "07 REFERENCE - File Explorer", "C:\\x\\09 25 Sample Apartments\\07 REFERENCE"),
                (12, "chrome.exe", "Bids - AirX Ops - Google Chrome", "")]

    def __getattr__(self, name):
        return lambda *a: None


def outcome(r):
    a = r.get("action")
    if a:
        return a["do"], brain.target_of(a)
    return r["verb"], None


def offline():
    root = tempfile.mkdtemp(prefix="airx_voice_")
    est, active = os.path.join(root, "01 - Estimating"), os.path.join(root, "02 - Active Projects")
    for d in ("09 25 Sample Apartments", "0a 2026 Post Bid/07 15 Sample Store", "Z Archive/01 01 Old"):
        os.makedirs(os.path.join(est, d))
    os.makedirs(os.path.join(active, "Sample Clinic - 25100"))
    os.makedirs(os.path.join(active, "z 2025 Archive", "Old Job - 25001"))
    reply = {}
    b = brain.Brain(FakeWin(), lambda state, qs, **k: reply.get("a"), est=est, active=active, state=os.path.join(root, "s"),
                    settings=os.path.join(root, "settings.json"))
    assert os.path.exists(os.path.join(root, "settings.json")), "first run seeds his settings"
    assert [x["name"] for x in b.settings["sites"]][:1] == ["PlanCenter NW"], "sites seeded from targets.json"
    assert b.settings["hotkey"] == "CapsLock" and b.settings["wispr_key"] == ""
    # a saved setting is used at once: a new site is in the tree, a bad hotkey is refused
    new = dict(b.settings, sites=b.settings["sites"] + [{"name": "Weather", "url": "https://weather.gov", "say": "weather, forecast"}])
    assert brain.settings_save(b, new)["ok"] and "Weather" in b.tree()["site"]
    assert b.settings["sites"][-1]["say"] == ["weather", "forecast"], "'you call it' is split on commas"
    assert not brain.settings_save(b, dict(new, hotkey="caps lock please"))["ok"]
    assert not brain.settings_save(b, dict(new, estimating_root=root))["ok"], "not an estimating folder"
    check_layout()
    # one helper per PC: a second server can't take the first one's port (9/30: ~60 piled up without this)
    first = brain.serve(b, "t", port=0)
    try:
        brain.serve(b, "t", port=first.server_address[1])
        raise AssertionError("a second helper bound the same port")
    except OSError:
        pass
    finally:
        first.server_close()
    t = b.tree()
    assert list(t["active job"]) == ["Sample Clinic (job 25100)"], t["active job"]
    assert list(t["live bid"]) == ["Sample Apartments (bid 09/25)"], "archives and Post Bid stay out of the tree"

    def ans(action, **branches):
        a = {"action": {"choice": max(action, key=action.get), "probabilities": action}}
        for k in t:
            p = branches.get(k, {brain.NONE: 1.0})
            a[k] = {"choice": max(p, key=p.get), "probabilities": p}
        return a

    cases = [
        (None, "anything", ("unknown", None)),                                        # Jev down: nothing happens
        (ans({"open": .98}, **{"active job": {"Sample Clinic (job 25100)": .97, brain.NONE: .03}}),
         "open sample clinic", ("folder", "Sample Clinic - 25100")),
        (ans({"open": .6, "switch": .35}, **{"live bid": {"Sample Apartments (bid 09/25)": .99}}),
         "pull up sample apartments", ("folder", "09 25 Sample Apartments")),       # open + switch count together
        (ans({"open": .98}, **{"active job": {"Sample Clinic (job 25100)": .9, brain.NONE: .1},
                               "live bid": {"Sample Apartments (bid 09/25)": .5, brain.NONE: .5}}),
         "open sample", ("folder", "Sample Clinic - 25100")),                  # both lists claim it: the top pick
        (ans({"close": .97}, program={"Google Chrome": .99}), "close chrome", ("close", "Google Chrome")),
        (ans({"none": .95}), "close everything", ("refuse", None)),
        (ans({"none": .95}), "hello there", ("unknown", None)),
        (ans({"open": .99}, app={brain.NONE: .74, "File Explorer": .26}), "open the thing", ("unknown", None)),  # every list says none
        (ans({"minimize": .95}), "minimize all", ("minimize", "")),
        (ans({"close": .97}, window={"07 REFERENCE window": .95}), "close the reference folder", ("close_window", "07 REFERENCE")),
        (ans({"close": .9, "open": .1}, **{"live bid": {"Sample Apartments (bid 09/25)": .9}}), "close the apartments folder",
         ("unknown", None)),                                                          # not open: never falls through to open
        (ans({"switch": .97}, window={"Bids - AirX Ops window": .9}), "switch to the bids page", ("switch_window", "Bids - AirX Ops")),
    ]
    bad = 0
    for a, said, want in cases:
        reply["a"] = a
        got = outcome(b.understand(said))
        if got != want:
            bad += 1
            print("FAIL  %-28s -> %s, wanted %s" % (said, got, want))
    reply["a"] = cases[1][0]
    assert b.command("open sample")[0].startswith("show\tOpening"), "a command opens and says so"
    print("offline: %d/%d walk cases passed" % (len(cases) - bad, len(cases)))
    return bad


def check_layout():
    """layout.py is a copy of Claude/job_layout.py's rules: they must still match when that file is here."""
    src = os.path.join(os.path.expanduser("~"), "Cowork Files", "Claude")
    if not os.path.exists(os.path.join(src, "job_layout.py")):
        return
    sys.path.insert(0, src)
    import job_layout
    import layout
    for name in ("JOB_RE", "MASTER", "BID_SHEET_GLOB", "TAKEOFF_PDF_GLOB", "ROOT_FILES"):
        a, b = getattr(layout, name), getattr(job_layout, name)
        assert (a.pattern if hasattr(a, "pattern") else a) == (b.pattern if hasattr(b, "pattern") else b), \
            "layout.%s no longer matches Claude/job_layout.py: copy it over" % name


def live():
    import win

    class DryWin:
        def __getattr__(self, n):
            return (lambda *a: 0) if n in ACTS else getattr(win, n)
    tmp = tempfile.mkdtemp(prefix="airx_voice_live_")                 # today's defaults, not his edits
    b = brain.Brain(DryWin(), None, state=os.path.join(tmp, "state"), settings=os.path.join(tmp, "settings.json"))
    if not b.jev_key()[0]:
        print("no Jev key on this PC: the live test needs one")
        return 1
    bad, n = 0, 0
    for line in open(os.path.join(HERE, "phrases.jsonl"), encoding="utf-8"):
        if not line.strip():
            continue
        c, n = json.loads(line), n + 1
        t0 = time.time()
        r = b.understand(c["say"])
        ms = int((time.time() - t0) * 1000)
        do, target = outcome(r)
        wants = c["do"] if isinstance(c["do"], list) else [c["do"]]
        ok = do in wants and (c.get("target") is None or target == c["target"])
        bad += not ok
        print("%s %-42s -> %-8s %-40s %4d ms  [%s]" % ("ok  " if ok else "FAIL", c["say"], do, target or "", ms, r["how"]))
    print("live: %d/%d phrases passed" % (n - bad, n))
    return bad


if __name__ == "__main__":
    sys.exit(1 if (live() if "--live" in sys.argv else offline()) else 0)
