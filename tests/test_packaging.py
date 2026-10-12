"""Tests for the Makefile: the staged install, the .deb and the source tarball. Everything is built in
temporary directories; tools that are not installed (make, dpkg-deb, the validators) skip their tests.
  python3 -m unittest discover tests
"""
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parent.parent
EPOCH = "1700000000"                                         # 2023-11-14
sys.path.insert(0, str(REPO / "app"))
import backend as be  # noqa: E402

VERSION = (REPO / "VERSION").read_text().strip()
HAVE_MAKE = shutil.which("make") is not None
HAVE_DEB = HAVE_MAKE and shutil.which("dpkg-deb") is not None
HAVE_GIT = shutil.which("git") is not None


def make(*args, cwd=REPO, **env):
    proc = subprocess.run(["make", *args], cwd=cwd, capture_output=True, text=True, env={**os.environ, **env})
    if proc.returncode:
        raise AssertionError(f"make {' '.join(args)} failed\n{proc.stdout}\n{proc.stderr}")
    return proc


def files_below(root):
    return sorted(str(p.relative_to(root)) for p in Path(root).rglob("*") if p.is_file() or p.is_symlink())


def known_ids():
    return [line.split()[0].lower() for line in (REPO / "data/devices.conf").read_text().splitlines()
            if line.strip() and not line.startswith("#")]


def expected_rule(ids):
    out = subprocess.run(["bash", "-c", '. scripts/common.sh; udev_rules "$@"', "x", *ids], cwd=REPO,
                         capture_output=True, text=True, check=True)
    return out.stdout


@unittest.skipUnless(HAVE_MAKE, "needs make")
class StagedInstall(unittest.TestCase):
    """`make install DESTDIR=... PREFIX=/usr`: what the .deb is made of."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.tmp.name)
        make("install", f"DESTDIR={cls.root}", "PREFIX=/usr", SOURCE_DATE_EPOCH=EPOCH)
        cls.app = cls.root / "usr/share/gsp-surround"

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_layout(self):
        for rel in ("usr/bin/gsp-surround", "usr/share/gsp-surround/gsp-surround", "usr/share/gsp-surround/VERSION",
                    "usr/share/gsp-surround/PACKAGED", "usr/share/gsp-surround/app/pages.py",
                    "usr/share/gsp-surround/app/backend.py", "usr/share/gsp-surround/app/gsp_surround.py",
                    "usr/share/gsp-surround/scripts/install.sh", "usr/share/gsp-surround/data/devices.conf",
                    "usr/share/gsp-surround/data/icons/hicolor/symbolic/apps/gsp-surround-headset-symbolic.svg",
                    "usr/share/applications/gsp-surround.desktop",
                    "usr/share/icons/hicolor/scalable/apps/gsp-surround.svg",
                    "usr/share/metainfo/io.github.sudashiii.GspSurround.metainfo.xml",
                    "usr/lib/udev/rules.d/70-gsp-surround.rules", "usr/lib/systemd/user/gsp-surround.service",
                    "usr/lib/systemd/user/pipewire.service.wants/gsp-surround.service",
                    "usr/share/doc/gsp-surround/LICENSE"):
            self.assertTrue((self.root / rel).exists() or (self.root / rel).is_symlink(), rel)

    def test_nothing_is_writable_by_group_or_others(self):
        for path in self.root.rglob("*"):
            if not path.is_symlink():
                self.assertEqual(path.stat().st_mode & 0o022, 0, f"{path.relative_to(self.root)} is writable")

    def test_scripts_are_executable_and_data_is_not(self):
        for name in ("gsp-surround", "scripts/install.sh", "scripts/uninstall.sh", "scripts/apply.sh",
                     "scripts/common.sh", "app/gsp_surround.py"):
            self.assertTrue(os.access(self.app / name, os.X_OK), name)
        for name in ("VERSION", "PACKAGED", "data/devices.conf", "app/pages.py"):
            self.assertFalse(os.access(self.app / name, os.X_OK), name)

    def test_launcher_is_a_relative_link_that_works(self):
        link = self.root / "usr/bin/gsp-surround"
        self.assertEqual(os.readlink(link), "../share/gsp-surround/gsp-surround")
        out = subprocess.run([str(link), "--version"], capture_output=True, text=True, check=True).stdout
        self.assertEqual(out.strip(), f"gsp-surround {VERSION}")

    def test_the_app_knows_it_is_packaged(self):
        self.assertTrue(be.is_packaged(self.app))
        self.assertFalse(be.is_packaged(REPO))
        self.assertFalse(be.is_self_hosted(self.app))

    def test_desktop_entry_has_one_menu_category_and_the_plain_command(self):
        entry = dict(line.split("=", 1) for line in
                     (self.root / "usr/share/applications/gsp-surround.desktop").read_text().splitlines()
                     if "=" in line)
        self.assertEqual(entry["Exec"], "gsp-surround")
        self.assertEqual(entry["Icon"], "gsp-surround")
        self.assertEqual(entry["Categories"], "AudioVideo;Audio;Mixer;")       # only one main category
        self.assertEqual(entry["StartupWMClass"], "io.github.sudashiii.GspSurround")

    def test_unit_runs_the_installed_script_and_waits_for_the_setup(self):
        unit = (self.root / "usr/lib/systemd/user/gsp-surround.service").read_text()
        self.assertIn("ExecStart=/usr/share/gsp-surround/scripts/apply.sh", unit)
        self.assertIn("ConditionPathExists=%E/pipewire/pipewire.conf.d/gsp-surround.conf", unit)
        self.assertNotIn("@", unit)
        link = self.root / "usr/lib/systemd/user/pipewire.service.wants/gsp-surround.service"
        self.assertEqual(os.readlink(link), "../gsp-surround.service")

    def test_the_apps_service_check_accepts_the_packaged_link(self):
        # `systemctl is-enabled` calls a unit that is only linked from /usr/lib "disabled"; the app must not
        with mock.patch.object(be, "_out", return_value="disabled\n"):
            self.assertTrue(be.service_enabled([self.root / "usr/lib/systemd/user"]))

    def test_udev_rule_covers_every_known_dongle(self):
        rule = (self.root / "usr/lib/udev/rules.d/70-gsp-surround.rules").read_text()
        self.assertEqual(rule, expected_rule(known_ids()))
        for usb_id in known_ids():
            self.assertIn(f'ATTRS{{idVendor}}=="{usb_id.split(":")[0]}"', rule)

    def test_metainfo_is_filled_in(self):
        text = (self.root / "usr/share/metainfo/io.github.sudashiii.GspSurround.metainfo.xml").read_text()
        self.assertNotIn("@", text)
        release = ET.fromstring(text).find("releases/release")
        self.assertEqual(release.get("version"), VERSION)
        self.assertEqual(release.get("date"), "2023-11-14")                    # from SOURCE_DATE_EPOCH

    def test_validators(self):
        entry = self.root / "usr/share/applications/gsp-surround.desktop"
        metainfo = self.root / "usr/share/metainfo/io.github.sudashiii.GspSurround.metainfo.xml"
        # desktop-file-validate and xmllint exit 0 even when they print hints/warnings: any output fails
        for tool, args in {"desktop-file-validate": [str(entry)],
                           "xmllint": ["--noout", str(metainfo), *map(str, REPO.glob("data/icons/**/*.svg"))]}.items():
            if shutil.which(tool):
                proc = subprocess.run([tool, *args], capture_output=True, text=True)
                self.assertEqual((proc.returncode, proc.stdout + proc.stderr), (0, ""), tool)
        if shutil.which("appstreamcli"):                      # prints a summary; errors and warnings fail
            proc = subprocess.run(["appstreamcli", "validate", "--no-net", str(metainfo)], capture_output=True,
                                  text=True)
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            self.assertNotRegex(proc.stdout, r"(?m)^[EW]: ")

    def test_local_prefix_puts_the_rule_in_etc_where_udev_reads_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            make("install", f"DESTDIR={tmp}", "PREFIX=/usr/local", SOURCE_DATE_EPOCH=EPOCH)
            for rel in ("etc/udev/rules.d/70-gsp-surround.rules", "usr/local/bin/gsp-surround",
                        "usr/local/share/gsp-surround/PACKAGED", "usr/local/lib/systemd/user/gsp-surround.service"):
                self.assertTrue(os.path.lexists(Path(tmp) / rel), rel)
            unit = (Path(tmp) / "usr/local/lib/systemd/user/gsp-surround.service").read_text()
            self.assertIn("ExecStart=/usr/local/share/gsp-surround/scripts/apply.sh", unit)

    def test_uninstall_removes_everything(self):
        with tempfile.TemporaryDirectory() as tmp:
            make("install", f"DESTDIR={tmp}", "PREFIX=/usr", SOURCE_DATE_EPOCH=EPOCH)
            self.assertTrue(files_below(tmp))
            make("uninstall", f"DESTDIR={tmp}", "PREFIX=/usr")
            self.assertEqual(files_below(tmp), [])


@unittest.skipUnless(HAVE_DEB, "needs make and dpkg-deb")
class DebPackage(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.tmp.name)
        cls.deb = cls.build("one")

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    @classmethod
    def build(cls, name):
        build, dist = cls.root / name / "build", cls.root / name / "dist"
        make("deb", f"BUILDDIR={build}", f"DISTDIR={dist}", SOURCE_DATE_EPOCH=EPOCH,
             DEB_MAINTAINER="Test Maintainer <test@example.org>")
        return dist / f"gsp-surround_{VERSION}_all.deb"

    def field(self, name):
        return subprocess.run(["dpkg-deb", "-f", str(self.deb), name], capture_output=True, text=True,
                              check=True).stdout.strip()

    def test_control_data(self):
        self.assertEqual(self.field("Package"), "gsp-surround")
        self.assertEqual(self.field("Version"), VERSION)
        self.assertEqual(self.field("Architecture"), "all")
        self.assertEqual(self.field("Maintainer"), "Test Maintainer <test@example.org>")
        self.assertEqual(self.field("Section"), "sound")
        depends = self.field("Depends")
        for needed in ("python3-gi", "gir1.2-gtk-4.0", "gir1.2-adw-1 (>= 1.2)", "pipewire-bin", "wireplumber"):
            self.assertIn(needed, depends)
        info = subprocess.run(["dpkg-deb", "-I", str(self.deb)], capture_output=True, text=True, check=True).stdout
        self.assertNotRegex(info, r"@[A-Z]+@")                                    # every placeholder was filled in

    def listing(self):
        out = subprocess.run(["dpkg-deb", "-c", str(self.deb)], capture_output=True, text=True, check=True).stdout
        return [line.split() for line in out.splitlines()]

    def test_everything_is_owned_by_root_and_not_writable_by_others(self):
        for fields in self.listing():
            mode, owner = fields[0], fields[1]
            self.assertEqual(owner, "root/root", fields)
            if not mode.startswith("l"):                             # a link's own mode is always 777
                self.assertNotIn("w", mode[4:], fields)              # no group/other write bit

    def test_contains_the_same_files_as_the_staged_install(self):
        with tempfile.TemporaryDirectory() as tmp:
            make("install", f"DESTDIR={tmp}", "PREFIX=/usr", SOURCE_DATE_EPOCH=EPOCH)
            staged = set(files_below(tmp))
        packaged = {fields[5][2:] for fields in self.listing() if not fields[0].startswith("d")}      # drop "./"
        self.assertEqual(packaged - staged, {"usr/share/doc/gsp-surround/copyright"})
        self.assertEqual(staged - packaged, set())

    def test_maintainer_scripts(self):
        out = self.root / "control"
        subprocess.run(["dpkg-deb", "-e", str(self.deb), str(out)], check=True)
        for name in ("postinst", "postrm"):
            script = out / name
            self.assertTrue(os.access(script, os.X_OK), name)
            subprocess.run(["sh", "-n", str(script)], check=True)
        self.assertIn("cmp -s", (out / "postinst").read_text())      # only an identical old rule is removed

    def run_maintainer_script(self, name, *args, dpkg_root):
        """Run postinst/postrm from the package against a fake root (DPKG_ROOT), with a udevadm that only logs."""
        control = self.root / "control-scripts"
        if not control.exists():
            subprocess.run(["dpkg-deb", "-e", str(self.deb), str(control)], check=True)
        bin_dir = self.root / "stub-bin"
        bin_dir.mkdir(exist_ok=True)
        log = self.root / "udevadm.log"
        stub = bin_dir / "udevadm"
        stub.write_text(f'#!/bin/sh\necho "$*" >> {log}\n')
        stub.chmod(0o755)
        env = {**os.environ, "DPKG_ROOT": str(dpkg_root), "PATH": f"{bin_dir}:{os.environ['PATH']}"}
        subprocess.run([str(control / name), *args], check=True, env=env, capture_output=True)
        return log.read_text() if log.exists() else ""

    def fake_root(self, packaged_rule, old_rule=None):
        root = Path(tempfile.mkdtemp(dir=self.root))
        for rel, text in (("usr/lib/udev/rules.d", packaged_rule), ("etc/udev/rules.d", old_rule)):
            if text is not None:
                (root / rel).mkdir(parents=True)
                (root / rel / "70-gsp-surround.rules").write_text(text)
        return root

    def test_postinst_removes_the_old_per_user_rule_when_it_is_identical(self):
        root = self.fake_root("# rule\n", old_rule="# rule\n")
        self.run_maintainer_script("postinst", "configure", dpkg_root=root)
        self.assertFalse((root / "etc/udev/rules.d/70-gsp-surround.rules").exists())
        self.assertTrue((root / "usr/lib/udev/rules.d/70-gsp-surround.rules").exists())      # the package's own stays

    def test_postinst_keeps_a_rule_the_user_changed(self):
        root = self.fake_root("# rule\n", old_rule="# rule\n# and an untested headset\n")
        self.run_maintainer_script("postinst", "configure", dpkg_root=root)
        self.assertTrue((root / "etc/udev/rules.d/70-gsp-surround.rules").exists())

    def test_postinst_without_an_old_rule_and_postrm_are_quiet_in_a_fake_root(self):
        root = self.fake_root("# rule\n")
        log = self.run_maintainer_script("postinst", "configure", dpkg_root=root)
        log += self.run_maintainer_script("postrm", "remove", dpkg_root=root)
        self.assertEqual(log, "")                                    # no udev to talk to in a non-live root

    def test_the_build_is_reproducible(self):
        again = self.build("two")
        self.assertEqual(hashlib.sha256(self.deb.read_bytes()).hexdigest(),
                         hashlib.sha256(again.read_bytes()).hexdigest())


@unittest.skipUnless(HAVE_DEB and HAVE_GIT, "needs make, dpkg-deb and git")
class ReleaseFiles(unittest.TestCase):
    """`make dist` and `make artifacts` in a throw-away git repository made from the working tree."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.repo = Path(cls.tmp.name) / "repo"
        listed = subprocess.run(["git", "ls-files", "-co", "--exclude-standard"], cwd=REPO, capture_output=True,
                                text=True, check=True).stdout.splitlines()
        for rel in listed:
            if (REPO / rel).is_file():
                (cls.repo / rel).parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(REPO / rel, cls.repo / rel)
        env = {**os.environ, "GIT_AUTHOR_DATE": f"{EPOCH} +0000", "GIT_COMMITTER_DATE": f"{EPOCH} +0000",
               "GIT_AUTHOR_NAME": "Test", "GIT_AUTHOR_EMAIL": "t@example.org",
               "GIT_COMMITTER_NAME": "Test", "GIT_COMMITTER_EMAIL": "t@example.org"}
        for cmd in (["init", "-q", "-b", "main"], ["add", "-A"], ["commit", "-q", "-m", "snapshot"]):
            subprocess.run(["git", *cmd], cwd=cls.repo, check=True, capture_output=True, env=env)
        make("artifacts", cwd=cls.repo)
        cls.dist = cls.repo / "dist"

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_the_three_release_files_exist_with_the_published_names(self):
        self.assertEqual(sorted(p.name for p in self.dist.iterdir()),
                         ["SHA256SUMS", f"gsp-surround-{VERSION}.tar.gz", f"gsp-surround_{VERSION}_all.deb"])

    def test_checksums_verify(self):
        proc = subprocess.run(["sha256sum", "-c", "SHA256SUMS"], cwd=self.dist, capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertEqual(len(proc.stdout.splitlines()), 2)

    def test_source_tarball_is_clean(self):
        out = subprocess.run(["tar", "-tzf", str(self.dist / f"gsp-surround-{VERSION}.tar.gz")],
                             capture_output=True, text=True, check=True).stdout.splitlines()
        prefix = f"gsp-surround-{VERSION}/"
        self.assertTrue(all(name.startswith(prefix) for name in out))
        names = {name[len(prefix):] for name in out}
        for needed in ("Makefile", "VERSION", "app/pages.py", "packaging/deb/control.in", "LICENSE"):
            self.assertIn(needed, names)
        for unwanted in (".github/", ".git/", "dist/", "build/", ".gitignore", ".gitattributes"):
            self.assertFalse(any(n.startswith(unwanted) for n in names), unwanted)

    def test_the_source_tarball_is_reproducible(self):
        first = (self.dist / f"gsp-surround-{VERSION}.tar.gz").read_bytes()
        make("dist", cwd=self.repo)
        self.assertEqual(hashlib.sha256(first).hexdigest(),
                         hashlib.sha256((self.dist / f"gsp-surround-{VERSION}.tar.gz").read_bytes()).hexdigest())


class Version(unittest.TestCase):
    def test_version_file_is_a_plain_version_number(self):
        self.assertRegex(VERSION, r"^\d+\.\d+\.\d+(-[0-9A-Za-z.]+)?$")

    def test_the_app_reports_it(self):
        self.assertEqual(be.VERSION, VERSION)

    def test_metainfo_template_takes_the_version_from_the_makefile(self):
        release = ET.parse(REPO / "data/io.github.sudashiii.GspSurround.metainfo.xml.in").find("releases/release")
        self.assertEqual((release.get("version"), release.get("date")), ("@VERSION@", "@DATE@"))   # nothing hand-kept


if __name__ == "__main__":
    unittest.main()
