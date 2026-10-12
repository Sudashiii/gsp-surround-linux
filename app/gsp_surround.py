#!/usr/bin/env python3
"""GSP Surround: small GTK4/libadwaita app for virtual 7.1 surround and the EQ presets of
GSP-family headset dongles on Linux. All work is done by backend.py and scripts/; the tab pages
are in pages.py."""
from __future__ import annotations

import sys
import threading
from pathlib import Path
from typing import Callable

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, GLib, Gtk  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
import backend as be  # noqa: E402
import pages  # noqa: E402

APP_ID = "io.github.sudashiii.GspSurround"
ICON_APP = "gsp-surround"
ICON_DIR = be.ROOT / "data/icons"
POLL_SECONDS = 2                  # how often to look for the dongle
RECHECK_DELAY_SECONDS = 3         # the service needs a moment after a plug-in before nodes and links exist
PAGE_SOUND, PAGE_SETUP, PAGE_LOGS = "sound", "setup", "logs"
PRESET_LABELS = {pid: label for pid, label, _text in be.PRESETS}


def call_in_main(fn: Callable, *args) -> None:
    """Run fn(*args) on the GTK main loop. This is how worker threads hand results to the UI."""
    def run() -> bool:
        fn(*args)
        return GLib.SOURCE_REMOVE

    GLib.idle_add(run)


def register_icons() -> None:
    """Make the icons that ship with this copy of the app known to GTK (so a plain clone works too)
    and use the app icon for the windows.

    The directory is appended on purpose: for the same theme directory a later search path entry
    wins in GTK 4.14, so this copy's icons beat an older installed copy of the same name."""
    Gtk.IconTheme.get_for_display(Gdk.Display.get_default()).add_search_path(str(ICON_DIR))
    Gtk.Window.set_default_icon_name(ICON_APP)


class TabSwitcher(Gtk.Box):
    """Compact tabs for the header bar: one toggle button per page of a Gtk.Stack.

    Gtk.StackSwitcher and Adw.ViewSwitcher need about 400 px, more than a 480 px header has left
    once the window buttons are in (KDE puts three of them there); this needs about 225 px."""

    def __init__(self, stack: Gtk.Stack) -> None:
        super().__init__(homogeneous=True)
        self.add_css_class("linked")
        self._stack = stack
        self._buttons: dict[str, Gtk.ToggleButton] = {}
        stack_pages = stack.get_pages()
        first = None
        for i in range(stack_pages.get_n_items()):
            page = stack_pages.get_item(i)
            button = Gtk.ToggleButton(label=page.get_title(), group=first)
            button.connect("toggled", self._on_toggled, page.get_name())
            self.append(button)
            self._buttons[page.get_name()] = button
            first = first or button
        stack.connect("notify::visible-child-name", self._on_visible_child_changed)
        self._on_visible_child_changed(stack, None)

    def _on_toggled(self, button: Gtk.ToggleButton, name: str) -> None:
        if button.get_active():
            self._stack.set_visible_child_name(name)

    def _on_visible_child_changed(self, stack: Gtk.Stack, _pspec) -> None:
        button = self._buttons.get(stack.get_visible_child_name())
        if button:
            button.set_active(True)


class Window(Adw.ApplicationWindow):
    """Header with the tabs, the three pages, and the glue between pages and backend."""

    def __init__(self, app: Adw.Application) -> None:
        super().__init__(application=app, title="GSP Surround", default_width=480, default_height=520)
        self._busy = False
        self._ready: bool | None = None       # setup complete? None until the first check is in
        self._dongle_key: tuple | None = None  # (usb id, card) of the dongle seen last, to notice plug/unplug
        self._check_serial = 0                # numbers the setup checks, so a stale result can be dropped

        self.sound_page = pages.SoundPage()
        self.setup_page = pages.SetupPage()
        self.log_page = pages.LogPage()
        self._connect_pages()

        self._stack = Gtk.Stack(vexpand=True)
        for name, title, page in ((PAGE_SOUND, "Sound", self.sound_page),
                                  (PAGE_SETUP, "Setup", self.setup_page),
                                  (PAGE_LOGS, "Logs", self.log_page)):
            self._stack.add_titled(page, name, title)
        self._spinner = Gtk.Spinner()

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        content.append(self._build_header())
        content.append(self._stack)
        self._toasts = Adw.ToastOverlay(child=content)
        self.set_content(self._toasts)

        self._sync_controls()
        self.refresh()
        self._poll_id = GLib.timeout_add_seconds(POLL_SECONDS, self._poll_device)
        self.connect("close-request", self._on_close_request)

    # --- building -----------------------------------------------------------------------------
    def _build_header(self) -> Adw.HeaderBar:
        header = Adw.HeaderBar()
        recheck = Gtk.Button(icon_name="view-refresh-symbolic", tooltip_text="Re-check")
        recheck.update_property([Gtk.AccessibleProperty.LABEL], ["Re-check"])
        recheck.connect("clicked", lambda _button: self.refresh())
        header.pack_start(recheck)
        self._tabs = TabSwitcher(self._stack)
        header.set_title_widget(self._tabs)
        header.pack_end(self._spinner)
        return header

    def _connect_pages(self) -> None:
        self.sound_page.connect("surround-toggled", self._on_surround_toggled)
        self.sound_page.connect("preset-selected", self._on_preset_selected)
        self.sound_page.connect("headset-selected", self._on_headset_selected)
        self.sound_page.connect("setup-requested", self._on_setup_requested)
        self.setup_page.connect("install-requested", self._on_install_requested)
        self.setup_page.connect("apply-requested", self._on_apply_requested)
        self.setup_page.connect("uninstall-requested", self._on_uninstall_requested)

    # --- helpers ------------------------------------------------------------------------------
    def show_page(self, name: str) -> None:
        self._stack.set_visible_child_name(name)

    def _toast(self, title: str, *, log_button: bool = False) -> None:
        toast = Adw.Toast(title=title, timeout=5 if log_button else 3)
        if log_button:
            toast.set_button_label("Show log")
            toast.connect("button-clicked", lambda _toast: self.show_page(PAGE_LOGS))
        self._toasts.add_toast(toast)

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        self._spinner.set_spinning(busy)
        self._sync_controls()

    def _sync_controls(self) -> None:
        usable = bool(self._ready) and not self._busy
        self.sound_page.set_controls_enabled(usable)
        self.setup_page.set_actions_enabled(install=not self._busy, manage=usable)

    # --- background tasks ---------------------------------------------------------------------
    def run_task(self, label: str, fn: Callable[..., int], *args, show_log: bool = False) -> None:
        """Run a backend action in a thread; its output goes to the log, then everything is re-checked."""
        if self._busy:
            return
        self._set_busy(True)
        self.log_page.add_line(f"--- {label}")
        if show_log:
            self.show_page(PAGE_LOGS)

        def work() -> None:
            try:
                rc = fn(*args, on_line=lambda line: call_in_main(self.log_page.add_line, line))
            except Exception as exc:          # e.g. bash is missing: say why and keep the UI usable
                call_in_main(self.log_page.add_line, f"error: {exc}")
                rc = 1
            call_in_main(self._task_finished, label, rc)

        threading.Thread(target=work, daemon=True).start()

    def _task_finished(self, label: str, rc: int) -> None:
        self._set_busy(False)
        if rc == 0:
            self._toast(f"{label}: done")
        else:
            self._toast(f"{label} failed", log_button=self._stack.get_visible_child_name() != PAGE_LOGS)
        self.refresh()

    # --- state -> UI --------------------------------------------------------------------------
    def refresh(self) -> None:
        """Run the setup checks in a thread and look for the dongle."""
        self._check_serial += 1
        serial = self._check_serial

        def work() -> None:
            try:
                checks = be.run_checks()
            except Exception as exc:
                call_in_main(self.log_page.add_line, f"checking the setup failed: {exc}")
                return
            call_in_main(self._show_checks, serial, checks)

        threading.Thread(target=work, daemon=True).start()
        self._poll_device()

    def _show_checks(self, serial: int, checks: list[be.Check]) -> None:
        if serial != self._check_serial:
            return                            # a newer check is on its way
        self._ready = be.setup_complete(checks)
        self.setup_page.show_checks(checks)
        self.sound_page.show_state(be.saved_surround() == "on", be.saved_preset())
        self.sound_page.show_setup_hint(not self._ready)
        self._sync_controls()

    def _poll_device(self) -> bool:
        dongle = be.find_dongle()
        self.sound_page.show_dongle(dongle)
        self.sound_page.show_untested(be.untested_cards(), be.manual_device(),
                                      visible=not (dongle and dongle.known))
        key = (dongle.usbid, dongle.card) if dongle else None
        if key != self._dongle_key:
            self._dongle_key = key
            GLib.timeout_add_seconds(RECHECK_DELAY_SECONDS, self._recheck_once)
        return GLib.SOURCE_CONTINUE

    def _recheck_once(self) -> bool:
        self.refresh()
        return GLib.SOURCE_REMOVE

    # --- UI -> actions ------------------------------------------------------------------------
    def _on_surround_toggled(self, _page: pages.SoundPage, on: bool) -> None:
        self.run_task(f"Surround {'on' if on else 'off'}", be.set_surround, on)

    def _on_preset_selected(self, _page: pages.SoundPage, preset_id: str) -> None:
        self.run_task(f"Preset {PRESET_LABELS[preset_id]}", be.set_preset, preset_id)

    def _on_headset_selected(self, _page: pages.SoundPage, usbid: str) -> None:
        be.set_manual_device(usbid)
        if self._ready:
            self.run_task("Re-apply", be.apply)

    def _on_setup_requested(self, _page: pages.SoundPage) -> None:
        self.show_page(PAGE_SETUP)

    def _on_install_requested(self, _page: pages.SetupPage) -> None:
        self.run_task("Install", be.install, show_log=True)

    def _on_apply_requested(self, _page: pages.SetupPage) -> None:
        self.run_task("Re-apply", be.apply, show_log=True)

    def _on_uninstall_requested(self, _page: pages.SetupPage) -> None:
        dialog = Adw.MessageDialog(
            transient_for=self, heading="Uninstall virtual surround?",
            body="Removes the virtual 7.1 device, the background service, the device rule "
                 "and the downloaded filter file. Your preset settings are kept.")
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("remove", "Uninstall")
        dialog.set_response_appearance("remove", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_default_response("cancel")
        dialog.set_close_response("cancel")
        dialog.connect("response", self._on_uninstall_response)
        dialog.present()

    def _on_uninstall_response(self, _dialog: Adw.MessageDialog, response: str) -> None:
        if response == "remove":
            self.run_task("Uninstall", be.uninstall, show_log=True)

    def _on_close_request(self, _window: Gtk.Window) -> bool:
        if self._poll_id:
            GLib.source_remove(self._poll_id)
            self._poll_id = 0
        return False                          # go on and close


class App(Adw.Application):
    def __init__(self) -> None:
        # GTK derives the X11 window class (WM_CLASS) from the program name; the app id makes it match
        # StartupWMClass in data/gsp-surround.desktop, so the launcher entry and its icon are used.
        GLib.set_prgname(APP_ID)
        GLib.set_application_name("GSP Surround")
        super().__init__(application_id=APP_ID)

    def do_startup(self) -> None:
        Adw.Application.do_startup(self)
        register_icons()

    def do_activate(self) -> None:
        (self.get_active_window() or Window(self)).present()


if __name__ == "__main__":
    sys.exit(App().run(sys.argv[:1]))
