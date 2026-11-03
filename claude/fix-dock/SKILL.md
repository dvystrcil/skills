---
name: fix-dock
description: Bring back a missing Ubuntu Dock / GNOME taskbar on the user's workstation by running the `fix-dock` script. Use when the user says their taskbar, dock, or panel disappeared, is missing, or is gone.
---

# fix-dock

The user's laptop runs Ubuntu GNOME on Wayland with 3 monitors. The dock is the
`ubuntu-dock@ubuntu.com` extension. It usually isn't crashed when it goes
missing. Instead it is stranded on the laptop panel (eDP-1), which GNOME makes
primary again after a monitor hotplug or resume.

The script is on PATH: `/usr/local/bin/fix-dock`, linked to
`~/Code/utilities/fix-dock`.

## Steps

1. Run `fix-dock`. It restarts the extension and prints `Dock state: ACTIVE`
   on success (exit 0).
2. Ask the user whether the dock is visible. You cannot see their screen, so
   exit 0 alone does not prove the dock is back on the screen they are using.
3. If it's still missing, run `fix-dock --status` and report which monitor is
   primary. Offer `fix-dock --all-monitors` (a persistent setting change:
   ask before running it). `fix-dock --primary-only` reverts it.
4. If it exits 1 (extension not ACTIVE), tell the user to log out and back in.
   Do not suggest Alt+F2 `r`, because that does not work on Wayland.

## Don't

- Don't kill or restart `gnome-shell`. On Wayland that ends the whole session.
- Don't change the primary display or other gsettings beyond what the script does.
