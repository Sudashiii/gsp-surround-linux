#!/usr/bin/env bash
# Install gsp-surround for the current user.
#   bash scripts/install.sh [--yes] [--ir FILE] [--profile NAME]
#     --yes          don't ask (used by the app's "Install everything" / "Set up" button)
#     --ir FILE      use a local filter file instead of downloading it from gsp-surround-irs
#     --profile NAME filter profile (default: from data/devices.conf for the connected dongle, else gsp350)
# From a clone (or the per-user copy) this copies the app into ~/.local/share/gsp-surround/app and adds
# the menu entry, command and service. When the app was installed by the .deb or `make install`
# (a PACKAGED file next to this script's folder) the files are already in place and only the per-user
# setup is done: filter file, PipeWire config, sound-server check; no password then.
# Root is needed only if packages are missing or the udev rule has to change: sudo in a terminal,
# pkexec from the app.
set -eu
here="$(dirname "$(readlink -f "$0")")"
. "$here/common.sh"
PATH_MARK="# added by gsp-surround install.sh"

yes=""; ir_file=""; profile=""
while [ $# -gt 0 ]; do
  case "$1" in
    --yes|-y) yes=1 ;;
    --ir) ir_file="$(readlink -f "$2")"; shift ;;
    --profile) profile="$2"; shift ;;
    *) echo "unknown option $1"; exit 1 ;;
  esac
  shift
done
ask() { [ -n "$yes" ] && return 0; local a; read -r -p "$1 [y/N] " a </dev/tty || true; [[ "$a" =~ ^[Yy] ]]; }
as_root() {
  if [ -t 0 ] && command -v sudo >/dev/null; then sudo "$@"
  elif command -v pkexec >/dev/null; then pkexec "$@"
  elif command -v sudo >/dev/null; then sudo "$@"
  else echo "neither sudo nor pkexec found"; return 1; fi
}

# --- what is missing --------------------------------------------------------------------------
missing_tools() {
  local t m=()
  for t in pw-cli pw-dump pw-link wpctl python3 systemctl; do command -v "$t" >/dev/null 2>&1 || m+=("$t"); done
  python3 -c "import gi; gi.require_version('Gtk', '4.0'); gi.require_version('Adw', '1'); from gi.repository import Adw" \
    >/dev/null 2>&1 || m+=("GTK4/libadwaita for Python (only needed for the app)")
  echo "${m[*]:-}"
}

echo "== packages"
need_pkgs=""
miss=$(missing_tools)
if [ -n "$miss" ]; then
  echo "missing: $miss"
  if ask "Install the missing packages (needs your password)?"; then need_pkgs=1
  elif ! command -v pw-cli >/dev/null || ! command -v wpctl >/dev/null; then
    echo "aborted - PipeWire is required (see README, Manual installation)"; exit 1
  fi
else
  echo "  all present"
fi

# --- root part: packages + udev rule (one password prompt, and only if something has to change) -
mkdir -p "$GSP_DATA" "$GSP_CONF"
rules="$GSP_DATA/70-gsp-surround.rules"
trap 'rm -f "$rules"' EXIT
udev_rules $(target_ids) > "$rules"
current_rule=$(installed_udev_rule)
rule_changed=""
if [ -z "$need_pkgs" ] && [ -n "$current_rule" ] && cmp -s "$rules" "$current_rule"; then
  echo "== root setup"
  echo "  device rule is up to date ($current_rule), no password needed"
else
  echo "== root setup (packages: ${need_pkgs:-no}, udev rule)"
  args=(--udev "$rules"); [ -n "$need_pkgs" ] && args=(--packages "${args[@]}")
  as_root "$(command -v bash)" "$here/root-setup.sh" "${args[@]}"
  rule_changed=1
fi
miss=$(missing_tools)
case "$miss" in *pw-*|*wpctl*|*python3*|*systemctl*) echo "still missing: $miss"; exit 1;; esac

# --- PipeWire must be the sound server ---------------------------------------------------------
echo "== sound server"
if systemctl --user is-active --quiet pulseaudio.service 2>/dev/null; then
  echo "PulseAudio (not PipeWire) is the active sound server."
  if ask "Switch to PipeWire now?"; then
    systemctl --user --now disable pulseaudio.service pulseaudio.socket
    systemctl --user --now enable pipewire.socket pipewire-pulse.socket wireplumber.service
  else
    echo "aborted - virtual surround needs PipeWire as sound server"; exit 1
  fi
fi
systemctl --user enable --now pipewire.socket pipewire-pulse.socket wireplumber.service >/dev/null 2>&1 || true
pw-cli info 0 2>/dev/null | grep -m1 -i "version" | sed 's/^ */  PipeWire /' || true

# --- older gsp350 scripts (sh-findings) are replaced -------------------------------------------
if [ -e "$HOME/.config/systemd/user/gsp350.service" ] || [ -e "$PW_CONFD/gsp350-filter-chain.conf" ]; then
  echo "== removing the older gsp350 install"
  systemctl --user disable --now gsp350.service 2>/dev/null || true
  rm -f "$HOME/.config/systemd/user/gsp350.service" "$PW_CONFD/gsp350-filter-chain.conf" \
        "$HOME/.local/bin/gsp350-preset" "$HOME/.local/bin/gsp350-check"
  for d in pipewire-pulse.conf.d client.conf.d client-rt.conf.d; do rm -f "$HOME/.config/pipewire/$d/90-gsp350-no-upmix.conf"; done
  [ -f "${XDG_CONFIG_HOME:-$HOME/.config}/gsp350/preset" ] && [ ! -f "$GSP_CONF/preset" ] \
    && cp "${XDG_CONFIG_HOME:-$HOME/.config}/gsp350/preset" "$GSP_CONF/preset"
  rm -rf "${XDG_DATA_HOME:-$HOME/.local/share}/gsp350"
  for rc in "$HOME/.profile" "$HOME/.bashrc" "$HOME/.zshrc"; do
    [ -f "$rc" ] && sed -i '/# added by gsp350 install.sh/{N;d;}' "$rc"
  done
fi

# --- app files ---------------------------------------------------------------------------------
# An earlier per-user install of the app (copy in ~/.local/share, command link, menu entry, icon,
# service) is replaced by the system-wide one. Only what that installer created is removed.
migrate_user_install() {
  local old="$GSP_DATA/app" bin="$HOME/.local/bin/gsp-surround" found=""
  local desktop="$HOME/.local/share/applications/gsp-surround.desktop"
  local unit="$HOME/.config/systemd/user/gsp-surround.service"
  if [ -d "$old" ]; then rm -rf "$old"; found=1; fi
  if [ -L "$bin" ] && [ "$(readlink "$bin")" = "$old/gsp-surround" ]; then rm -f "$bin"; found=1; fi
  if [ -f "$desktop" ] && grep -qF "Exec=$old/" "$desktop"; then
    rm -f "$desktop" "$HOME/.local/share/icons/hicolor/scalable/apps/gsp-surround.svg"; found=1
  fi
  if [ -f "$unit" ] && grep -qF "$old/" "$unit"; then rm -f "$unit"; found=1; fi
  [ -z "$found" ] || echo "  replaced the older per-user copy of the app"
  return 0
}

echo "== app"
if packaged; then
  app="$GSP_ROOT"
  echo "  installed system-wide in $app"
  migrate_user_install
else
  app="$GSP_DATA/app"
  if [ "$GSP_ROOT" != "$app" ]; then
    rm -rf "$app"; mkdir -p "$app"
    cp -r "$GSP_ROOT/gsp-surround" "$GSP_ROOT/app" "$GSP_ROOT/scripts" "$GSP_ROOT/data" "$app/"
    cp "$GSP_ROOT/README.md" "$GSP_ROOT/LICENSE" "$GSP_ROOT/VERSION" "$app/" 2>/dev/null || true
    rm -rf "$app/app/__pycache__"
  fi
  chmod +x "$app/gsp-surround" "$app"/scripts/*.sh "$app"/scripts/*.py
  mkdir -p "$HOME/.local/bin" "$HOME/.local/share/applications" "$HOME/.local/share/icons/hicolor/scalable/apps"
  ln -sf "$app/gsp-surround" "$HOME/.local/bin/gsp-surround"
  sed "s|@BIN@|$app/gsp-surround|" "$app/data/gsp-surround.desktop" > "$HOME/.local/share/applications/gsp-surround.desktop"
  cp "$app/data/icons/hicolor/scalable/apps/gsp-surround.svg" "$HOME/.local/share/icons/hicolor/scalable/apps/gsp-surround.svg"
  echo "  $app, app menu entry \"GSP Surround\""
fi

# --- filter file --------------------------------------------------------------------------------
echo "== filter file"
if [ -z "$profile" ]; then
  found=$(gsp_find || true)
  [ -n "$found" ] && profile=$(device_lines | awk -v id="${found#* }" '$1==id {print $2}')
  profile="${profile:-$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["profile"])' "$GSP_PROFILE_JSON" 2>/dev/null || echo gsp350)}"
fi
python3 "$app/scripts/fetch_ir.py" --profile "$profile" --dest "$GSP_DATA" ${ir_file:+--file "$ir_file"}
[ -f "$GSP_CONF/preset" ] || echo game > "$GSP_CONF/preset"
[ -f "$GSP_CONF/surround" ] || echo on > "$GSP_CONF/surround"
mkdir -p "$PW_CONFD"
sed -e "s|@IR_PATH@|$GSP_IR|g" -e "s|@LFE_GAIN@|$(preset_lfe "$(saved_preset)")|g" \
    "$app/data/filter-chain.conf.in" > "$PW_CONFD/gsp-surround.conf"

# --- ~/.local/bin on PATH -----------------------------------------------------------------------
echo "== PATH"
path_added=""
if packaged; then
  echo "  not needed, the command is installed system-wide"
else
  case ":$PATH:" in
    *":$HOME/.local/bin:"*) echo "  ~/.local/bin already on PATH" ;;
    *)
      for rc in "$HOME/.profile" "$HOME/.bashrc" "$HOME/.zshrc"; do
        { [ "$rc" = "$HOME/.profile" ] || [ -f "$rc" ]; } || continue
        grep -qF "$PATH_MARK" "$rc" 2>/dev/null && continue
        printf '\n%s\nexport PATH="$HOME/.local/bin:$PATH"\n' "$PATH_MARK" >> "$rc"
        echo "  added ~/.local/bin to PATH in $rc"; path_added=1
      done
      if command -v fish >/dev/null 2>&1; then
        fish -c 'contains ~/.local/bin $fish_user_paths; or set -Ua fish_user_paths ~/.local/bin' \
          && echo "  added ~/.local/bin to fish_user_paths" && path_added=1
      fi
      ;;
  esac
fi

# --- no automatic stereo upmix (the Windows driver fed stereo apps only to front L/R) ----------
for d in pipewire-pulse.conf.d client.conf.d client-rt.conf.d; do
  mkdir -p "$HOME/.config/pipewire/$d"
  printf 'stream.properties = {\n  channelmix.upmix = false\n}\n' > "$HOME/.config/pipewire/$d/90-gsp-surround-no-upmix.conf"
done

# --- service --------------------------------------------------------------------------------------
echo "== systemd user service"
if packaged; then
  echo "  provided by the package"
else
  mkdir -p "$HOME/.config/systemd/user"
  sed "s|@APPLY@|$app/scripts/apply.sh|" "$app/data/gsp-surround.service.in" > "$HOME/.config/systemd/user/gsp-surround.service"
fi
systemctl --user daemon-reload
packaged || systemctl --user enable gsp-surround.service

echo "== restart PipeWire and apply"
systemctl --user restart pipewire pipewire-pulse wireplumber
sleep 3
"$app/scripts/apply.sh" || true
echo
echo "Done."
[ -z "$rule_changed" ] || echo "Unplug and replug the dongle once, so the new udev rule gives access to its EQ control."
[ -z "$path_added" ] || echo "Open a new terminal to use the 'gsp-surround' command."
exit 0
