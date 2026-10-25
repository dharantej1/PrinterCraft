import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock
from printer_craft.core import PrinterManager
from printer_craft.models import PrintJobOptions


class TestCore(unittest.TestCase):
    def test_dry_run_print_document(self):
        mgr = PrinterManager()
        mock_p = MagicMock()
        mock_p.name = "TestPrinter"
        mock_p.is_default = True
        mgr.list_printers = MagicMock(return_value=[mock_p])

        with tempfile.TemporaryDirectory() as tmp_dir:
            test_file = Path(tmp_dir) / "sample.pdf"
            test_file.write_text("%PDF-1.4 sample content")

            opts = PrintJobOptions(printer="TestPrinter", copies=2, dry_run=True)
            result = mgr.print_document(test_file, options=opts)

            self.assertTrue(result.success)
            self.assertTrue(result.dry_run)
            self.assertEqual(result.printer, "TestPrinter")
            self.assertIn("-n", result.command_run)
            self.assertIn(str(test_file.resolve()), result.command_run)

    def test_print_bytes_dry_run(self):
        mgr = PrinterManager()
        mock_p = MagicMock()
        mock_p.name = "TestPrinter"
        mgr.get_default_printer = MagicMock(return_value=mock_p)

        data = b"%PDF-1.4 dummy bytes"
        opts = PrintJobOptions(copies=1, dry_run=True)

        result = mgr.print_bytes(data, title="Stream Test", options=opts)
        self.assertTrue(result.success)
        self.assertTrue(result.dry_run)
        self.assertEqual(result.printer, "TestPrinter")


if __name__ == "__main__":
    unittest.main()
