"""Tests for app/backend.py against fake /proc/asound, sysfs and PipeWire output.
  python3 -m unittest discover tests
"""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))
import backend as be  # noqa: E402

CARDS = """ 0 [PCH            ]: HDA-Intel - HDA Intel PCH
                      HDA Intel PCH at 0xf7f10000 irq 32
 2 [GSP350         ]: USB-Audio - GSP 350
                      Sennheiser GSP 350 at usb-0000:00:14.0-2, full speed
 3 [Headset        ]: USB-Audio - Some Headset
                      Vendor Some Headset at usb-0000:00:14.0-3, full speed
"""

PW_LINKS = """effect_output.gsp_surround:output_FL
  |-> gsp_surround.main:playback_FL
effect_output.gsp_surround:output_FR
  |-> gsp_surround.main:playback_FR
alsa_input.usb-Sennheiser:capture_FL
  |-> some.app:input_FL
"""

PW_DUMP = """[
 {"id": 30, "type": "PipeWire:Interface:Node", "info": {"props": {"node.name": "effect_input.gsp_surround"}}},
 {"id": 31, "type": "PipeWire:Interface:Node", "info": {"props": {"node.name": "gsp_surround.main"}}},
 {"id": 40, "type": "PipeWire:Interface:Port", "info": {"props": {"port.name": "x"}}},
 {"id": 41, "type": "PipeWire:Interface:Node", "info": {"props": {}}}
]"""


class Backend(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        t = Path(self.tmp.name)
        self.proc = t / "asound"
        (self.proc / "card0").mkdir(parents=True)
        for n, usbid, cid in ((2, "1395:005D", "GSP350"), (3, "abcd:1234", "Headset")):
            d = self.proc / f"card{n}"
            d.mkdir()
            (d / "usbid").write_text(usbid + "\n")
            (d / "id").write_text(cid + "\n")
        (self.proc / "cards").write_text(CARDS)
        self.devices = be.load_devices()

    def tearDown(self):
        self.tmp.cleanup()

    def test_devices_conf(self):
        gsp = [d for d in self.devices if d.usbid == "1395:005d"]
        self.assertEqual(len(gsp), 1)
        self.assertEqual(gsp[0].profile, "gsp350")
        self.assertTrue(gsp[0].hid_eq)
        self.assertEqual(gsp[0].name, "Sennheiser GSP 350")

    def test_usb_cards(self):
        cards = be.usb_cards(self.proc)
        self.assertEqual(cards, [(2, "1395:005d", "GSP 350"), (3, "abcd:1234", "Some Headset")])

    def test_find_known_dongle(self):
        d = be.find_dongle(self.devices, "", self.proc)
        self.assertEqual((d.card, d.usbid, d.known, d.hid_eq), (2, "1395:005d", True, True))

    def test_find_untested_dongle(self):
        (self.proc / "card2" / "usbid").write_text("dead:beef\n")
        self.assertIsNone(be.find_dongle(self.devices, "", self.proc))
        d = be.find_dongle(self.devices, "abcd:1234", self.proc)
        self.assertEqual((d.card, d.known, d.hid_eq, d.name), (3, False, False, "Some Headset"))

    def test_untested_cards(self):
        self.assertEqual(be.untested_cards(self.devices, self.proc), [("abcd:1234", "Some Headset")])
        (self.proc / "card2" / "usbid").write_text("dead:beef\n")
        self.assertEqual([u for u, _ in be.untested_cards(self.devices, self.proc)], ["dead:beef", "abcd:1234"])

    def test_hidraw(self):
        sysfs = Path(self.tmp.name) / "hidraw"
        for n, hid in ((0, "0003:0000046D:0000C52B"), (3, "0003:00001395:0000005D")):
            (sysfs / f"hidraw{n}" / "device").mkdir(parents=True)
            (sysfs / f"hidraw{n}" / "device" / "uevent").write_text(f"DRIVER=hid-generic\nHID_ID={hid}\n")
        self.assertEqual(str(be.hidraw_for("1395:005d", sysfs)), "/dev/hidraw3")
        self.assertIsNone(be.hidraw_for("abcd:1234", sysfs))

    def test_pw_nodes(self):
        self.assertEqual(be.pw_nodes(PW_DUMP), {"effect_input.gsp_surround": 30, "gsp_surround.main": 31})
        self.assertEqual(be.pw_nodes("not json"), {})

    def test_filter_linked(self):
        self.assertTrue(be.filter_linked(PW_LINKS))
        self.assertFalse(be.filter_linked(PW_LINKS.replace("playback_FR", "nothing").replace("gsp_surround.main:nothing", "x:y")))
        self.assertFalse(be.filter_linked(""))

    def test_setup_complete(self):
        c = [be.Check(k, k, True) for k in ("tools", "ir", "filter", "service")] + [be.Check("hid", "", False)]
        self.assertTrue(be.setup_complete(c))
        c[1].ok = False
        self.assertFalse(be.setup_complete(c))


if __name__ == "__main__":
    unittest.main()
