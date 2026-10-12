#!/usr/bin/env python3
"""Release notes from the commit messages: what changed since the previous release.

  python3 packaging/release_notes.py --tag v1.1.0 [--prev v1.0.0] [--version 1.1.0]
                                     [--repo URL] [--checksums dist/SHA256SUMS]

Prints Markdown. The subject (first line) of every commit between the previous release tag and --tag is
listed, newest first, with a link to the commit. An optional Conventional-Commits prefix groups them:
`feat:` -> New, `fix:` -> Fixes, `docs: test: ci: build: chore: style: refactor:` -> Maintenance (collapsed);
everything else, plain sentences included, goes to Changes. Merge commits and release-bump commits
("Release 1.2.0", "Bump version to 1.2.0") are left out, as is anything marked [skip changelog].

The previous release is the newest `vX.Y.Z` tag with a lower version that is part of the history; for a
stable release pre-release tags such as v1.1.0-rc1 are skipped, so the notes cover everything since the last
stable release.
"""
import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

SECTIONS = ("New", "Fixes", "Changes", "Maintenance")
GROUP_OF = {"feat": "New", "fix": "Fixes", "perf": "Changes",
            "docs": "Maintenance", "test": "Maintenance", "tests": "Maintenance", "ci": "Maintenance",
            "build": "Maintenance", "chore": "Maintenance", "style": "Maintenance", "refactor": "Maintenance"}
PREFIX = re.compile(r"^(?P<type>[a-z]+)(?:\([^)]*\))?!?:\s+(?P<text>\S.*)$")
VERSION_TAG = re.compile(r"^v(\d+)\.(\d+)\.(\d+)(?:-(.+))?$")
LEFT_OUT = re.compile(r"^(?:release|bump version)\b.*\d+\.\d+|^chore\(release\)|\[skip changelog\]", re.IGNORECASE)


def git(*args, cwd=None):
    return subprocess.run(["git", *args], check=True, capture_output=True, text=True, cwd=cwd).stdout


def version_key(tag):
    """Sort key of a `vX.Y.Z[-pre]` tag (a release sorts after its own pre-releases), None for other tags."""
    m = VERSION_TAG.match(tag)
    return (int(m[1]), int(m[2]), int(m[3]), m[4] is None, m[4] or "") if m else None


def previous_tag(version, rev, cwd=None):
    """The newest release tag below `version` among the tags in the history of `rev` (None: first release).
    Pre-release tags only count when `version` is a pre-release itself."""
    current = version_key(f"v{version}")
    stable = current is not None and current[3]
    found = [(version_key(tag), tag) for tag in git("tag", "--list", "v*", "--merged", rev, cwd=cwd).split()]
    older = [(key, tag) for key, tag in found
             if key and (current is None or key < current) and (key[3] or not stable)]
    return max(older)[1] if older else None


def commits(rev, prev, cwd=None):
    """[(full hash, short hash, subject)] newest first, without merges."""
    span = f"{prev}..{rev}" if prev else rev
    out = git("log", "--no-merges", "--format=%H%x1f%h%x1f%s%x1e", span, cwd=cwd)
    rows = [row.strip("\n").split("\x1f") for row in out.split("\x1e") if row.strip()]
    return [(full, short, subject) for full, short, subject in rows]


def repo_url(explicit=None, cwd=None):
    """https URL of the repository: --repo, else the GitHub Actions environment, else `origin`."""
    if explicit:
        return explicit.rstrip("/")
    server, repo = os.environ.get("GITHUB_SERVER_URL"), os.environ.get("GITHUB_REPOSITORY")
    if server and repo:
        return f"{server}/{repo}"
    try:
        remote = git("remote", "get-url", "origin", cwd=cwd).strip()
    except subprocess.CalledProcessError:
        return None
    m = re.match(r"^(?:git@|ssh://git@|https?://)(?P<host>[^:/]+)[:/](?P<path>.+?)(?:\.git)?/?$", remote)
    return f"https://{m['host']}/{m['path']}" if m else None


def classify(subject):
    """(section, text to show) for a commit subject."""
    m = PREFIX.match(subject)
    if m and m["type"] in GROUP_OF:
        subject, section = m["text"], GROUP_OF[m["type"]]
    else:
        section = "Changes"
    return section, subject[:1].upper() + subject[1:]


def render(version, tag, prev, rows, repo=None, tag_exists=True, checksums=None):
    groups = {name: [] for name in SECTIONS}
    for full, short, subject in rows:
        if LEFT_OUT.search(subject):
            continue
        section, text = classify(subject)
        link = f"[`{short}`]({repo}/commit/{full})" if repo else f"`{short}`"
        groups[section].append(f"- {text} ({link})")

    lines = [f"## What's new in {version}", ""]
    if not any(groups.values()):
        lines += ["No changes recorded.", ""]
    for name in SECTIONS:
        entries = groups[name]
        if not entries:
            continue
        if name == "Maintenance":
            lines += ["<details>", f"<summary>Maintenance ({len(entries)})</summary>", "", *entries, "",
                      "</details>", ""]
        else:
            lines += [f"### {name}", "", *entries, ""]
    if repo and tag_exists:
        if prev:
            lines += [f"**Full changelog:** [{prev}...{tag}]({repo}/compare/{prev}...{tag})", ""]
        else:
            lines += [f"**All commits:** [{tag}]({repo}/commits/{tag})", ""]
    lines += [
        "## Install", "",
        f"- **Debian, Ubuntu, Linux Mint:** download `gsp-surround_{version}_all.deb` below and double-click it. "
        "Then open *GSP Surround* from your application menu and use *Setup → Set up*.",
        f"- **Other distributions:** download `gsp-surround-{version}.tar.gz`, unpack it and run "
        "`sudo make install` (see the README), or run the app from a clone.", "",
    ]
    if checksums:
        lines += ["## Checksums (SHA-256)", "", "```text", checksums.strip(), "```", ""]
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tag", required=True, help="the release tag (or any revision for a rehearsal)")
    ap.add_argument("--prev", help="previous release tag (default: the nearest v* tag before --tag)")
    ap.add_argument("--version", help="version to show (default: --tag without the leading v)")
    ap.add_argument("--repo", help="repository URL for the links (default: from GitHub Actions or `origin`)")
    ap.add_argument("--checksums", help="file with SHA-256 sums to append")
    ap.add_argument("--cwd", help="run git in this directory")
    a = ap.parse_args(argv)

    version = a.version or (a.tag[1:] if a.tag.startswith("v") else a.tag)
    prev = a.prev or previous_tag(version, a.tag, cwd=a.cwd)
    try:
        git("rev-parse", "-q", "--verify", f"refs/tags/{a.tag}", cwd=a.cwd)
        tag_exists = True
    except subprocess.CalledProcessError:
        tag_exists = False                      # a rehearsal on a branch: there is no tag to link to
    checksums = Path(a.checksums).read_text(encoding="utf-8") if a.checksums else None
    sys.stdout.write(render(version, a.tag, prev, commits(a.tag, prev, cwd=a.cwd), repo_url(a.repo, cwd=a.cwd),
                            tag_exists, checksums))


if __name__ == "__main__":
    main()
