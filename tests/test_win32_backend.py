import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from printer_craft.backends import win32_backend
from printer_craft.backends.win32_backend import JOB_CONTROL_CANCEL, Win32Backend
from printer_craft.converter import DocumentConverter
from printer_craft.core import PrinterManager
from printer_craft.exceptions import DocumentConversionError, SpoolerUnavailableError
from printer_craft.models import ColorMode, DuplexMode, Orientation, PrintJobOptions

HANDLE = object()


def make_devmode():
    return SimpleNamespace(
        Fields=0,
        Copies=1,
        Duplex=1,
        Color=2,
        Orientation=1,
        PaperSize=1,
        FormName="Letter",
        Collate=1,
        DefaultSource=7,
    )


def make_win32print():
    api = MagicMock(name="win32print")
    api.EnumPrinters.return_value = [
        {"pPrinterName": "HP LaserJet", "Status": 0, "pComment": "Office", "pLocation": "Floor 2"},
        {"pPrinterName": "Microsoft Print to PDF", "Status": 0x400, "pComment": "", "pDriverName": "MSPDF"},
    ]
    api.GetDefaultPrinter.return_value = "HP LaserJet"
    api.OpenPrinter.return_value = HANDLE
    api.GetPrinter.side_effect = lambda h, level: {"pPortName": "USB001", "pDevMode": make_devmode()}

    caps = {
        win32_backend.DC_PAPERNAMES: ["Letter", "A4", "Legal\x00\x00"],
        win32_backend.DC_BINNAMES: ["Auto", "Tray 1"],
        win32_backend.DC_BINS: [15, 7],
        win32_backend.DC_DUPLEX: 1,
        win32_backend.DC_COLORDEVICE: 1,
        win32_backend.DC_COLLATE: 1,
        win32_backend.DC_COPIES: 999,
    }
    api.DeviceCapabilities.side_effect = lambda name, port, cap, dm=None: caps.get(cap)
    api.StartDocPrinter.return_value = 42
    api.EnumJobs.return_value = [
        {"JobId": 42, "pPrinterName": "HP LaserJet", "pUserName": "alice", "Size": 2048, "Submitted": None},
        {"JobId": 43, "pPrinterName": "HP LaserJet", "pUserName": "bob", "Size": 10, "Submitted": None},
    ]
    return api


class Win32TestCase(unittest.TestCase):
    def setUp(self):
        self.api = make_win32print()
        patcher = patch.object(win32_backend, "win32print", self.api)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.backend = Win32Backend()


class TestWin32Discovery(Win32TestCase):
    def test_list_printers(self):
        printers = self.backend.list_printers()
        self.assertEqual([p.name for p in printers], ["HP LaserJet", "Microsoft Print to PDF"])
        self.assertTrue(printers[0].is_default)
        self.assertFalse(printers[1].is_default)
        self.assertEqual(printers[0].status, "is idle.")
        self.assertEqual(printers[1].status, "is printing.")
        self.assertEqual(printers[0].location, "Floor 2")
        self.assertEqual(printers[1].description, "MSPDF")
        flags = self.api.EnumPrinters.call_args[0][0]
        self.assertEqual(flags, win32_backend.PRINTER_ENUM_LOCAL | win32_backend.PRINTER_ENUM_CONNECTIONS)

    def test_default_printer(self):
        self.assertEqual(self.backend.get_default_printer().name, "HP LaserJet")

    def test_no_default_picks_first(self):
        self.api.GetDefaultPrinter.side_effect = Exception("no default")
        self.assertEqual(self.backend.get_default_printer().name, "HP LaserJet")

    def test_no_printers(self):
        self.api.EnumPrinters.return_value = []
        self.assertEqual(self.backend.list_printers(), [])
        self.assertIsNone(self.backend.get_default_printer())

    def test_enum_failure_raises_spooler_error(self):
        self.api.EnumPrinters.side_effect = Exception("RPC server unavailable")
        with self.assertRaises(SpoolerUnavailableError):
            self.backend.list_printers()

    def test_printer_options(self):
        options = self.backend.get_printer_options("HP LaserJet")
        self.assertEqual([c.name for c in options["PageSize"].choices], ["Letter", "A4", "Legal"])
        self.assertEqual(options["PageSize"].default_choice.name, "Letter")
        self.assertEqual(options["InputSlot"].default_choice.name, "Tray 1")
        self.assertEqual(options["Duplex"].default_choice.name, "None")
        self.assertEqual(options["ColorModel"].default_choice.name, "RGB")
        self.assertEqual(options["Collate"].default_choice.name, "True")
        self.assertEqual(options["Orientation"].default_choice.name, "Portrait")
        self.api.ClosePrinter.assert_called_with(HANDLE)

    def test_printer_options_without_duplex_or_color(self):
        self.api.DeviceCapabilities.side_effect = lambda name, port, cap, dm=None: (
            0 if cap in (win32_backend.DC_DUPLEX, win32_backend.DC_COLORDEVICE) else None
        )
        options = self.backend.get_printer_options("HP LaserJet")
        self.assertNotIn("Duplex", options)
        self.assertNotIn("ColorModel", options)

    def test_printer_options_unknown_printer(self):
        self.api.OpenPrinter.side_effect = Exception("invalid printer name")
        self.assertEqual(self.backend.get_printer_options("Nope"), {})


def _have(module):
    try:
        __import__(module)
        return True
    except ImportError:
        return False


HAVE_RENDER_DEPS = _have("pypdfium2") and _have("PIL") and _have("pypdf")


def make_pdf(path, pages=1, size=(612, 792)):
    import pypdf

    writer = pypdf.PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=size[0], height=size[1])
    with open(path, "wb") as f:
        writer.write(f)
    return path


DEVICE_CAPS = {
    win32_backend.HORZRES: 850,
    win32_backend.VERTRES: 1100,
    win32_backend.LOGPIXELSX: 100,
    win32_backend.LOGPIXELSY: 100,
    win32_backend.PHYSICALWIDTH: 850,
    win32_backend.PHYSICALHEIGHT: 1100,
    win32_backend.PHYSICALOFFSETX: 0,
    win32_backend.PHYSICALOFFSETY: 0,
}


class GdiTestCase(Win32TestCase):
    def setUp(self):
        super().setUp()
        self.api.GetDeviceCaps.side_effect = lambda hdc, index: DEVICE_CAPS[index]
        self.api.StartDoc.return_value = 77
        self.gdi = MagicMock(name="win32gui")
        self.gdi.CreateDC.return_value = 1234
        patcher = patch.object(win32_backend, "win32gui", self.gdi)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.drawn = []
        draw_patch = patch.object(
            Win32Backend, "_draw", staticmethod(lambda hdc, image, rect: self.drawn.append((image, rect)))
        )
        draw_patch.start()
        self.addCleanup(draw_patch.stop)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def pdf(self, pages=1, size=(612, 792)):
        return make_pdf(Path(self.tmp.name) / "doc.pdf", pages, size)

    def devmode(self):
        return self.gdi.CreateDC.call_args[0][2]


class TestWin32RawSubmission(Win32TestCase):
    def test_submit_bytes_raw(self):
        opts = PrintJobOptions(
            printer="HP LaserJet",
            title="Stream",
            copies=3,
            duplex=DuplexMode.TWO_SIDED_SHORT_EDGE,
            color_mode=ColorMode.MONOCHROME,
            orientation=Orientation.LANDSCAPE,
            media="A4",
            collate=False,
            raw_options={"InputSlot": "Tray 1"},
        )
        result = self.backend.submit_bytes(b"%!PS-Adobe-3.0 data", opts)

        self.assertTrue(result.success)
        self.assertEqual(result.printer, "HP LaserJet")
        self.assertEqual(result.job_id, "HP LaserJet-42")
        self.assertIn("request id is HP LaserJet-42", result.output)
        self.api.StartDocPrinter.assert_called_once_with(HANDLE, 1, ("Stream", None, "RAW"))
        self.api.WritePrinter.assert_called_once_with(HANDLE, b"%!PS-Adobe-3.0 data")
        self.api.EndDocPrinter.assert_called_once_with(HANDLE)

        defaults = self.api.OpenPrinter.call_args_list[-1][0][1]
        self.assertEqual(defaults["pDatatype"], "RAW")
        dm = defaults["pDevMode"]
        self.assertEqual(dm.Copies, 3)
        self.assertEqual(dm.Duplex, 3)
        self.assertEqual(dm.Color, 1)
        self.assertEqual(dm.Orientation, 2)
        self.assertEqual(dm.PaperSize, 9)
        self.assertEqual(dm.Collate, 0)
        self.assertEqual(dm.DefaultSource, 7)
        for attr in ("Copies", "Duplex", "Color", "Orientation", "PaperSize", "Collate", "DefaultSource"):
            self.assertTrue(dm.Fields & win32_backend.DEVMODE_FIELD_FLAGS[attr], attr)
        self.api.DocumentProperties.assert_called_once()
        self.assertIn("datatype=RAW", result.command_run)
        self.assertIn("InputSlot=Tray 1", result.command_run)

    def test_submit_file_raw_in_chunks(self):
        with tempfile.TemporaryDirectory() as tmp:
            doc = Path(tmp) / "doc.ps"
            payload = b"%!PS " + b"x" * (200 * 1024)
            doc.write_bytes(payload)
            result = self.backend.submit_file(doc, PrintJobOptions(printer="HP LaserJet", title="doc.ps"))

        self.assertTrue(result.success)
        written = b"".join(c[0][1] for c in self.api.WritePrinter.call_args_list)
        self.assertEqual(written, payload)
        self.assertGreater(self.api.WritePrinter.call_count, 1)
        self.assertEqual(result.command_run[-1], str(doc.resolve()))

    def test_raw_option_sends_pdf_unchanged(self):
        result = self.backend.submit_bytes(
            b"%PDF-1.4 data", PrintJobOptions(printer="HP LaserJet", title="t", raw_options={"raw": "true"})
        )
        self.assertTrue(result.success)
        self.api.WritePrinter.assert_called_once_with(HANDLE, b"%PDF-1.4 data")
        self.api.StartDoc.assert_not_called()

    def test_submit_failure_returns_unsuccessful_result(self):
        self.api.StartDocPrinter.side_effect = Exception("Access is denied.")
        result = self.backend.submit_bytes(b"PCL data", PrintJobOptions(printer="HP LaserJet", title="t"))
        self.assertFalse(result.success)
        self.assertIn("Access is denied", result.error)
        self.api.ClosePrinter.assert_called_with(HANDLE)

    def test_resolution_and_media_type_options(self):
        result = self.backend.submit_bytes(
            b"PCL", PrintJobOptions(printer="HP LaserJet", raw_options={"Resolution": "600x300dpi", "Scale": "90"})
        )
        dm = self.api.OpenPrinter.call_args_list[-1][0][1]["pDevMode"]
        self.assertEqual((dm.PrintQuality, dm.YResolution, dm.Scale), (600, 300, 90))
        self.assertTrue(result.success)

    def test_unknown_option_is_ignored_with_warning(self):
        with self.assertLogs("printer_craft.backends.win32_backend", level="WARNING") as logs:
            result = self.backend.submit_bytes(
                b"PCL", PrintJobOptions(printer="HP LaserJet", raw_options={"pjlDensity": "3"})
            )
        self.assertTrue(result.success)
        self.assertIn("pjlDensity", logs.output[0])

    def test_manager_dispatches_to_win32(self):
        with patch("printer_craft.core.sys.platform", "win32"):
            mgr = PrinterManager()
        result = mgr.print_bytes(b"data", title="Via manager")
        self.assertTrue(result.success)
        self.assertEqual(result.printer, "HP LaserJet")
        self.assertEqual([p.name for p in mgr.list_printers()], ["HP LaserJet", "Microsoft Print to PDF"])


@unittest.skipUnless(HAVE_RENDER_DEPS, "pypdfium2, Pillow and pypdf are required")
class TestWin32GdiSubmission(GdiTestCase):
    def test_pdf_rendered_through_gdi(self):
        doc = self.pdf(pages=3)
        opts = PrintJobOptions(printer="HP LaserJet", title="doc.pdf", copies=2, duplex=DuplexMode.TWO_SIDED_LONG_EDGE)
        result = self.backend.submit_file(doc, opts)

        self.assertTrue(result.success, result.error)
        self.assertEqual(result.job_id, "HP LaserJet-77")
        self.assertEqual(result.output, "request id is HP LaserJet-77 (1 file(s))")
        self.assertEqual(
            result.command_run[:7], ["win32print", "-d", "HP LaserJet", "-t", "doc.pdf", "-o", "render=gdi"]
        )
        self.gdi.CreateDC.assert_called_once()
        self.assertEqual(self.gdi.CreateDC.call_args[0][:2], ("WINSPOOL", "HP LaserJet"))
        self.assertEqual((self.devmode().Copies, self.devmode().Duplex), (2, 2))
        self.api.StartDoc.assert_called_once_with(1234, ("doc.pdf", None, None, 0))
        self.assertEqual(self.api.StartPage.call_count, 3)
        self.api.EndDoc.assert_called_once_with(1234)
        self.gdi.DeleteDC.assert_called_once_with(1234)
        self.assertEqual([rect for _, rect in self.drawn], [(0, 0, 850, 1100)] * 3)
        self.api.StartDocPrinter.assert_not_called()

    def test_repeat_with_number_up(self):
        result = self.backend.submit_file(self.pdf(), PrintJobOptions(printer="HP LaserJet", repeat=4, number_up=2))
        self.assertTrue(result.success)
        self.assertEqual(self.api.StartPage.call_count, 2)
        self.assertEqual(len(self.drawn), 4)
        rects = [rect for _, rect in self.drawn[:2]]
        self.assertLess(rects[0][3], rects[1][1] + 1)  # stacked top/bottom
        image = self.drawn[0][0]
        self.assertGreater(image.width, image.height)  # portrait page rotated into landscape cell
        self.assertIn("number-up=2", result.command_run)

    def test_page_ranges(self):
        doc = self.pdf(pages=5)
        for ranges, sheets in (("2-", 4), ("-2", 2), ("1,1,1", 3), ("3,1", 2), ("2-3,5", 3)):
            self.api.StartPage.reset_mock()
            result = self.backend.submit_file(doc, PrintJobOptions(printer="HP LaserJet", page_ranges=ranges))
            self.assertTrue(result.success)
            self.assertEqual(self.api.StartPage.call_count, sheets, ranges)

    def test_copies_emulated_when_driver_cannot_copy(self):
        caps = {win32_backend.DC_COPIES: 1}
        self.api.DeviceCapabilities.side_effect = lambda name, port, cap, dm=None: caps.get(cap)
        result = self.backend.submit_file(
            self.pdf(pages=3), PrintJobOptions(printer="HP LaserJet", copies=2, duplex=DuplexMode.TWO_SIDED_LONG_EDGE)
        )
        self.assertTrue(result.success)
        self.assertEqual(self.devmode().Copies, 1)
        self.assertEqual(self.api.StartPage.call_count, 8)  # 3 pages + blank back side, twice
        self.assertIn("copies-emulated=2", result.command_run)

    def test_uncollated_emulated_copies(self):
        self.api.DeviceCapabilities.side_effect = lambda name, port, cap, dm=None: None
        self.backend.submit_file(self.pdf(pages=2), PrintJobOptions(printer="HP LaserJet", copies=3, collate=False))
        self.assertEqual(self.api.StartPage.call_count, 6)

    def test_monochrome_renders_grayscale(self):
        self.backend.submit_file(self.pdf(), PrintJobOptions(printer="HP LaserJet", color_mode=ColorMode.MONOCHROME))
        self.assertEqual(self.drawn[0][0].mode, "L")
        self.assertEqual(self.devmode().Color, 1)

    def test_no_fit_to_page_prints_actual_size_centered(self):
        doc = self.pdf(size=(297, 420))  # A6
        self.backend.submit_file(doc, PrintJobOptions(printer="HP LaserJet", fit_to_page=False))
        left, top, right, bottom = self.drawn[0][1]
        self.assertEqual((right - left, bottom - top), (412, 583))
        self.assertEqual((left, top), ((850 - 412) // 2, (1100 - 583) // 2))

    def test_fit_to_page_scales_small_page_up(self):
        self.backend.submit_file(self.pdf(size=(297, 420)), PrintJobOptions(printer="HP LaserJet"))
        left, top, right, bottom = self.drawn[0][1]
        self.assertEqual(right - left, 778)
        self.assertEqual(bottom - top, 1100)

    def test_reverse_landscape_rotates_180(self):
        self.backend.submit_file(
            self.pdf(), PrintJobOptions(printer="HP LaserJet", orientation=Orientation.REVERSE_LANDSCAPE)
        )
        self.assertEqual(self.devmode().Orientation, 2)

    def test_cups_style_raw_options_apply(self):
        self.backend.submit_file(
            self.pdf(pages=4),
            PrintJobOptions(printer="HP LaserJet", raw_options={"number-up": "4", "sides": "two-sided-short-edge"}),
        )
        self.assertEqual(self.api.StartPage.call_count, 1)
        self.assertEqual(len(self.drawn), 4)
        self.assertEqual(self.devmode().Duplex, 3)

    def test_image_and_text_documents(self):
        from PIL import Image

        img = Path(self.tmp.name) / "pic.png"
        Image.new("RGBA", (400, 200), (255, 0, 0, 128)).save(img)
        self.assertTrue(self.backend.submit_file(img, PrintJobOptions(printer="HP LaserJet")).success)
        self.assertEqual(self.api.StartPage.call_count, 1)

        txt = Path(self.tmp.name) / "notes.txt"
        txt.write_text("\n".join(f"line {i}" for i in range(150)))
        self.assertTrue(self.backend.submit_file(txt, PrintJobOptions(printer="HP LaserJet")).success)
        self.assertEqual(self.api.StartPage.call_count, 1 + 3)

    def test_pdf_bytes_rendered(self):
        data = self.pdf(pages=2).read_bytes()
        result = self.backend.submit_bytes(data, PrintJobOptions(printer="HP LaserJet", title="Bytes"))
        self.assertTrue(result.success)
        self.assertEqual(self.api.StartPage.call_count, 2)
        self.api.WritePrinter.assert_not_called()

    def test_draw_failure_aborts_job(self):
        with patch.object(Win32Backend, "_draw", staticmethod(MagicMock(side_effect=OSError("device lost")))):
            result = self.backend.submit_file(self.pdf(), PrintJobOptions(printer="HP LaserJet"))
        self.assertFalse(result.success)
        self.assertIn("device lost", result.error)
        self.api.AbortDoc.assert_called_once_with(1234)
        self.gdi.DeleteDC.assert_called_once_with(1234)

    def test_dry_run_does_not_spool(self):
        result = self.backend.submit_file(
            self.pdf(), PrintJobOptions(printer="HP LaserJet", title="doc.pdf", copies=2, dry_run=True)
        )
        self.assertTrue(result.dry_run)
        self.assertEqual(result.job_id, "DRY-RUN-0")
        self.assertIn("Copies=2", result.command_run)
        self.assertIn("scaling=fit", result.command_run)
        self.gdi.CreateDC.assert_not_called()
        self.api.StartDoc.assert_not_called()

    def test_empty_page_selection_raises(self):
        with self.assertRaises(DocumentConversionError):
            self.backend.submit_file(self.pdf(), PrintJobOptions(printer="HP LaserJet", page_ranges="7-9"))

    def test_printer_options_include_media_type_and_resolution(self):
        caps = {
            win32_backend.DC_MEDIATYPENAMES: ["Plain", "Glossy"],
            win32_backend.DC_MEDIATYPES: [1, 257],
            win32_backend.DC_ENUMRESOLUTIONS: [(600, 600), {"x": 1200, "y": 600}, "bogus"],
        }
        self.api.DeviceCapabilities.side_effect = lambda name, port, cap, dm=None: caps.get(cap)
        options = self.backend.get_printer_options("HP LaserJet")
        self.assertEqual([c.name for c in options["MediaType"].choices], ["Plain", "Glossy"])
        self.assertEqual([c.name for c in options["Resolution"].choices], ["600dpi", "1200x600dpi"])
        opts = PrintJobOptions(printer="HP LaserJet", raw_options={"MediaType": "Glossy"})
        self.backend.submit_file(self.pdf(), opts)
        self.assertEqual(self.devmode().MediaType, 257)


class TestWin32Queue(Win32TestCase):
    def test_get_jobs(self):
        jobs = self.backend.get_jobs("HP LaserJet")
        self.assertEqual(jobs[0], {"job_id": "HP LaserJet-42", "user": "alice", "size_bytes": "2048", "date": ""})
        self.api.EnumJobs.assert_called_once_with(HANDLE, 0, -1, 2)

    def test_cancel_job(self):
        self.assertTrue(self.backend.cancel_job("HP LaserJet-42"))
        self.api.SetJob.assert_called_once_with(HANDLE, 42, 0, None, JOB_CONTROL_CANCEL)
        self.assertEqual(self.api.OpenPrinter.call_args[0][0], "HP LaserJet")

    def test_cancel_bare_job_id(self):
        self.assertTrue(self.backend.cancel_job("43"))
        self.api.SetJob.assert_called_once_with(HANDLE, 43, 0, None, JOB_CONTROL_CANCEL)

    def test_cancel_unknown_job(self):
        self.assertFalse(self.backend.cancel_job("999"))
        self.api.SetJob.side_effect = Exception("job not found")
        self.assertFalse(self.backend.cancel_job("HP LaserJet-999"))

    def test_purge_all(self):
        self.assertTrue(self.backend.cancel_job("HP LaserJet", purge_all=True))
        ids = [c[0][1] for c in self.api.SetJob.call_args_list]
        self.assertEqual(ids, [42, 43])


class TestWin32WithoutPywin32(unittest.TestCase):
    def test_module_imports_and_errors_clearly(self):
        with patch.object(win32_backend, "win32print", None):
            backend = Win32Backend()
            with self.assertRaises(SpoolerUnavailableError):
                backend.list_printers()


class TestDevmodeSettings(unittest.TestCase):
    def test_build_devmode_settings(self):
        opts = PrintJobOptions(
            copies=5000,
            duplex=DuplexMode.TWO_SIDED_LONG_EDGE,
            color_mode=ColorMode.COLOR,
            orientation=Orientation.REVERSE_PORTRAIT,
            media="na_letter_8.5x11in",
            collate=True,
            raw_options={"InputSlot": "Manual"},
        )
        self.assertEqual(
            opts.build_devmode_settings(),
            {"Copies": 999, "Collate": 1, "Duplex": 2, "Color": 2, "Orientation": 1, "PaperSize": 1},
        )

    def test_auto_color_and_custom_form(self):
        opts = PrintJobOptions(color_mode=ColorMode.AUTO, media="Photo 4x6")
        self.assertEqual(opts.build_devmode_settings(), {"Copies": 1, "FormName": "Photo 4x6"})


class TestWindowsConverterFallbacks(unittest.TestCase):
    def test_image_converted_with_pillow(self):
        try:
            from PIL import Image
        except ImportError:
            self.skipTest("Pillow not installed")
        with tempfile.TemporaryDirectory() as tmp:
            img = Path(tmp) / "pic.png"
            Image.new("RGBA", (20, 10), (255, 0, 0, 128)).save(img)
            with patch("printer_craft.converter.sys.platform", "win32"), \
                    patch("printer_craft.converter.subprocess.run") as run:
                with DocumentConverter.prepare_for_print(img, force_pdf=True) as out:
                    self.assertTrue(out.read_bytes().startswith(b"%PDF"))
                run.assert_not_called()

    def test_office_doc_uses_soffice(self):
        with tempfile.TemporaryDirectory() as tmp:
            doc = Path(tmp) / "report.docx"
            doc.write_bytes(b"PK\x03\x04\x00")

            def fake_run(cmd, **kwargs):
                out_dir = Path(cmd[cmd.index("--outdir") + 1])
                (out_dir / "report.pdf").write_bytes(b"%PDF-1.4 converted")
                return MagicMock(returncode=0, stdout="", stderr="")

            with patch("printer_craft.converter.sys.platform", "win32"), \
                    patch.object(DocumentConverter, "_find_soffice", return_value="soffice"), \
                    patch("printer_craft.converter.subprocess.run", side_effect=fake_run) as run:
                with DocumentConverter.prepare_for_print(doc) as out:
                    self.assertEqual(out.read_bytes(), b"%PDF-1.4 converted")
            cmd = run.call_args[0][0]
            self.assertEqual(cmd[:4], ["soffice", "--headless", "--convert-to", "pdf"])

    def test_page_repetition_requires_pypdf_on_windows(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "a.pdf"
            src.write_bytes(b"%PDF-1.4")
            with patch("printer_craft.converter.sys.platform", "win32"), \
                    patch.dict(sys.modules, {"pypdf": None}), \
                    patch("printer_craft.converter.subprocess.run") as run:
                with self.assertRaises(DocumentConversionError):
                    DocumentConverter.duplicate_pdf_pages(src, Path(tmp) / "b.pdf", [1, 1])
                run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
