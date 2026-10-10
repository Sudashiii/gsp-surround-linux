#!/usr/bin/env bash
# Switch the preset: preset.sh off|game|music|esport
# (dongle EQ via HID + LFE level of the virtual surround; remembered for replugs and logins)
set -eu
. "$(dirname "$(readlink -f "$0")")/common.sh"

p="${1:-}"
[ "$p" = esports ] && p=esport
if ! preset_eq "$p" >/dev/null 2>&1; then echo "usage: preset off|game|music|esport (current: $(saved_preset))"; exit 1; fi
mkdir -p "$GSP_CONF"
echo "$p" > "$GSP_CONF/preset"

found=$(gsp_find || true)
if [ -n "$found" ]; then send_eq "${found#* }" "$p" || true; else echo "dongle not connected (preset saved, applied on plug-in)"; fi
lfe=$(preset_lfe "$p")
set_lfe "$lfe"
echo "preset $p (LFE x$lfe)"
