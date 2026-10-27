import unittest
from unittest.mock import patch

from printer_craft.backends import CUPSBackend, PrinterBackend, Win32Backend
from printer_craft.core import PrinterManager


class TestBackendSelection(unittest.TestCase):
    def test_non_win32_platforms_always_select_cups(self):
        for platform in ("darwin", "linux", "freebsd14", "cygwin", "aix"):
            with self.subTest(platform=platform), patch("printer_craft.core.sys.platform", platform):
                mgr = PrinterManager()
                self.assertIsInstance(mgr.backend, CUPSBackend)
                self.assertNotIsInstance(mgr.backend, Win32Backend)

    def test_win32_selects_win32_backend(self):
        with patch("printer_craft.core.sys.platform", "win32"):
            mgr = PrinterManager()
        self.assertIsInstance(mgr.backend, Win32Backend)
        with self.assertRaises(AttributeError):
            mgr.lp_bin

    def test_cups_binary_overrides_reach_backend(self):
        with patch("printer_craft.core.sys.platform", "darwin"):
            mgr = PrinterManager(
                lp_bin="/opt/lp",
                lpstat_bin="/opt/lpstat",
                lpoptions_bin="/opt/lpoptions",
                cancel_bin="/opt/cancel",
            )
        self.assertEqual(mgr.backend.lp_bin, "/opt/lp")
        self.assertEqual(mgr.backend.lpstat_bin, "/opt/lpstat")
        self.assertEqual(mgr.backend.lpoptions_bin, "/opt/lpoptions")
        self.assertEqual(mgr.backend.cancel_bin, "/opt/cancel")
        self.assertEqual(mgr.lp_bin, "/opt/lp")
        mgr.lp_bin = "/usr/local/bin/lp"
        self.assertEqual(mgr.backend.lp_bin, "/usr/local/bin/lp")

    def test_backends_implement_interface(self):
        self.assertTrue(issubclass(CUPSBackend, PrinterBackend))
        self.assertTrue(issubclass(Win32Backend, PrinterBackend))
        with self.assertRaises(TypeError):
            PrinterBackend()


if __name__ == "__main__":
    unittest.main()
