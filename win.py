"""win.py - everything in airx-voice that only runs on Windows (pywin32, Shell.Application, ctypes).

brain.py calls only these functions, and tests/run_phrases.py swaps this module for a fake, so the matcher
is tested anywhere. Closing is clicking the X: WM_CLOSE to a program's windows, or .Quit() on File Explorer
windows. Never TerminateProcess, never taskkill.
"""
import ctypes
import os
import subprocess
import time
import winreg
from ctypes import wintypes

import pythoncom
import win32com.client
import win32con
import win32gui
import win32process

APPS_FOLDER = "shell:::{4234d49b-0245-4df3-b780-3893943456e1}"     # shell:AppsFolder, what Get-StartApps lists
NO_WINDOW = 0x08000000                                             # CREATE_NO_WINDOW: nothing flashes
_k32 = ctypes.windll.kernel32
_dwm = ctypes.windll.dwmapi


def _shell():
    pythoncom.CoInitialize()                      # every server thread needs its own COM start; repeats are free
    return win32com.client.Dispatch("Shell.Application")


def start_apps():
    """[(name, AppID)] from the Start menu's app list."""
    return [(i.Name, i.Path) for i in _shell().NameSpace(APPS_FOLDER).Items()]


def open_app(appid):
    subprocess.Popen(["explorer.exe", "shell:AppsFolder\\" + appid], creationflags=NO_WINDOW)


def open_path(path):
    os.startfile(path)


def _chrome():
    for root in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        try:
            with winreg.OpenKey(root, r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\chrome.exe") as k:
                return winreg.QueryValue(k, None)
        except OSError:
            pass
    return None


def open_url(url):
    exe = _chrome()
    if exe:
        subprocess.Popen([exe, url], creationflags=NO_WINDOW)
    else:
        os.startfile(url)                           # no Chrome found: the default browser


def _explorers():
    for w in _shell().Windows():
        try:
            if os.path.basename(w.FullName).lower() == "explorer.exe":
                yield w
        except Exception:                           # a window closing while we look
            continue


def explorer_window(path):
    """The hwnd of a File Explorer window already showing path, or None."""
    want = os.path.normcase(os.path.normpath(path))
    for w in _explorers():
        try:
            if os.path.normcase(os.path.normpath(w.Document.Folder.Self.Path)) == want:
                return w.HWND
        except Exception:
            continue
    return None


def _exe(hwnd):
    _, pid = win32process.GetWindowThreadProcessId(hwnd)
    h = _k32.OpenProcess(0x1000, False, pid)        # PROCESS_QUERY_LIMITED_INFORMATION: works on elevated apps too
    if not h:
        return ""
    try:
        buf, n = ctypes.create_unicode_buffer(1024), wintypes.DWORD(1024)
        return os.path.basename(buf.value).lower() if _k32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(n)) else ""
    finally:
        _k32.CloseHandle(h)


def _cloaked(hwnd):
    v = ctypes.c_int(0)
    _dwm.DwmGetWindowAttribute(wintypes.HWND(hwnd), 14, ctypes.byref(v), ctypes.sizeof(v))   # DWMWA_CLOAKED
    return v.value != 0


def windows():
    """[(hwnd, exe)] of the visible top-level app windows, front to back (the first is the newest used)."""
    out = []

    def each(hwnd, _):
        if (win32gui.IsWindowVisible(hwnd) and win32gui.GetWindowText(hwnd) and not win32gui.GetWindow(hwnd, win32con.GW_OWNER)
                and not win32gui.GetWindowLong(hwnd, win32con.GWL_EXSTYLE) & win32con.WS_EX_TOOLWINDOW and not _cloaked(hwnd)):
            out.append((hwnd, _exe(hwnd)))
        return True
    win32gui.EnumWindows(each, None)
    return out


def open_apps():
    return [exe for _, exe in windows() if exe]


def window_titles():
    """[(hwnd, exe, title, folder path or "")] of the visible app windows; File Explorer windows carry their path."""
    paths = {}
    for w in _explorers():
        try:
            paths[int(w.HWND)] = w.Document.Folder.Self.Path
        except Exception:
            continue
    return [(h, exe, win32gui.GetWindowText(h), paths.get(h, "")) for h, exe in windows()]


def close_window(hwnd):
    """Asks one window to close, as its X would."""
    win32gui.PostMessage(hwnd, win32con.WM_CLOSE, 0, 0)


def new_window(before, exes=None, timeout=4.0):
    """The first app window that wasn't in `before` (hwnds), optionally of these programs; None after timeout."""
    exes = {x.lower() for x in exes} if exes else None
    end = time.time() + timeout
    while time.time() < end:
        for h, exe in windows():
            if h not in before and (exes is None or exe in exes):
                return h
        time.sleep(0.1)
    return None


def wait_explorer(path, timeout=4.0):
    end = time.time() + timeout
    while time.time() < end:
        h = explorer_window(path)
        if h:
            return h
        time.sleep(0.1)
    return None


def top_window(exes):
    exes = {x.lower() for x in exes}
    return next((h for h, exe in windows() if exe in exes), None)


def close_windows(exes):
    """Asks each window of these programs to close, as its X would. Returns how many were asked."""
    exes = {x.lower() for x in exes}
    if "explorer.exe" in exes:                      # folder windows only: the taskbar and desktop are explorer too
        n = 0
        for w in list(_explorers()):
            try:
                w.Quit()
                n += 1
            except Exception:
                pass
        return n
    hwnds = [h for h, exe in windows() if exe in exes]
    for h in hwnds:
        win32gui.PostMessage(h, win32con.WM_CLOSE, 0, 0)
    return len(hwnds)


def minimize_all():
    _shell().MinimizeAll()


def toggle_desktop():
    _shell().ToggleDesktop()
