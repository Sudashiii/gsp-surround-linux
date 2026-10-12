"""Tests for the release pipeline: the release-notes generator (against throw-away git repositories) and
the structure of the GitHub workflow (parsed, never run; it can only run on GitHub).
  python3 -m unittest discover tests
"""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "packaging"))
import release_notes as rn  # noqa: E402

try:
    import yaml
except ImportError:                                           # the workflow tests need PyYAML
    yaml = None

HAVE_GIT = shutil.which("git") is not None
URL = "https://example.org/owner/repo"


class Classify(unittest.TestCase):
    def test_prefixes_group_and_are_stripped(self):
        cases = {
            "feat: add a switch": ("New", "Add a switch"),
            "fix(ui): log follows output": ("Fixes", "Log follows output"),
            "feat!: drop the old flag": ("New", "Drop the old flag"),
            "docs: explain the install": ("Maintenance", "Explain the install"),
            "ci: build the release": ("Maintenance", "Build the release"),
            "perf: faster poll": ("Changes", "Faster poll"),
        }
        for subject, expected in cases.items():
            self.assertEqual(rn.classify(subject), expected, subject)

    def test_plain_sentences_are_left_alone(self):
        self.assertEqual(rn.classify("Cleaned up UI in tabs"), ("Changes", "Cleaned up UI in tabs"))
        self.assertEqual(rn.classify("GSP Surround: GTK app + scripts"), ("Changes", "GSP Surround: GTK app + scripts"))
        self.assertEqual(rn.classify("note: keep this"), ("Changes", "Note: keep this"))      # not a known prefix
        self.assertEqual(rn.classify("feat:no space"), ("Changes", "Feat:no space"))


@unittest.skipUnless(HAVE_GIT, "needs git")
class Notes(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name)
        self.git("init", "-q", "-b", "main")
        self.git("config", "user.name", "Test")
        self.git("config", "user.email", "test@example.org")
        self.git("config", "commit.gpgsign", "false")

    def git(self, *args):
        return subprocess.run(["git", *args], cwd=self.path, check=True, capture_output=True, text=True).stdout

    def commit(self, subject):
        self.git("commit", "--allow-empty", "-q", "-m", subject)
        return self.git("rev-parse", "HEAD").strip()

    def notes(self, *args):
        argv = ["--cwd", str(self.path), "--repo", URL, *args]
        with mock.patch("sys.stdout") as out:
            rn.main(argv)
        return "".join(call.args[0] for call in out.write.call_args_list)

    def test_lists_the_commits_since_the_previous_tag_newest_first_with_links(self):
        self.commit("Old one")
        self.commit("Old two")
        self.git("tag", "v1.0.0")
        first = self.commit("Added the log tab")
        second = self.commit("Fixed the window height")
        self.git("tag", "v1.1.0")
        text = self.notes("--tag", "v1.1.0")
        self.assertIn("## What's new in 1.1.0", text)
        self.assertNotIn("Old one", text)
        self.assertLess(text.index("Fixed the window height"), text.index("Added the log tab"))   # newest first
        self.assertIn(f"[`{second[:7]}`]({URL}/commit/{second})", text)
        self.assertIn(f"[`{first[:7]}`]({URL}/commit/{first})", text)
        self.assertIn(f"**Full changelog:** [v1.0.0...v1.1.0]({URL}/compare/v1.0.0...v1.1.0)", text)

    def test_the_first_release_lists_everything(self):
        self.commit("First thing")
        self.commit("Second thing")
        self.git("tag", "v1.0.0")
        text = self.notes("--tag", "v1.0.0")
        self.assertIn("First thing", text)
        self.assertIn("Second thing", text)
        self.assertIn(f"**All commits:** [v1.0.0]({URL}/commits/v1.0.0)", text)
        self.assertNotIn("Full changelog", text)

    def test_groups_and_a_collapsed_maintenance_section(self):
        self.commit("Plain sentence")
        self.commit("feat: new switch")
        self.commit("fix: crash on start")
        self.commit("docs: readme")
        self.commit("chore: tidy")
        self.git("tag", "v1.0.0")
        text = self.notes("--tag", "v1.0.0")
        order = [text.index(h) for h in ("### New", "### Fixes", "### Changes", "<summary>Maintenance (2)</summary>")]
        self.assertEqual(order, sorted(order))
        self.assertIn("<details>", text)
        self.assertIn("</details>", text)
        self.assertIn("- New switch (", text)
        self.assertNotIn("feat:", text)

    def test_merges_release_bumps_and_skipped_commits_are_left_out(self):
        self.commit("Base")
        self.git("tag", "v1.0.0")
        self.git("checkout", "-q", "-b", "side")
        self.commit("Work on a branch")
        self.git("checkout", "-q", "main")
        self.commit("Work on main")
        self.git("merge", "--no-ff", "-q", "-m", "Merge branch 'side'", "side")
        self.commit("Release 1.1.0")
        self.commit("Bump version to 1.1.0")
        self.commit("tweak [skip changelog]")
        self.git("tag", "v1.1.0")
        text = self.notes("--tag", "v1.1.0")
        self.assertIn("Work on a branch", text)
        self.assertIn("Work on main", text)
        for left_out in ("Merge branch", "Release 1.1.0", "Bump version", "tweak"):
            self.assertNotIn(left_out, text)

    def test_a_stable_release_skips_prerelease_tags_when_looking_back(self):
        self.commit("Base")
        self.git("tag", "v1.0.0")
        self.commit("Before the candidate")
        self.git("tag", "v1.1.0-rc1")
        self.commit("After the candidate")
        self.git("tag", "v1.1.0")
        stable = self.notes("--tag", "v1.1.0")
        self.assertIn("Before the candidate", stable)                # everything since the last stable release
        self.assertIn("After the candidate", stable)
        self.assertIn("[v1.0.0...v1.1.0]", stable)
        candidate = self.notes("--tag", "v1.1.0-rc1")
        self.assertIn("Before the candidate", candidate)
        self.assertNotIn("After the candidate", candidate)
        self.assertIn("[v1.0.0...v1.1.0-rc1]", candidate)

    def test_candidates_are_compared_with_each_other_and_two_tags_on_one_commit_are_fine(self):
        self.commit("Base")
        self.git("tag", "v1.0.0")
        self.commit("Candidate one work")
        self.git("tag", "v1.1.0-rc1")
        self.commit("Candidate two work")
        self.git("tag", "v1.1.0-rc2")
        self.git("tag", "v1.1.0")                                    # the release is the same commit as rc2
        second = self.notes("--tag", "v1.1.0-rc2")
        self.assertIn("[v1.1.0-rc1...v1.1.0-rc2]", second)
        self.assertIn("Candidate two work", second)
        self.assertNotIn("Candidate one work", second)
        stable = self.notes("--tag", "v1.1.0")
        self.assertIn("[v1.0.0...v1.1.0]", stable)                   # candidates are skipped, nothing is lost
        self.assertIn("Candidate one work", stable)
        self.assertIn("Candidate two work", stable)

    def test_tags_that_are_not_versions_are_ignored(self):
        self.commit("Base")
        self.git("tag", "v1.0.0")
        self.commit("Later")
        self.git("tag", "vnext")
        self.git("tag", "v2")
        self.commit("Even later")
        self.git("tag", "v1.1.0")
        self.assertIn("[v1.0.0...v1.1.0]", self.notes("--tag", "v1.1.0"))

    def test_a_rehearsal_on_a_branch_has_no_links_to_a_tag(self):
        self.commit("Something")
        self.git("tag", "v1.0.0")
        self.commit("Work after the tag")
        text = self.notes("--tag", "HEAD", "--version", "1.1.0")
        self.assertIn("## What's new in 1.1.0", text)
        self.assertIn("Work after the tag", text)
        self.assertNotIn("Full changelog", text)
        self.assertIn("gsp-surround_1.1.0_all.deb", text)

    def test_no_commits_says_so(self):
        self.commit("Only")
        self.git("tag", "v1.0.0")
        self.git("tag", "v1.0.1")
        text = self.notes("--tag", "v1.0.1")
        self.assertIn("No changes recorded.", text)

    def test_install_hints_and_checksums(self):
        self.commit("Something")
        self.git("tag", "v1.2.3")
        sums = self.path / "SHA256SUMS"
        sums.write_text("abc123  gsp-surround_1.2.3_all.deb\n")
        text = self.notes("--tag", "v1.2.3", "--checksums", str(sums))
        self.assertIn("`gsp-surround_1.2.3_all.deb`", text)
        self.assertIn("`gsp-surround-1.2.3.tar.gz`", text)
        self.assertIn("```text\nabc123  gsp-surround_1.2.3_all.deb\n```", text)

    def test_the_repository_url_comes_from_origin_or_from_github_actions(self):
        self.commit("Something")
        self.git("remote", "add", "origin", "git@github.com:Owner/Repo.git")
        clean = {k: v for k, v in os.environ.items() if not k.startswith("GITHUB_")}
        with mock.patch.dict(os.environ, clean, clear=True):
            self.assertEqual(rn.repo_url(cwd=self.path), "https://github.com/Owner/Repo")
            self.git("remote", "set-url", "origin", "https://github.com/Owner/Other.git")
            self.assertEqual(rn.repo_url(cwd=self.path), "https://github.com/Owner/Other")
            self.assertEqual(rn.repo_url("https://example.org/x/y/", cwd=self.path), "https://example.org/x/y")
        with mock.patch.dict(os.environ, {"GITHUB_SERVER_URL": "https://github.com", "GITHUB_REPOSITORY": "A/B"}):
            self.assertEqual(rn.repo_url(cwd=self.path), "https://github.com/A/B")


@unittest.skipUnless(yaml, "needs PyYAML")
class Workflow(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = (REPO / ".github/workflows/release.yml").read_text()
        cls.doc = yaml.safe_load(cls.text)
        cls.jobs = cls.doc["jobs"]

    def steps(self, job):
        return self.jobs[job]["steps"]

    def runs(self, job):
        return "\n".join(step.get("run", "") for step in self.steps(job))

    def test_triggers_are_a_version_tag_and_a_manual_rehearsal(self):
        triggers = self.doc.get("on", self.doc.get(True))             # YAML 1.1 reads a bare `on` as true
        self.assertEqual(triggers["push"]["tags"], ["v*"])
        self.assertIn("workflow_dispatch", triggers)
        self.assertNotIn("pull_request", triggers)
        self.assertNotIn("branches", triggers["push"])

    def test_only_the_publish_job_may_write(self):
        self.assertEqual(self.doc["permissions"], {"contents": "read"})
        self.assertNotIn("permissions", self.jobs["build"])
        self.assertEqual(self.jobs["publish"]["permissions"], {"contents": "write"})

    def test_publishing_needs_a_tag_and_a_successful_build(self):
        self.assertEqual(self.jobs["publish"]["needs"], "build")
        self.assertIn("github.ref_type == 'tag'", self.jobs["publish"]["if"])

    def test_the_build_checks_everything_before_anything_is_published(self):
        runs = self.runs("build")
        self.assertIn("VERSION", runs)                                # the tag must match VERSION
        self.assertIn("make test", runs)
        self.assertIn("make check STRICT=1", runs)
        self.assertIn("make artifacts", runs)
        self.assertIn("packaging/release_notes.py", runs)
        self.assertLess(runs.index("make test"), runs.index("make artifacts"))
        checkout = next(step for step in self.steps("build") if step.get("uses", "").startswith("actions/checkout"))
        self.assertEqual(checkout["with"]["fetch-depth"], 0)          # the notes need the history and the tags

    def test_only_first_party_actions_are_used(self):
        used = [step["uses"] for job in self.jobs.values() for step in job["steps"] if "uses" in step]
        self.assertTrue(used)
        self.assertTrue(all(u.startswith("actions/") for u in used), used)

    def test_no_untrusted_text_is_pasted_into_scripts(self):
        # ${{ }} inside `run:` is a script-injection risk (tag names are user input); use environment variables
        for job in self.jobs:
            self.assertNotIn("${{", self.runs(job), job)

    def test_the_release_assets_are_the_files_the_makefile_builds(self):
        publish = self.runs("publish")
        makefile = (REPO / "Makefile").read_text()
        self.assertIn("gsp-surround_${version}_all.deb", publish)
        self.assertIn("gsp-surround-${version}.tar.gz", publish)
        self.assertIn("gsp-surround_$(VERSION)_all.deb", makefile)
        self.assertIn("gsp-surround-$(VERSION).tar.gz", makefile)
        self.assertIn("SHA256SUMS", publish)
        self.assertIn("--verify-tag", publish)
        self.assertIn("--notes-file dist/release-notes.md", publish)
        self.assertIn("--prerelease", publish)

    def test_build_output_is_never_committed(self):
        ignored = (REPO / ".gitignore").read_text().splitlines()
        self.assertIn("dist/", ignored)
        self.assertIn("build/", ignored)
        if HAVE_GIT and (REPO / ".git").exists():
            tracked = subprocess.run(["git", "ls-files"], cwd=REPO, capture_output=True, text=True,
                                     check=True).stdout.splitlines()
            built = [f for f in tracked if f.endswith((".deb", ".tar.gz")) or f.startswith(("dist/", "build/"))]
            self.assertEqual(built, [])


if __name__ == "__main__":
    unittest.main()
