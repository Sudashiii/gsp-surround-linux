"""The three tab pages of the GSP Surround window: Sound, Setup and Logs.

The pages only show state and emit signals when the user changes something. Running the backend
actions is the window's job (gsp_surround.py).
"""
from __future__ import annotations

import contextlib
from typing import Iterable, Iterator

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, GLib, GObject, Gtk  # noqa: E402

import backend as be  # noqa: E402

# Icon themes differ (Breeze has no audio-headset-symbolic), so the headset glyph ships with the app:
# data/icons/hicolor/symbolic/apps. The log icon exists in both Adwaita and Breeze.
ICON_HEADSET = "gsp-surround-headset-symbolic"
ICON_LOG = "text-x-generic-symbolic"

# result of a setup check (True / False / None = not applicable) -> (icon, style class, accessible label)
_STATUS = {
    True: ("emblem-ok-symbolic", "success", "OK"),
    False: ("dialog-warning-symbolic", "warning", "Needs attention"),
    None: ("list-remove-symbolic", "dim-label", "Not applicable"),
}


def _signal(*arg_types: type) -> tuple:
    """Entry for __gsignals__: a signal without return value and with the given argument types."""
    return (GObject.SignalFlags.RUN_FIRST, None, arg_types)


def _flat_button(icon_name: str, label: str) -> Gtk.Button:
    """A flat button with icon and text, for action bars."""
    button = Gtk.Button(child=Adw.ButtonContent(icon_name=icon_name, label=label))
    button.add_css_class("flat")
    return button


class SoundPage(Adw.PreferencesPage):
    """Headset status, virtual surround switch and EQ preset."""

    __gsignals__ = {
        "surround-toggled": _signal(bool),
        "preset-selected": _signal(str),          # preset id
        "headset-selected": _signal(str),         # "vid:pid" of an untested headset, "" for none
        "setup-requested": _signal(),
    }

    def __init__(self) -> None:
        super().__init__()
        self._quiet = False                        # True while state is shown, not chosen: no signals
        self._untested_ids: list[str] | None = None
        self._preset_texts = {pid: text for pid, _label, text in be.PRESETS}
        self._build_setup_hint()
        self._build_headset_group()
        self._build_surround_group()
        self._build_preset_group()

    # --- building -----------------------------------------------------------------------------
    def _build_setup_hint(self) -> None:
        """Why the controls below are greyed out; only shown while setup is known to be incomplete."""
        self._hint_group = Adw.PreferencesGroup(visible=False)
        row = Adw.ActionRow(title="Setup is not finished", subtitle="Needed for surround and presets")
        button = Gtk.Button(label="Open Setup", valign=Gtk.Align.CENTER)
        button.connect("clicked", self._on_open_setup_clicked)
        row.add_suffix(button)
        self._hint_group.add(row)
        self.add(self._hint_group)

    def _build_headset_group(self) -> None:
        group = Adw.PreferencesGroup(title="Headset")
        self._dongle_row = Adw.ActionRow(title="Looking for the dongle…", use_markup=False)
        self._dongle_row.add_prefix(Gtk.Image(icon_name=ICON_HEADSET, pixel_size=32))
        group.add(self._dongle_row)

        self._untested_model = Gtk.StringList()
        self._untested_row = Adw.ComboRow(
            title="Use an untested USB headset", model=self._untested_model, visible=False,
            subtitle="Only if your GSP dongle is not detected. Please report it if it works.")
        self._untested_row.connect("notify::selected", self._on_untested_selected)
        group.add(self._untested_row)
        self.add(group)

    def _build_surround_group(self) -> None:
        self._surround_group = Adw.PreferencesGroup()
        self._surround_switch = Gtk.Switch(valign=Gtk.Align.CENTER)
        self._surround_switch.update_property([Gtk.AccessibleProperty.LABEL], ["Virtual 7.1 surround"])
        self._surround_switch.connect("notify::active", self._on_surround_active)
        row = Adw.ActionRow(title="Virtual 7.1 surround", subtitle="Off: plain stereo straight to the headset",
                            activatable_widget=self._surround_switch)
        row.add_suffix(self._surround_switch)
        self._surround_group.add(row)
        self.add(self._surround_group)

    def _build_preset_group(self) -> None:
        self._preset_group = Adw.PreferencesGroup(title="Preset")
        box = Gtk.Box(homogeneous=True, margin_top=4)
        box.add_css_class("linked")
        self._preset_buttons: dict[str, Gtk.ToggleButton] = {}
        first = None
        for preset_id, label, _text in be.PRESETS:
            button = Gtk.ToggleButton(label=label, group=first)
            button.connect("toggled", self._on_preset_toggled, preset_id)
            box.append(button)
            self._preset_buttons[preset_id] = button
            first = first or button
        self._preset_group.add(box)
        self.add(self._preset_group)

    # --- state -> widgets -----------------------------------------------------------------------
    @contextlib.contextmanager
    def _programmatic(self) -> Iterator[None]:
        """While active, widget changes are not reported as user choices."""
        self._quiet = True
        try:
            yield
        finally:
            self._quiet = False

    def show_dongle(self, dongle: be.Dongle | None) -> None:
        if dongle:
            self._dongle_row.set_title(dongle.name)
            self._dongle_row.set_subtitle(f"USB {dongle.usbid}" + ("" if dongle.known else " · untested device"))
        else:
            self._dongle_row.set_title("No GSP dongle connected")
            self._dongle_row.set_subtitle("Plug in the USB dongle of your headset")

    def show_untested(self, cards: list[tuple[str, str]], selected: str, visible: bool) -> None:
        """Offer `cards` ([(vid:pid, name)]) to choose from. `selected` (the saved choice) is only
        shown when the list changes, so polling does not undo what the user is picking."""
        ids = [usbid for usbid, _name in cards]
        self._untested_row.set_visible(visible and bool(ids))
        if ids == self._untested_ids:
            return
        self._untested_ids = ids
        with self._programmatic():
            self._untested_model.splice(0, self._untested_model.get_n_items(),
                                        ["None"] + [f"{name} ({usbid})" for usbid, name in cards])
            self._untested_row.set_selected(ids.index(selected) + 1 if selected in ids else 0)

    def show_state(self, surround: bool, preset: str) -> None:
        """Show the saved settings."""
        with self._programmatic():
            self._surround_switch.set_active(surround)
            if preset in self._preset_buttons:
                self._preset_buttons[preset].set_active(True)

    def set_controls_enabled(self, enabled: bool) -> None:
        self._surround_group.set_sensitive(enabled)
        self._preset_group.set_sensitive(enabled)

    def show_setup_hint(self, visible: bool) -> None:
        self._hint_group.set_visible(visible)

    # --- widgets -> signals ---------------------------------------------------------------------
    def _on_open_setup_clicked(self, _button: Gtk.Button) -> None:
        self.emit("setup-requested")

    def _on_surround_active(self, switch: Gtk.Switch, _pspec: GObject.ParamSpec) -> None:
        if not self._quiet:
            self.emit("surround-toggled", switch.get_active())

    def _on_preset_toggled(self, button: Gtk.ToggleButton, preset_id: str) -> None:
        if not button.get_active():
            return                                 # the button that was switched off
        self._preset_group.set_description(self._preset_texts[preset_id])
        if not self._quiet:
            self.emit("preset-selected", preset_id)

    def _on_untested_selected(self, row: Adw.ComboRow, _pspec: GObject.ParamSpec) -> None:
        if self._quiet or self._untested_ids is None:
            return
        index = row.get_selected()                 # 0 is "None"
        chosen = self._untested_ids[index - 1] if 0 < index <= len(self._untested_ids) else ""
        self.emit("headset-selected", chosen)


class SetupPage(Gtk.Box):
    """What virtual surround needs on this system, with the buttons to set it up or remove it."""

    __gsignals__ = {
        "install-requested": _signal(),
        "apply-requested": _signal(),
        "uninstall-requested": _signal(),
    }

    def __init__(self) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self._rows: dict[str, tuple[Adw.ActionRow, Gtk.Image]] = {}
        self._checks = Adw.PreferencesGroup(title="Requirements", description="Checking…")
        manual = Gtk.LinkButton(uri=be.MANUAL_URL, label="Prefer to do it yourself? Manual installation")
        manual.set_margin_top(6)
        links = Adw.PreferencesGroup()
        links.add(manual)
        page = Adw.PreferencesPage(vexpand=True)    # scrolls; the action bar below stays in view
        page.add(self._checks)
        page.add(links)
        self.append(page)
        self.append(self._build_action_bar())

    def _build_action_bar(self) -> Gtk.ActionBar:
        self._install_button = Gtk.Button(label="Install everything")
        self._install_button.add_css_class("suggested-action")
        self._apply_button = Gtk.Button(label="Re-apply")
        self._uninstall_button = Gtk.Button(label="Uninstall")
        self._uninstall_button.add_css_class("destructive-action")
        buttons = Gtk.Box(spacing=8)
        for button, signal in ((self._install_button, "install-requested"),
                               (self._apply_button, "apply-requested"),
                               (self._uninstall_button, "uninstall-requested")):
            button.connect("clicked", self._on_button_clicked, signal)
            buttons.append(button)
        bar = Gtk.ActionBar()
        bar.set_center_widget(buttons)
        return bar

    def _on_button_clicked(self, _button: Gtk.Button, signal: str) -> None:
        self.emit(signal)

    def show_checks(self, checks: Iterable[be.Check]) -> None:
        checks = list(checks)
        for check in checks:
            row, icon = self._rows.get(check.key) or self._add_row(check)
            row.set_subtitle(check.hint)
            icon_name, style, description = _STATUS[None if check.ok is None else bool(check.ok)]
            icon.set_from_icon_name(icon_name)
            icon.update_property([Gtk.AccessibleProperty.LABEL], [description])
            for _icon_name, other_style, _description in _STATUS.values():
                icon.remove_css_class(other_style)
            icon.add_css_class(style)
        all_ok = all(check.ok is not False for check in checks)
        self._install_button.set_label("Reinstall" if all_ok else "Install everything")
        self._checks.set_description(
            "Everything is set up" if all_ok else
            "Something is missing – “Install everything” sets it up (asks for your password once)")

    def _add_row(self, check: be.Check) -> tuple[Adw.ActionRow, Gtk.Image]:
        row = Adw.ActionRow(title=check.title, use_markup=False)
        icon = Gtk.Image()
        row.add_prefix(icon)
        self._checks.add(row)
        self._rows[check.key] = (row, icon)
        return row, icon

    def set_actions_enabled(self, *, install: bool, manage: bool) -> None:
        """Install needs no finished setup; Re-apply and Uninstall do."""
        self._install_button.set_sensitive(install)
        self._apply_button.set_sensitive(manage)
        self._uninstall_button.set_sensitive(manage)


class LogPage(Gtk.Box):
    """Output of the install / apply / preset scripts."""

    def __init__(self) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self._buffer = Gtk.TextBuffer()
        self._buffer.connect("changed", self._on_changed)
        view = Gtk.TextView(buffer=self._buffer, editable=False, cursor_visible=False, monospace=True,
                            wrap_mode=Gtk.WrapMode.WORD_CHAR, top_margin=8, bottom_margin=8,
                            left_margin=12, right_margin=12)
        view.connect("map", self._on_map)
        scroller = Gtk.ScrolledWindow(child=view)
        self._scroll = scroller.get_vadjustment()
        empty = Adw.StatusPage(icon_name=ICON_LOG, title="No log yet",
                               description="Output from Install, Re-apply and other actions shows up here.")
        empty.add_css_class("compact")
        self._stack = Gtk.Stack(vexpand=True)
        self._stack.add_named(empty, "empty")
        self._stack.add_named(scroller, "log")
        self.append(self._stack)
        self.append(self._build_action_bar())
        self._on_changed(self._buffer)

    def _build_action_bar(self) -> Gtk.ActionBar:
        bar = Gtk.ActionBar()
        self._copy_button = _flat_button("edit-copy-symbolic", "Copy")
        self._copy_button.connect("clicked", self._on_copy)
        self._clear_button = _flat_button("edit-clear-all-symbolic", "Clear")
        self._clear_button.connect("clicked", self._on_clear)
        bar.pack_end(self._copy_button)
        bar.pack_end(self._clear_button)
        return bar

    @property
    def text(self) -> str:
        return self._buffer.get_text(self._buffer.get_start_iter(), self._buffer.get_end_iter(), False)

    def add_line(self, line: str) -> None:
        """Add a line at the end and scroll to it."""
        self._buffer.insert(self._buffer.get_end_iter(), line + "\n")
        self._scroll_to_end()

    def clear(self) -> None:
        self._buffer.set_text("")

    def _scroll_to_end(self) -> None:
        # The end is only known once the text is laid out, which happens before idle callbacks run
        # (wrapped lines take a while); a view that is hidden lays out when it is shown.
        GLib.idle_add(self._jump_to_end)

    def _jump_to_end(self) -> bool:
        self._scroll.set_value(self._scroll.get_upper() - self._scroll.get_page_size())
        return GLib.SOURCE_REMOVE

    def _on_map(self, _view: Gtk.TextView) -> None:
        self._scroll_to_end()                      # output that came in while the tab was hidden

    def _on_changed(self, buffer: Gtk.TextBuffer) -> None:
        has_text = buffer.get_char_count() > 0
        self._stack.set_visible_child_name("log" if has_text else "empty")
        self._copy_button.set_sensitive(has_text)
        self._clear_button.set_sensitive(has_text)

    def _on_copy(self, _button: Gtk.Button) -> None:
        self.get_clipboard().set(self.text)

    def _on_clear(self, _button: Gtk.Button) -> None:
        self.clear()
