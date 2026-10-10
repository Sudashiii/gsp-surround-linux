#!/usr/bin/env bash
# Bring virtual surround up for the connected dongle: EQ preset via HID, a sink for the dongle's
# main playback path, links from the filter to it, the preset's LFE gain and the default output.
# Run by gsp-surround.service (at login / PipeWire start, and by udev when the dongle is plugged in).
set -u
. "$(dirname "$(readlink -f "$0")")/common.sh"

for _ in $(seq 20); do found=$(gsp_find); [ -n "$found" ] && break; sleep 0.5; done
[ -z "${found:-}" ] && { echo "gsp-surround: no supported dongle connected"; exit 0; }
read -r card usbid <<< "$found"
dev=$(gsp_main_dev "$card")
[ -z "$dev" ] && { echo "gsp-surround: main playback path not found on card $card ($usbid)"; exit 1; }
cardid=$(cat /proc/asound/card"$card"/id)
preset=$(saved_preset)

# 1. dongle EQ preset (2-byte HID output report: id 0x23, value 0..3)
send_eq "$usbid" "$preset"

# 2. wait for PipeWire and the filter-chain, then (re)create the main-path sink
for _ in $(seq 20); do [ -n "$(pw_node_id "$NODE_IN")" ] && break; sleep 0.5; done
old=$(pw_node_id "$NODE_MAIN")
[ -n "$old" ] && pw-cli destroy "$old" >/dev/null 2>&1   # stale after a replug
pw-cli create-node adapter "{ factory.name = api.alsa.pcm.sink node.name = $NODE_MAIN
  node.description = \"GSP dongle (main path, plain stereo)\" media.class = Audio/Sink
  api.alsa.path = \"hw:CARD=$cardid,DEV=$dev\" audio.rate = 48000 audio.channels = 2
  audio.position = [ FL FR ] priority.session = 0 object.linger = true }" >/dev/null
for _ in $(seq 20); do [ -n "$(pw_node_id "$NODE_MAIN")" ] && break; sleep 0.25; done

# 3. filter output -> main path
pw-link "$NODE_OUT:output_FL" "$NODE_MAIN:playback_FL" 2>/dev/null
pw-link "$NODE_OUT:output_FR" "$NODE_MAIN:playback_FR" 2>/dev/null

# 4. LFE gain of the preset, default output
lfe=$(preset_lfe "$preset")
set_lfe "$lfe"
set_default_sink "$(saved_surround)"
echo "gsp-surround: $usbid card $card ($cardid) main path hw:$card,$dev, preset $preset (LFE x$lfe), surround $(saved_surround)"
