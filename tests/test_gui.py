"""Tests for the GTK pages and the window, against a fake backend (no hardware, nothing installed).
They need GTK 4, libadwaita and a display (a desktop session, or e.g. `xvfb-run`) and are skipped
without; the icon file checks always run.
  python3 -m unittest discover tests
"""
import sys
import time
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))

try:
    import gi

    gi.require_version("Gtk", "4.0")
    gi.require_version("Adw", "1")
    from gi.repository import Adw, Gdk, GLib, Gtk

    HAVE_GUI = bool(Gtk.init_check())
    if HAVE_GUI:
        Adw.init()
except (ImportError, ValueError):
    HAVE_GUI = False

if HAVE_GUI:
    import backend as be
    import gsp_surround as gs
    import pages

ICONS = ROOT / "data/icons/hicolor"
GOOD = [be.Check(k, k, True) for k in ("tools", "ir", "filter", "service")] if HAVE_GUI else []


def descendants(widget):
    """The widget and everything below it."""
    yield widget
    child = widget.get_first_child()
    while child:
        yield from descendants(child)
        child = child.get_next_sibling()


def pump(until=None, timeout=5.0):
    """Run the GTK main loop: just what is pending, or until `until()` is true (or the timeout)."""
    context = GLib.MainContext.default()
    deadline = time.monotonic() + timeout
    while True:
        while context.pending():
            context.iteration(False)
        if until is None or until() or time.monotonic() > deadline:
            return
        time.sleep(0.005)


class IconFiles(unittest.TestCase):
    def test_well_formed(self):
        for path in ICONS.glob("**/*.svg"):
            ET.parse(path)

    def test_symbolic_icon_is_fill_only(self):
        # GTK recolours symbolic icons through `fill`; a stroke would stay black in the dark theme
        for path in ICONS.glob("symbolic/**/*-symbolic.svg"):
            for element in ET.parse(path).iter():
                self.assertNotIn("stroke", element.attrib, f"{path.name}: <{element.tag}> has a stroke")

    def test_icons_exist(self):
        self.assertTrue((ICONS / "scalable/apps/gsp-surround.svg").is_file())
        self.assertTrue((ICONS / "symbolic/apps/gsp-surround-headset-symbolic.svg").is_file())


@unittest.skipUnless(HAVE_GUI, "needs GTK 4, libadwaita and a display")
class SoundPageTest(unittest.TestCase):
    def setUp(self):
        self.page = pages.SoundPage()
        self.events = []
        self.page.connect("surround-toggled", lambda _p, on: self.events.append(("surround", on)))
        self.page.connect("preset-selected", lambda _p, pid: self.events.append(("preset", pid)))
        self.page.connect("headset-selected", lambda _p, usbid: self.events.append(("headset", usbid)))
        self.page.connect("setup-requested", lambda _p: self.events.append(("setup",)))

    def test_shown_state_is_not_a_user_choice(self):
        self.page.show_state(False, "music")
        self.assertEqual(self.events, [])
        self.assertFalse(self.page._surround_switch.get_active())
        self.assertTrue(self.page._preset_buttons["music"].get_active())
        self.assertIn("Music EQ", self.page._preset_group.get_description())

    def test_user_changes_are_signalled_after_state_was_shown(self):
        self.page.show_state(False, "music")
        self.page._surround_switch.set_active(True)
        self.page._preset_buttons["esport"].set_active(True)
        self.assertEqual(self.events, [("surround", True), ("preset", "esport")])

    def test_unknown_saved_preset_is_ignored(self):
        self.page.show_state(True, "no-such-preset")
        self.assertEqual(self.events, [])

    def test_dongle_texts(self):
        self.page.show_dongle(be.Dongle(2, "1395:005d", "Sennheiser GSP 350", True, True))
        self.assertEqual(self.page._dongle_row.get_title(), "Sennheiser GSP 350")
        self.assertEqual(self.page._dongle_row.get_subtitle(), "USB 1395:005d")
        self.page.show_dongle(be.Dongle(3, "abcd:1234", "Some Headset", False, False))
        self.assertIn("untested device", self.page._dongle_row.get_subtitle())
        self.page.show_dongle(None)
        self.assertEqual(self.page._dongle_row.get_title(), "No GSP dongle connected")

    def test_untested_headsets(self):
        cards = [("abcd:1234", "Some Headset"), ("dead:beef", "Other")]
        self.page.show_untested(cards, "dead:beef", visible=True)
        row, model = self.page._untested_row, self.page._untested_model
        self.assertTrue(row.get_visible())
        self.assertEqual([model.get_string(i) for i in range(model.get_n_items())],
                         ["None", "Some Headset (abcd:1234)", "Other (dead:beef)"])
        self.assertEqual(row.get_selected(), 2)
        self.assertEqual(self.events, [])               # showing the saved choice is silent
        row.set_selected(1)
        row.set_selected(0)
        self.assertEqual(self.events, [("headset", "abcd:1234"), ("headset", "")])

    def test_untested_row_visibility(self):
        self.page.show_untested([("abcd:1234", "Some Headset")], "", visible=False)
        self.assertFalse(self.page._untested_row.get_visible())      # a known dongle is connected
        self.page.show_untested([], "", visible=True)
        self.assertFalse(self.page._untested_row.get_visible())      # nothing to choose from

    def test_polling_does_not_undo_the_users_pick(self):
        cards = [("abcd:1234", "Some Headset")]
        self.page.show_untested(cards, "", visible=True)
        self.page._untested_row.set_selected(1)
        self.page.show_untested(cards, "", visible=True)             # same list again, saved choice not yet in
        self.assertEqual(self.page._untested_row.get_selected(), 1)

    def test_controls_and_hint(self):
        self.page.set_controls_enabled(False)
        self.assertFalse(self.page._surround_group.get_sensitive())
        self.assertFalse(self.page._preset_group.get_sensitive())
        self.page.set_controls_enabled(True)
        self.assertTrue(self.page._preset_group.get_sensitive())
        self.assertFalse(self.page._hint_group.get_visible())
        self.page.show_setup_hint(True)
        self.assertTrue(self.page._hint_group.get_visible())

    def test_open_setup_button_signals(self):
        button = next(w for w in descendants(self.page) if isinstance(w, Gtk.Button) and w.get_label() == "Open Setup")
        button.emit("clicked")
        self.assertEqual(self.events, [("setup",)])


@unittest.skipUnless(HAVE_GUI, "needs GTK 4, libadwaita and a display")
class SetupPageTest(unittest.TestCase):
    def setUp(self):
        self.page = pages.SetupPage()

    def test_rows_are_created_once_and_updated(self):
        self.page.show_checks([be.Check("tools", "PipeWire tools", True, "pw-cli"),
                               be.Check("hid", "EQ control", None, "dongle not connected")])
        self.assertEqual(set(self.page._rows), {"tools", "hid"})
        row, icon = self.page._rows["tools"]
        self.assertEqual(row.get_title(), "PipeWire tools")
        self.assertEqual(row.get_subtitle(), "pw-cli")
        self.assertTrue(icon.has_css_class("success"))
        self.page.show_checks([be.Check("tools", "PipeWire tools", False, "missing: pw-cli"),
                               be.Check("hid", "EQ control", None, "")])
        self.assertIs(self.page._rows["tools"][0], row)
        self.assertEqual(row.get_subtitle(), "missing: pw-cli")
        self.assertTrue(icon.has_css_class("warning"))
        self.assertFalse(icon.has_css_class("success"))
        self.assertTrue(self.page._rows["hid"][1].has_css_class("dim-label"))

    def test_text_is_not_parsed_as_markup(self):
        self.page.show_checks([be.Check("x", "A & B", False, "<b>1 & 2</b>")])
        row, _icon = self.page._rows["x"]
        self.assertFalse(row.get_use_markup())

    def test_summary_and_install_label(self):
        self.page.show_checks([be.Check("a", "A", True), be.Check("b", "B", None)])
        self.assertEqual(self.page._install_button.get_label(), "Reinstall")
        self.assertEqual(self.page._checks.get_description(), "Everything is set up")
        self.page.show_checks([be.Check("a", "A", True), be.Check("b", "B", False)])
        self.assertEqual(self.page._install_button.get_label(), "Install everything")
        self.assertIn("Something is missing", self.page._checks.get_description())

    def test_buttons_signal_and_can_be_disabled(self):
        got = []
        for name in ("install-requested", "apply-requested", "uninstall-requested"):
            self.page.connect(name, lambda _p, name=name: got.append(name))
        for button in (self.page._install_button, self.page._apply_button, self.page._uninstall_button):
            button.emit("clicked")
        self.assertEqual(got, ["install-requested", "apply-requested", "uninstall-requested"])
        self.page.set_actions_enabled(install=True, manage=False)
        self.assertTrue(self.page._install_button.get_sensitive())
        self.assertFalse(self.page._apply_button.get_sensitive())
        self.assertFalse(self.page._uninstall_button.get_sensitive())


@unittest.skipUnless(HAVE_GUI, "needs GTK 4, libadwaita and a display")
class LogPageTest(unittest.TestCase):
    def setUp(self):
        self.page = pages.LogPage()

    def test_empty_state_and_buttons(self):
        self.assertEqual(self.page._stack.get_visible_child_name(), "empty")
        self.assertFalse(self.page._copy_button.get_sensitive())
        self.assertFalse(self.page._clear_button.get_sensitive())

    def test_new_lines_are_scrolled_to(self):
        with mock.patch.object(self.page, "_scroll_to_end") as scroll_to_end:
            self.page.add_line("one")
            self.page.add_line("two")
        self.assertEqual(scroll_to_end.call_count, 2)

    def test_add_and_clear(self):
        self.page.add_line("--- Install")
        self.page.add_line("done")
        self.assertEqual(self.page.text, "--- Install\ndone\n")
        self.assertEqual(self.page._stack.get_visible_child_name(), "log")
        self.assertTrue(self.page._copy_button.get_sensitive())
        self.page._clear_button.emit("clicked")
        self.assertEqual(self.page.text, "")
        self.assertEqual(self.page._stack.get_visible_child_name(), "empty")
        self.assertFalse(self.page._clear_button.get_sensitive())


@unittest.skipUnless(HAVE_GUI, "needs GTK 4, libadwaita and a display")
class WindowTest(unittest.TestCase):
    app = None

    @classmethod
    def setUpClass(cls):
        cls.app = gs.App()
        cls.app.register(None)                      # runs do_startup: icons, default icon

    def setUp(self):
        self.checks = list(GOOD)
        patcher = mock.patch.multiple(
            be, run_checks=mock.Mock(side_effect=lambda: self.checks), find_dongle=mock.Mock(return_value=None),
            untested_cards=mock.Mock(return_value=[]), manual_device=mock.Mock(return_value=""),
            saved_surround=mock.Mock(return_value="on"), saved_preset=mock.Mock(return_value="game"),
            set_manual_device=mock.Mock())
        patcher.start()
        self.addCleanup(patcher.stop)
        self.win = gs.Window(self.app)
        self.addCleanup(self.close_window)

    def close_window(self):
        pump(until=lambda: not self.win._busy)
        pump(until=lambda: False, timeout=0.2)                       # let checks that are still running land
        self.win.close()
        self.win.destroy()
        pump()

    def settle(self):
        """Wait for the first setup check to arrive."""
        pump(until=lambda: self.win._ready is not None)

    def test_icons_are_found(self):
        theme = Gtk.IconTheme.get_for_display(Gdk.Display.get_default())
        self.assertTrue(theme.has_icon(pages.ICON_HEADSET))
        self.assertTrue(theme.has_icon(gs.ICON_APP))

    def test_tabs(self):
        stack = self.win._stack
        self.assertEqual([(page.get_name(), page.get_title()) for page in stack.get_pages()],
                         [("sound", "Sound"), ("setup", "Setup"), ("logs", "Logs")])
        self.assertEqual(stack.get_visible_child_name(), "sound")
        buttons = self.win._tabs._buttons
        self.assertTrue(buttons["sound"].get_active())
        buttons["setup"].set_active(True)                           # the user clicks a tab
        self.assertEqual(stack.get_visible_child_name(), "setup")
        self.win.show_page("logs")                                  # the app switches the tab
        self.assertTrue(buttons["logs"].get_active())
        self.assertFalse(buttons["setup"].get_active())

    def test_window_is_smaller_than_the_old_single_page(self):
        self.assertEqual(self.win.get_default_size(), (480, 520))

    def test_controls_follow_the_setup_state(self):
        self.assertFalse(self.win.sound_page._preset_group.get_sensitive())     # until the first check
        self.settle()
        self.assertTrue(self.win._ready)
        self.assertTrue(self.win.sound_page._preset_group.get_sensitive())
        self.assertFalse(self.win.sound_page._hint_group.get_visible())
        self.assertTrue(self.win.setup_page._uninstall_button.get_sensitive())
        self.assertTrue(self.win.sound_page._surround_switch.get_active())
        self.assertTrue(self.win.sound_page._preset_buttons["game"].get_active())

    def test_incomplete_setup_disables_controls_and_shows_hint(self):
        self.settle()
        self.checks = [be.Check("tools", "tools", True), be.Check("ir", "ir", False)]
        self.win.refresh()
        pump(until=lambda: self.win._ready is False)
        self.assertFalse(self.win._ready)
        self.assertFalse(self.win.sound_page._preset_group.get_sensitive())
        self.assertTrue(self.win.sound_page._hint_group.get_visible())
        self.assertTrue(self.win.setup_page._install_button.get_sensitive())
        self.assertFalse(self.win.setup_page._apply_button.get_sensitive())

    def test_open_setup_hint_switches_the_tab(self):
        self.win.sound_page.emit("setup-requested")
        self.assertEqual(self.win._stack.get_visible_child_name(), "setup")

    def test_stale_check_result_is_dropped(self):
        self.settle()
        before = self.win._check_serial
        self.win._show_checks(before - 1, [be.Check("tools", "tools", False)])
        self.assertTrue(self.win._ready)

    def test_task_output_goes_to_the_log_and_ends_busy(self):
        self.settle()

        def action(on_line):
            on_line("line one")
            on_line("line two")
            return 0

        self.win.run_task("Install", action, show_log=True)
        self.assertTrue(self.win._busy)
        self.assertEqual(self.win._stack.get_visible_child_name(), "logs")
        self.assertFalse(self.win.setup_page._install_button.get_sensitive())
        pump(until=lambda: not self.win._busy)
        self.assertEqual(self.win.log_page.text, "--- Install\nline one\nline two\n")
        self.assertTrue(self.win.setup_page._install_button.get_sensitive())

    def test_quiet_task_stays_on_the_tab(self):
        self.settle()
        self.win.run_task("Preset Music", lambda on_line: 0)
        self.assertEqual(self.win._stack.get_visible_child_name(), "sound")
        pump(until=lambda: not self.win._busy)

    def test_failing_task_ends_busy(self):
        self.settle()
        self.win.run_task("Re-apply", lambda on_line: 1)
        pump(until=lambda: not self.win._busy)
        self.assertFalse(self.win._busy)

    def test_raising_task_does_not_leave_the_window_busy(self):
        self.settle()

        def broken(on_line):
            raise FileNotFoundError("bash")

        self.win.run_task("Install", broken)
        pump(until=lambda: not self.win._busy)
        self.assertFalse(self.win._busy)
        self.assertIn("error: bash", self.win.log_page.text)

    def test_second_task_is_ignored_while_busy(self):
        self.settle()
        self.win._set_busy(True)
        action = mock.Mock(return_value=0)
        self.win.run_task("Install", action)
        pump()
        action.assert_not_called()
        self.win._set_busy(False)

    def test_user_choices_run_backend_actions(self):
        self.settle()
        with mock.patch.object(be, "set_preset", return_value=0) as set_preset, \
                mock.patch.object(be, "set_surround", return_value=0) as set_surround:
            self.win.sound_page._preset_buttons["music"].set_active(True)
            pump(until=lambda: set_preset.called)
            set_preset.assert_called_once()
            self.assertEqual(set_preset.call_args.args, ("music",))
            pump(until=lambda: not self.win._busy)
            self.win.sound_page._surround_switch.set_active(False)
            pump(until=lambda: set_surround.called)
            self.assertEqual(set_surround.call_args.args, (False,))
            pump(until=lambda: not self.win._busy)

    def test_showing_saved_state_runs_nothing(self):
        with mock.patch.object(be, "set_preset") as set_preset, mock.patch.object(be, "set_surround") as set_surround:
            self.settle()                                           # shows saved surround/preset
            pump()
            set_preset.assert_not_called()
            set_surround.assert_not_called()

    def test_chosen_untested_headset_is_saved_and_applied(self):
        self.settle()
        with mock.patch.object(be, "apply", return_value=0) as apply:
            self.win.sound_page.emit("headset-selected", "abcd:1234")
            be.set_manual_device.assert_called_with("abcd:1234")
            pump(until=lambda: apply.called)
            apply.assert_called_once()
            pump(until=lambda: not self.win._busy)


if __name__ == "__main__":
    unittest.main()
