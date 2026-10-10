#!/usr/bin/env bash
# Virtual surround on/off: surround.sh on|off
#   on  = default output is "GSP Virtual Surround 7.1" (the measured filter)
#   off = default output is the dongle's main path directly (plain stereo; the EQ preset stays active)
set -eu
. "$(dirname "$(readlink -f "$0")")/common.sh"

s="${1:-}"
case "$s" in on|off) ;; *) echo "usage: surround on|off (current: $(saved_surround))"; exit 1;; esac
mkdir -p "$GSP_CONF"
echo "$s" > "$GSP_CONF/surround"
set_default_sink "$s" || echo "surround $s saved (applied when the dongle is connected)"
