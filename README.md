# gsp-surround-linux

Virtual 7.1 surround and the EQ presets of the **Sennheiser GSP 350** gaming headset on Linux,
without the Windows software, with a small app to switch them.

It is made for the GSP 350 (USB dongle `1395:005d`). It **may also work with other headsets of the
GSP family that use the same USB dongle and drivers**, but that is untested; see
[Other headsets](#other-headsets).

> Not affiliated with, endorsed by or connected to Sennheiser, EPOS, Conexant or Dolby
> Laboratories. Product names are only used to say which hardware this works with.

## What it does
On Windows, the Sennheiser driver turns a game's 7.1 sound into headphone stereo with a fixed
filter ("Dolby Headphone"). The dongle itself is a plain USB sound card with an EQ built in.

This project recreates exactly that:

1. **Virtual 7.1 device.** A PipeWire filter adds a "GSP Virtual Surround 7.1" output. Every channel is
   run through the filter measured from the original driver. The filter file comes from
   [gsp-surround-irs](https://github.com/Sudashiii/gsp-surround-irs) and is downloaded during
   installation. Compared with the real driver output, the difference is about −46 dB, which is
   inaudible.
2. **Presets.** Off / Game / Music / eSports. The EQ of each preset runs inside the dongle. The app
   selects it with the same 2-byte USB command the Sennheiser app sends. Game also raises the bass
   (LFE) channel by 3 dB, as the driver did.
3. **Surround on/off.** Off sends plain stereo straight to the headset.
4. **Kept up to date.** A small background service re-applies everything at login and whenever the
   dongle is plugged in.

### Recreated from
| | version |
|---|---|
| Headset / dongle | Sennheiser GSP 350, USB `1395:005D`, firmware (bcdDevice) 0x0007 |
| Driver package | Conexant "USB Audio" 1.31.35.10 (2016-05-20) |
| Driver file | `usbaud64.sys` 1.31.36.6 |
| Control app | Sennheiser SmartAudio3 2.1.4.0 |
| Measured on | Windows 11 23H2 |

## Quick start
```bash
git clone https://github.com/Sudashiii/gsp-surround-linux
cd gsp-surround-linux
./gsp-surround
```
1. Open the **Setup** tab and click **Install everything**. It asks for your password once, to
   install missing packages and a device rule.
2. **Unplug and replug the dongle** once.
3. Choose **GSP Virtual Surround 7.1** as output if it isn't already the default. In games, select
   7.1 / surround in the audio settings if the game asks.

After installation the app is in your app menu as **GSP Surround**, and the `gsp-surround`
command is available in new terminals.

If the app doesn't start, the GTK 4 / libadwaita Python bindings are missing. `./gsp-surround`
prints the command for your distribution, or run `./gsp-surround install` to install everything
from the terminal.

## The app
- **Sound**: the connected headset, virtual 7.1 surround on/off and the EQ preset.
- **Setup**: what virtual surround needs on your system, with **Install everything** (or
  **Reinstall**), **Re-apply** and **Uninstall**.
- **Logs**: the output of what the app ran, with **Copy** (handy for a bug report) and **Clear**.

## Requirements
- Linux with **PipeWire** and **WirePlumber**, the default on current Fedora, Ubuntu (22.10 and
  newer), Arch, openSUSE and others. "Install everything" can install it or switch over from
  PulseAudio, after asking.
- systemd (user session), Python 3.
- For the app: GTK 4 and libadwaita with Python bindings (PyGObject).

## Manual installation
If you'd rather not let the app install things:

1. Install the packages:
   | distribution | command |
   |---|---|
   | Debian / Ubuntu | `sudo apt install pipewire pipewire-pulse pipewire-bin wireplumber python3 python3-gi gir1.2-gtk-4.0 gir1.2-adw-1` |
   | Fedora | `sudo dnf install pipewire pipewire-pulseaudio pipewire-utils wireplumber python3 python3-gobject gtk4 libadwaita` |
   | Arch | `sudo pacman -S --needed pipewire pipewire-pulse wireplumber python python-gobject gtk4 libadwaita` |
   | openSUSE | `sudo zypper install pipewire pipewire-pulseaudio pipewire-tools wireplumber python3 python3-gobject typelib-1_0-Gtk-4_0 typelib-1_0-Adw-1` |

   The GTK packages are only needed for the app.
2. Run the installer in a terminal. It asks before anything that needs `sudo`:
   ```bash
   bash scripts/install.sh
   ```
   Options:
   - `--ir FILE` uses a filter file you already have instead of downloading it.
   - `--profile NAME` chooses a profile from gsp-surround-irs.
3. Unplug and replug the dongle.

What the installer sets up, so you can check or undo it by hand:
| what | where |
|---|---|
| app, scripts, filter file | `~/.local/share/gsp-surround/` |
| PipeWire filter (virtual 7.1 device) | `~/.config/pipewire/pipewire.conf.d/gsp-surround.conf` |
| no automatic stereo→7.1 upmix | `~/.config/pipewire/{pipewire-pulse,client,client-rt}.conf.d/90-gsp-surround-no-upmix.conf` |
| background service | `~/.config/systemd/user/gsp-surround.service` |
| device rule (EQ access, start on plug-in) | `/etc/udev/rules.d/70-gsp-surround.rules` |
| command / app menu entry | `~/.local/bin/gsp-surround`, `~/.local/share/applications/gsp-surround.desktop` |
| settings | `~/.config/gsp-surround/` |

## Terminal commands
```text
gsp-surround                         open the app
gsp-surround preset off|game|music|esport
gsp-surround surround on|off
gsp-surround check                   what is installed / missing
gsp-surround apply                   re-apply (what the background service does)
gsp-surround uninstall
```

## Troubleshooting
- Run `gsp-surround check` and look for `[FAIL]` lines.
- **EQ presets have no effect / "EQ control: no access":** unplug and replug the dongle once after
  installing.
- **No sound on the virtual device:** check that "Sound routed to the dongle" is ✓ in the **Setup**
  tab. If not, click **Re-apply** or replug the dongle.
- Don't switch the dongle's profile to "Pro Audio" in your sound settings. The app needs the
  normal profile.
- The surround button on the headset does nothing; on Windows the Sennheiser app handled it. Use
  the app instead.

## Uninstall
Click **Uninstall** in the app's **Setup** tab, or run `gsp-surround uninstall`. Your preset
settings in `~/.config/gsp-surround` are kept.

## Other headsets
Other GSP headsets that came with the same dongle and the same Sennheiser/Conexant drivers
probably work the same way. To try one:

1. Plug it in and open the app. If it isn't detected, pick it under **Use an untested USB headset**
   in the **Sound** tab. EQ presets are not sent to untested dongles; virtual surround uses the
   GSP 350 filter.
2. If it works, or doesn't, please open an issue with the output of `lsusb` and `gsp-surround check`.

If your headset's driver sounds different from the GSP 350's, its filter has to be measured on
Windows; see [gsp-surround-irs](https://github.com/Sudashiii/gsp-surround-irs/blob/main/CONTRIBUTING.md).

## Development
```bash
python3 -m unittest discover tests     # backend and GUI tests (no hardware needed)
```
The GUI tests need GTK 4, libadwaita and a display (a desktop session, or `xvfb-run`); without one
they are skipped.
- `app/gsp_surround.py`: the GTK app and window (header with the tabs, background tasks).
- `app/pages.py`: the Sound, Setup and Logs pages.
- `app/backend.py`: checks and actions.
- `scripts/`: the actual work, which also runs without the app.
- `data/devices.conf`: the list of supported dongles.
- `data/icons/`: the app icon and the small headset icon used inside the app. The latter is
  `-symbolic`, so it has to stay fill-only (no strokes) for GTK to recolor it in dark mode.

## License
MIT, see [LICENSE](LICENSE). The filter files in gsp-surround-irs are not covered by this license.
