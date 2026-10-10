#!/usr/bin/env python3
"""GSP Surround: small GTK4/libadwaita app for virtual 7.1 surround and the EQ presets of
GSP-family headset dongles on Linux. All work is done by backend.py and scripts/."""
import sys
import threading
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, GLib, Gtk  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
import backend as be  # noqa: E402

APP_ID = "io.github.sudashiii.GspSurround"
ICON_OK, ICON_BAD, ICON_NA = "emblem-ok-symbolic", "dialog-warning-symbolic", "list-remove-symbolic"


class Window(Adw.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="GSP Surround")
        self.set_default_size(480, 820)
        self.busy = False
        self.updating = False          # True while the UI is set from saved state (no actions)
        self.ready = False
        self.dongle_key = None
        self.untested_ids = None

        header = Adw.HeaderBar()
        recheck = Gtk.Button(icon_name="view-refresh-symbolic", tooltip_text="Re-check")
        recheck.connect("clicked", lambda *_: self.refresh())
        header.pack_start(recheck)
        self.spinner = Gtk.Spinner()
        header.pack_end(self.spinner)

        page = Adw.PreferencesPage()
        page.set_vexpand(True)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        box.append(header)
        box.append(page)
        self.toasts = Adw.ToastOverlay()
        self.toasts.set_child(box)
        self.set_content(self.toasts)

        # --- headset ---------------------------------------------------------------------------
        g = Adw.PreferencesGroup(title="Headset")
        self.dev_row = Adw.ActionRow(title="Looking for the dongle…")
        self.dev_row.add_prefix(Gtk.Image(icon_name="audio-headphones-symbolic", pixel_size=32))
        g.add(self.dev_row)
        self.untested_row = Adw.ComboRow(title="Use an untested USB headset",
                                         subtitle="Only if your GSP dongle is not detected. Please report it if it works.")
        self.untested_model = Gtk.StringList()
        self.untested_row.set_model(self.untested_model)
        self.untested_row.connect("notify::selected", self.on_untested)
        g.add(self.untested_row)
        page.add(g)

        # --- surround + presets -----------------------------------------------------------------
        self.sound_group = Adw.PreferencesGroup(title="Sound")
        row = Adw.ActionRow(title="Virtual 7.1 surround",
                            subtitle="Off: plain stereo straight to the headset")
        self.surround_sw = Gtk.Switch(valign=Gtk.Align.CENTER)
        self.surround_sw.connect("notify::active", self.on_surround)
        row.add_suffix(self.surround_sw)
        row.set_activatable_widget(self.surround_sw)
        self.sound_group.add(row)
        page.add(self.sound_group)

        self.preset_group = Adw.PreferencesGroup(title="Preset")
        bbox = Gtk.Box(spacing=0, homogeneous=True, margin_top=4)
        bbox.add_css_class("linked")
        self.preset_btns = {}
        first = None
        for pid, label, _ in be.PRESETS:
            b = Gtk.ToggleButton(label=label)
            if first:
                b.set_group(first)
            first = first or b
            b.connect("toggled", self.on_preset, pid)
            bbox.append(b)
            self.preset_btns[pid] = b
        self.preset_group.add(bbox)
        page.add(self.preset_group)

        # --- setup ------------------------------------------------------------------------------
        self.setup_group = Adw.PreferencesGroup(title="Setup",
                                                description="What virtual surround needs on this system")
        self.check_rows = {}
        page.add(self.setup_group)

        g = Adw.PreferencesGroup()
        btns = Gtk.Box(spacing=8, halign=Gtk.Align.CENTER)
        self.install_btn = Gtk.Button(label="Install everything")
        self.install_btn.add_css_class("suggested-action")
        self.install_btn.add_css_class("pill")
        self.install_btn.connect("clicked", lambda *_: self.run_bg("Install", be.install))
        self.apply_btn = Gtk.Button(label="Re-apply")
        self.apply_btn.add_css_class("pill")
        self.apply_btn.connect("clicked", lambda *_: self.run_bg("Re-apply", be.apply))
        self.uninstall_btn = Gtk.Button(label="Uninstall")
        self.uninstall_btn.add_css_class("destructive-action")
        self.uninstall_btn.add_css_class("pill")
        self.uninstall_btn.connect("clicked", self.on_uninstall)
        for b in (self.install_btn, self.apply_btn, self.uninstall_btn):
            btns.append(b)
        g.add(btns)
        manual = Gtk.LinkButton(uri=be.MANUAL_URL, label="Prefer to do it yourself? Manual installation")
        manual.set_margin_top(6)
        g.add(manual)

        self.log_buf = Gtk.TextBuffer()
        view = Gtk.TextView(buffer=self.log_buf, editable=False, monospace=True,
                            wrap_mode=Gtk.WrapMode.WORD_CHAR, top_margin=6, bottom_margin=6,
                            left_margin=6, right_margin=6)
        self.log_scroll = Gtk.ScrolledWindow(min_content_height=200, child=view)
        self.log_exp = Gtk.Expander(label="Log", child=self.log_scroll, margin_top=6)
        g.add(self.log_exp)
        page.add(g)

        self.refresh()
        GLib.timeout_add_seconds(2, self.poll_device)

    # --- helpers ------------------------------------------------------------------------------
    def toast(self, text):
        self.toasts.add_toast(Adw.Toast(title=text, timeout=3))

    def log(self, line):
        self.log_buf.insert(self.log_buf.get_end_iter(), line + "\n")
        adj = self.log_scroll.get_vadjustment()
        GLib.idle_add(lambda: adj.set_value(adj.get_upper()))
        return False

    def set_busy(self, busy):
        self.busy = busy
        self.spinner.set_spinning(busy)
        self.update_sensitivity()

    def update_sensitivity(self):
        on = self.ready and not self.busy
        self.sound_group.set_sensitive(on)
        self.preset_group.set_sensitive(on)
        self.install_btn.set_sensitive(not self.busy)
        self.apply_btn.set_sensitive(on)
        self.uninstall_btn.set_sensitive(on)

    def run_bg(self, label, fn, *args, quiet=False):
        """Run a backend action in a thread; output goes to the log, then re-check."""
        if self.busy:
            return
        self.set_busy(True)
        self.log(f"--- {label}")
        if not quiet:
            self.log_exp.set_expanded(True)

        def work():
            rc = fn(*args, on_line=lambda l: GLib.idle_add(self.log, l))
            GLib.idle_add(self.finished, label, rc)

        threading.Thread(target=work, daemon=True).start()

    def finished(self, label, rc):
        self.set_busy(False)
        self.toast(f"{label}: done" if rc == 0 else f"{label} failed – see the log")
        if rc != 0:
            self.log_exp.set_expanded(True)
        self.refresh()
        return False

    # --- state -> UI --------------------------------------------------------------------------
    def refresh(self):
        def work():
            checks = be.run_checks()
            GLib.idle_add(self.show_checks, checks)

        threading.Thread(target=work, daemon=True).start()
        self.poll_device()

    def show_checks(self, checks):
        for c in checks:
            if c.key not in self.check_rows:
                row = Adw.ActionRow(title=c.title)
                icon = Gtk.Image()
                row.add_prefix(icon)
                self.setup_group.add(row)
                self.check_rows[c.key] = (row, icon)
            row, icon = self.check_rows[c.key]
            row.set_subtitle(GLib.markup_escape_text(c.hint or ""))
            icon.set_from_icon_name(ICON_OK if c.ok else ICON_NA if c.ok is None else ICON_BAD)
            for cls in ("success", "warning", "dim-label"):
                icon.remove_css_class(cls)
            icon.add_css_class("success" if c.ok else "dim-label" if c.ok is None else "warning")
        self.ready = be.setup_complete(checks)
        all_ok = all(c.ok is not False for c in checks)
        self.install_btn.set_label("Reinstall" if all_ok else "Install everything")
        self.setup_group.set_description("Everything is set up" if all_ok else
                                         "Something is missing – “Install everything” sets it up "
                                         "(asks for your password once)")
        self.updating = True
        self.surround_sw.set_active(be.saved_surround() == "on")
        preset = be.saved_preset()
        if preset in self.preset_btns:
            self.preset_btns[preset].set_active(True)
            self.preset_group.set_description(dict((p, d) for p, _, d in be.PRESETS)[preset])
        self.updating = False
        self.update_sensitivity()
        return False

    def poll_device(self):
        dongle = be.find_dongle()
        key = (dongle.usbid, dongle.card) if dongle else None
        if dongle:
            self.dev_row.set_title(GLib.markup_escape_text(dongle.name))
            self.dev_row.set_subtitle(f"USB {dongle.usbid}" + ("" if dongle.known else " · untested device"))
        else:
            self.dev_row.set_title("No GSP dongle connected")
            self.dev_row.set_subtitle("Plug in the USB dongle of your headset")
        known = {d.usbid for d in be.load_devices()}
        others = [(u, n) for _, u, n in be.usb_cards() if u not in known]
        ids = [u for u, _ in others]
        self.untested_row.set_visible(bool(ids) and not (dongle and dongle.known))
        if ids != self.untested_ids:
            self.updating = True
            self.untested_ids = ids
            self.untested_model.splice(0, self.untested_model.get_n_items(),
                                       ["None"] + [f"{n} ({u})" for u, n in others])
            manual = be.manual_device()
            self.untested_row.set_selected(ids.index(manual) + 1 if manual in ids else 0)
            self.updating = False
        if key != self.dongle_key:
            self.dongle_key = key
            self.refresh_later()
        return True

    def refresh_later(self):
        # the service needs a moment after a plug-in before nodes and links exist
        GLib.timeout_add_seconds(3, lambda: (self.refresh(), False)[1])

    # --- UI -> actions ------------------------------------------------------------------------
    def on_preset(self, btn, pid):
        if not btn.get_active():
            return
        self.preset_group.set_description(dict((p, d) for p, _, d in be.PRESETS)[pid])
        if not self.updating:
            self.run_bg(f"Preset {btn.get_label()}", be.set_preset, pid, quiet=True)

    def on_surround(self, sw, _):
        if not self.updating:
            on = sw.get_active()
            self.run_bg(f"Surround {'on' if on else 'off'}", be.set_surround, on, quiet=True)

    def on_untested(self, row, _):
        if self.updating:
            return
        i = row.get_selected()
        be.set_manual_device(self.untested_ids[i - 1] if 0 < i <= len(self.untested_ids) else "")
        if self.ready:
            self.run_bg("Re-apply", be.apply)

    def on_uninstall(self, *_):
        d = Adw.MessageDialog(transient_for=self, heading="Uninstall virtual surround?",
                              body="Removes the virtual 7.1 device, the background service, the device rule "
                                   "and the downloaded filter file. Your preset settings are kept.")
        d.add_response("cancel", "Cancel")
        d.add_response("remove", "Uninstall")
        d.set_response_appearance("remove", Adw.ResponseAppearance.DESTRUCTIVE)
        d.connect("response", lambda _d, r: r == "remove" and self.run_bg("Uninstall", be.uninstall))
        d.present()


class App(Adw.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID)

    def do_activate(self):
        win = self.get_active_window() or Window(self)
        win.present()


if __name__ == "__main__":
    sys.exit(App().run(sys.argv[:1]))
