#!/usr/bin/env python3
"""gsp-surround backend: device detection, setup checks and the calls into scripts/.

No GTK imports here, so the terminal commands work without the GUI libraries:
  python3 app/backend.py check
"""
import hashlib
import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent          # repo clone or installed app
SCRIPTS = ROOT / "scripts"
HOME = Path.home()
DATA = Path(os.environ.get("XDG_DATA_HOME", HOME / ".local/share")) / "gsp-surround"
CONF = Path(os.environ.get("XDG_CONFIG_HOME", HOME / ".config")) / "gsp-surround"
PW_CONF = Path(os.environ.get("XDG_CONFIG_HOME", HOME / ".config")) / "pipewire/pipewire.conf.d/gsp-surround.conf"
IR = DATA / "ir.wav"
PROFILE_JSON = DATA / "profile.json"
UDEV_RULE = Path("/etc/udev/rules.d/70-gsp-surround.rules")
SERVICE = "gsp-surround.service"
NODE_IN, NODE_OUT, NODE_MAIN = "effect_input.gsp_surround", "effect_output.gsp_surround", "gsp_surround.main"
REPO_URL = "https://github.com/Sudashiii/gsp-surround-linux"
MANUAL_URL = REPO_URL + "#manual-installation"

PRESETS = [  # (id, label, description)
    ("off", "Off", "Flat EQ in the dongle, surround stays on"),
    ("game", "Game", "Game EQ in the dongle, bass channel +3 dB"),
    ("music", "Music", "Music EQ in the dongle"),
    ("esport", "eSports", "eSports EQ in the dongle"),
]


@dataclass
class Device:
    usbid: str
    profile: str
    hid_eq: bool
    name: str


@dataclass
class Dongle:
    card: int
    usbid: str
    name: str
    known: bool          # listed in data/devices.conf (tested)
    hid_eq: bool


@dataclass
class Check:
    key: str
    title: str
    ok: object           # True / False / None (not applicable right now)
    hint: str = ""


# --- state ------------------------------------------------------------------------------------
def _read(path, default=""):
    try:
        return Path(path).read_text().strip() or default
    except OSError:
        return default


def saved_preset():
    return _read(CONF / "preset", "game")


def saved_surround():
    return _read(CONF / "surround", "on")


def manual_device():
    return _read(CONF / "device").lower()


def set_manual_device(usbid):
    CONF.mkdir(parents=True, exist_ok=True)
    if usbid:
        (CONF / "device").write_text(usbid + "\n")
    else:
        (CONF / "device").unlink(missing_ok=True)


def profile_info():
    try:
        return json.loads(PROFILE_JSON.read_text())
    except (OSError, ValueError):
        return {}


# --- devices ----------------------------------------------------------------------------------
def load_devices(path=ROOT / "data/devices.conf"):
    devs = []
    for line in Path(path).read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        usbid, profile, hid, *name = line.split()
        devs.append(Device(usbid.lower(), profile, hid.lower() == "yes", " ".join(name)))
    return devs


def usb_cards(proc="/proc/asound"):
    """[(card index, vid:pid, card name)] of all USB audio cards."""
    cards = []
    names = {}
    for line in _read(Path(proc) / "cards").splitlines():   # " 2 [GSP350         ]: USB-Audio - GSP 350"
        parts = line.split("]:", 1)
        if len(parts) == 2 and parts[0].strip().split(" ")[0].isdigit():
            names[int(parts[0].strip().split(" ")[0])] = parts[1].split(" - ", 1)[-1].strip()
    for d in sorted(Path(proc).glob("card[0-9]*")):
        usbid = _read(d / "usbid").lower()
        if usbid:
            n = int(d.name[4:])
            cards.append((n, usbid, names.get(n, _read(d / "id"))))
    return cards


def find_dongle(devices=None, manual=None, proc="/proc/asound"):
    devices = load_devices() if devices is None else devices
    manual = manual_device() if manual is None else manual
    by_id = {d.usbid: d for d in devices}
    for card, usbid, cname in usb_cards(proc):
        if usbid in by_id:
            d = by_id[usbid]
            return Dongle(card, usbid, d.name, True, d.hid_eq)
        if manual and usbid == manual:
            return Dongle(card, usbid, cname or usbid, False, False)
    return None


def hidraw_for(usbid, sysfs="/sys/class/hidraw"):
    vid, pid = usbid.split(":")
    want = f"HID_ID=0003:0000{vid}:0000{pid}".upper()
    for d in sorted(Path(sysfs).glob("hidraw*")):
        if want in _read(d / "device/uevent").upper().splitlines():
            return Path("/dev") / d.name
    return None


# --- PipeWire / systemd -----------------------------------------------------------------------
def _out(cmd, timeout=5):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def pw_nodes(dump_text=None):
    """{node.name: id} from pw-dump."""
    try:
        objs = json.loads(dump_text if dump_text is not None else _out(["pw-dump"]))
    except ValueError:
        return {}
    return {o["info"]["props"]["node.name"]: o["id"] for o in objs
            if o.get("type", "").endswith(":Node") and "node.name" in o.get("info", {}).get("props", {})}


def filter_linked(links_text=None):
    """True if both filter outputs are linked to the dongle's main path (pw-link -l)."""
    text = links_text if links_text is not None else _out(["pw-link", "-l"])
    linked, port = set(), None
    for line in text.splitlines():
        if not line.startswith(" "):
            port = line.strip()
        elif port and port.startswith(NODE_OUT + ":") and "|->" in line and NODE_MAIN + ":" in line:
            linked.add(port.split(":", 1)[1])
    return {"output_FL", "output_FR"} <= linked


def _active(unit):
    return _out(["systemctl", "--user", "is-active", unit]).strip() == "active"


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 16), b""):
            h.update(block)
    return h.hexdigest()


# --- checks -----------------------------------------------------------------------------------
def run_checks():
    c = []
    missing = [t for t in ("pw-cli", "pw-dump", "pw-link", "wpctl", "systemctl") if not shutil.which(t)]
    c.append(Check("tools", "PipeWire tools", not missing,
                   "missing: " + ", ".join(missing) if missing else "pw-cli, pw-dump, pw-link, wpctl"))
    pulse = _active("pulseaudio.service")
    pw = _active("pipewire.service")
    c.append(Check("server", "PipeWire is the sound server", pw and not pulse,
                   "PulseAudio is still running" if pulse else ("" if pw else "pipewire.service is not running")))
    c.append(Check("wireplumber", "WirePlumber session manager", _active("wireplumber.service"),
                   "" if _active("wireplumber.service") else "wireplumber.service is not running"))

    prof = profile_info()
    if IR.exists() and prof:
        good = _sha256(IR) == prof.get("sha256")
        c.append(Check("ir", "Filter file", good, (prof.get("name", prof.get("profile", "")) if good
                                                   else "file changed or damaged - reinstall")))
    else:
        c.append(Check("ir", "Filter file", False, "not downloaded yet"))

    nodes = pw_nodes()
    if not PW_CONF.exists():
        c.append(Check("filter", "Virtual 7.1 device", False, "not installed"))
    else:
        c.append(Check("filter", "Virtual 7.1 device", NODE_IN in nodes,
                       "GSP Virtual Surround 7.1" if NODE_IN in nodes else "installed but not running - restart PipeWire or log out/in"))
    enabled = _out(["systemctl", "--user", "is-enabled", SERVICE]).strip() == "enabled"
    c.append(Check("service", "Background service", enabled,
                   "re-applies everything at login and plug-in" if enabled else "not installed"))
    c.append(Check("udev", "Device rule (udev)", UDEV_RULE.exists(),
                   str(UDEV_RULE) if UDEV_RULE.exists() else "not installed (needs your password once)"))

    dongle = find_dongle()
    c.append(Check("dongle", "Headset dongle", True if dongle else None,
                   f"{dongle.name} ({dongle.usbid}, card {dongle.card})" if dongle else "not connected"))
    if dongle and dongle.hid_eq:
        hid = hidraw_for(dongle.usbid)
        okw = bool(hid) and os.access(hid, os.W_OK)
        c.append(Check("hid", "EQ control", okw, str(hid) if okw else
                       ("no access - unplug and replug the dongle once" if hid else "HID interface not found")))
    else:
        c.append(Check("hid", "EQ control", None, "untested device: EQ presets not sent" if dongle else "dongle not connected"))
    if dongle and NODE_IN in nodes:
        okl = NODE_MAIN in nodes and filter_linked()
        c.append(Check("linked", "Sound routed to the dongle", okl, "main audio path" if okl else
                       "not linked - press Re-apply or replug the dongle"))
    else:
        c.append(Check("linked", "Sound routed to the dongle", None, "dongle not connected" if not dongle else ""))
    return c


def setup_complete(checks):
    st = {k.key: k.ok for k in checks}
    return all(st.get(k) for k in ("tools", "ir", "filter", "service"))


# --- actions ----------------------------------------------------------------------------------
def script_cmd(name, *args):
    path = SCRIPTS / name
    return ["bash", str(path), *args] if name.endswith(".sh") else ["python3", str(path), *args]


def run(cmd, on_line=None):
    """Run a command, pass each output line to on_line (stdout+stderr), return the exit code."""
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                         text=True, bufsize=1)
    for line in p.stdout:
        if on_line:
            on_line(line.rstrip("\n"))
    return p.wait()


def set_preset(preset, on_line=None):
    return run(script_cmd("preset.sh", preset), on_line)


def set_surround(on, on_line=None):
    return run(script_cmd("surround.sh", "on" if on else "off"), on_line)


def apply(on_line=None):
    return run(script_cmd("apply.sh"), on_line)


def install(on_line=None):
    return run(script_cmd("install.sh", "--yes"), on_line)


def uninstall(on_line=None):
    return run(script_cmd("uninstall.sh"), on_line)


# --- terminal ---------------------------------------------------------------------------------
def main(argv):
    if argv[:1] != ["check"]:
        print("usage: backend.py check")
        return 2
    mark = {True: "[ok]  ", False: "[FAIL]", None: "[--]  "}
    checks = run_checks()
    for k in checks:
        print(f"  {mark[k.ok]} {k.title:<30} {k.hint}")
    print(f"  preset: {saved_preset()}, surround: {saved_surround()}")
    return 0 if all(k.ok is not False for k in checks) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
