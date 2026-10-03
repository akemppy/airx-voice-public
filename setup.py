"""setup.py - "AirX Voice Setup.exe": installs, updates and uninstalls AirX Voice for the current Windows user.

No admin rights: everything goes under the user's own profile.
    %LOCALAPPDATA%\\Programs\\AirX Voice\\     the app (AirX Voice.exe, AirX Voice.ahk, brain\\, icon, pages)
    Start menu + Startup shortcuts            "AirX Voice", so it starts with Windows
    HKCU ...\\Uninstall\\AirXVoice              so it shows in Settings > Apps, with an Uninstall button
His settings (%APPDATA%\\AirX Voice) and log (%LOCALAPPDATA%\\AirX Voice) are left alone by both install
and uninstall, so an update keeps his websites, folders, key and Jev key.

    AirX Voice Setup.exe               install or update, start it, say so
    AirX Voice Setup.exe /uninstall    remove it (asks first)
    add /quiet to either to skip the message boxes
build.py freezes this with the app folder zipped inside (app.zip).
"""
import ctypes
import os
import shutil
import subprocess
import sys
import tempfile
import time
import winreg
import zipfile

NAME = "AirX Voice"
DEST = os.path.join(os.environ["LOCALAPPDATA"], "Programs", NAME)
EXE = os.path.join(DEST, NAME + ".exe")
UNINSTALLER = os.path.join(DEST, "Uninstall " + NAME + ".exe")
UNINSTALL_KEY = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\AirXVoice"
NO_WINDOW = 0x08000000
QUIET = "/quiet" in sys.argv


def box(text, flags=0x40):
    """A Windows message box; 0x40 info, 0x30 warning, 0x24 yes/no question. Returns the button (6 = Yes)."""
    if QUIET:
        return 6
    return ctypes.windll.user32.MessageBoxW(None, text, NAME, flags | 0x10000)   # 0x10000: in front


def shell_folder(name):
    import win32com.client
    return win32com.client.Dispatch("WScript.Shell").SpecialFolders(name)


def shortcuts():
    return [os.path.join(shell_folder("Programs"), NAME + ".lnk"), os.path.join(shell_folder("Startup"), NAME + ".lnk")]


def stop_running():
    """Ends AirX Voice's own processes (the ones running from the install folder), so files can be replaced."""
    ps = ("Get-CimInstance Win32_Process | Where-Object { $_.ExecutablePath -and $_.ExecutablePath.StartsWith('%s', "
          "[StringComparison]::OrdinalIgnoreCase) } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }" % DEST.replace("'", "''"))
    subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps], creationflags=NO_WINDOW, timeout=30)
    time.sleep(0.5)


def install():
    payload = os.path.join(getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__))), "app.zip")
    stop_running()
    if os.path.isdir(DEST):
        shutil.rmtree(DEST, ignore_errors=True)
    os.makedirs(DEST, exist_ok=True)
    with zipfile.ZipFile(payload) as z:
        z.extractall(DEST)
        version = z.read("version.txt").decode().strip() if "version.txt" in z.namelist() else ""
    if getattr(sys, "frozen", False):
        shutil.copy2(sys.executable, UNINSTALLER)

    import win32com.client
    sh = win32com.client.Dispatch("WScript.Shell")
    for lnk in shortcuts():
        s = sh.CreateShortcut(lnk)
        s.TargetPath = EXE
        s.WorkingDirectory = DEST
        s.IconLocation = os.path.join(DEST, "icon.ico")
        s.Description = "Voice commands for your PC: press Caps Lock, talk, press it again"
        s.Save()

    size = sum(os.path.getsize(os.path.join(r, f)) for r, _, fs in os.walk(DEST) for f in fs) // 1024
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, UNINSTALL_KEY) as k:
        for name, val in (("DisplayName", NAME), ("DisplayVersion", version), ("Publisher", "AirX LLC"),
                          ("DisplayIcon", os.path.join(DEST, "icon.ico")), ("InstallLocation", DEST),
                          ("UninstallString", '"%s" /uninstall' % UNINSTALLER),
                          ("QuietUninstallString", '"%s" /uninstall /quiet' % UNINSTALLER)):
            winreg.SetValueEx(k, name, 0, winreg.REG_SZ, val)
        for name, val in (("NoModify", 1), ("NoRepair", 1), ("EstimatedSize", size)):
            winreg.SetValueEx(k, name, 0, winreg.REG_DWORD, val)

    subprocess.Popen([EXE], cwd=DEST, creationflags=0x00000008)            # DETACHED_PROCESS
    box("AirX Voice %s is installed and running.\n\nPress Caps Lock, say what you want, press Caps Lock again.\n\n"
        "Your websites, folders, keys and Jev key: right-click the tray icon > Settings." % version)


def relaunched_from_temp():
    """Running from the folder it's about to replace or delete: run a copy from %TEMP% instead."""
    here = os.path.dirname(os.path.abspath(sys.executable))
    if not getattr(sys, "frozen", False) or os.path.normcase(here) != os.path.normcase(DEST):
        return False
    tmp = os.path.join(tempfile.gettempdir(), "AirX Voice Setup (temp).exe")
    shutil.copy2(sys.executable, tmp)
    subprocess.Popen([tmp] + sys.argv[1:], creationflags=0x00000008)
    return True


def uninstall():
    if box("Remove AirX Voice from this PC?\n\nYour settings stay, in case you install it again.", 0x24) != 6:
        return
    stop_running()
    for lnk in shortcuts():
        try:
            os.remove(lnk)
        except OSError:
            pass
    try:
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, UNINSTALL_KEY)
    except OSError:
        pass
    shutil.rmtree(DEST, ignore_errors=True)
    box("AirX Voice is removed.")


if __name__ == "__main__":
    try:
        if not relaunched_from_temp():
            uninstall() if "/uninstall" in sys.argv else install()
    except Exception as e:
        box("AirX Voice setup stopped: %s: %s" % (type(e).__name__, e), 0x30)
        sys.exit(1)
