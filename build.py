"""build.py - makes dist\\AirX Voice Setup.exe from this repo, on a Windows PC.

    python build.py

Needs: Python 3.12 with pyinstaller, pywin32 and pillow (pip install pyinstaller pywin32 pillow), and
AutoHotkey v2 installed (its AutoHotkey64.exe becomes "AirX Voice.exe", which runs "AirX Voice.ahk"
because the names match). Runs the offline tests first and stops if they fail.
"""
import os
import shutil
import subprocess
import sys
import zipfile

VERSION = "1.0.3"
HERE = os.path.dirname(os.path.abspath(__file__))
BUILD = os.path.join(HERE, "build")
DIST = os.path.join(HERE, "dist")
APP = os.path.join(BUILD, "app")
AHK = r"C:\Program Files\AutoHotkey\v2"
APP_FILES = ("AirX Voice.ahk", "targets.json", "icon.ico")


def make_icon(path):
    """A blue rounded square with a white microphone, at every size Windows asks for."""
    from PIL import Image, ImageDraw
    n = 256
    im = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle((8, 8, n - 8, n - 8), radius=56, fill=(29, 95, 209, 255))
    w = (255, 255, 255, 255)
    d.rounded_rectangle((98, 44, 158, 150), radius=30, fill=w)              # the mic head
    d.arc((70, 88, 186, 184), start=0, end=180, fill=w, width=14)           # the cradle
    d.rectangle((121, 182, 135, 208), fill=w)                                # the stand
    d.rounded_rectangle((90, 204, 166, 218), radius=7, fill=w)               # the base
    im.save(path, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])


def run(*cmd):
    print(">", " ".join(cmd))
    subprocess.run(cmd, cwd=HERE, check=True)


def main():
    if not os.path.exists(os.path.join(HERE, "icon.ico")):
        make_icon(os.path.join(HERE, "icon.ico"))
    run(sys.executable, os.path.join("tests", "run_phrases.py"))
    shutil.rmtree(BUILD, ignore_errors=True)
    os.makedirs(APP)

    # the helper, frozen with everything it imports (pywin32, tkinter for the folder picker)
    run(sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onedir", "--noconsole", "--name", "brain",
        "--icon", os.path.join(HERE, "icon.ico"), "--distpath", APP, "--workpath", os.path.join(BUILD, "pyi"), "--specpath", BUILD, os.path.join(HERE, "brain.py"))

    for f in APP_FILES:
        shutil.copy2(os.path.join(HERE, f), APP)
    shutil.copy2(os.path.join(AHK, "AutoHotkey64.exe"), os.path.join(APP, "AirX Voice.exe"))
    shutil.copy2(os.path.join(AHK, "license.txt") if os.path.exists(os.path.join(AHK, "license.txt"))
                 else os.path.join(os.path.dirname(AHK), "license.txt"), os.path.join(APP, "AutoHotkey license.txt"))
    with open(os.path.join(APP, "version.txt"), "w") as f:
        f.write(VERSION)

    payload = os.path.join(BUILD, "app.zip")
    with zipfile.ZipFile(payload, "w", zipfile.ZIP_DEFLATED) as z:
        for root, _, files in os.walk(APP):
            for f in files:
                full = os.path.join(root, f)
                z.write(full, os.path.relpath(full, APP))

    run(sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onefile", "--noconsole",
        "--name", "AirX Voice Setup", "--icon", os.path.join(HERE, "icon.ico"), "--add-data", payload + os.pathsep + ".",
        "--distpath", DIST, "--workpath", os.path.join(BUILD, "pyi-setup"), "--specpath", BUILD, os.path.join(HERE, "setup.py"))
    out = os.path.join(DIST, "AirX Voice Setup.exe")
    print("built %s (%.1f MB), version %s" % (out, os.path.getsize(out) / 1e6, VERSION))


if __name__ == "__main__":
    main()
