#!/usr/bin/env bash
# Remove gsp-surround again (settings in ~/.config/gsp-surround are kept).
#   bash scripts/uninstall.sh
# A per-user install is removed completely, app included. When the app was installed by the .deb or
# `make install` only the per-user setup goes (filter file, PipeWire config, a device rule the app added);
# the app itself is removed with the package manager (`sudo apt remove gsp-surround`, `sudo make uninstall`).
set -u
here="$(dirname "$(readlink -f "$0")")"
. "$here/common.sh"
as_root() {
  if [ -t 0 ] && command -v sudo >/dev/null; then sudo "$@"
  elif command -v pkexec >/dev/null; then pkexec "$@"
  else sudo "$@"; fi
}

# the root part first: afterwards the app files (and this script, when run from the app) are gone.
# Only a rule in /etc is ours to remove; the one of the package stays with the package.
if [ -f "$UDEV_RULE" ] || [ -f "${UDEV_RULE_DIRS[0]}/70-gsp350.rules" ]; then
  tmp=$(mktemp -d)
  cp "$here/root-setup.sh" "$tmp/"
  as_root "$(command -v bash)" "$tmp/root-setup.sh" --remove-udev || echo "udev rule not removed (remove $UDEV_RULE yourself)"
  rm -rf "$tmp"
fi

systemctl --user disable --now gsp-surround.service 2>/dev/null
rm -f "$HOME/.config/systemd/user/gsp-surround.service" "$PW_CONFD/gsp-surround.conf"
for d in pipewire-pulse.conf.d client.conf.d client-rt.conf.d; do rm -f "$HOME/.config/pipewire/$d/90-gsp-surround-no-upmix.conf"; done
if ! packaged; then
  rm -f "$HOME/.local/bin/gsp-surround" "$HOME/.local/share/applications/gsp-surround.desktop" \
        "$HOME/.local/share/icons/hicolor/scalable/apps/gsp-surround.svg"
  # PATH lines added by install.sh (marker line + the export after it); fish_user_paths is left alone
  for rc in "$HOME/.profile" "$HOME/.bashrc" "$HOME/.zshrc"; do
    [ -f "$rc" ] && sed -i '/# added by gsp-surround install.sh/{N;d;}' "$rc"
  done
fi
id=$(pw_node_id "$NODE_MAIN"); [ -n "$id" ] && pw-cli destroy "$id" >/dev/null 2>&1
rm -rf "$GSP_DATA"
systemctl --user daemon-reload
systemctl --user restart pipewire pipewire-pulse wireplumber
if packaged; then
  echo "setup removed (settings kept in $GSP_CONF). Remove the app itself with your software manager."
else
  echo "removed (settings kept in $GSP_CONF)"
fi
