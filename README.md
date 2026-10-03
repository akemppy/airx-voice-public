# AirX Voice

Voice commands for your PC. Press Caps Lock, say what you want, press Caps Lock again: "open PlanHub",
"open my downloads", "close all Chrome", "switch to Outlook", "minimize everything".

The first press opens a bar at the top of the screen and starts Wispr Flow listening (it sends Wispr's own
hands-free key for you). The second press stops Wispr; Wispr types what it heard into the bar and AirX
Voice does it, then says what it did. Esc cancels. Shift+Caps Lock still toggles capitals. You can also
type into the bar and press Enter.

Built at AirX LLC, an HVAC contractor. The job, bid and AirX Ops commands only work on AirX's folders; on
any other PC it opens, closes and switches your own websites, folders, apps and windows.

## Set it up

1. **Wispr Flow** installed and signed in (wisprflow.ai). AirX Voice uses Wispr to hear you.
2. **A TypeSafe key.** AirX Voice uses Jev, TypeSafe's model, to decide what you meant. It's in early
   access: get on the list at typesafe.ai, then create a key in their console.
3. **Install.** Download `AirX Voice Setup.exe` from
   [Releases](https://github.com/akemppy/airx-voice-public/releases/latest) and run it. Windows warns
   because it isn't signed: More info > Run anyway. No admin rights: it installs for your Windows login
   only, starts with Windows, and shows up in the Start menu and in Settings > Apps (Uninstall is there).
4. **Paste the key.** Click the blue microphone in the tray > General > paste the key > Save key. It checks
   the key with Jev before saving.
5. **Try it.** The Try it tab shows what a phrase would do without opening anything. Then press Caps Lock
   and talk.
6. **Make it yours** with the prompt below.

## Make it yours: have your AI set it up from how you actually use your PC

It starts with AirX's websites and apps. The fastest way to make it useful is to let Claude Code (or any
AI that can read files and run PowerShell on your PC) look at what you open most and load that in. That's
how AirX's list was built: 90 days of Chrome history, program launch counts, and recently opened files.
Paste this:

```text
I installed AirX Voice, a voice command tool for my PC (README: https://github.com/akemppy/airx-voice-public).
Make it fit how I actually use this computer.

1. Look at the last 90 days, read-only:
   - Browser history. Chrome: %LOCALAPPDATA%\Google\Chrome\User Data\Default\History (and any other
     profile folders). Edge: %LOCALAPPDATA%\Microsoft\Edge\User Data\Default\History. Copy the file
     before you read it; the browser locks it. Rank sites by visits.
   - Programs I start most: the UserAssist run counts in HKCU\Software\Microsoft\Windows\CurrentVersion\
     Explorer\UserAssist (the names are ROT13), plus Get-StartApps for each program's Start menu name.
   - Folders and files I open most: the shortcuts in %APPDATA%\Microsoft\Windows\Recent.
2. Work only. Leave out personal browsing, banking, health and anything private.
3. Show me the list before you write anything: about 20 websites, 10 folders and 10 apps, each with 2 to 4
   names I'd actually say out loud (short ones, plus how dictation is likely to mishear them). Wait for my OK.
4. Back up %APPDATA%\AirX Voice\settings.json, then replace only its "sites", "folders" and "apps" lists,
   in the format already in the file. An app's "name" must match its Start menu name exactly; "exe" is its
   .exe file. Don't touch any other key in that file.
5. Have me check a few in Settings > Try it. Remind me to come back in a week: you'll read
   %LOCALAPPDATA%\AirX Voice\log.jsonl and fix every phrase that didn't work.
```

AirX Voice reads `settings.json` again each time you press your key, so a change takes effect on the next
command. The entries look like this:

```json
"sites":   [{"name": "PlanHub", "url": "https://subcontractor.planhub.com/leads/list", "say": ["planhub", "plan hub"]}],
"folders": [{"name": "Bids folder", "path": "C:\\Users\\you\\Documents\\Bids", "say": ["bids", "the bids folder"]}],
"apps":    [{"name": "Bluebeam Revu", "say": ["revu", "bluebeam"], "exe": ["Revu.exe"]}]
```

## Settings

Click the tray icon (a blue microphone), or right-click it > Settings. Tabs: General, Websites, Folders,
Apps, Try it.

- **Your key**: Caps Lock unless you pick another. Press "Change", then the key.
- **Wispr's hands-free key**: read from Wispr's own settings, so it follows Wispr. "Change" only if you
  want a different one.
- **Jev key**: saved encrypted to your Windows login. With none saved it uses `TYPESAFE_API_KEY` from the
  environment.
- **Websites, Folders, Apps**: Add, Edit, Remove. Name, address or folder (Browse), and what you call it,
  separated by commas. Jev reads these; nothing needs to match exactly.
- **Built in**: closing, switching and minimizing windows; at AirX, every active job and live bid.
- **Try it**: type what you'd say; it shows what would happen and opens nothing.

Settings live in `%APPDATA%\AirX Voice\settings.json`; the log of every command (what it heard, what it
did, how Jev decided) in `%LOCALAPPDATA%\AirX Voice\log.jsonl` (tray > Open the log).

## How it decides

No fuzzy matching and no pick lists. The helper keeps a tree in memory and Jev walks it in one call: what
to do, then what kind (website, app, folder, open program, one open window, and at AirX a job or bid), then
which one. It opens Jev's top pick. Only the action Jev heard can happen, so "close X" never opens X.
Nothing named, or Jev unreachable: nothing happens and the bar says so. Closing is the window's X, so
unsaved work still asks; "close everything" is refused.

It reads folder names only, never a file's contents. It writes only its settings, token and log.

## Files

| File | Job |
|---|---|
| `AirX Voice.ahk` | AutoHotkey v2: your key, the bar, Wispr's key, the tray. Installed as `AirX Voice.exe` (AutoHotkey renamed, so it runs the .ahk with its name). Starts the helper and restarts it if it stops. |
| `brain.py` | The helper (`brain\brain.exe` installed), on 127.0.0.1 with a token: the tree, Jev, the actions, the settings API. Exactly one runs: its port is exclusive. |
| `win.py` | The Windows-only part: windows, File Explorer, the Start menu list, opening and closing. |
| `jevcall.py` | Calls Jev directly (one try, 3 s). |
| `layout.py` | AirX's job-folder rules. |
| `settings_app.py` | The Settings window (tkinter; the helper started with `--settings`). It saves through the helper. |
| `targets.json` | The websites, folders and apps a new install starts with. |
| `setup.py`, `build.py`, `icon.ico` | The installer and the build. |
| `tests/` | `run_phrases.py` (offline: the tree walk with a scripted Jev, and settings) and `phrases.jsonl` (phrases for `--live`). |

## Build and test (on a Windows PC)

    pip install pyinstaller pywin32 pillow
    python tests\run_phrases.py            # offline
    python tests\run_phrases.py --live     # live Jev, opens nothing
    python build.py                        # runs the offline tests, then makes dist\AirX Voice Setup.exe

`build.py` needs AutoHotkey v2 installed.
