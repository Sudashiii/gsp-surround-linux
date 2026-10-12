"""Tests for scripts/install.sh and scripts/uninstall.sh in a sandbox: a fake home directory, stub
commands first on PATH (sudo, pkexec, systemctl, pw-*, ...) that only write down what they were asked to
do, a fake filter repository and no access to the sound hardware. Nothing real is touched.
  python3 -m unittest discover tests
"""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PINNED_SHA = "45cfbaab0629583843d6d2dc328152cc94d0368e514de71370521f8b7d684c25"   # scripts/fetch_ir.py
INDEX = ('{"profiles": {"gsp350": {"name": "Test profile", "file": "gsp350/test.wav", "sha256": "%s", '
         '"rate": 48000, "lfe_gain": {"off": 0.708, "game": 1.0, "music": 0.708, "esport": 0.708}}}}' % PINNED_SHA)

LOGGING_STUB = '#!/bin/sh\necho "{name} $*" >> "$GSP_TEST_LOG"\n{extra}exit 0\n'
STUBS = {
    "sudo": "", "pkexec": "", "pw-cli": "", "pw-link": "", "wpctl": "", "udevadm": "", "fish": "", "sleep": "",
    "systemctl": 'case "$*" in *is-active*) exit 1;; esac\n',          # PulseAudio is not the sound server
    "pw-dump": 'echo "[]"\n',
}


class Sandbox:
    """A fake home, stubs for everything that would touch the system, and a log of what they were asked."""

    def __init__(self, root):
        self.root = Path(root)
        self.home = self.root / "home"
        self.bin = self.root / "bin"
        self.log = self.root / "calls.log"
        self.udev = self.root / "udev"                      # stands for /etc/udev/rules.d
        self.sys_udev = self.root / "sys-udev"              # stands for /usr/lib/udev/rules.d
        for d in (self.home, self.bin, self.udev, self.sys_udev):
            d.mkdir()
        for name, extra in STUBS.items():
            self.stub(name, LOGGING_STUB.format(name=name, extra=extra))
        # `python3 -c "import gi ..."` (is the GTK binding there?) must not depend on the machine
        self.stub("python3", f'#!/bin/sh\ncase "$*" in *"import gi"*) exit 0;; esac\nexec {sys.executable} "$@"\n')
        ir = self.root / "irs"
        (ir / "gsp350").mkdir(parents=True)
        (ir / "index.json").write_text(INDEX)
        self.wav = self.root / "filter.wav"
        self.wav.write_bytes(b"RIFF fake filter file")
        self.ir_base = ir.as_uri()

    def stub(self, name, text):
        path = self.bin / name
        path.write_text(text)
        path.chmod(0o755)

    def env(self):
        return {"HOME": str(self.home), "PATH": f"{self.bin}:{os.environ['PATH']}", "TMPDIR": str(self.root),
                "GSP_TEST_LOG": str(self.log), "GSP_UDEV_DIRS": f"{self.udev}:{self.sys_udev}",
                "GSP_IRS_BASE": self.ir_base, "LANG": "C"}

    def run(self, script, *args):
        proc = subprocess.run(["bash", str(script), *args], env=self.env(), capture_output=True, text=True,
                              stdin=subprocess.DEVNULL, timeout=120)
        if proc.returncode:
            raise AssertionError(f"{script.name} failed ({proc.returncode})\n{proc.stdout}\n{proc.stderr}")
        return proc.stdout

    def install(self, script, *args):
        return self.run(script, "--yes", "--ir", str(self.wav), *args)

    def calls(self):
        return self.log.read_text().splitlines() if self.log.exists() else []

    def called(self, prefix):
        return [c for c in self.calls() if c.startswith(prefix)]

    # --- the trees the scripts run from --------------------------------------------------------------
    def clone(self):
        """A copy of the repository (what a git clone is) whose apply.sh does not touch hardware."""
        dest = self.root / "clone"
        dest.mkdir()
        for name in ("gsp-surround", "VERSION", "README.md", "LICENSE", "app", "scripts", "data"):
            src = REPO / name
            if src.is_dir():
                shutil.copytree(src, dest / name, ignore=shutil.ignore_patterns("__pycache__"))
            else:
                shutil.copy2(src, dest / name)
        self.stub_apply(dest)
        return dest

    def packaged(self):
        """A `make install DESTDIR=... PREFIX=/usr` tree (what the .deb contains), with a harmless apply.sh."""
        stage = self.root / "pkg"
        subprocess.run(["make", "install", f"DESTDIR={stage}", "PREFIX=/usr"], cwd=REPO, check=True,
                       capture_output=True, env={**os.environ, "SOURCE_DATE_EPOCH": "1700000000"})
        app = stage / "usr/share/gsp-surround"
        self.stub_apply(app)
        self.sys_udev = stage / "usr/lib/udev/rules.d"      # the rule the package brought
        return app

    @staticmethod
    def stub_apply(tree):
        apply = tree / "scripts/apply.sh"
        apply.write_text('#!/bin/sh\necho "apply.sh" >> "$GSP_TEST_LOG"\n')
        apply.chmod(0o755)

    # --- places in the fake home ---------------------------------------------------------------------
    @property
    def data(self):
        return self.home / ".local/share/gsp-surround"

    @property
    def pw_conf(self):
        return self.home / ".config/pipewire/pipewire.conf.d/gsp-surround.conf"

    @property
    def unit(self):
        return self.home / ".config/systemd/user/gsp-surround.service"

    @property
    def desktop(self):
        return self.home / ".local/share/applications/gsp-surround.desktop"

    @property
    def launcher(self):
        return self.home / ".local/bin/gsp-surround"

    @property
    def icon(self):
        return self.home / ".local/share/icons/hicolor/scalable/apps/gsp-surround.svg"

    def no_upmix_files(self):
        return [self.home / f".config/pipewire/{d}/90-gsp-surround-no-upmix.conf"
                for d in ("pipewire-pulse.conf.d", "client.conf.d", "client-rt.conf.d")]


def wanted_rule(*ids):
    """The rule install.sh would write for these ids (from the same function)."""
    out = subprocess.run(["bash", "-c", '. scripts/common.sh; udev_rules "$@"', "x", *ids], cwd=REPO,
                         capture_output=True, text=True, check=True)
    return out.stdout


class SandboxTestCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.sb = Sandbox(tmp.name)


class CloneInstall(SandboxTestCase):
    """Run from a clone: the app is copied into the home directory (the original, per-user way)."""

    def setUp(self):
        super().setUp()
        self.clone = self.sb.clone()

    def test_installs_the_app_for_the_user(self):
        out = self.sb.install(self.clone / "scripts/install.sh")
        sb, app = self.sb, self.sb.data / "app"
        self.assertTrue(os.access(app / "gsp-surround", os.X_OK))
        self.assertTrue((app / "app/pages.py").is_file())
        self.assertEqual((app / "VERSION").read_text(), (REPO / "VERSION").read_text())
        self.assertTrue(sb.launcher.is_symlink())
        self.assertEqual(os.readlink(sb.launcher), str(app / "gsp-surround"))
        entry = sb.desktop.read_text()
        self.assertIn(f"Exec={app}/gsp-surround", entry)
        self.assertIn("Categories=AudioVideo;Audio;Mixer;", entry)
        self.assertTrue(sb.icon.is_file())
        self.assertTrue((sb.data / "ir.wav").is_file())
        self.assertTrue((sb.data / "profile.json").is_file())
        self.assertIn(f'filename = "{sb.data / "ir.wav"}"', sb.pw_conf.read_text())
        self.assertTrue(all(f.is_file() for f in sb.no_upmix_files()))
        unit = sb.unit.read_text()
        self.assertIn(f"ExecStart={app}/scripts/apply.sh", unit)
        self.assertIn("ConditionPathExists=", unit)
        self.assertIn("added ~/.local/bin to PATH", out)
        self.assertEqual((sb.home / ".profile").read_text().count("added by gsp-surround install.sh"), 1)

    def test_asks_for_root_when_the_device_rule_is_missing(self):
        out = self.sb.install(self.clone / "scripts/install.sh")
        root_calls = self.sb.called("pkexec")
        self.assertEqual(len(root_calls), 1)
        self.assertIn("root-setup.sh --udev", root_calls[0])
        self.assertIn("Unplug and replug", out)
        self.assertIn("systemctl --user enable gsp-surround.service", self.sb.calls())
        self.assertIn("systemctl --user restart pipewire pipewire-pulse wireplumber", self.sb.calls())
        self.assertIn("apply.sh", self.sb.calls())

    def test_no_password_when_the_rule_is_already_current(self):
        (self.sb.udev / "70-gsp-surround.rules").write_text(wanted_rule("1395:005d"))
        out = self.sb.install(self.clone / "scripts/install.sh")
        self.assertEqual(self.sb.called("pkexec") + self.sb.called("sudo"), [])
        self.assertIn("no password needed", out)
        self.assertNotIn("Unplug and replug", out)

    def test_asks_for_root_when_the_installed_rule_differs(self):
        (self.sb.udev / "70-gsp-surround.rules").write_text("# an older rule\n")
        self.sb.install(self.clone / "scripts/install.sh")
        self.assertEqual(len(self.sb.called("pkexec")), 1)

    def test_a_chosen_untested_headset_goes_into_the_rule(self):
        conf = self.sb.home / ".config/gsp-surround"
        conf.mkdir(parents=True)
        (conf / "device").write_text("abcd:1234\n")
        (self.sb.udev / "70-gsp-surround.rules").write_text(wanted_rule("1395:005d"))      # only the known one
        self.sb.install(self.clone / "scripts/install.sh")
        self.assertEqual(len(self.sb.called("pkexec")), 1)       # the rule has to change

    def test_reinstall_from_the_installed_copy_keeps_the_app(self):
        self.sb.install(self.clone / "scripts/install.sh")
        installed = self.sb.data / "app"
        self.sb.install(installed / "scripts/install.sh")           # what the app's Reinstall button runs
        self.assertTrue((installed / "app/pages.py").is_file())
        self.assertTrue(self.sb.launcher.is_symlink())

    def test_uninstall_removes_everything_including_the_app(self):
        self.sb.install(self.clone / "scripts/install.sh")
        (self.sb.udev / "70-gsp-surround.rules").write_text(wanted_rule("1395:005d"))
        self.sb.log.write_text("")
        self.sb.run(self.sb.data / "app/scripts/uninstall.sh")        # the installed copy removes itself
        sb = self.sb
        self.assertFalse(sb.data.exists())
        for path in (sb.pw_conf, sb.unit, sb.desktop, sb.launcher, sb.icon, *sb.no_upmix_files()):
            self.assertFalse(path.exists() or path.is_symlink(), path)
        self.assertEqual(len(sb.called("pkexec")), 1)
        self.assertIn("--remove-udev", sb.called("pkexec")[0])
        self.assertIn("systemctl --user restart pipewire pipewire-pulse wireplumber", sb.calls())
        self.assertNotIn("added by gsp-surround", (sb.home / ".profile").read_text())

    def test_uninstall_does_not_ask_for_root_without_a_rule(self):
        self.sb.install(self.clone / "scripts/install.sh")
        self.sb.log.write_text("")                                    # forget what the install asked for
        self.sb.run(self.sb.data / "app/scripts/uninstall.sh")
        self.assertEqual(self.sb.called("pkexec") + self.sb.called("sudo"), [])


class PackagedInstall(SandboxTestCase):
    """Installed by `make install` / the .deb: only the user's own setup is done, never the app files."""

    def setUp(self):
        super().setUp()
        self.app = self.sb.packaged()

    def test_sets_up_the_user_without_copying_the_app_or_asking_for_a_password(self):
        out = self.sb.install(self.app / "scripts/install.sh")
        sb = self.sb
        self.assertFalse((sb.data / "app").exists())
        for path in (sb.desktop, sb.launcher, sb.unit, sb.icon):
            self.assertFalse(path.exists(), path)
        self.assertTrue((sb.data / "ir.wav").is_file())
        self.assertIn(f'filename = "{sb.data / "ir.wav"}"', sb.pw_conf.read_text())
        self.assertTrue(all(f.is_file() for f in sb.no_upmix_files()))
        self.assertEqual(sb.called("pkexec") + sb.called("sudo"), [])               # the package brought the rule
        self.assertIn("systemctl --user daemon-reload", sb.calls())
        self.assertEqual(sb.called("systemctl --user enable gsp-surround"), [])      # enabled by the package
        self.assertIn("apply.sh", sb.calls())
        self.assertIn("installed system-wide", out)
        self.assertFalse((sb.home / ".profile").exists())                            # no PATH edits
        self.assertNotIn("Unplug and replug", out)

    def test_replaces_an_older_per_user_install(self):
        sb, old = self.sb, self.sb.data / "app"
        (old / "scripts").mkdir(parents=True)
        (old / "gsp-surround").write_text("#!/bin/sh\n")
        for d in (sb.launcher.parent, sb.desktop.parent, sb.icon.parent, sb.unit.parent):
            d.mkdir(parents=True)
        sb.launcher.symlink_to(old / "gsp-surround")
        sb.desktop.write_text(f"[Desktop Entry]\nExec={old}/gsp-surround\n")
        sb.icon.write_text("<svg/>")
        sb.unit.write_text(f"[Service]\nExecStart={old}/scripts/apply.sh\n")
        out = sb.install(self.app / "scripts/install.sh")
        self.assertFalse(old.exists())
        for path in (sb.desktop, sb.icon, sb.unit):
            self.assertFalse(path.exists(), path)
        self.assertFalse(sb.launcher.is_symlink())
        self.assertIn("replaced the older per-user copy", out)
        self.assertTrue((sb.data / "ir.wav").is_file())          # the data directory itself survives

    def test_leaves_entries_it_did_not_create_alone(self):
        sb = self.sb
        sb.desktop.parent.mkdir(parents=True)
        sb.desktop.write_text("[Desktop Entry]\nExec=/opt/mine/gsp\n")
        sb.unit.parent.mkdir(parents=True)
        sb.unit.write_text("[Service]\nExecStart=/opt/mine/apply\n")
        sb.launcher.parent.mkdir(parents=True)
        sb.launcher.symlink_to("/opt/mine/gsp")
        sb.install(self.app / "scripts/install.sh")
        self.assertIn("/opt/mine/gsp", sb.desktop.read_text())
        self.assertIn("/opt/mine/apply", sb.unit.read_text())
        self.assertEqual(os.readlink(sb.launcher), "/opt/mine/gsp")

    def test_asks_for_root_only_if_the_rule_has_to_change(self):
        conf = self.sb.home / ".config/gsp-surround"
        conf.mkdir(parents=True)
        (conf / "device").write_text("abcd:1234\n")               # an untested headset: the rule needs its id
        self.sb.install(self.app / "scripts/install.sh")
        self.assertEqual(len(self.sb.called("pkexec")), 1)

    def test_uninstall_removes_only_the_users_setup(self):
        self.sb.install(self.app / "scripts/install.sh")
        before = sorted(p.relative_to(self.app) for p in self.app.rglob("*"))
        out = self.sb.run(self.app / "scripts/uninstall.sh")
        sb = self.sb
        self.assertFalse(sb.data.exists())
        self.assertFalse(sb.pw_conf.exists())
        self.assertTrue(all(not f.exists() for f in sb.no_upmix_files()))
        self.assertEqual(sorted(p.relative_to(self.app) for p in self.app.rglob("*")), before)   # app untouched
        self.assertEqual(sb.called("pkexec") + sb.called("sudo"), [])      # the package's rule is not ours to remove
        self.assertIn("software manager", out)

    def test_uninstall_removes_a_rule_the_app_added_in_etc(self):
        self.sb.install(self.app / "scripts/install.sh")
        (self.sb.udev / "70-gsp-surround.rules").write_text("# added by the app for an untested headset\n")
        self.sb.run(self.app / "scripts/uninstall.sh")
        self.assertEqual(len(self.sb.called("pkexec")), 1)
        self.assertIn("--remove-udev", self.sb.called("pkexec")[0])


class Generator(unittest.TestCase):
    """The udev rule generator that install.sh and the Makefile share."""

    def test_rule_format_and_duplicates(self):
        rule = wanted_rule("1395:005d", "1395:005d", "", "abcd:1234")
        lines = rule.splitlines()
        self.assertEqual(len(lines), 4)                              # two comment lines, two rules
        self.assertIn('ATTRS{idVendor}=="1395", ATTRS{idProduct}=="005d"', lines[2])
        self.assertIn('ATTRS{idVendor}=="abcd", ATTRS{idProduct}=="1234"', lines[3])
        self.assertTrue(all('ENV{SYSTEMD_USER_WANTS}+="gsp-surround.service"' in line for line in lines[2:]))

    def test_matches_what_the_earlier_installer_wrote(self):
        # byte for byte what install.sh produced before the generator moved to common.sh, so rules written
        # by an older version still count as "current" and no password is asked for
        old = ("# gsp-surround: give the logged-in user access to the dongle's HID interface (EQ preset) and\n"
               "# start the user's gsp-surround.service when the dongle is plugged in.\n"
               'SUBSYSTEM=="hidraw", ATTRS{idVendor}=="1395", ATTRS{idProduct}=="005d", TAG+="uaccess", '
               'TAG+="systemd", ENV{SYSTEMD_USER_WANTS}+="gsp-surround.service"\n')
        self.assertEqual(wanted_rule("1395:005d"), old)


if __name__ == "__main__":
    unittest.main()
