import io
import sys
import tempfile
import unittest
from pathlib import Path
from printer_craft.cli import main


class TestCLI(unittest.TestCase):
    def test_cli_help(self):
        saved_stdout = sys.stdout
        try:
            sys.stdout = io.StringIO()
            with self.assertRaises(SystemExit) as cm:
                main(["--help"])
            self.assertEqual(cm.exception.code, 0)
            output = sys.stdout.getvalue()
            self.assertIn("Universal CLI printing tool", output)
        finally:
            sys.stdout = saved_stdout

    def test_cli_dry_run(self):
        saved_stdout = sys.stdout
        try:
            sys.stdout = io.StringIO()
            with tempfile.TemporaryDirectory() as tmp_dir:
                doc = Path(tmp_dir) / "test.pdf"
                doc.write_text("%PDF-1.4 sample")

                code = main(["print", str(doc), "--dry-run", "--copies", "2", "--color", "monochrome"])
                self.assertEqual(code, 0)

                output = sys.stdout.getvalue()
                self.assertIn("=== DRY RUN MODE ===", output)
                self.assertIn("-n 2", output)
                self.assertIn("print-color-mode=monochrome", output)
                self.assertIn("fit-to-page=true", output)

            # Test --no-fit-to-page
            sys.stdout = io.StringIO()
            with tempfile.TemporaryDirectory() as tmp_dir:
                doc = Path(tmp_dir) / "test.pdf"
                doc.write_text("%PDF-1.4 sample")

                code = main(["print", str(doc), "--dry-run", "--no-fit-to-page"])
                self.assertEqual(code, 0)
                output = sys.stdout.getvalue()
                self.assertIn("fit-to-page=false", output)
        finally:
            sys.stdout = saved_stdout

    def test_cli_list(self):
        saved_stdout = sys.stdout
        try:
            sys.stdout = io.StringIO()
            code = main(["list"])
            self.assertEqual(code, 0)
            output = sys.stdout.getvalue().lower()
            self.assertTrue("printer" in output or "no printers" in output)
        finally:
            sys.stdout = saved_stdout


if __name__ == "__main__":
    unittest.main()
