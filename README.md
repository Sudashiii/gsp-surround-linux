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
   setup. Compared with the real driver output, the difference is about −46 dB, which is
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

## Install

### Debian, Ubuntu, Linux Mint
1. Download `gsp-surround_<version>_all.deb` from the
   [latest release](https://github.com/Sudashiii/gsp-surround-linux/releases/latest) and double-click
   it. Your software installer opens: click **Install**. It asks for your password once and brings
   PipeWire and the GTK bindings along if they are missing. In a terminal:
   `sudo apt install ./gsp-surround_*_all.deb`.
2. Open **GSP Surround** from your application menu, go to the **Setup** tab and click **Set up**. This
   downloads the filter file and configures PipeWire for your user; no password is needed.
3. Choose **GSP Virtual Surround 7.1** as output if it isn't already the default. In games, select
   7.1 / surround in the audio settings if the game asks.

If the EQ presets have no effect, unplug and replug the dongle once (see [Troubleshooting](#troubleshooting)).
The package needs libadwaita 1.2 or newer: Debian 12, Ubuntu 22.10 and Linux Mint 22 or newer.

### Other distributions
Download `gsp-surround-<version>.tar.gz` from the same page and unpack it. Install the packages from
[Manual installation](#manual-installation), then:
```bash
sudo make install              # to /usr/local; use PREFIX=/usr for /usr
```
Open **GSP Surround** from the menu and use **Setup → Set up** as above. `sudo make uninstall` removes it
again. The device rule goes to `/etc/udev/rules.d` for `/usr/local` (udev does not read `/usr/local`)
and to `/usr/lib/udev/rules.d` for `PREFIX=/usr`.

### Run from a clone
No system install, everything stays in your home folder:
```bash
git clone https://github.com/Sudashiii/gsp-surround-linux
cd gsp-surround-linux
./gsp-surround
```
1. Open the **Setup** tab and click **Install everything**. It asks for your password once, to
   install missing packages and a device rule.
2. **Unplug and replug the dongle** once.
3. Choose **GSP Virtual Surround 7.1** as output if it isn't already the default.

After installation the app is in your app menu as **GSP Surround**, and the `gsp-surround`
command is available in new terminals.

If the app doesn't start, the GTK 4 / libadwaita Python bindings are missing. `./gsp-surround`
prints the command for your distribution, or run `./gsp-surround install` to install everything
from the terminal.

## The app
- **Sound**: the connected headset, virtual 7.1 surround on/off and the EQ preset.
- **Setup**: what virtual surround needs on your system, with **Set up** (**Install everything** when run
  from a clone), **Re-apply** and **Remove setup** (**Uninstall** from a clone).
- **Logs**: the output of what the app ran, with **Copy** (handy for a bug report) and **Clear**.

## Requirements
- Linux with **PipeWire** and **WirePlumber**, the default on current Fedora, Ubuntu (22.10 and
  newer), Arch, openSUSE and others. Setup can switch over from PulseAudio.
- systemd (user session), Python 3.
- For the app: GTK 4 and libadwaita 1.2 or newer with Python bindings (PyGObject).

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
2. Run the installer in a terminal. It asks before anything that needs `sudo`, and only asks for it when
   a package is missing or the device rule has to change:
   ```bash
   bash scripts/install.sh
   ```
   Options:
   - `--ir FILE` uses a filter file you already have instead of downloading it.
   - `--profile NAME` chooses a profile from gsp-surround-irs.
3. Unplug and replug the dongle.

What the installer sets up from a clone, so you can check or undo it by hand:
| what | where |
|---|---|
| app, scripts, filter file | `~/.local/share/gsp-surround/` |
| PipeWire filter (virtual 7.1 device) | `~/.config/pipewire/pipewire.conf.d/gsp-surround.conf` |
| no automatic stereo→7.1 upmix | `~/.config/pipewire/{pipewire-pulse,client,client-rt}.conf.d/90-gsp-surround-no-upmix.conf` |
| background service | `~/.config/systemd/user/gsp-surround.service` |
| device rule (EQ access, start on plug-in) | `/etc/udev/rules.d/70-gsp-surround.rules` |
| command / app menu entry | `~/.local/bin/gsp-surround`, `~/.local/share/applications/gsp-surround.desktop` |
| settings | `~/.config/gsp-surround/` |

With the `.deb` (or `make install PREFIX=/usr`) the first part lives in system folders instead, and
**Set up** only does your own part (filter file, PipeWire filter, no-upmix files, settings, as above):
| what | where |
|---|---|
| app, scripts | `/usr/share/gsp-surround/`, command `/usr/bin/gsp-surround` |
| menu entry, icon, AppStream data | `/usr/share/applications/gsp-surround.desktop`, `/usr/share/icons/hicolor/scalable/apps/gsp-surround.svg`, `/usr/share/metainfo/io.github.sudashiii.GspSurround.metainfo.xml` |
| device rule | `/usr/lib/udev/rules.d/70-gsp-surround.rules` |
| background service | `/usr/lib/systemd/user/gsp-surround.service`, enabled through `pipewire.service.wants/`; it does nothing until you have run **Set up** |

## Terminal commands
```text
gsp-surround                         open the app
gsp-surround preset off|game|music|esport
gsp-surround surround on|off
gsp-surround check                   what is installed / missing
gsp-surround apply                   re-apply (what the background service does)
gsp-surround uninstall               remove your setup (and the app, when installed from a clone)
gsp-surround --version
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

## Remove
- **Installed with the `.deb` or `make install`:** click **Remove setup** in the app's **Setup** tab, then
  remove the app in your software manager (`sudo apt remove gsp-surround`, or `sudo make uninstall`). Remove
  setup deletes the filter file and PipeWire settings of your account first, because a package cannot touch
  your home folder.
- **Installed from a clone:** click **Uninstall** in the **Setup** tab, or run `gsp-surround uninstall`. The
  app closes afterwards, since it removed its own files.

Your preset settings in `~/.config/gsp-surround` are kept.

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
make test        # python3 -m unittest discover tests: backend, GUI, installer, packaging and release tests
make check       # validate the desktop entry, AppStream data, service unit and scripts (STRICT=1: fail if a tool is missing)
make deb         # dist/gsp-surround_<version>_all.deb
make dist        # dist/gsp-surround-<version>.tar.gz, from git HEAD
```
The GUI tests need GTK 4, libadwaita and a display (a desktop session, or `xvfb-run`); without one
they are skipped. The installer tests run `scripts/install.sh` and `uninstall.sh` against a fake home
directory with stub commands, so they never touch the real system.
- `app/gsp_surround.py`: the GTK app and window (header with the tabs, background tasks).
- `app/pages.py`: the Sound, Setup and Logs pages.
- `app/backend.py`: checks and actions.
- `scripts/`: the actual work, which also runs without the app.
- `data/devices.conf`: the list of supported dongles.
- `data/icons/`: the app icon and the small headset icon used inside the app. The latter is
  `-symbolic`, so it has to stay fill-only (no strokes) for GTK to recolor it in dark mode.
- `Makefile`, `packaging/`: `make install`, the `.deb` and the release helpers. `VERSION` is the one place
  that holds the version number.

## Releasing
A GitHub Actions pipeline (`.github/workflows/release.yml`) builds the release when you push a version tag:

1. Set the new number in `VERSION` and commit it.
2. Tag and push; the tag must be `v` plus the number from `VERSION`:
   ```bash
   git tag v$(cat VERSION)
   git push origin main v$(cat VERSION)
   ```
3. The pipeline runs the tests and checks, then publishes a GitHub release with
   - `gsp-surround_<version>_all.deb`, the installer (built by `make deb`, never committed),
   - `gsp-surround-<version>.tar.gz`, the source (`make dist`), and `SHA256SUMS`,
   - release notes made from the commit messages since the previous release. A tag with a suffix such as
     `v1.1.0-rc1` becomes a pre-release.

The notes list the **first line** of every commit, so write it for the people who read the release. An
optional prefix groups them: `feat:` under New, `fix:` under Fixes; `docs:`, `test:`, `ci:`, `build:`,
`chore:`, `style:` and `refactor:` under a collapsed Maintenance section. Everything else, plain sentences
included, goes under Changes. Merge commits, commits named "Release x.y.z" and anything marked
`[skip changelog]` are left out.

To rehearse, open the repository's **Actions** tab, choose **Release** and **Run workflow**: it builds
everything and attaches it to the run as a download, and publishes nothing. The same files can be built
locally with `make artifacts` (into `dist/`) and the notes with
`python3 packaging/release_notes.py --tag HEAD --version "$(cat VERSION)"`.

## License
MIT, see [LICENSE](LICENSE). The filter files in gsp-surround-irs are not covered by this license.
