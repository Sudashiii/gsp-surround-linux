#!/usr/bin/env python3
"""Get the measured filter file of a profile from gsp-surround-irs (or a local file) and check it.

  fetch_ir.py --profile gsp350 --dest ~/.local/share/gsp-surround [--file my.wav]

Writes <dest>/ir.wav and <dest>/profile.json (the profile's entry of index.json).
"""
import argparse
import hashlib
import json
import os
import shutil
import sys
import tempfile
import urllib.request

IRS_BASE = "https://raw.githubusercontent.com/Sudashiii/gsp-surround-irs/v1"
# hashes pinned in the app, so a changed upstream file is noticed
PINNED = {"gsp350": "45cfbaab0629583843d6d2dc328152cc94d0368e514de71370521f8b7d684c25"}
# used when the index can't be downloaded but a local file is given
FALLBACK = {"gsp350": {"name": "Sennheiser GSP 350", "file": "gsp350/gsp350_16ch.wav",
                       "sha256": PINNED["gsp350"], "rate": 48000,
                       "lfe_gain": {"off": 0.708, "game": 1.0, "music": 0.708, "esport": 0.708}}}


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 16), b""):
            h.update(block)
    return h.hexdigest()


def download(url, dest):
    with urllib.request.urlopen(url, timeout=30) as r, open(dest, "wb") as f:
        shutil.copyfileobj(r, f)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile", default="gsp350")
    ap.add_argument("--dest", required=True)
    ap.add_argument("--file", help="use this local WAV instead of downloading")
    a = ap.parse_args()
    os.makedirs(a.dest, exist_ok=True)

    try:
        with urllib.request.urlopen(f"{IRS_BASE}/index.json", timeout=30) as r:
            profiles = json.load(r)["profiles"]
    except Exception as e:  # offline: fine with a local file
        if not a.file:
            sys.exit(f"could not download the profile index ({e}). Check your internet connection, "
                     f"or pass a local file with --ir FILE")
        print(f"profile index not reachable ({e}), using built-in defaults")
        profiles = FALLBACK
    if a.profile not in profiles:
        sys.exit(f"unknown profile '{a.profile}' (available: {', '.join(profiles)})")
    prof = profiles[a.profile]
    want = prof["sha256"]
    if a.profile in PINNED and want != PINNED[a.profile]:
        sys.exit(f"hash of profile '{a.profile}' in the index differs from the one pinned in the app - refusing")

    out = os.path.join(a.dest, "ir.wav")
    with tempfile.TemporaryDirectory(dir=a.dest) as tmp:
        tmpfile = os.path.join(tmp, "ir.wav")
        if a.file:
            shutil.copyfile(a.file, tmpfile)
        else:
            url = f"{IRS_BASE}/{prof['file']}"
            print(f"downloading {url}")
            download(url, tmpfile)
        got = sha256(tmpfile)
        if got != want:
            if not a.file:
                sys.exit(f"download is corrupt: sha256 {got}, expected {want}")
            print(f"WARNING: {a.file} is not the published '{a.profile}' file (sha256 {got}) - using it anyway")
        os.replace(tmpfile, out)
    prof = dict(prof, profile=a.profile, sha256=got)
    with open(os.path.join(a.dest, "profile.json"), "w") as f:
        json.dump(prof, f, indent=2)
    print(f"filter file: {out} ({prof.get('name', a.profile)}, sha256 {got[:12]}...)")


if __name__ == "__main__":
    main()
