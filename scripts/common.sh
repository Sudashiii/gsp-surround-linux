#!/usr/bin/env bash
# shellcheck disable=SC2034  # variables are used by the scripts that source this file
# Shared helpers for gsp-surround (sourced by the other scripts).

GSP_ROOT="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/.." && pwd)"   # repo clone or installed app
GSP_DATA="${XDG_DATA_HOME:-$HOME/.local/share}/gsp-surround"
GSP_CONF="${XDG_CONFIG_HOME:-$HOME/.config}/gsp-surround"
PW_CONFD="${XDG_CONFIG_HOME:-$HOME/.config}/pipewire/pipewire.conf.d"
GSP_IR="$GSP_DATA/ir.wav"
GSP_PROFILE_JSON="$GSP_DATA/profile.json"
NODE_IN="effect_input.gsp_surround"
NODE_OUT="effect_output.gsp_surround"
NODE_MAIN="gsp_surround.main"
UDEV_RULE="/etc/udev/rules.d/70-gsp-surround.rules"

# --- saved state ------------------------------------------------------------------------------
saved_preset()   { cat "$GSP_CONF/preset" 2>/dev/null || echo game; }
saved_surround() { cat "$GSP_CONF/surround" 2>/dev/null || echo on; }
manual_device()  { cat "$GSP_CONF/device" 2>/dev/null; }   # vid:pid of an untested dongle picked in the app

# preset -> HID EQ value of the dongle
preset_eq() { case "$1" in off) echo 0;; game) echo 1;; music) echo 2;; esport) echo 3;; *) return 1;; esac; }
# preset -> LFE gain relative to the profile's filter file (from profile.json, GSP 350 values as fallback)
preset_lfe() {
  preset_eq "$1" >/dev/null || return 1
  python3 - "$GSP_PROFILE_JSON" "$1" <<'EOF' 2>/dev/null || { [ "$1" = game ] && echo 1.0 || echo 0.708; }
import json, sys
print(json.load(open(sys.argv[1]))["lfe_gain"][sys.argv[2]])
EOF
}

# --- devices ----------------------------------------------------------------------------------
# "vid:pid profile hid_eq name..." lines of data/devices.conf (lower-case ids)
device_lines() { grep -Ev '^\s*(#|$)' "$GSP_ROOT/data/devices.conf" | awk '{$1=tolower($1); print}'; }
target_ids()   { device_lines | awk '{print $1}'; manual_device; }

# ALSA card index and usb id of the first connected supported dongle: "card vid:pid" (empty if none)
gsp_find() {
  local f id want
  for f in /proc/asound/card*/usbid; do
    [ -r "$f" ] || continue
    id=$(tr 'A-F' 'a-f' < "$f")
    for want in $(target_ids); do
      [ "$id" = "$want" ] && { echo "$(basename "$(dirname "$f")" | sed 's/card//') $id"; return; }
    done
  done
}

# does the dongle take the EQ preset via HID? (untested dongles: no)
device_hid_eq() { device_lines | awk -v id="$1" '$1==id {print $3; f=1} END {if(!f) print "no"}'; }

# PCM device number of the dongle's MAIN playback path (USB endpoint 0x02 OUT, the one the Windows
# driver renders to). The other path (endpoint 0x01) is the "Communication" path that desktop Linux
# usually exposes as default sink. Dongles without EP 0x02: their only playback stream.
gsp_main_dev() {
  local card="$1" f n=0 last=""
  for f in /proc/asound/card"$card"/stream*; do
    if grep -Eq "Endpoint: (0x02 \(2 OUT\)|2 OUT)" "$f"; then basename "$f" | sed 's/stream//'; return; fi
    grep -q "^Playback:" "$f" && { n=$((n + 1)); last=$(basename "$f" | sed 's/stream//'); }
  done
  [ "$n" = 1 ] && echo "$last"
}

# /dev/hidrawN of the dongle (vendor collection with the EQ/NR/LED reports)
gsp_hidraw() {
  local id="$1" d want
  want=$(printf "HID_ID=0003:0000%s:0000%s" "${id%%:*}" "${id##*:}" | tr 'a-f' 'A-F')
  for d in /sys/class/hidraw/hidraw*; do
    grep -qi "^$want$" "$d/device/uevent" 2>/dev/null && { echo "/dev/$(basename "$d")"; return; }
  done
}

# send the EQ preset to the dongle (if it supports it and the hidraw node is writable)
send_eq() {
  local id="$1" preset="$2" hid
  [ "$(device_hid_eq "$id")" = yes ] || { echo "dongle $id: no HID EQ (untested device)"; return 0; }
  hid=$(gsp_hidraw "$id")
  if [ -n "$hid" ] && [ -w "$hid" ]; then
    printf "\x23\x$(printf %02x "$(preset_eq "$preset")")" > "$hid" && echo "EQ preset $preset -> $hid"
  else
    echo "no writable hidraw node for $id (udev rule installed? replug the dongle once)"
  fi
}

# --- PipeWire ---------------------------------------------------------------------------------
# object id of a node by node.name (empty if missing)
pw_node_id() {
  pw-dump 2>/dev/null | python3 -c '
import json, sys
for o in json.load(sys.stdin):
    p = o.get("info", {}).get("props", {})
    if o.get("type", "").endswith(":Node") and p.get("node.name") == sys.argv[1]:
        print(o["id"]); break
' "$1"
}

set_lfe() {
  local fid
  fid=$(pw_node_id "$NODE_IN")
  [ -n "$fid" ] && pw-cli set-param "$fid" Props "{ params = [ \"mixL:Gain 4\" $1 \"mixR:Gain 4\" $1 ] }" >/dev/null
  # also the default for the next PipeWire start
  sed -i -E "s/(\"Gain 4\" = )[0-9.]+/\1$1/" "$PW_CONFD/gsp-surround.conf" 2>/dev/null || true
}

# default output: virtual surround (on) or the dongle's main path directly (off)
set_default_sink() {
  local id
  if [ "$1" = on ]; then id=$(pw_node_id "$NODE_IN"); else id=$(pw_node_id "$NODE_MAIN"); fi
  [ -n "$id" ] && wpctl set-default "$id" && echo "default output: $([ "$1" = on ] && echo "GSP Virtual Surround 7.1" || echo "dongle, plain stereo")"
}
