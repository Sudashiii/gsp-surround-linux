#!/usr/bin/env bash
# The parts of the setup that need root. Called by install.sh / uninstall.sh through sudo
# (terminal) or pkexec (app, graphical password prompt):
#   root-setup.sh [--packages] [--udev RULES_FILE] [--remove-udev]
#     --packages     install PipeWire, WirePlumber, their CLI tools and the app's GTK4/libadwaita bindings
#     --udev FILE    install FILE as /etc/udev/rules.d/70-gsp-surround.rules (dongle HID access + service start)
#     --remove-udev  remove the rule again
set -eu
[ "$(id -u)" = 0 ] || { echo "root-setup.sh must run as root"; exit 1; }
RULE=/etc/udev/rules.d/70-gsp-surround.rules
LEGACY_RULE=/etc/udev/rules.d/70-gsp350.rules

packages=""; udev=""; remove=""
while [ $# -gt 0 ]; do
  case "$1" in
    --packages) packages=1 ;;
    --udev) udev="$2"; shift ;;
    --remove-udev) remove=1 ;;
    *) echo "unknown option $1"; exit 1 ;;
  esac
  shift
done

if [ -n "$packages" ]; then
  if   command -v apt-get >/dev/null; then
    apt-get install -y pipewire pipewire-pulse pipewire-bin wireplumber python3 python3-gi gir1.2-gtk-4.0 gir1.2-adw-1
  elif command -v dnf >/dev/null; then
    dnf install -y pipewire pipewire-pulseaudio pipewire-utils wireplumber python3 python3-gobject gtk4 libadwaita
  elif command -v pacman >/dev/null; then
    pacman -S --needed --noconfirm pipewire pipewire-pulse wireplumber python python-gobject gtk4 libadwaita
  elif command -v zypper >/dev/null; then
    zypper --non-interactive install pipewire pipewire-pulseaudio pipewire-tools wireplumber python3 \
      python3-gobject python3-gobject-Gdk typelib-1_0-Gtk-4_0 typelib-1_0-Adw-1
  else
    echo "unknown package manager - install PipeWire, pipewire-pulse, WirePlumber, their CLI tools,"
    echo "python3, PyGObject, GTK 4 and libadwaita yourself (see README, Manual installation)"
    exit 1
  fi
fi

if [ -n "$udev" ]; then
  install -m 644 "$udev" "$RULE"
  rm -f "$LEGACY_RULE"   # rule of the older gsp350 scripts
  echo "installed $RULE"
fi
if [ -n "$remove" ]; then
  rm -f "$RULE" "$LEGACY_RULE"
  echo "removed $RULE"
fi
if [ -n "$udev$remove" ]; then
  udevadm control --reload
  udevadm trigger --subsystem-match=hidraw --action=change
fi
