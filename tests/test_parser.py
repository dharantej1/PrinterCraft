import unittest
from unittest.mock import MagicMock
from printer_craft.core import PrinterManager


LPSTAT_SAMPLE = """printer HP_LaserJet_Professional_M1136_MFP is idle.  enabled since Sun Oct 25 16:02:51 2026
printer Office_Canon_MF is printing.  enabled since Sun Oct 25 15:00:00 2026
system default destination: HP_LaserJet_Professional_M1136_MFP
"""

LPOPTIONS_SAMPLE = """PageSize/Media Size: *Letter Legal A4 Executive 8.5x13Custom A5 A6
Duplex/2-Sided Printing: *None DuplexNoTumble DuplexTumble
MediaType/Media Type: *Paper Heavy111-130g TransparencyPaper
Resolutions/Resolution: *600x400dpi 600x600dpi
EconoMode/Economode: True *False
"""


class TestParser(unittest.TestCase):
    def test_parse_lpstat(self):
        mgr = PrinterManager()
        mgr._run_cmd = MagicMock(side_effect=[
            (0, LPSTAT_SAMPLE, ""),  # lpstat -p -d
            (0, "HP_LaserJet_Professional_M1136_MFP\nOffice_Canon_MF", ""),  # lpstat -e
        ])

        printers = mgr.list_printers(load_options=False)
        self.assertEqual(len(printers), 2)

        p1 = next(p for p in printers if p.name == "HP_LaserJet_Professional_M1136_MFP")
        self.assertTrue(p1.is_default)
        self.assertIn("idle", p1.status)

        p2 = next(p for p in printers if p.name == "Office_Canon_MF")
        self.assertFalse(p2.is_default)
        self.assertIn("printing", p2.status)

    def test_parse_lpoptions(self):
        mgr = PrinterManager()
        mgr._run_cmd = MagicMock(return_value=(0, LPOPTIONS_SAMPLE, ""))

        options = mgr.get_printer_options("HP_LaserJet_Professional_M1136_MFP")
        self.assertIn("PageSize", options)
        self.assertIn("Duplex", options)
        self.assertIn("Resolutions", options)
        self.assertIn("EconoMode", options)

        # Check PageSize
        ps = options["PageSize"]
        self.assertEqual(ps.display_name, "Media Size")
        self.assertIsNotNone(ps.default_choice)
        self.assertEqual(ps.default_choice.name, "Letter")
        self.assertTrue(any(c.name == "A4" for c in ps.choices))

        # Check EconoMode
        em = options["EconoMode"]
        self.assertIsNotNone(em.default_choice)
        self.assertEqual(em.default_choice.name, "False")


if __name__ == "__main__":
    unittest.main()
