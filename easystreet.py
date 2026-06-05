import csv
import io
import json
import os
import re
import shutil
import subprocess
import time
import urllib.parse
import urllib.request
import socket
import threading
import tkinter as tk
from tkinter import messagebox, filedialog
import winsound
import sys

# ============================================================
#  EasyStreet - Version 0.14
#  Reproduces the proven launch recipe we ran by hand:
#  point at the REAL server, kill zombies, check Steam,
#  launch the working bat, then verify it actually came up.
# ============================================================

VERSION = "0.14"

# ---- Auto-detect Steam / server / workshop so EasyStreet runs on any PC.
#      Order: saved config.json -> known-good path if present -> detect -> default.
try:
    if getattr(sys, "frozen", False):
        _HERE = os.path.dirname(sys.executable)
    else:
        _HERE = os.path.dirname(os.path.abspath(__file__))
except Exception:
    _HERE = os.getcwd()
_BS = chr(92)


def _isdir(p):
    return p if p and os.path.isdir(p) else None


def _isfile(p):
    return p if p and os.path.isfile(p) else None


def _steam_root():
    try:
        import winreg
        for hive, key, name in (
                (winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam", "SteamPath"),
                (winreg.HKEY_LOCAL_MACHINE,
                 r"SOFTWARE\WOW6432Node\Valve\Steam", "InstallPath")):
            try:
                with winreg.OpenKey(hive, key) as k:
                    v = winreg.QueryValueEx(k, name)[0]
                if v and os.path.isdir(v):
                    return v
            except Exception:
                pass
    except Exception:
        pass
    for p in (r"C:\Program Files (x86)\Steam", r"C:\Program Files\Steam"):
        if os.path.isdir(p):
            return p
    return None


def _steam_libraries():
    libs = []
    root = _steam_root()
    if root:
        libs.append(root)
        try:
            txt = open(os.path.join(root, "steamapps", "libraryfolders.vdf"),
                       errors="ignore").read()
            for line in txt.splitlines():
                if '"path"' in line:
                    parts = line.split('"')
                    if len(parts) >= 4:
                        libs.append(parts[3].replace(_BS + _BS, _BS))
        except Exception:
            pass
    seen = []
    for lb in libs:
        if lb and lb not in seen:
            seen.append(lb)
    return seen


def _find_steamapps(sub, must_contain=None):
    for lib in _steam_libraries():
        cand = os.path.join(lib, "steamapps", sub)
        if os.path.isdir(cand):
            if must_contain and not os.path.isfile(
                    os.path.join(cand, must_contain)):
                continue
            return cand
    return None


_cfg = {}
try:
    _cfg = json.load(open(os.path.join(_HERE, "config.json"), errors="ignore"))
except Exception:
    _cfg = {}

SERVER_DIR = (_cfg.get("server_dir")
              or _isdir(r"D:\SteamLibrary\steamapps\common\DayZServer")
              or _find_steamapps(os.path.join("common", "DayZServer"), "DayZServer_x64.exe")
              or r"D:\SteamLibrary\steamapps\common\DayZServer")
WORKSHOP_DIR = (_cfg.get("workshop_dir")
                or _isdir(r"D:\SteamLibrary\steamapps\workshop\content\221100")
                or _find_steamapps(os.path.join("workshop", "content", "221100"))
                or r"D:\SteamLibrary\steamapps\workshop\content\221100")
STEAM_EXE = (_cfg.get("steam_exe")
             or _isfile(r"C:\Program Files (x86)\Steam\steam.exe")
             or _isfile(os.path.join(_steam_root() or "", "steam.exe"))
             or r"C:\Program Files (x86)\Steam\steam.exe")
SERVER_EXE = "DayZServer_x64.exe"


def _find_bat(server_dir):
    cand = os.path.join(server_dir, "Easy Street.bat")
    if os.path.isfile(cand):
        return cand
    try:
        for f in os.listdir(server_dir):
            if f.lower().endswith(".bat"):
                fp = os.path.join(server_dir, f)
                try:
                    if "dayzserver" in open(fp, errors="ignore").read().lower():
                        return fp
                except Exception:
                    pass
    except Exception:
        pass
    return cand


BAT_PATH = _cfg.get("bat_path") or _find_bat(SERVER_DIR)
PROFILES = os.path.join(SERVER_DIR, "profiles")

# The folder this script lives in (where a load song would sit).
try:
    if getattr(sys, "frozen", False):
        APP_DIR = os.path.dirname(sys.executable)
    else:
        APP_DIR = os.path.dirname(os.path.abspath(__file__))
except Exception:
    APP_DIR = os.getcwd()

# The advisor's learned dependency memory.
DEPS_PATH = os.path.join(APP_DIR, "deps.json")

# Cached map of which addon-tokens each mod provides (built once).
PROVIDERS_CACHE = os.path.join(APP_DIR, "providers.json")

# Saved mod combos (the Lineup) and the server config we read the
# active mission from (for fresh-world wipes).
LOADOUTS_PATH = os.path.join(APP_DIR, "loadouts.json")
SERVER_CFG = os.path.join(SERVER_DIR, "serverDZ.cfg")

# Stops helper commands from flashing little black console windows.
NO_WINDOW = 0x08000000


def set_status(text, color="gray"):
    status_label.config(text=text, fg=color)
    window.update()


_WINDOWS = {}


def _solo_window(key):
    # Already-open window for this key? Focus it, return True (no dup).
    w = _WINDOWS.get(key)
    try:
        if w is not None and w.winfo_exists():
            w.deiconify()
            w.lift()
            w.focus_force()
            return True
    except Exception:
        pass
    return False


def _register_window(key, w):
    _WINDOWS[key] = w


def _first_run_setup():
    # Auto-detect came up empty - ask the user to point at their server folder.
    try:
        messagebox.showinfo(
            "EasyStreet - first time setup",
            "I could not auto-find your DayZ server. On the next screen, pick "
            "your DayZServer folder (the one with DayZServer_x64.exe inside).")
        d = filedialog.askdirectory(title="Select your DayZServer folder")
    except Exception:
        d = None
    if not d:
        return False
    cfg = {"server_dir": d}
    low = d.lower().replace("/", _BS)
    if "steamapps" in low:
        base = d[:low.index("steamapps") + len("steamapps")]
        wd = os.path.join(base, "workshop", "content", "221100")
        if os.path.isdir(wd):
            cfg["workshop_dir"] = wd
    try:
        with open(os.path.join(_HERE, "config.json"), "w") as f:
            json.dump(cfg, f, indent=2)
    except Exception:
        pass
    try:
        messagebox.showinfo(
            "EasyStreet - setup saved",
            "Saved. Close EasyStreet and open it again - you are good to go.")
    except Exception:
        pass
    return True


def get_active_mods():
    """Read the mod line straight out of the launch bat, so we show
    exactly what WILL load - not just every @folder on the drive."""
    try:
        with open(BAT_PATH, "r") as f:
            for line in f:
                if line.strip().lower().startswith("set modlist="):
                    raw = line.split("=", 1)[1].strip().strip('"')
                    raw = raw.replace("-mod=", "").strip().strip(";")
                    if raw:
                        return raw.split(";")
    except Exception:
        pass
    return []


def _tasklist(image_name):
    return subprocess.run(
        f'tasklist /FI "IMAGENAME eq {image_name}" /FO CSV /NH',
        shell=True, capture_output=True, text=True,
        creationflags=NO_WINDOW,
    ).stdout


def is_running(image_name):
    """True if a process with this exe name is running."""
    return image_name.lower() in _tasklist(image_name).lower()


def server_memory_mb():
    """Total memory the server process is using. A loaded, live server
    uses gigs; a stalled zombie uses ~10 MB. This is how we KNOW.
    NOTE: Windows prints memory like "2,539,800 K" - those commas are
    thousands separators, so we parse the CSV properly instead of
    splitting on commas (that bug made a LIVE server look dead)."""
    total_kb = 0
    for row in csv.reader(io.StringIO(_tasklist(SERVER_EXE))):
        if len(row) >= 5 and SERVER_EXE.lower() in row[0].lower():
            digits = "".join(c for c in row[4] if c.isdigit())
            if digits:
                total_kb += int(digits)
    return total_kb // 1024


def kill_zombies():
    """Clear stale server processes so a fresh launch has a clean slate.
    (We found ELEVEN of these piled up from failed launches.)"""
    subprocess.run(
        f"taskkill /F /IM {SERVER_EXE}",
        shell=True, capture_output=True, creationflags=NO_WINDOW,
    )


def newest_file(folder, ext):
    try:
        files = [os.path.join(folder, f) for f in os.listdir(folder)
                 if f.lower().endswith(ext)]
        return max(files, key=os.path.getmtime) if files else None
    except Exception:
        return None


def mods_loaded_from_log():
    """Confirm CF + VPP actually initialized in the newest script log."""
    log = newest_file(PROFILES, ".log")
    if not log:
        return False
    try:
        with open(log, "r", errors="ignore") as f:
            text = f.read()
        return "JM_CommunityFramework" in text and "[VPPAT]" in text
    except Exception:
        return False


def wait_for_steam(seconds=40):
    """Steam must be fully running before the server can register with it
    (SteamGameServer_Init). Start it if needed, then wait until it's awake
    plus a short grace period so login finishes. THIS is what stops the
    server hanging at 'Reading mission...'."""
    if is_running("steam.exe"):
        return True
    set_status("Steam is down - starting it...", "yellow")
    try:
        subprocess.Popen([STEAM_EXE])
    except Exception:
        set_status("Couldn't start Steam. Open it, then try again.", "red")
        return False
    for i in range(seconds):
        if is_running("steam.exe"):
            break
        set_status(f"Waiting for Steam to wake up... {i}s", "yellow")
        time.sleep(1)
    else:
        set_status("Steam didn't start. Open it, then try again.", "red")
        return False
    for i in range(15, 0, -1):
        set_status(f"Steam up - {i}s for it to finish logging in...", "yellow")
        time.sleep(1)
    return True


def play_load_song():
    """If a file named 'easystreet.*' (an audio file) sits in the app
    folder, play it when the server launches. Drop your own copy of the
    song in next to easystreet.py - .wav plays cleanest (no window)."""
    try:
        for fn in os.listdir(APP_DIR):
            low = fn.lower()
            if not low.startswith("easystreet"):
                continue
            full = os.path.join(APP_DIR, fn)
            if low.endswith(".wav"):
                winsound.PlaySound(full,
                                   winsound.SND_FILENAME | winsound.SND_ASYNC)
                return True
            if low.endswith((".mp3", ".m4a", ".wma", ".aac", ".flac")):
                ps = ("Add-Type -AssemblyName presentationCore; "
                      "$p = New-Object System.Windows.Media.MediaPlayer; "
                      f"$p.Open([uri]'{full}'); $p.Play(); "
                      "Start-Sleep -Seconds 600")
                subprocess.Popen([PS_EXE, "-NoProfile", "-WindowStyle",
                                  "Hidden", "-Command", ps],
                                 creationflags=NO_WINDOW)
                return True
    except Exception:
        pass
    return False


def launch_server():
    set_status("Clearing old server processes...", "yellow")
    kill_zombies()
    _keepalive["stopped"] = False
    if not wait_for_steam():
        return
    set_status("Launching Easy Street...", "yellow")
    # Launch the bat MINIMIZED so its restart-loop console sits in the
    # taskbar instead of on top of everything.
    _si = subprocess.STARTUPINFO()
    _si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    _si.wShowWindow = 6  # SW_MINIMIZE
    subprocess.Popen(f'"{BAT_PATH}"', shell=True, cwd=SERVER_DIR,
                     startupinfo=_si)
    play_load_song()
    set_status("Launched. Give it ~1 min, then hit CHECK STATUS.", "lime")


def stop_server():
    # Stop the running server (with a confirm). Tells KEEP IT UP this was
    # on purpose, so the watchdog won't immediately relaunch it.
    if not messagebox.askyesno(
            "Stop the server?",
            "Shut the server down and disconnect any players?",
            icon="warning"):
        return
    _keepalive["stopped"] = True
    _keepalive["was_up"] = False
    set_status("Stopping server...", "yellow")
    kill_zombies()
    set_status("Server stopped. KEEP IT UP is paused until you START again.",
               "lime")
    refresh_active_label()


def check_status():
    mem = server_memory_mb()
    if mem == 0:
        set_status("Server not running. Hit START SERVER.", "red")
    elif mem < 500:
        set_status(f"Booting... ({mem} MB, loading the map)", "yellow")
    elif mods_loaded_from_log():
        set_status(f"LIVE ({mem} MB). CF + VPP loaded. "
                   f"Connect: 127.0.0.1:2302", "lime")
    else:
        set_status(f"LIVE ({mem} MB), but mods not confirmed yet.", "yellow")


# ---- Keep It Up: crash watchdog + scheduled restart ------------------
SETTINGS_PATH = os.path.join(APP_DIR, "settings.json")

_keepalive = {"watchdog": False, "restart_hours": 0,
              "was_up": False, "next_restart": None, "stopped": False}


def _load_settings():
    try:
        with open(SETTINGS_PATH, "r") as f:
            return json.load(f)
    except Exception:
        return {}


def _persist_keepalive():
    try:
        with open(SETTINGS_PATH, "w") as f:
            json.dump({"watchdog": _keepalive["watchdog"],
                       "restart_hours": _keepalive["restart_hours"]},
                      f, indent=2)
    except Exception:
        pass


def _keepalive_tick():
    """Every 30s: revive a crashed server and fire scheduled restarts.
    Off unless the user turned it on. Never launches a server that was
    never up - it only brings back one that was running and then died."""
    try:
        mem = server_memory_mb()
        ka = _keepalive
        now = time.time()
        if mem and mem >= 500:
            ka["was_up"] = True
        if ka.get("stopped"):
            pass
        elif ka["watchdog"] and ka["was_up"] and mem == 0:
            ka["was_up"] = False
            set_status("Server went down - bringing it back...", "yellow")
            launch_server()
        elif (ka["restart_hours"] and ka["next_restart"]
              and now >= ka["next_restart"] and mem and mem >= 500):
            ka["was_up"] = False
            ka["next_restart"] = now + ka["restart_hours"] * 3600
            set_status("Scheduled restart...", "yellow")
            launch_server()
    except Exception:
        pass
    finally:
        try:
            window.after(30000, _keepalive_tick)
        except Exception:
            pass


def open_keepalive():
    """Settings window: let the server look after itself."""
    if _solo_window("keepitup"):
        return
    win = tk.Toplevel(window)
    _register_window("keepitup", win)
    win.title("Keep It Up")
    win.geometry("440x380")
    win.configure(bg="black")

    tk.Label(win, text="KEEP IT UP", font=("Arial", 18, "bold"),
             bg="black", fg="white").pack(pady=(14, 2))
    tk.Label(win, text="Make your server look after itself.",
             font=("Arial", 9), bg="black", fg="gray").pack(pady=(0, 12))

    ka_lbl = tk.Label(win, text="", font=("Arial", 9), bg="black",
                      fg="lime", wraplength=390, justify="left")

    def refresh():
        wd = "ON" if _keepalive["watchdog"] else "off"
        sch = (f"every {_keepalive['restart_hours']}h"
               if _keepalive["restart_hours"] else "off")
        ka_lbl.config(text=f"Watchdog: {wd}      Scheduled restart: {sch}")

    wd_var = tk.BooleanVar(value=_keepalive["watchdog"])

    def toggle_wd():
        _keepalive["watchdog"] = wd_var.get()
        _persist_keepalive()
        refresh()

    tk.Checkbutton(win, text="Auto-restart if it crashes",
                   variable=wd_var, command=toggle_wd,
                   font=("Arial", 11, "bold"), bg="black", fg="white",
                   selectcolor="black", activebackground="black",
                   activeforeground="white").pack(anchor="w", padx=20,
                                                   pady=(4, 0))
    tk.Label(win, text="Checks every 30s. If the server was up and dies, "
             "EasyStreet brings it back.", font=("Arial", 8), bg="black",
             fg="gray", wraplength=390,
             justify="left").pack(anchor="w", padx=42)

    rrow = tk.Frame(win, bg="black")
    rrow.pack(fill="x", padx=20, pady=(16, 2))
    tk.Label(rrow, text="Scheduled restart every", font=("Arial", 10),
             bg="black", fg="white").pack(side="left")
    hours_var = tk.StringVar(value=str(_keepalive["restart_hours"] or 0))
    tk.Entry(rrow, textvariable=hours_var, width=4, font=("Arial", 10),
             bg="#0a0a0a", fg="white",
             insertbackground="white").pack(side="left", padx=6)
    tk.Label(rrow, text="hours  (0 = off)", font=("Arial", 10),
             bg="black", fg="white").pack(side="left")

    def save_hours():
        try:
            h = max(0, int(float(hours_var.get())))
        except Exception:
            h = 0
        _keepalive["restart_hours"] = h
        _keepalive["next_restart"] = (time.time() + h * 3600) if h else None
        _persist_keepalive()
        refresh()

    tk.Button(win, text="Save schedule", font=("Arial", 9, "bold"),
              bg="#2b3a4d", fg="white",
              command=save_hours).pack(pady=(6, 10))

    ka_lbl.pack(pady=(6, 4))
    refresh()
# ----------------------------------------------------------------------


def list_all_mods():
    """Every @mod folder sitting in the server directory."""
    try:
        return sorted(f for f in os.listdir(SERVER_DIR)
                      if f.startswith("@")
                      and os.path.isdir(os.path.join(SERVER_DIR, f)))
    except Exception:
        return []


# Mods that must load early, in this exact order (frameworks / cores).
LOAD_PRIORITY = [
    "@CF",
    "@Dabs Framework",
    "@DayZ-Expansion-Core",
]

# If a selected mod matches a trigger, the listed deps get pulled in too
# (only if they're actually installed on the server).
DEP_RULES = [
    (lambda m: m.startswith("@DayZ-Expansion"),
     ["@CF", "@Dabs Framework", "@DayZ-Expansion-Core"]),
    (lambda m: m == "@VPPAdminTools", ["@CF"]),
    (lambda m: m == "@Community-Online-Tools", ["@CF"]),
]


def order_mods(mods):
    """Auto-add known dependencies, then sort into a load-safe order:
    frameworks/cores first (in priority order), everything else after."""
    mods = list(dict.fromkeys(mods))          # de-dupe, keep order
    installed = set(list_all_mods())
    for trigger, deps in DEP_RULES:
        if any(trigger(m) for m in mods):
            for dep in deps:
                if dep in installed and dep not in mods:
                    mods.append(dep)

    def key(m):
        if m in LOAD_PRIORITY:
            return (0, LOAD_PRIORITY.index(m))
        return (1, 0)
    return sorted(mods, key=key)


def set_mod_line(mods):
    """Order the mods safely, then write them into the launch bat's
    modList line. Returns the final ordered list, or None on failure."""
    ordered = order_mods(mods)
    new_line = 'set modList="-mod=' + ";".join(ordered) + ';"\n'
    try:
        with open(BAT_PATH, "r") as f:
            lines = f.readlines()
        for i, ln in enumerate(lines):
            if ln.strip().lower().startswith("set modlist="):
                lines[i] = new_line
                break
        with open(BAT_PATH, "w") as f:
            f.writelines(lines)
        return ordered
    except Exception:
        return None


def refresh_active_label():
    active = get_active_mods()
    mod_label.config(text=f"Active mods: {len(active)}"
                     if active else "No mods set")
    try:
        mod_list_box.config(state="normal")
        mod_list_box.delete("1.0", "end")
        mod_list_box.insert("1.0", ", ".join(active) if active
                            else "No mods set")
        mod_list_box.config(state="disabled")
    except (NameError, tk.TclError):
        pass


# ===================== THE LINEUP (loadouts) =====================

def _load_loadouts():
    try:
        with open(LOADOUTS_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_loadouts(data):
    try:
        with open(LOADOUTS_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=1)
        return True
    except Exception:
        return False


def _active_mission_dir():
    """The mission folder the server actually loads, read from
    serverDZ.cfg's template= line."""
    try:
        with open(SERVER_CFG, "r", errors="ignore") as f:
            m = re.search(r'template\s*=\s*"([^"]+)"', f.read())
        if m:
            d = os.path.join(SERVER_DIR, "mpmissions", m.group(1))
            if os.path.isdir(d):
                return d
    except Exception:
        pass
    return None


def wipe_persistence():
    """Archive the active world's storage so it rebuilds fresh next
    launch. Reversible - renames storage_* to storage_*_old_<stamp>,
    never deletes. Returns a human status string."""
    if server_memory_mb() > 0:
        return "Server looks like it's running - STOP it first, then wipe."
    mdir = _active_mission_dir()
    if not mdir:
        return "Couldn't find the active mission folder."
    stamp = time.strftime("%Y%m%d_%H%M%S")
    moved = []
    try:
        for d in os.listdir(mdir):
            full = os.path.join(mdir, d)
            if (d.lower().startswith("storage_") and "_old_" not in d
                    and os.path.isdir(full)):
                os.rename(full, os.path.join(mdir, f"{d}_old_{stamp}"))
                moved.append(d)
    except Exception as e:
        return f"Wipe failed: {e}"
    if moved:
        return f"Fresh world ready (archived {', '.join(moved)})."
    return "World already fresh - nothing to archive."


def do_fresh_world():
    """Main-screen one-click fresh world, with a confirm."""
    if not messagebox.askyesno(
            "Fresh World",
            "Archive the current saved world so it rebuilds fresh on the "
            "next launch?\n\nReversible - the old world is renamed, not "
            "deleted. Do this after you change mods."):
        return
    set_status(wipe_persistence(), "lime")


def open_loadouts():
    """The Lineup: save the current mod combo under a name, and load any
    saved combo back with one click (optionally with a fresh world)."""
    if _solo_window("lineup"):
        return
    win = tk.Toplevel(window)
    _register_window("lineup", win)
    win.title("The Lineup")
    win.geometry("460x580")
    win.configure(bg="black")

    tk.Label(win, text="THE LINEUP", font=("Arial", 18, "bold"),
             bg="black", fg="white").pack(pady=(14, 2))
    tk.Label(win, text="save mod combos - run a different one any day",
             font=("Arial", 9), bg="black", fg="gray").pack()

    lo_status = tk.Label(win, text="", font=("Arial", 9), bg="black",
                         fg="lime", wraplength=430)
    lo_status.pack(side="bottom", pady=(0, 8))

    def say(msg, color="lime"):
        lo_status.config(text=msg, fg=color)
        set_status(msg, color)

    saverow = tk.Frame(win, bg="black")
    saverow.pack(fill="x", padx=14, pady=(12, 4))
    name_var = tk.StringVar()
    tk.Entry(saverow, textvariable=name_var, font=("Arial", 11),
             bg="#0a0a0a", fg="white", insertbackground="white").pack(
                 side="left", fill="x", expand=True)

    def do_save():
        name = name_var.get().strip()
        if not name:
            say("Type a name first (e.g. Monday, Heavy PvP).", "yellow")
            return
        mods = get_active_mods()
        if not mods:
            say("No active mods to save - pick some in CHOOSE MODS.",
                "yellow")
            return
        data = _load_loadouts()
        existed = name in data
        data[name] = mods
        _save_loadouts(data)
        name_var.set("")
        rebuild()
        say(f"{'Updated' if existed else 'Saved'} '{name}' "
            f"({len(mods)} mods).", "lime")

    tk.Button(saverow, text="Save current", font=("Arial", 9, "bold"),
              bg="#1a4d1a", fg="white", command=do_save).pack(
                  side="left", padx=(6, 0))

    tk.Label(win, text="saved loadouts", font=("Arial", 9),
             bg="black", fg="gray").pack(pady=(6, 0))

    outer = tk.Frame(win, bg="black")
    outer.pack(fill="both", expand=True, padx=14, pady=(2, 6))
    canvas = tk.Canvas(outer, bg="black", highlightthickness=0)
    sb = tk.Scrollbar(outer, command=canvas.yview)
    sb.pack(side="right", fill="y")
    canvas.pack(side="left", fill="both", expand=True)
    canvas.configure(yscrollcommand=sb.set)
    listframe = tk.Frame(canvas, bg="black")
    canvas.create_window((0, 0), window=listframe, anchor="nw", width=410)
    listframe.bind("<Configure>", lambda e: canvas.configure(
        scrollregion=canvas.bbox("all")))

    def load_one(name, fresh):
        mods = _load_loadouts().get(name, [])
        if not mods:
            return
        ordered = set_mod_line(mods)
        n = len(ordered) if ordered else len(mods)
        refresh_active_label()
        msg = f"Loaded '{name}' ({n} mods). Ready to START."
        if fresh:
            msg += "  " + wipe_persistence()
        say(msg, "lime")
        win.lift()

    def delete_one(name):
        if not messagebox.askyesno("Delete loadout",
                                   f"Delete loadout '{name}'?\n"
                                   "(Only removes the saved combo, not "
                                   "any mods.)"):
            return
        data = _load_loadouts()
        data.pop(name, None)
        _save_loadouts(data)
        rebuild()
        say(f"Deleted '{name}'.", "gray")

    def rebuild():
        for w in listframe.winfo_children():
            w.destroy()
        data = _load_loadouts()
        if not data:
            tk.Label(listframe, text="(none yet - save one above)",
                     font=("Arial", 10), bg="black", fg="gray").pack(
                         pady=12)
            return
        for name in sorted(data, key=str.lower):
            mods = data[name]
            row = tk.Frame(listframe, bg="#111111")
            row.pack(fill="x", pady=3)
            tk.Label(row, text=name, font=("Arial", 11, "bold"),
                     bg="#111111", fg="cyan", anchor="w").pack(
                         side="top", fill="x", padx=8, pady=(5, 0))
            tk.Label(row, text=f"{len(mods)} mods", font=("Arial", 8),
                     bg="#111111", fg="gray", anchor="w").pack(
                         side="top", fill="x", padx=8)
            btns = tk.Frame(row, bg="#111111")
            btns.pack(side="top", fill="x", padx=8, pady=(2, 6))
            tk.Button(btns, text="Load", font=("Arial", 8, "bold"),
                      bg="#2b2b2b", fg="white",
                      command=lambda n=name: load_one(n, False)).pack(
                          side="left")
            tk.Button(btns, text="Load + Fresh World",
                      font=("Arial", 8, "bold"), bg="#1a3a4d", fg="white",
                      command=lambda n=name: load_one(n, True)).pack(
                          side="left", padx=4)
            tk.Button(btns, text="Delete", font=("Arial", 8),
                      bg="#4d1a1a", fg="white",
                      command=lambda n=name: delete_one(n)).pack(
                          side="right")

    rebuild()


# Curated family prefixes, matched against normalized mod names
# (lowercase, letters+digits only). First match wins, so list the
# more-specific prefixes before the more-general ones.
FAMILY_PREFIXES = [
    ("DayZ-Expansion",     "dayzexpansion"),
    ("Iconic Server Pack", "iconic"),
    ("BallerZ",            "ballerz"),
    ("BBP",                "bbp"),
    ("Big Grampa",         "biggrampa"),
    ("Loftd",              "loftd"),
    ("Bullet Stacks",      "bullet"),
    ("Basic Territories",  "basicterrit"),
    ("Better",             "better"),
    ("FOG",                "fog"),
    ("RFFS Heli",          "rffsheli"),
    ("Zodiac",             "zodiac"),
    ("Advanced",           "advanced"),
    ("Auto",               "auto"),
    ("Building",           "build"),
]


def detect_families(mods):
    """Group installed mods into name-families. Returns {label: [mods]}
    for every family that actually has 2+ members."""
    fam = {}
    for m in mods:
        nm = _norm(m)
        for label, pref in FAMILY_PREFIXES:
            if nm.startswith(pref):
                fam.setdefault(label, []).append(m)
                break
    return {k: sorted(v) for k, v in fam.items() if len(v) >= 2}


def _meta_fields(path):
    """Pull publishedid and name out of a mod's meta.cpp."""
    pid = name = None
    try:
        with open(path, "r", errors="ignore") as f:
            txt = f.read()
        m = re.search(r"publishedid\s*=\s*(\d+)", txt)
        if m:
            pid = m.group(1)
        n = re.search(r'name\s*=\s*"(.*?)"', txt)
        if n:
            name = n.group(1)
    except Exception:
        pass
    return pid, name


def _clean_modname(name):
    """Turn a meta.cpp name into a safe @FolderName."""
    safe = re.sub(r'[<>:"/\\|?*]', "", name).strip()
    return "@" + safe if safe else None


def scan_workshop_backlog():
    """Find mods downloaded in the Steam workshop that aren't wired into
    the server yet. Match by publishedid so a renamed folder still counts
    as 'already installed'. Returns sorted [(workshop_id, pid, @Name)]."""
    if not os.path.isdir(WORKSHOP_DIR):
        return []

    # publishedids already present in the server
    server_ids = set()
    for d in os.listdir(SERVER_DIR):
        full = os.path.join(SERVER_DIR, d)
        if d.startswith("@") and os.path.isdir(full):
            pid, _ = _meta_fields(os.path.join(full, "meta.cpp"))
            if pid:
                server_ids.add(pid)

    backlog = []
    for d in os.listdir(WORKSHOP_DIR):
        full = os.path.join(WORKSHOP_DIR, d)
        if not os.path.isdir(full):
            continue
        pid, name = _meta_fields(os.path.join(full, "meta.cpp"))
        key = pid or d
        if key in server_ids or not name:
            continue
        modname = _clean_modname(name)
        if modname:
            backlog.append((d, pid, modname))
    backlog.sort(key=lambda x: x[2].lower())
    return backlog


PS_EXE = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"),
                      "System32", "WindowsPowerShell", "v1.0", "powershell.exe")


def _ps_quote(p):
    """Single-quote a path for PowerShell, escaping any inner quotes."""
    return "'" + p.replace("'", "''") + "'"


def _copy_keys(src, keys_dir):
    """Copy a mod's .bikey signing keys into the server keys folder.
    Looks in the usual key subfolders + the mod root (fast, no deep walk)."""
    copied = 0
    spots = [src] + [os.path.join(src, s) for s in
                     ("keys", "Keys", "key", "Key")]
    for spot in spots:
        if not os.path.isdir(spot):
            continue
        try:
            for fn in os.listdir(spot):
                if fn.lower().endswith(".bikey"):
                    shutil.copy2(os.path.join(spot, fn),
                                 os.path.join(keys_dir, fn))
                    copied += 1
        except Exception:
            pass
    return copied


def wire_up_mods(items, progress_cb=None):
    """For each (workshop_id, pid, @Name): make a junction in the server
    folder pointing at the workshop copy, and copy its .bikey keys. Uses
    PowerShell New-Item for the junctions (the method proven on this box).
    Returns (linked, keys_copied, errors)."""
    keys_dir = os.path.join(SERVER_DIR, "keys")
    os.makedirs(keys_dir, exist_ok=True)
    errors = []

    # 1) Build ONE PowerShell script that makes every junction, so we
    #    spawn a single process instead of hundreds.
    lines = []
    for wsid, pid, modname in items:
        src = os.path.join(WORKSHOP_DIR, wsid)
        dst = os.path.join(SERVER_DIR, modname)
        if os.path.exists(dst):
            errors.append(f"{modname}: already exists, skipped")
            continue
        lines.append(
            f"try {{ New-Item -ItemType Junction -Path {_ps_quote(dst)} "
            f"-Target {_ps_quote(src)} -ErrorAction Stop | Out-Null; "
            f"Write-Output ('OK||' + {_ps_quote(modname)}) }} "
            f"catch {{ Write-Output ('FAIL||' + {_ps_quote(modname)}) }}")

    linked = 0
    if lines:
        if progress_cb:
            progress_cb(0, len(items))
        script_path = os.path.join(SERVER_DIR, "_sync_links.ps1")
        try:
            with open(script_path, "w", encoding="utf-8") as f:
                f.write("\n".join(lines))
            r = subprocess.run(
                [PS_EXE, "-NoProfile", "-ExecutionPolicy", "Bypass",
                 "-File", script_path],
                capture_output=True, text=True, creationflags=NO_WINDOW)
            for ln in (r.stdout or "").splitlines():
                if ln.startswith("OK||"):
                    linked += 1
                elif ln.startswith("FAIL||"):
                    errors.append(ln.split("||", 1)[1] + ": link failed")
        except Exception as e:
            errors.append(f"batch: {e}")
        finally:
            try:
                os.remove(script_path)
            except Exception:
                pass

    # 2) Copy signing keys (pure Python, fast).
    keys_copied = 0
    for i, (wsid, pid, modname) in enumerate(items):
        keys_copied += _copy_keys(os.path.join(WORKSHOP_DIR, wsid), keys_dir)
        if progress_cb and (i % 20 == 0):
            progress_cb(i + 1, len(items))
    if progress_cb:
        progress_cb(len(items), len(items))
    return linked, keys_copied, errors


def _lan_ip():
    # Your address on the local network (same Wi-Fi / router).
    try:
        sk = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sk.connect(("8.8.8.8", 80))
        ip = sk.getsockname()[0]
        sk.close()
        return ip
    except Exception:
        return None


def _all_ipv4():
    found = []
    try:
        r = subprocess.run("ipconfig", shell=True, capture_output=True,
                           text=True, creationflags=NO_WINDOW)
        for line in (r.stdout or "").splitlines():
            if "IPv4" in line and ":" in line:
                cand = line.split(":")[-1].strip()
                if cand.count(".") == 3:
                    found.append(cand)
    except Exception:
        pass
    return found


def _tailscale_ip():
    # Tailscale hands out 100.64.x - 100.127.x addresses (great for friends).
    for ip in _all_ipv4():
        parts = ip.split(".")
        if len(parts) == 4 and parts[0] == "100":
            try:
                if 64 <= int(parts[1]) <= 127:
                    return ip
            except Exception:
                pass
    return None


def _public_ip(callback):
    # Look up the internet-facing IP off the GUI thread.
    def work():
        ip = None
        try:
            ip = urllib.request.urlopen(
                "https://api.ipify.org", timeout=4).read().decode().strip()
        except Exception:
            ip = None
        try:
            callback(ip)
        except Exception:
            pass
    threading.Thread(target=work, daemon=True).start()


def open_connect():
    # Invite & Connect: show friends how to join + copy a ready invite.
    if _solo_window("connect"):
        return
    win = tk.Toplevel(window)
    _register_window("connect", win)
    win.title("Invite & Connect")
    win.geometry("530x590")
    win.configure(bg="black")

    tk.Label(win, text="INVITE & CONNECT", font=("Arial", 18, "bold"),
             bg="black", fg="white").pack(pady=(14, 0))
    tk.Label(win, text="Hand these to your friends so they can join.",
             font=("Arial", 9), bg="black", fg="gray").pack(pady=(0, 10))

    port = 2302
    try:
        for line in open(BAT_PATH, errors="ignore").read().splitlines():
            if line.strip().lower().startswith("set serverport="):
                digits = "".join(c for c in line.split("=")[-1] if c.isdigit())
                if digits:
                    port = int(digits)
    except Exception:
        pass

    mem = server_memory_mb()
    if mem and mem >= 500:
        stxt, scol = "Server is UP and listening on port %d." % port, "lime"
    elif mem:
        stxt, scol = "Server is still booting...", "yellow"
    else:
        stxt, scol = "Server is not running - hit START SERVER first.", "red"
    tk.Label(win, text=stxt, font=("Arial", 10, "bold"), bg="black",
             fg=scol, wraplength=490).pack(pady=(0, 8))

    lan = _lan_ip()
    ts = _tailscale_ip()
    rows = tk.Frame(win, bg="black")
    rows.pack(fill="x", padx=18)

    def addr_row(label, value, hint, col):
        f = tk.LabelFrame(rows, text=" " + label + " ",
                          font=("Arial", 10, "bold"), bg="black", fg="cyan",
                          labelanchor="nw")
        f.pack(fill="x", pady=5)
        e = tk.Entry(f, font=("Consolas", 12), bg="#0a0a0a", fg=col,
                     readonlybackground="#0a0a0a", relief="flat",
                     justify="center")
        e.insert(0, value or "not detected")
        e.config(state="readonly")
        e.pack(fill="x", padx=8, pady=(6, 2))
        tk.Label(f, text=hint, font=("Arial", 8), bg="black", fg="gray",
                 wraplength=470, justify="left").pack(anchor="w", padx=8,
                                                      pady=(0, 6))
        return e

    addr_row("Same Wi-Fi / LAN",
             ("%s:%d" % (lan, port)) if lan else None,
             "Friends in your house / on your network use this.", "lime")
    addr_row("Tailscale (private - no router setup)",
             ("%s:%d" % (ts, port)) if ts else None,
             ("Add your friend on Tailscale, they connect to this - easiest "
              "for far-away friends.") if ts else
             ("Not detected. Install Tailscale + add friends for an easy "
              "private connect with no port forwarding."),
             "lime" if ts else "gray")
    pub = addr_row("Internet (public)", "checking...",
                   "Anyone can join, but you must forward UDP port %d on "
                   "your router first." % port, "yellow")

    def set_pub(ip):
        try:
            pub.config(state="normal")
            pub.delete(0, "end")
            pub.insert(0, ("%s:%d" % (ip, port)) if ip else "couldn't detect")
            pub.config(state="readonly")
        except Exception:
            pass
    _pub_box = {"ip": None, "done": False}

    def _fetch_pub():
        try:
            _pub_box["ip"] = urllib.request.urlopen(
                "https://api.ipify.org", timeout=4).read().decode().strip()
        except Exception:
            _pub_box["ip"] = None
        _pub_box["done"] = True

    def _poll_pub():
        try:
            if _pub_box["done"]:
                set_pub(_pub_box["ip"])
            elif win.winfo_exists():
                win.after(500, _poll_pub)
        except Exception:
            pass

    threading.Thread(target=_fetch_pub, daemon=True).start()
    win.after(500, _poll_pub)

    def best():
        if ts:
            return "%s:%d" % (ts, port)
        if lan:
            return "%s:%d" % (lan, port)
        return "YOUR_IP:%d" % port

    inv = tk.Label(win, text="", font=("Arial", 9), bg="black", fg="lime")

    def copy_invite():
        msg = ("Come play on my DayZ server! In DayZ open the Community tab, "
               "Direct Connect, and enter " + best() + " . Ask me which mods "
               "to subscribe to first.")
        try:
            win.clipboard_clear()
            win.clipboard_append(msg)
            inv.config(text="Invite copied - paste it to your friends.",
                       fg="lime")
        except Exception as e:
            inv.config(text="Couldn't copy: %s" % e, fg="red")

    tk.Button(win, text="COPY INVITE MESSAGE", font=("Arial", 12, "bold"),
              bg="green", fg="white", command=copy_invite).pack(pady=(14, 2))
    inv.pack(pady=(2, 6))
    tk.Label(win, text="Easiest path for friends: Tailscale. They install it, "
             "you add them to your tailnet, and the Tailscale address works "
             "with zero router setup.", font=("Arial", 8), bg="black",
             fg="gray", wraplength=490, justify="left").pack(padx=18,
                                                             pady=(2, 8))


def open_map_picker():
    """Pick which map the server runs. Lists the missions installed in
    mpmissions and rewrites serverDZ.cfg's template= line. Official maps
    (Chernarus / Livonia / Sakhal) just need the mission present; a
    community map also needs its map mod loaded."""
    if _solo_window("mappicker"):
        return
    win = tk.Toplevel(window)
    _register_window("mappicker", win)
    win.title("Map Picker")
    win.geometry("440x470")
    win.configure(bg="black")

    tk.Label(win, text="PICK YOUR MAP", font=("Arial", 18, "bold"),
             bg="black", fg="white").pack(pady=(14, 2))
    tk.Label(win, text="Switches the world your server loads on start.",
             font=("Arial", 9), bg="black", fg="gray").pack(pady=(0, 10))

    pretty = {
        "chernarusplus": "Chernarus (+)", "enoch": "Livonia", "sakhal": "Sakhal",
        "deerisle": "Deer Isle", "namalsk": "Namalsk", "banov": "Banov",
        "esseker": "Esseker", "chiemsee": "Chiemsee", "rostow": "Rostow",
        "takistanplus": "Takistan", "pripyat": "Pripyat", "valning": "Valning",
    }

    def friendly(mission):
        terr = mission.split(".")[-1].lower()
        return pretty.get(terr, terr.replace("_", " ").title())

    cur = ""
    try:
        m = re.search(r'template\s*=\s*"(.*?)"',
                      open(SERVER_CFG, errors="ignore").read())
        if m:
            cur = m.group(1)
    except Exception:
        pass

    missions = []
    try:
        mpm = os.path.join(SERVER_DIR, "mpmissions")
        for d in sorted(os.listdir(mpm)):
            if os.path.isdir(os.path.join(mpm, d)) and "." in d:
                missions.append(d)
    except Exception:
        pass

    status = tk.Label(win, text="", font=("Arial", 9), bg="black",
                      fg="lime", wraplength=400, justify="left")
    sel = tk.StringVar(value=cur)

    frame = tk.Frame(win, bg="black")
    frame.pack(fill="both", expand=True, padx=22, pady=6)
    if not missions:
        tk.Label(frame, text="No missions found in mpmissions.",
                 font=("Arial", 10), bg="black", fg="yellow").pack()
    for mis in missions:
        tag = "   <- current" if mis == cur else ""
        tk.Radiobutton(frame, text=friendly(mis) + tag, value=mis,
                       variable=sel, font=("Arial", 11), bg="black",
                       fg="white", selectcolor="black", activebackground="black",
                       activeforeground="cyan", anchor="w").pack(fill="x", pady=2)

    def apply_map():
        mis = sel.get()
        if not mis:
            status.config(text="Pick a map first.", fg="yellow")
            return
        try:
            cfg = open(SERVER_CFG, "r", errors="ignore").read()
            new, n = re.subn(r'(template\s*=\s*")(.*?)(")',
                             lambda mo: mo.group(1) + mis + mo.group(3),
                             cfg, count=1)
            if n == 0:
                status.config(text="Couldn't find the template line in "
                              "serverDZ.cfg.", fg="red")
                return
            with open(SERVER_CFG, "w") as f:
                f.write(new)
        except Exception as e:
            status.config(text="Couldn't write serverDZ.cfg: %s" % e, fg="red")
            return
        refresh_active_label()
        status.config(text="Map set to %s. Your other maps' worlds are kept. "
                      "Hit START SERVER." % friendly(mis), fg="lime")

    tk.Button(win, text="SET MAP", font=("Arial", 12, "bold"), bg="green",
              fg="white", command=apply_map).pack(pady=(8, 4))
    status.pack(pady=(2, 10))


def open_get_mods():
    """The easy button for new mods: search or open the Workshop right
    inside your already-open Steam, then one-click wire whatever you
    subscribed to into the server. Reuses the proven sync wiring."""
    if _solo_window("getmods"):
        return
    win = tk.Toplevel(window)
    _register_window("getmods", win)
    win.title("Get Mods")
    win.geometry("480x640")
    win.configure(bg="black")

    tk.Label(win, text="GET MODS", font=("Arial", 18, "bold"),
             bg="black", fg="white").pack(pady=(14, 0))
    tk.Label(win, text="find it in Steam  ->  hit Subscribe  ->  I wire it in",
             font=("Arial", 9), bg="black", fg="gray").pack(pady=(0, 8))

    gm_status = tk.Label(win, text="", font=("Arial", 9), bg="black",
                         fg="lime", wraplength=450)
    gm_status.pack(side="bottom", pady=(0, 8))

    def say(msg, color="lime"):
        gm_status.config(text=msg, fg=color)

    def open_steam(url):
        try:
            os.startfile(url)
            return True
        except Exception as e:
            say(f"Couldn't reach Steam: {e}", "red")
            return False

    # --- 1. FIND ---
    f1 = tk.LabelFrame(win, text=" 1. Find a mod ",
                       font=("Arial", 10, "bold"), bg="black", fg="cyan",
                       labelanchor="nw")
    f1.pack(fill="x", padx=14, pady=4)

    srow = tk.Frame(f1, bg="black")
    srow.pack(fill="x", padx=8, pady=6)
    search_var = tk.StringVar()
    tk.Entry(srow, textvariable=search_var, font=("Arial", 11),
             bg="#0a0a0a", fg="white", insertbackground="white").pack(
                 side="left", fill="x", expand=True)

    def do_search():
        term = search_var.get().strip()
        if not term:
            say("Type what you're looking for first.", "yellow")
            return
        url = ("steam://openurl/https://steamcommunity.com/workshop/browse/"
               "?appid=221100&searchtext=" + urllib.parse.quote_plus(term))
        if open_steam(url):
            say("Opened the Workshop search in Steam. Subscribe to what "
                "you want, then hit 'Check for new mods' below.", "lime")

    tk.Button(srow, text="Search in Steam", font=("Arial", 9, "bold"),
              bg="#2b3a4d", fg="white", command=do_search).pack(
                  side="left", padx=(6, 0))

    prow = tk.Frame(f1, bg="black")
    prow.pack(fill="x", padx=8, pady=(0, 8))
    tk.Label(prow, text="or paste a Workshop link / ID:",
             font=("Arial", 8), bg="black", fg="gray").pack(
                 anchor="w")
    prow2 = tk.Frame(f1, bg="black")
    prow2.pack(fill="x", padx=8, pady=(0, 8))
    link_var = tk.StringVar()
    tk.Entry(prow2, textvariable=link_var, font=("Arial", 11),
             bg="#0a0a0a", fg="white", insertbackground="white").pack(
                 side="left", fill="x", expand=True)

    def do_open_link():
        txt = link_var.get().strip()
        m = re.search(r"(\d{6,})", txt)
        if m:
            if open_steam(f"steam://url/CommunityFilePage/{m.group(1)}"):
                say("Opened that item in Steam. Click Subscribe, then "
                    "'Check for new mods'.", "lime")
        elif txt:
            search_var.set(txt)
            do_search()
        else:
            say("Paste a Workshop link or ID first.", "yellow")

    tk.Button(prow2, text="Open in Steam", font=("Arial", 9, "bold"),
              bg="#2b3a4d", fg="white", command=do_open_link).pack(
                  side="left", padx=(6, 0))

    # --- 2. SUBSCRIBE (just a reminder) ---
    tk.Label(win, text="2.  In Steam, click the green Subscribe button - "
             "it downloads on its own.", font=("Arial", 9), bg="black",
             fg="gray", wraplength=450).pack(padx=14, pady=(6, 2))

    # --- 3. WIRE ---
    f3 = tk.LabelFrame(win, text=" 3. Pull new mods into your server ",
                       font=("Arial", 10, "bold"), bg="black", fg="cyan",
                       labelanchor="nw")
    f3.pack(fill="both", expand=True, padx=14, pady=4)

    box = tk.Text(f3, height=7, wrap="word", bg="#0a0a0a", fg="cyan",
                  font=("Consolas", 9), borderwidth=0, padx=8, pady=6)
    box.pack(fill="both", expand=True, padx=8, pady=(6, 4))

    state = {"backlog": []}
    wire_btn = tk.Button(f3, text="WIRE UP", font=("Arial", 11, "bold"),
                         bg="green", fg="white", state="disabled")

    def show_backlog():
        backlog = scan_workshop_backlog()
        state["backlog"] = backlog
        box.config(state="normal")
        box.delete("1.0", "end")
        if not backlog:
            box.insert("1.0", "No new mods waiting - everything you've "
                       "subscribed to is already wired into the server.")
            wire_btn.config(state="disabled", text="WIRE UP")
        else:
            rows = []
            for b in backlog:
                tag = ("   (name already used by another mod)"
                       if os.path.exists(os.path.join(SERVER_DIR, b[2]))
                       else "")
                rows.append("  - " + b[2] + tag)
            names = "\n".join(rows)
            box.insert("1.0", f"{len(backlog)} new mod(s) downloaded and "
                       f"ready to wire:\n\n{names}")
            wire_btn.config(state="normal",
                            text=f"WIRE UP {len(backlog)} MOD(S)")
        box.config(state="disabled")

    def do_wire():
        backlog = state["backlog"]
        if not backlog:
            return
        wire_btn.config(state="disabled", text="Wiring...")
        say(f"Wiring {len(backlog)} mod(s)...", "yellow")
        win.update()
        linked, keys, errors = wire_up_mods(backlog)
        refresh_active_label()
        already = [e.split(":", 1)[0] for e in errors if "already exists" in e]
        trouble = [e.split(":", 1)[0] for e in errors
                   if "already exists" not in e]
        parts = []
        if linked:
            parts.append(f"Added {linked} mod(s) to your server.")
        if already:
            parts.append("Left alone (already installed under that "
                         "name): " + ", ".join(already) + ".")
        if trouble:
            parts.append("Couldn't link (try running EasyStreet as "
                         "admin): " + ", ".join(trouble) + ".")
        if not parts:
            parts.append("Nothing new to add - you're all set.")
        say("  ".join(parts),
            "red" if trouble else ("lime" if linked else "yellow"))
        show_backlog()

    wire_btn.config(command=do_wire)

    tk.Button(f3, text="Check for new mods", font=("Arial", 9, "bold"),
              bg="#2b2b2b", fg="white", command=show_backlog).pack(
                  pady=(2, 4))
    wire_btn.pack(pady=(0, 8))

    show_backlog()


def open_mod_picker():
    """A scrollable, searchable, mouse-wheel-friendly checklist of every
    mod on the server. Filter, Check/Uncheck shown, watch the live count,
    Save - and it rewrites the launch line for you (CF first)."""
    all_mods = list_all_mods()
    active = set(get_active_mods())

    if _solo_window("choosemods"):
        return
    picker = tk.Toplevel(window)
    _register_window("choosemods", picker)
    picker.title("Choose Mods")
    picker.geometry("470x600")
    picker.configure(bg="black")

    tk.Label(picker, text="CHOOSE YOUR MODS", font=("Arial", 16, "bold"),
             bg="black", fg="white").pack(pady=(14, 0))

    count_label = tk.Label(picker, text="", font=("Arial", 10),
                           bg="black", fg="lime")
    count_label.pack()

    states = {m: tk.IntVar(value=1 if m in active else 0) for m in all_mods}

    def update_count():
        n = sum(v.get() for v in states.values())
        count_label.config(text=f"{n} of {len(all_mods)} mods selected")

    filter_var = tk.StringVar()
    tk.Entry(picker, textvariable=filter_var, font=("Arial", 11),
             bg="#1a1a1a", fg="white",
             insertbackground="white").pack(fill="x", padx=14, pady=(8, 4))

    def visible_mods():
        needle = filter_var.get().lower()
        shown = [m for m in all_mods if needle in m.lower()]
        # Checked mods float to the top; alphabetical within each group.
        shown.sort(key=lambda m: (states[m].get() == 0, m.lower()))
        return shown

    def check_all():
        for m in visible_mods():
            states[m].set(1)
        update_count()
        rebuild()

    def uncheck_all():
        for m in visible_mods():
            states[m].set(0)
        update_count()
        rebuild()

    btnrow = tk.Frame(picker, bg="black")
    btnrow.pack(pady=(0, 6))
    tk.Button(btnrow, text="Check shown", font=("Arial", 9, "bold"),
              bg="#2b2b2b", fg="white",
              command=check_all).pack(side="left", padx=4)
    tk.Button(btnrow, text="Uncheck shown", font=("Arial", 9, "bold"),
              bg="#2b2b2b", fg="white",
              command=uncheck_all).pack(side="left", padx=4)
    tk.Button(btnrow, text="Packages", font=("Arial", 9, "bold"),
              bg="#3a2b4d", fg="white",
              command=lambda: open_packages()).pack(side="left", padx=4)
    tk.Button(btnrow, text="Pre-flight", font=("Arial", 9, "bold"),
              bg="#1a3a4d", fg="white",
              command=lambda: open_preflight()).pack(side="left", padx=4)

    box = tk.Frame(picker, bg="black")
    box.pack(fill="both", expand=True, padx=14)
    canvas = tk.Canvas(box, bg="black", highlightthickness=0)
    bar = tk.Scrollbar(box, orient="vertical", command=canvas.yview)
    inner = tk.Frame(canvas, bg="black")
    inner.bind("<Configure>",
               lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
    canvas.create_window((0, 0), window=inner, anchor="nw")
    canvas.configure(yscrollcommand=bar.set)
    canvas.pack(side="left", fill="both", expand=True)
    bar.pack(side="right", fill="y")

    def on_wheel(event):
        canvas.yview_scroll(int(-event.delta / 120), "units")
    canvas.bind_all("<MouseWheel>", on_wheel)

    def rebuild(*_):
        pos = canvas.yview()[0]          # remember where we're scrolled
        for w in inner.winfo_children():
            w.destroy()
        for m in visible_mods():
            tk.Checkbutton(inner, text=m, variable=states[m],
                           command=lambda mm=m: on_toggle(mm),
                           bg="black", fg="cyan",
                           selectcolor="#1a1a1a", activebackground="black",
                           activeforeground="cyan",
                           anchor="w").pack(fill="x", anchor="w")
        inner.update_idletasks()
        canvas.configure(scrollregion=canvas.bbox("all"))
        canvas.yview_moveto(pos)         # ...and stay there

    def on_toggle(_m):
        # Just update the count - DON'T redraw the whole list. Redrawing
        # ~700 checkboxes on every click is what caused the white flash.
        # Re-sorting (checked-to-top) happens when you type in the filter.
        update_count()

    filter_var.trace_add("write", rebuild)
    rebuild()
    update_count()

    def open_packages():
        """Toggle whole mod-families on/off in one click."""
        fams = detect_families(all_mods)
        if not fams:
            return
        pk = tk.Toplevel(picker)
        pk.title("Packages")
        pk.geometry("370x500")
        pk.configure(bg="black")
        tk.Label(pk, text="MOD PACKAGES", font=("Arial", 14, "bold"),
                 bg="black", fg="white").pack(pady=(12, 0))
        tk.Label(pk, text="Flip a whole family at once.",
                 font=("Arial", 9), bg="black", fg="gray").pack(pady=(0, 8))

        holder = tk.Frame(pk, bg="black")
        holder.pack(fill="both", expand=True, padx=12, pady=(0, 12))
        rows = {}

        def status(members):
            on = sum(states[m].get() for m in members)
            return f"{on}/{len(members)}"

        def refresh_rows():
            for lbl, members in fams.items():
                rows[lbl].config(text=f"{lbl}   ({status(members)})")

        def add_fam(members):
            for m in members:
                states[m].set(1)
            update_count()
            rebuild()
            refresh_rows()

        def rem_fam(members):
            for m in members:
                states[m].set(0)
            update_count()
            rebuild()
            refresh_rows()

        for lbl, members in sorted(fams.items(),
                                   key=lambda kv: -len(kv[1])):
            row = tk.Frame(holder, bg="black")
            row.pack(fill="x", pady=3)
            name = tk.Label(row, text=f"{lbl}   ({status(members)})",
                            font=("Arial", 10, "bold"), bg="black",
                            fg="cyan", anchor="w", width=20)
            name.pack(side="left")
            rows[lbl] = name
            tk.Button(row, text="All", font=("Arial", 8, "bold"),
                      bg="#1a4d1a", fg="white", width=5,
                      command=lambda mm=members: add_fam(mm)).pack(
                          side="right", padx=2)
            tk.Button(row, text="None", font=("Arial", 8, "bold"),
                      bg="#4d1a1a", fg="white", width=5,
                      command=lambda mm=members: rem_fam(mm)).pack(
                          side="right", padx=2)

    def open_preflight():
        """Look at what's ticked and advise what ELSE to tick before
        launch - using the learned dependency memory."""
        selected = [m for m in all_mods if states[m].get() == 1]
        set_status("Pre-flight: building the mod map - first time can take "
                   "a minute, please wait...", "yellow")
        try:
            window.update()
        except Exception:
            pass
        suggestions, missing = preflight_check(selected)
        set_status("Ready", "gray")

        pf = tk.Toplevel(picker)
        pf.title("Pre-flight Check")
        pf.geometry("520x540")
        pf.configure(bg="black")
        tk.Label(pf, text="PRE-FLIGHT CHECK", font=("Arial", 15, "bold"),
                 bg="black", fg="white").pack(pady=(12, 2))

        if not suggestions and not missing:
            tk.Label(pf, text="All known dependencies satisfied.\n"
                     "Cleared for launch.", font=("Arial", 11),
                     bg="black", fg="lime").pack(pady=26)
            return

        body = tk.Frame(pf, bg="black")
        body.pack(fill="both", expand=True, padx=14, pady=(4, 6))
        sb = tk.Scrollbar(body)
        sb.pack(side="right", fill="y")
        txt = tk.Text(body, wrap="word", bg="#0a0a0a", fg="cyan",
                      font=("Consolas", 9), yscrollcommand=sb.set,
                      borderwidth=0, padx=8, pady=6)
        txt.pack(side="left", fill="both", expand=True)
        sb.config(command=txt.yview)

        report = []
        if suggestions:
            report.append("ALSO TICK THESE - you own them, your picks need "
                          "them:")
            for s in suggestions:
                report.append(f"   {s}")
            report.append("")
        if missing:
            report.append("MISSING - subscribe on the Workshop, or untick "
                          "what needs it:")
            for addon in sorted(missing, key=str.lower):
                who = ", ".join(sorted(set(missing[addon]))[:2])
                report.append(f"   {addon}   (needed by {who})")
        txt.insert("1.0", "\n".join(report))
        txt.config(state="disabled")

        def tick_them():
            for s in suggestions:
                if s in states:
                    states[s].set(1)
            update_count()
            rebuild()
            set_status(f"Pre-flight added {len(suggestions)} mod(s). "
                       "Re-check or SAVE.", "lime")
            pf.destroy()

        if suggestions:
            tk.Button(pf, text=f"TICK THESE {len(suggestions)} MODS",
                      font=("Arial", 12, "bold"), bg="green", fg="white",
                      command=tick_them).pack(pady=10)

    def finish():
        canvas.unbind_all("<MouseWheel>")
        picker.destroy()

    def save():
        chosen = [m for m in all_mods if states[m].get() == 1]
        ordered = set_mod_line(chosen)
        if ordered:
            refresh_active_label()
            extra = len(ordered) - len(chosen)
            note = f"  (+{extra} dependency auto-added)" if extra else ""
            set_status(f"Saved {len(ordered)} mods.{note}  Hit START SERVER.",
                       "lime")
        else:
            set_status("Couldn't write the mod list.", "red")
        finish()

    picker.protocol("WM_DELETE_WINDOW", finish)
    tk.Button(picker, text="SAVE & APPLY", font=("Arial", 13, "bold"),
              bg="green", fg="white", command=save).pack(pady=10)


def open_dayz():
    """Open the DayZ launcher so you can jump straight onto the server."""
    try:
        os.startfile("steam://rungameid/221100")
        set_status("Opening DayZ - Direct Connect to 127.0.0.1:2302", "lime")
    except Exception:
        set_status("Couldn't open DayZ. Launch it from Steam.", "red")


def _newest_file(match):
    """Newest file in PROFILES whose name passes the match() test."""
    try:
        files = [os.path.join(PROFILES, f) for f in os.listdir(PROFILES)
                 if match(f)]
        return max(files, key=os.path.getmtime) if files else None
    except Exception:
        return None


def _norm(s):
    """Squash a name to bare letters+digits for loose matching."""
    return re.sub(r"[^a-z0-9]", "", s.lower())


def _read_pbo_prefix(path):
    """Read a PBO's internal 'prefix' (e.g. JM\\CF\\Scripts). The addon
    name a mod really provides lives here, NOT in the .pbo filename -
    that's why CF's 'scripts.pbo' actually provides 'JM_CF_Scripts'."""
    try:
        with open(path, "rb") as f:
            data = f.read(8192)
    except Exception:
        return None
    pos, n = 0, len(data)

    def rstr():
        nonlocal pos
        start = pos
        while pos < n and data[pos] != 0:
            pos += 1
        s = data[start:pos].decode("ascii", "ignore")
        pos += 1
        return s

    fn = rstr()
    pos += 20                       # skip the 5x uint32 entry header
    if fn == "":                    # header-extension block holds prefix
        while pos < n:
            k = rstr()
            if k == "":
                break
            v = rstr()
            if k.lower() == "prefix":
                return v
    return None


def _scan_mod_tokens(full, name):
    """Every addon-token a mod provides: its folder name, each .pbo
    filename, and each .pbo's internal prefix."""
    toks = {_norm(name)}
    ad = os.path.join(full, "addons")
    if os.path.isdir(ad):
        try:
            for fn in os.listdir(ad):
                if fn.lower().endswith(".pbo"):
                    toks.add(_norm(fn[:-4]))
                    pref = _read_pbo_prefix(os.path.join(ad, fn))
                    if pref:
                        toks.add(_norm(pref))
        except Exception:
            pass
    return sorted(t for t in toks if t)


def build_addon_providers():
    """Map every addon-token -> the @folder that provides it. Backed by
    a cache (providers.json) so the slow PBO-prefix read happens once;
    new mods get scanned the first time they're seen."""
    try:
        with open(PROVIDERS_CACHE, "r", encoding="utf-8") as f:
            cache = json.load(f)
    except Exception:
        cache = {}
    try:
        installed = [d for d in os.listdir(SERVER_DIR)
                     if d.startswith("@")
                     and os.path.isdir(os.path.join(SERVER_DIR, d))]
    except Exception:
        installed = []
    dirty = False
    for d in installed:
        if d not in cache:
            cache[d] = _scan_mod_tokens(os.path.join(SERVER_DIR, d), d)
            dirty = True
    if dirty:
        try:
            with open(PROVIDERS_CACHE, "w", encoding="utf-8") as f:
                json.dump(cache, f)
        except Exception:
            pass
    inv = {}
    installed_set = set(installed)
    for fold, toks in cache.items():
        if fold not in installed_set:
            continue
        for t in toks:
            inv.setdefault(t, fold)
    return inv


def _resolve_provider(addon, providers):
    """Which installed @folder provides this addon name? Exact first,
    then a loose prefix match (RFFSHeli_Blackhawk_Heli -> ...Blackhawk)."""
    nb = _norm(addon)
    p = providers.get(nb)
    if not p:
        for tok, fold in providers.items():
            if len(tok) >= 5 and (nb.startswith(tok) or tok.startswith(nb)):
                return fold
    return p


def _load_deps():
    try:
        with open(DEPS_PATH, "r", encoding="utf-8") as f:
            d = json.load(f)
    except Exception:
        d = {}
    d.setdefault("ingested", [])   # RPT filenames already learned from
    d.setdefault("edges", {})      # @folder -> [required @folders it needs]
    d.setdefault("missing", {})    # @folder -> [needed addons nothing provides]
    return d


def _save_deps(d):
    try:
        with open(DEPS_PATH, "w", encoding="utf-8") as f:
            json.dump(d, f, indent=1)
    except Exception:
        pass


def learn_dependencies(providers=None):
    """Read every RPT we haven't seen yet, harvest 'Addon A requires
    addon B', resolve both to their mods, and remember folder->folder
    needs. Self-improving: every launch makes the advisor smarter."""
    if providers is None:
        providers = build_addon_providers()
    d = _load_deps()
    seen = set(d["ingested"])
    try:
        rpts = [f for f in os.listdir(PROFILES) if f.lower().endswith(".rpt")]
    except Exception:
        rpts = []
    new = [f for f in rpts if f not in seen]
    for fn in new:
        try:
            with open(os.path.join(PROFILES, fn), "r", errors="ignore") as f:
                for ln in f:
                    mm = re.search(r"Addon '(.+?)' requires addon '(.+?)'", ln)
                    if not mm:
                        continue
                    fa = _resolve_provider(mm.group(1), providers)
                    if not fa:
                        continue
                    fb = _resolve_provider(mm.group(2), providers)
                    if fb and fb != fa:
                        lst = d["edges"].setdefault(fa, [])
                        if fb not in lst:
                            lst.append(fb)
                    elif not fb:
                        lst = d["missing"].setdefault(fa, [])
                        if mm.group(2) not in lst:
                            lst.append(mm.group(2))
        except Exception:
            pass
        d["ingested"].append(fn)
    if new:
        _save_deps(d)
    return d


def preflight_check(selected):
    """Given the mods currently ticked, return (suggestions, missing):
    suggestions = installed mods you SHOULD also tick (followed through
    chains), missing = {needed addon: [mods that need it]} with no owner."""
    providers = build_addon_providers()
    d = learn_dependencies(providers)
    edges = d["edges"]
    miss = d["missing"]
    installed = set(list_all_mods())
    selected = set(selected)

    suggestions = set()
    frontier = list(selected)
    seen = set(selected)
    while frontier:
        m = frontier.pop()
        for req in edges.get(m, []):
            if req in installed and req not in selected:
                suggestions.add(req)
            if req not in seen:
                seen.add(req)
                frontier.append(req)

    missing = {}
    for m in list(selected) + list(suggestions):
        for addon in miss.get(m, []):
            missing.setdefault(addon, []).append(m)
    return sorted(suggestions), missing


def diagnose_logs():
    """Read the newest server logs and turn the failures into plain
    English: the fatal compile/conflict that stopped the boot, plus
    every missing-requirement sorted into 'just load it' vs 'go get it'."""
    set_status("Reading logs and scanning mods...", "yellow")
    rpt = _newest_file(lambda f: f.lower().endswith(".rpt"))
    crash = _newest_file(lambda f: f.startswith("crash_")
                         and f.endswith(".log"))

    installed = list_all_mods()
    loaded = get_active_mods()
    norm_loaded = {_norm(m) for m in loaded}
    lines = []

    # ---- fatal compile / conflict (from the crash log) ----
    # Only trust the crash log if it's from THIS launch (>= the RPT).
    fatal_current = crash and (not rpt or
                               os.path.getmtime(crash) >= os.path.getmtime(rpt) - 2)
    fatal = False
    if fatal_current:
        try:
            with open(crash, "r", errors="ignore") as f:
                clines = f.read().splitlines()
        except Exception:
            clines = []
        for i, ln in enumerate(clines):
            cm = re.search(r'Can.t compile "(.+?)" script module', ln)
            if not cm:
                continue
            fatal = True
            module = cm.group(1)
            reason = next((x.strip() for x in clines[i + 1:] if x.strip()), "")
            lines.append("X  FATAL - the server did not boot.")
            lines.append(f'   The "{module}" script module would not compile.')
            lines.append(f"   {reason}")
            if "Multiple declaration" in reason:
                pathm = re.match(r"([A-Za-z0-9_]+)[/\\]", reason)
                token = _norm(pathm.group(1)) if pathm else ""
                culprits = [m for m in loaded if token and
                            (_norm(m).startswith(token) or
                             (len(_norm(m)) >= 4 and token.startswith(_norm(m))))]
                if len(culprits) >= 2:
                    lines.append("   Two loaded mods declare the same thing:")
                    for c in culprits:
                        lines.append(f"       {c}")
                    lines.append("   -> Keep ONE of these, uncheck the rest.")
            elif "Unknown type" in reason:
                lines.append("   A base mod that defines this isn't loaded yet")
                lines.append("   -> see the 'tick these' list below.")
            lines.append("")
            break
    if not fatal and rpt:
        # Some script errors land in the RPT, not a crash log - scan it too.
        try:
            rtxt = open(rpt, "r", errors="ignore").read()
        except Exception:
            rtxt = ""
        rm = (re.search(r'Can.t compile "(.+?)" script module', rtxt)
              or re.search(r"Multiple declaration of \w+ '[^']+'", rtxt)
              or re.search(r"Unknown type '[^']+'", rtxt))
        if rm:
            fatal = True
            lines.append("X  FATAL - the server hit a script error:")
            lines.append("   " + rm.group(0))
            lines.append("   If it says 'Multiple declaration', two loaded mods")
            lines.append("   define the same thing - keep ONE, uncheck the rest.")
            lines.append("")
    if not fatal:
        if fatal_current:
            lines.append("OK  No fatal compile error in the last launch.")
        else:
            lines.append("No fatal error in the logs I can read - BUT I can't")
            lines.append("confirm a clean boot either (no fresh crash log).")
            lines.append("A compile-error popup freezes the server before it")
            lines.append("writes one. If you saw that popup, click ABORT, then")
            lines.append("run me again and I'll catch it.")
        lines.append("")

    # ---- missing requirements (from the RPT) ----
    reqs = []
    if rpt:
        try:
            with open(rpt, "r", errors="ignore") as f:
                for ln in f:
                    mm = re.search(r"Addon '(.+?)' requires addon '(.+?)'", ln)
                    if mm:
                        reqs.append((mm.group(1), mm.group(2)))
        except Exception:
            pass

    providers = build_addon_providers()
    targets = sorted({b for _, b in reqs}, key=str.lower)
    just_load = {}     # installed-but-unloaded provider -> addons it covers
    go_get = []        # addons no installed mod provides
    for b in targets:
        nb = _norm(b)
        provider = providers.get(nb)
        if not provider:
            for tok, fold in providers.items():
                if len(tok) >= 5 and (nb.startswith(tok) or tok.startswith(nb)):
                    provider = fold
                    break
        if provider is None:
            go_get.append(b)
        elif _norm(provider) not in norm_loaded:
            just_load.setdefault(provider, []).append(b)
        # provided AND already loaded -> harmless, skip

    if just_load:
        lines.append("INSTALLED but NOT loaded - just tick these in CHOOSE MODS:")
        for prov in sorted(just_load):
            lines.append(f"   {prov}")
        lines.append("")

    if go_get:
        need = {}
        for a, b in reqs:
            if b in go_get:
                need.setdefault(b, set()).add(a)
        lines.append("NOT installed - get it on the Workshop, or remove the")
        lines.append("mod that needs it:")
        for b in sorted(go_get, key=str.lower):
            who = ", ".join(sorted(need.get(b, []))[:2])
            lines.append(f"   {b}   (needed by {who})")
        lines.append("")

    if not fatal and not just_load and not go_get:
        lines.append("Nothing flagged. This loadout looks clean.")

    set_status("Ready", "gray")
    _show_report("\n".join(lines))


def _show_report(text):
    win = tk.Toplevel(window)
    win.title("Diagnosis")
    win.geometry("580x520")
    win.configure(bg="black")
    tk.Label(win, text="LAST LAUNCH - DIAGNOSIS", font=("Arial", 14, "bold"),
             bg="black", fg="white").pack(pady=(12, 6))
    frame = tk.Frame(win, bg="black")
    frame.pack(fill="both", expand=True, padx=12, pady=(0, 12))
    sb = tk.Scrollbar(frame)
    sb.pack(side="right", fill="y")
    txt = tk.Text(frame, wrap="word", bg="#0a0a0a", fg="lime",
                  font=("Consolas", 10), yscrollcommand=sb.set,
                  borderwidth=0, padx=10, pady=10)
    txt.pack(side="left", fill="both", expand=True)
    sb.config(command=txt.yview)
    txt.insert("1.0", text)
    txt.config(state="disabled")


def open_sync_window():
    """Show every downloaded-but-not-installed mod, and wire them all up
    on one click (junction + keys). Nothing happens until WIRE UP ALL."""
    set_status("Scanning workshop...", "yellow")
    backlog = scan_workshop_backlog()
    set_status("Ready", "gray")

    win = tk.Toplevel(window)
    win.title("Sync from Workshop")
    win.geometry("520x580")
    win.configure(bg="black")
    tk.Label(win, text="SYNC FROM WORKSHOP", font=("Arial", 15, "bold"),
             bg="black", fg="white").pack(pady=(12, 2))

    if not backlog:
        tk.Label(win, text="Nothing to wire up - every downloaded mod\n"
                 "is already on the server.", font=("Arial", 10),
                 bg="black", fg="lime").pack(pady=20)
        return

    tk.Label(win, text=f"{len(backlog)} downloaded mods are NOT on the "
             "server yet.", font=("Arial", 10, "bold"),
             bg="black", fg="cyan").pack()
    tk.Label(win, text="Wiring them up makes them show in CHOOSE MODS.\n"
             "Uses links (no extra disk) and copies their keys.",
             font=("Arial", 9), bg="black", fg="gray").pack(pady=(0, 8))

    box = tk.Frame(win, bg="black")
    box.pack(fill="both", expand=True, padx=14)
    sb = tk.Scrollbar(box)
    sb.pack(side="right", fill="y")
    txt = tk.Text(box, wrap="none", bg="#0a0a0a", fg="cyan",
                  font=("Consolas", 9), yscrollcommand=sb.set,
                  borderwidth=0, padx=8, pady=6)
    txt.pack(side="left", fill="both", expand=True)
    sb.config(command=txt.yview)
    txt.insert("1.0", "\n".join(name for _w, _p, name in backlog))
    txt.config(state="disabled")

    prog = tk.Label(win, text="", font=("Arial", 10), bg="black", fg="lime")
    prog.pack(pady=(8, 2))

    def do_wire():
        wire_btn.config(state="disabled")

        def cb(done, total):
            prog.config(text=f"Wiring... {done}/{total}")
            win.update()

        linked, keys, errors = wire_up_mods(backlog, cb)
        prog.config(text=f"Done: {linked} wired, {keys} keys copied, "
                    f"{len(errors)} skipped.")
        set_status(f"Workshop sync: +{linked} mods now in CHOOSE MODS.",
                   "lime")

    wire_btn = tk.Button(win, text="WIRE UP ALL", font=("Arial", 13, "bold"),
                         bg="green", fg="white", command=do_wire)
    wire_btn.pack(pady=10)


# ----------------------------- GUI -----------------------------
window = tk.Tk()
window.title("EasyStreet")
window.geometry("460x740")
window.configure(bg="black")

if not os.path.isdir(SERVER_DIR):
    _first_run_setup()

tk.Label(window, text="EASY STREET", font=("Arial", 26, "bold"),
         bg="black", fg="white").pack(pady=(22, 0))

tk.Label(window, text=f"DayZ Server Manager   v{VERSION}", font=("Arial", 11),
         bg="black", fg="gray").pack()

mod_label = tk.Label(window, text="", font=("Arial", 11, "bold"),
                     bg="black", fg="cyan")
mod_label.pack(pady=(14, 10))

tk.Button(window, text="CHOOSE MODS", font=("Arial", 11, "bold"),
          bg="#2b2b2b", fg="white", width=20,
          command=open_mod_picker).pack(pady=(0, 4))

tk.Button(window, text="THE LINEUP  (loadouts)", font=("Arial", 11, "bold"),
          bg="#3a2b4d", fg="white", width=20,
          command=open_loadouts).pack(pady=(0, 10))

tk.Button(window, text="MAP  (Chernarus / Livonia / Sakhal)",
          font=("Arial", 10, "bold"), bg="#2b4d3a", fg="white", width=28,
          command=open_map_picker).pack(pady=(0, 10))

tk.Button(window, text="START SERVER", font=("Arial", 16, "bold"),
          bg="green", fg="white", width=20, height=2,
          command=launch_server).pack(pady=(2, 8))

tk.Button(window, text="STOP SERVER", font=("Arial", 11, "bold"),
          bg="#5a1a1a", fg="white", width=20,
          command=stop_server).pack(pady=(0, 8))

tk.Button(window, text="CHECK STATUS", font=("Arial", 11, "bold"),
          bg="#2b2b2b", fg="white", width=20,
          command=check_status).pack(pady=2)

tk.Button(window, text="OPEN DAYZ", font=("Arial", 11, "bold"),
          bg="#1a4d1a", fg="white", width=20,
          command=open_dayz).pack(pady=2)

tk.Button(window, text="INVITE / CONNECT", font=("Arial", 11, "bold"),
          bg="#1a3a4d", fg="white", width=20,
          command=open_connect).pack(pady=2)

tk.Button(window, text="KEEP IT UP", font=("Arial", 11, "bold"),
          bg="#2b2b4d", fg="white", width=20,
          command=open_keepalive).pack(pady=2)

tk.Button(window, text="DIAGNOSE LAST LAUNCH", font=("Arial", 11, "bold"),
          bg="#3a2b00", fg="white", width=20,
          command=diagnose_logs).pack(pady=2)

tk.Button(window, text="FRESH WORLD", font=("Arial", 11, "bold"),
          bg="#3a1a1a", fg="white", width=20,
          command=do_fresh_world).pack(pady=2)

tk.Button(window, text="GET MODS", font=("Arial", 11, "bold"),
          bg="#2b3a4d", fg="white", width=20,
          command=open_get_mods).pack(pady=2)

status_label = tk.Label(window, text="Ready", font=("Arial", 10),
                        bg="black", fg="gray", wraplength=420)
status_label.pack(pady=(12, 4))

# Full mod list lives down here in a fixed, scrollable box so it can
# never push the buttons off-screen again.
tk.Label(window, text="loaded mods", font=("Arial", 9),
         bg="black", fg="gray").pack()
_listframe = tk.Frame(window, bg="black")
_listframe.pack(fill="both", expand=True, padx=14, pady=(2, 12))
_listsb = tk.Scrollbar(_listframe, width=16, bg="#555",
                       troughcolor="#0a0a0a", activebackground="#888")
_listsb.pack(side="right", fill="y")
mod_list_box = tk.Text(_listframe, height=6, wrap="word", bg="#0a0a0a",
                       fg="cyan", font=("Consolas", 9),
                       yscrollcommand=_listsb.set, borderwidth=0,
                       padx=8, pady=6)
mod_list_box.pack(side="left", fill="both", expand=True)
_listsb.config(command=mod_list_box.yview)

_active = get_active_mods()
mod_label.config(text=f"Active mods: {len(_active)}"
                 if _active else "No mods set")
mod_list_box.insert("1.0", ", ".join(_active) if _active else "No mods set")
mod_list_box.config(state="disabled")

# Arm Keep It Up from saved settings, then start the 30s heartbeat.
_ks = _load_settings()
_keepalive["watchdog"] = bool(_ks.get("watchdog", False))
try:
    _keepalive["restart_hours"] = max(0, int(_ks.get("restart_hours", 0) or 0))
except Exception:
    _keepalive["restart_hours"] = 0
if _keepalive["restart_hours"]:
    _keepalive["next_restart"] = time.time() + _keepalive["restart_hours"] * 3600
window.after(30000, _keepalive_tick)

window.mainloop()
