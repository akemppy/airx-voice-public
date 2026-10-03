#Requires AutoHotkey v2.0
#SingleInstance Force
; AirX Voice.ahk - the keyboard half of AirX Voice: your key, the bar, Wispr, the tray icon.
; Installed, "AirX Voice.exe" (AutoHotkey, renamed) runs this file because it has the same name; it starts
; brain\brain.exe hidden and starts it again if it stops answering. From the repo it starts pythonw brain.py.
;
; Press your key (Caps Lock unless Settings says otherwise): the bar opens with the cursor in it and this
; sends Wispr's hands-free key, so Wispr starts listening. Press your key again: Wispr stops and types what
; it heard into the bar, and the brain does it. Esc cancels (Wispr's own Esc throws the dictation away).
; Wispr gets its key only after yours is let go: Wispr ignores its shortcut while another key is held down
; (tested 9/30, the reason holding Caps Lock never worked).

PORT := 47823                                           ; brain.py's AIRX_VOICE_PORT
STATE := EnvGet("LOCALAPPDATA") "\AirX Voice"           ; the brain's token, log.jsonl
SETTINGS := EnvGet("APPDATA") "\AirX Voice\settings.json"
PYTHONW := EnvGet("LOCALAPPDATA") "\Programs\Python\Python312\pythonw.exe"

MYKEY := Setting("hotkey", "CapsLock")
BASE := RegExReplace(MYKEY, "^[\^!+#<>*~$]+")          ; the key itself, to wait for its release
WISPR := WisprKeys()
bar := "", box := "", status := ""
listening := false, awaiting := false, heard := "", keyUp := 0, lastStart := 0, misses := 0
SETTINGS_WINDOWS := ["AirX Voice Settings", "Press the key you want to use", "Press Wispr's hands-free keys together"]
settingsTime := FileTimeOf(SETTINGS)

A_IconTip := "AirX Voice: press " KeyLabel(MYKEY)
if FileExist(A_ScriptDir "\icon.ico")
    TraySetIcon(A_ScriptDir "\icon.ico")
A_TrayMenu.Delete()
A_TrayMenu.Add("Settings", OpenSettings)
A_TrayMenu.Add("What can I say", (*) => (ShowBar(false), status.Value := HelpText(), SetTimer(HideBar, -12000)))
A_TrayMenu.Add("Open the log", (*) => Run('notepad.exe "' STATE '\log.jsonl"'))
A_TrayMenu.Add()
A_TrayMenu.Add("Pause", TogglePause)
A_TrayMenu.Add("Quit", (*) => ExitApp())
A_TrayMenu.Default := "Settings"
A_TrayMenu.ClickCount := 1

HotIf(NotInSettings)                                     ; in Settings the key is just a key, so it can be picked
try Hotkey("$" MYKEY, Pressed)
catch {
    TrayTip("Can't use " KeyLabel(MYKEY) " as the key. Pick another in Settings.", "AirX Voice")
}
if BASE = "CapsLock"
    Hotkey("+CapsLock", (*) => SetCapsLockState(!GetKeyState("CapsLock", "T")))   ; Shift+Caps Lock still toggles it
HotIf()

StartBrain()
SetTimer(StartBrain, 5000)
SetTimer(WatchSettings, 2000)

; ---------------------------------------------------------------- your key

Pressed(*) {
    global listening, awaiting, keyUp
    KeyWait(BASE)
    Loop 40 {                                            ; and any Ctrl/Alt/Shift/Win of the hotkey (up to 2 s)
        if !(GetKeyState("Ctrl", "P") || GetKeyState("Alt", "P") || GetKeyState("Shift", "P") || GetKeyState("LWin", "P") || GetKeyState("RWin", "P"))
            break
        Sleep(50)
    }
    if listening {                                       ; second press: stop, Wispr types into the bar
        listening := false, awaiting := true, keyUp := A_TickCount
        SetTimer(StopListening, 0)
        status.Value := "Working..."
        WisprToggle()
        SetTimer(Settled, -1000)                         ; Windows voice typing types as you talk: it's already there
        SetTimer(GiveUp, -10000)
        return
    }
    ShowBar(true)
    Call("/refresh")                                     ; the tree reloads while he talks
    WisprToggle()
    listening := true, awaiting := false
    status.Value := "Listening. Press " KeyLabel(MYKEY) " when you're done, Esc to cancel."
    SetTimer(StopListening, -60000)                      ; a minute is the most one command needs
}

StopListening() {
    if listening
        Pressed()
}

GiveUp() {
    global awaiting
    if awaiting {
        awaiting := false
        status.Value := "Wispr didn't type anything. Is Wispr running?"
        SetTimer(HideBar, -4000)
    }
}

; ---------------------------------------------------------------- Wispr

WisprKeys() {
    ; Settings' Wispr key, else Wispr's own hands-free key ("popo" in its config, read, never written).
    v := Setting("wispr_key", "")
    wispr := EnvGet("APPDATA") "\Wispr Flow\config.json"
    if v = "" && FileExist(wispr) {
        try {
            if RegExMatch(FileRead(wispr, "UTF-8"), '"(\d+(?:\+\d+)*)"\s*:\s*"popo"', &m)
                v := m[1]
        }
        if v = ""
            v := "162+91+32"                             ; Ctrl+Win+Space, Wispr's default
    }
    if v = ""
        v := "91+72"                                     ; no Wispr on this PC: Windows voice typing, Win+H
    mods := [], keys := []
    for k in StrSplit(v, "+") {
        k := Integer(k)
        (k >= 160 && k <= 165 || k = 91 || k = 92) ? mods.Push(k) : keys.Push(k)
    }
    s := "{Blind}"
    for k in mods
        s .= Format("{vk{:02X} down}", k)
    for k in keys
        s .= Format("{vk{:02X} down}{vk{:02X} up}", k, k)
    s .= "{vkE8}"                                        ; the menu mask, or letting go of Win opens Start
    i := mods.Length
    while i >= 1
        s .= Format("{vk{:02X} up}", mods[i--])
    return s
}

WisprToggle() {
    Send(WISPR)
}

; ---------------------------------------------------------------- the bar

ShowBar(focus) {
    global bar, box, status
    if !bar {
        bar := Gui("+AlwaysOnTop -Caption +ToolWindow +Border", "AirX Voice")
        bar.BackColor := "202020"
        bar.SetFont("s12 cWhite", "Segoe UI")
        box := bar.Add("Edit", "w640 r1 -E0x200 Background303030 cWhite")
        status := bar.Add("Text", "w640 r8 cSilver")
        bar.Add("Button", "Default x-100 y-100 w1 h1", "Go").OnEvent("Click", (*) => Submit())   ; Enter runs what's typed
        box.OnEvent("Change", Changed)
        bar.OnEvent("Escape", Cancel)
    }
    SetTimer(HideBar, 0)
    SetTimer(Submit, 0)
    box.Value := ""
    status.Value := ""
    bar.Show("xCenter y12 AutoSize")
    if focus {
        try WinActivate("ahk_id " bar.Hwnd)              ; Windows won't always hand focus to a new window
        try WinWaitActive("ahk_id " bar.Hwnd, , 0.5)
        box.Focus()
    }
}

Changed(*) {
    if awaiting                                          ; Wispr pastes it all at once: go 350 ms after
        SetTimer(Settled, -350)
}

Settled() {
    if awaiting && Trim(box.Value) != ""                 ; once per command, whichever timer comes first
        Submit()
}

Cancel(*) {
    global listening, awaiting
    listening := false, awaiting := false               ; Wispr sees the same Esc and throws its dictation away
    SetTimer(StopListening, 0)
    HideBar()
}

HideBar(*) {
    SetTimer(Submit, 0)
    if bar && !listening && !awaiting
        bar.Hide()
}

Submit() {
    global heard, awaiting
    text := RegExReplace(Trim(box.Value), "[.!?,;:]+$")
    if text = ""
        return
    awaiting := false
    SetTimer(GiveUp, 0)
    heard := text
    status.Value := "Heard: " heard "`nOpening..."
    DllCall("AllowSetForegroundWindow", "UInt", 0xFFFFFFFF)   ; the bar is in front: let what it opens come forward
    Reply(Call("/cmd", heard, keyUp ? A_TickCount - keyUp : 0))
}

Reply(r) {
    if r = "" {
        status.Value := "Heard: " heard "`nAirX Voice's helper isn't answering. Starting it again; try once more."
        StartBrain()
        SetTimer(HideBar, -4000)
        return
    }
    msg := "", hwnd := 0
    for line in StrSplit(r, "`n", "`r") {
        f := StrSplit(line, "`t")
        switch f[1] {
            case "show": msg .= f[2] "`n"
            case "activate": hwnd := Integer(f[2])
        }
    }
    status.Value := "Heard: " heard "`n" RTrim(msg, "`n")
    if hwnd {                                            ; what it opened, or found open: bring it to the front,
        try {                                            ; then hide the bar (hidden first, the bar isn't in front
            WinActivate("ahk_id " hwnd)                  ; any more and Windows refuses to hand the front over)
            WinWaitActive("ahk_id " hwnd, , 1)
        }
        HideBar()
    } else
        SetTimer(HideBar, -2000)
}

HelpText() {
    return "Press " KeyLabel(MYKEY) ", say it, press " KeyLabel(MYKEY) " again.`n"
        . "open <job or bid> · open the <job> submittals / plans / BID Sheet · open <job> in Ops`n"
        . "open procurement / bids / schedule / AI dispatch (Ops) · open PlanHub, Gensco, QuickBooks...`n"
        . "open Revu, Excel... · open downloads, pricing... · switch to <app or window>`n"
        . "close all <app> windows · close the <folder> window · minimize everything · show desktop`n"
        . "Your own websites, folders and apps: tray icon > Settings."
}

; ---------------------------------------------------------------- tray

OpenSettings(*) {
    if WinExist("AirX Voice Settings") {
        WinActivate()
        return
    }
    exe := A_ScriptDir "\brain\brain.exe"                  ; the Settings window is the helper started with --settings
    try {
        if FileExist(exe)
            Run('"' exe '" --settings', A_ScriptDir)
        else
            Run('"' PYTHONW '" "' A_ScriptDir '\brain.py" --settings', A_ScriptDir)
    }
}

NotInSettings(*) {
    for t in SETTINGS_WINDOWS
        if WinActive(t)
            return false
    return true
}

TogglePause(*) {
    Suspend(-1)
    A_IconTip := A_IsSuspended ? "AirX Voice (paused)" : "AirX Voice: press " KeyLabel(MYKEY)
    A_IsSuspended ? A_TrayMenu.Check("Pause") : A_TrayMenu.Uncheck("Pause")
}

WatchSettings() {
    global settingsTime
    t := FileTimeOf(SETTINGS)
    if t != settingsTime {                               ; saved in Settings: new key, new Wispr key
        settingsTime := t
        if (Setting("hotkey", "CapsLock") != MYKEY || WisprKeys() != WISPR) && !listening && !awaiting
            Reload()
    }
}

; ---------------------------------------------------------------- the brain

Call(path, body := "", waited := 0) {
    try {
        r := ComObject("WinHttp.WinHttpRequest.5.1")
        r.SetTimeouts(300, 300, 3000, 16000)             ; two Jev calls of up to 3 s, then up to 8 s for the window
        r.Open("POST", "http://127.0.0.1:" PORT path, false)
        r.SetRequestHeader("X-Token", Trim(FileRead(STATE "\token", "UTF-8")))
        r.SetRequestHeader("X-Waited-Ms", waited)
        r.SetRequestHeader("Content-Type", "text/plain; charset=utf-8")
        r.Send(body)
        return r.Status = 200 ? r.ResponseText : ""
    }
    return ""
}

StartBrain() {
    global lastStart, misses
    if Call("/ping") = "ok" {
        misses := 0
        return
    }
    misses += 1                                          ; one slow answer is not a dead helper
    if (misses < 2 && lastStart) || A_TickCount - lastStart < 20000
        return
    lastStart := A_TickCount, misses := 0
    exe := A_ScriptDir "\brain\brain.exe"
    try {
        if FileExist(exe)
            Run('"' exe '"', A_ScriptDir, "Hide")
        else
            Run('"' PYTHONW '" "' A_ScriptDir '\brain.py"', A_ScriptDir, "Hide")
    } catch {
        TrayTip("AirX Voice couldn't start its helper. Reinstall it, or check the log.", "AirX Voice")
    }
}

; ---------------------------------------------------------------- small helpers

Setting(name, default) {
    try {
        if RegExMatch(FileRead(SETTINGS, "UTF-8"), '"' name '"\s*:\s*"((?:[^"\\]|\\.)*)"', &m)
            return m[1] = "" ? default : StrReplace(StrReplace(m[1], '\"', '"'), "\\", "\")
    }
    return default
}

FileTimeOf(p) {
    try return FileGetTime(p, "M")
    return ""
}

KeyLabel(h) {
    names := Map("CapsLock", "Caps Lock", "ScrollLock", "Scroll Lock", "PgUp", "Page Up", "PgDn", "Page Down",
        "AppsKey", "the Menu key", "RCtrl", "Right Ctrl", "RAlt", "Right Alt", "RShift", "Right Shift", "RWin", "Right Win")
    RegExMatch(h, "^([\^!+#<>]*)(.+)$", &m)
    out := ""
    for pair in [["^", "Ctrl+"], ["!", "Alt+"], ["+", "Shift+"], ["#", "Win+"]]
        if InStr(m[1], pair[1])
            out .= pair[2]
    k := m[2]
    return out (names.Has(k) ? names[k] : StrLen(k) = 1 ? StrUpper(k) : k)
}
