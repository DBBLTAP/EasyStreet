# EasyStreet

**DayZ server setup for everyone. Free. Open source. One button.**

Running a DayZ server is harder than it should be — `.bat` files, split Steam
libraries, broken mods, silent crashes, port forwarding. Most people give up
before their server ever runs. **EasyStreet does the annoying parts for you.**

One Windows app. It auto-detects your server, wires in mods, launches it, keeps
it alive, and helps your friends connect. No command line, no Python.

## Download

1. Open the [**Releases**](../../releases) page.
2. Download **EasyStreet_share.zip**.
3. Unzip, and double-click **EasyStreet.exe**.

> Windows may show a blue **"Windows protected your PC / unknown publisher"**
> box. That's normal for small, unsigned indie tools — click
> **More info -> Run anyway**. Some antivirus may also false-flag apps built
> with PyInstaller. It is clean: the full source is right here in this repo,
> and you can build it yourself (see below) if you'd rather not trust the .exe.

## What it does (v0.14)

- **GET MODS** - find a Steam Workshop mod, hit Subscribe, and it wires it into
  your server for you (folders + keys handled).
- **CHOOSE MODS / THE LINEUP** - pick which mods load, save named loadouts,
  safe load order handled automatically.
- **MAP** - switch the world between Chernarus, Livonia, and Sakhal.
- **START / STOP SERVER** - one click each (Stop asks first).
- **KEEP IT UP** - auto-restart if the server crashes, plus scheduled restarts.
- **DIAGNOSE** - reads your crash logs and explains failures in plain English.
- **INVITE / CONNECT** - shows your connect address (LAN / Tailscale / public)
  and copies a ready-to-paste "come play" invite for your friends.
- **FRESH WORLD** - wipe the world for a fresh start (reversible).

## Requirements

- **Windows.**
- A **DayZ Server already installed** through Steam
  (Steam -> Library -> tick "Tools" -> install "DayZ Server").
  EasyStreet manages an existing server; it does not install DayZ for you.

## First run

If it can't auto-find your server, it asks you to point at your `DayZServer`
folder once, then remembers it. The first time you press **Pre-flight** it
takes a minute to learn your mods - that's normal, only happens once.

## Build it yourself (don't trust the .exe? totally fair)

1. Install [Python for Windows](https://www.python.org/downloads/)
   (tick "Add Python to PATH" during install).
2. Put `easystreet.py` and `build_exe.bat` (both in this repo) in one folder.
3. Double-click `build_exe.bat`. Your own `dist\EasyStreet.exe` is built.

## A tip that trips everyone up

If you run **DayZ-Expansion**, load **either** the individual modules
(`@DayZ-Expansion-Core`, `-Market`, etc.) **or** the all-in-one
`@DayZ-Expansion-Bundle` - **not both.** Loading both double-loads the same
code and causes "Can't compile" / Abort errors.

## License

MIT - free to use, share, and modify. Made so more people can just play.
