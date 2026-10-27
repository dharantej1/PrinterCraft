"""
Windows print spooler backend built on pywin32 (`win32print` / `win32gui`).

Documents (PDF, images, text, Office files) are rendered through GDI onto a printer
device context, so any installed Windows printer driver works and layout options
(fit-to-page, scaling, number-up, page ranges, orientation) are applied locally.
Printer-language files (.ps, .pcl, .prn, ...) or jobs with `-o raw` are spooled
unchanged with the RAW datatype.
"""

from __future__ import annotations

import dataclasses
import logging
import re
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, List, Optional, Tuple, Union

try:
    import win32print  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover - exercised implicitly on non-Windows platforms
    win32print = None

try:
    import win32gui  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover - exercised implicitly on non-Windows platforms
    win32gui = None

from ..converter import DocumentConverter
from ..exceptions import DocumentConversionError, SpoolerUnavailableError
from ..models import (
    ColorMode,
    DuplexMode,
    Orientation,
    PrintJobOptions,
    PrintScaling,
    PrintResult,
    Printer,
    PrinterOption,
    PrinterOptionChoice,
)
from .base import PrinterBackend
from .win32_render import (
    LETTER_PT,
    DeviceGeometry,
    layout_sheet,
    open_bytes,
    open_document,
    plan_sheets,
    render_placement,
    resolve_number_up,
    resolve_scaling,
    select_pages,
    sniff_bytes,
)

logger = logging.getLogger(__name__)

# winspool.h / wingdi.h constants (fixed Win32 ABI values)
PRINTER_ENUM_LOCAL = 0x00000002
PRINTER_ENUM_CONNECTIONS = 0x00000004
PRINTER_ACCESS_USE = 0x00000008
JOB_CONTROL_CANCEL = 3

DM_OUT_BUFFER = 2
DM_IN_BUFFER = 8

DC_BINS = 6
DC_DUPLEX = 7
DC_BINNAMES = 12
DC_ENUMRESOLUTIONS = 13
DC_PAPERNAMES = 16
DC_COPIES = 18
DC_COLLATE = 22
DC_COLORDEVICE = 32
DC_MEDIATYPENAMES = 34
DC_MEDIATYPES = 35

# GetDeviceCaps indices
HORZRES = 8
VERTRES = 10
LOGPIXELSX = 88
LOGPIXELSY = 90
PHYSICALWIDTH = 110
PHYSICALHEIGHT = 111
PHYSICALOFFSETX = 112
PHYSICALOFFSETY = 113

DEVMODE_FIELD_FLAGS = {
    "Orientation": 0x00000001,  # DM_ORIENTATION
    "PaperSize": 0x00000002,  # DM_PAPERSIZE
    "Copies": 0x00000100,  # DM_COPIES
    "Color": 0x00000800,  # DM_COLOR
    "Duplex": 0x00001000,  # DM_DUPLEX
    "Collate": 0x00008000,  # DM_COLLATE
    "FormName": 0x00010000,  # DM_FORMNAME
    "PaperLength": 0x00000004,  # DM_PAPERLENGTH
    "PaperWidth": 0x00000008,  # DM_PAPERWIDTH
    "Scale": 0x00000010,  # DM_SCALE
    "Nup": 0x00000040,  # DM_NUP
    "DefaultSource": 0x00000200,  # DM_DEFAULTSOURCE
    "PrintQuality": 0x00000400,  # DM_PRINTQUALITY
    "YResolution": 0x00002000,  # DM_YRESOLUTION
    "TTOption": 0x00004000,  # DM_TTOPTION
    "ICMMethod": 0x00800000,  # DM_ICMMETHOD
    "ICMIntent": 0x01000000,  # DM_ICMINTENT
    "MediaType": 0x02000000,  # DM_MEDIATYPE
    "DitherType": 0x04000000,  # DM_DITHERTYPE
}

# `-o KEY=VALUE` driver keys accepted on Windows (lower-cased) -> canonical name.
# PPD-style names are resolved through DeviceCapabilities; the rest are DEVMODE fields.
DRIVER_OPTION_KEYS = {
    "inputslot": "InputSlot",
    "mediatype": "MediaType",
    "resolution": "Resolution",
    **{name.lower(): name for name in (
        "DefaultSource", "PrintQuality", "YResolution", "DitherType", "ICMMethod",
        "ICMIntent", "Scale", "PaperWidth", "PaperLength", "PaperSize", "Nup", "TTOption",
    )},
}

_STATUS_TEXT = [
    (0x00000001, "is paused."),  # PRINTER_STATUS_PAUSED
    (0x00000002, "has an error."),  # PRINTER_STATUS_ERROR
    (0x00000008, "has a paper jam."),  # PRINTER_STATUS_PAPER_JAM
    (0x00000010, "is out of paper."),  # PRINTER_STATUS_PAPER_OUT
    (0x00000080, "is offline."),  # PRINTER_STATUS_OFFLINE
    (0x00001000, "is not available."),  # PRINTER_STATUS_NOT_AVAILABLE
    (0x00000400, "is printing."),  # PRINTER_STATUS_PRINTING
    (0x00004000, "is processing."),  # PRINTER_STATUS_PROCESSING
    (0x00000200, "is busy."),  # PRINTER_STATUS_BUSY
]

# Printer-language files always spooled unchanged with the RAW datatype.
RAW_EXTENSIONS = {".ps", ".eps", ".prn", ".pcl", ".pxl", ".raw"}

# With `-o raw`, these are sent as-is; anything else is converted to PDF first.
RAW_PASSTHROUGH_EXTENSIONS = RAW_EXTENSIONS | {".pdf", ".txt", ".text", ".log"}

_WRITE_CHUNK = 64 * 1024


def _status_text(status: int) -> str:
    for flag, text in _STATUS_TEXT:
        if status & flag:
            return text
    return "is idle."


def _clean(value: Any) -> str:
    return str(value).split("\x00", 1)[0].strip()


def _truthy(value: str) -> bool:
    return value.strip().lower() not in ("false", "0", "no", "off")


def _lookup_id(value: str, names: List[Any], ids: List[Any]) -> int:
    """Resolve a driver choice name (e.g. a tray name) to its numeric id."""
    wanted = value.strip().lower()
    for name, ident in zip(names, ids):
        if _clean(name).lower() == wanted:
            return int(ident)
    if wanted.lstrip("-").isdigit():
        return int(wanted)
    raise ValueError(value)


def _parse_resolution(value: str) -> Tuple[int, int]:
    match = re.fullmatch(r"\s*(\d+)\s*(?:x\s*(\d+))?\s*(?:dpi)?\s*", value, re.IGNORECASE)
    if not match:
        raise ValueError(value)
    x = int(match.group(1))
    return x, int(match.group(2) or x)


def _resolution_pair(value: Any) -> Tuple[int, int]:
    """DC_ENUMRESOLUTIONS entries come back as (x, y) pairs or as dicts depending on pywin32."""
    if isinstance(value, dict):
        lowered = {str(k).lower(): v for k, v in value.items()}
        x = next((lowered[k] for k in ("x", "xdpi", "xresolution", "cx") if k in lowered), None)
        y = next((lowered[k] for k in ("y", "ydpi", "yresolution", "cy") if k in lowered), None)
        if x is None or y is None:
            x, y = list(value.values())[:2]
        return int(x), int(y)
    return int(value[0]), int(value[1])


def _format_time(value: Any) -> str:
    if hasattr(value, "strftime"):
        try:
            return value.strftime("%a %b %d %H:%M:%S %Y")
        except Exception:
            pass
    return str(value) if value is not None else ""


class Win32Backend(PrinterBackend):
    """Printer backend for the Windows print spooler via pywin32 `win32print`."""

    def _api(self) -> Any:
        if win32print is None:
            raise SpoolerUnavailableError(
                "pywin32 is required for printing on Windows. "
                "Install it with: pip install \"printer-craft[windows]\""
            )
        return win32print

    # =========================================================================
    # PRINTER DISCOVERY & ENUMERATION
    # =========================================================================

    def _default_printer_name(self) -> Optional[str]:
        try:
            name = self._api().GetDefaultPrinter()
        except SpoolerUnavailableError:
            raise
        except Exception:
            return None
        return _clean(name) or None

    def list_printers(self, load_options: bool = False) -> List[Printer]:
        api = self._api()
        try:
            entries = api.EnumPrinters(PRINTER_ENUM_LOCAL | PRINTER_ENUM_CONNECTIONS, None, 2)
        except Exception as e:
            raise SpoolerUnavailableError(f"Windows print spooler error: {e}") from e

        default_name = self._default_printer_name()
        printers: Dict[str, Printer] = {}
        for entry in entries:
            name = _clean(entry.get("pPrinterName", ""))
            if not name or name in printers:
                continue
            printers[name] = Printer(
                name=name,
                status=_status_text(int(entry.get("Status") or 0)),
                is_default=False,
                description=_clean(entry.get("pComment") or entry.get("pDriverName") or ""),
                location=_clean(entry.get("pLocation") or ""),
            )

        if default_name and default_name in printers:
            printers[default_name].is_default = True
        elif printers and not default_name:
            next(iter(printers.values())).is_default = True

        if load_options:
            for p in printers.values():
                p.options = self.get_printer_options(p.name)

        return list(printers.values())

    def get_default_printer(self) -> Optional[Printer]:
        printers = self.list_printers(load_options=False)
        for p in printers:
            if p.is_default:
                return p
        return printers[0] if printers else None

    # =========================================================================
    # DRIVER OPTIONS INSPECTION
    # =========================================================================

    def _get_printer_info(self, printer_name: str) -> Dict[str, Any]:
        api = self._api()
        handle = api.OpenPrinter(printer_name)
        try:
            return api.GetPrinter(handle, 2)
        finally:
            api.ClosePrinter(handle)

    def _capability(self, printer_name: str, port: str, capability: int, devmode: Any = None) -> Any:
        try:
            return self._api().DeviceCapabilities(printer_name, port, capability, devmode)
        except SpoolerUnavailableError:
            raise
        except Exception:
            return None

    @staticmethod
    def _make_option(keyword: str, display_name: str, names: List[str], default: Any) -> PrinterOption:
        return PrinterOption(
            keyword=keyword,
            display_name=display_name,
            choices=[
                PrinterOptionChoice(name=n, display_text=n, is_default=(n == default)) for n in names
            ],
        )

    def get_printer_options(self, printer_name: str) -> Dict[str, PrinterOption]:
        """
        Query driver capabilities via `DeviceCapabilities`, with defaults taken from the
        printer's DEVMODE. Keywords mirror common PPD names where possible.
        """
        try:
            info = self._get_printer_info(printer_name)
        except SpoolerUnavailableError:
            raise
        except Exception:
            return {}

        port = _clean(info.get("pPortName") or "")
        devmode = info.get("pDevMode")
        options: Dict[str, PrinterOption] = {}

        papers = self._capability(printer_name, port, DC_PAPERNAMES)
        if papers:
            names = [n for n in (_clean(p) for p in papers) if n]
            default = _clean(getattr(devmode, "FormName", "") or "")
            options["PageSize"] = self._make_option("PageSize", "Media Size", names, default)

        bins = self._capability(printer_name, port, DC_BINNAMES)
        if bins:
            names = [n for n in (_clean(b) for b in bins) if n]
            bin_ids = self._capability(printer_name, port, DC_BINS) or []
            default_source = getattr(devmode, "DefaultSource", None)
            default = None
            for bin_id, bin_name in zip(bin_ids, names):
                if bin_id == default_source:
                    default = bin_name
            options["InputSlot"] = self._make_option("InputSlot", "Media Source", names, default)

        if self._capability(printer_name, port, DC_DUPLEX) == 1:
            default = {1: "None", 2: "DuplexNoTumble", 3: "DuplexTumble"}.get(
                getattr(devmode, "Duplex", None)
            )
            options["Duplex"] = self._make_option(
                "Duplex", "2-Sided Printing", ["None", "DuplexNoTumble", "DuplexTumble"], default
            )

        if self._capability(printer_name, port, DC_COLORDEVICE) == 1:
            default = {1: "Gray", 2: "RGB"}.get(getattr(devmode, "Color", None))
            options["ColorModel"] = self._make_option("ColorModel", "Color Mode", ["Gray", "RGB"], default)

        if self._capability(printer_name, port, DC_COLLATE) == 1:
            default = {0: "False", 1: "True"}.get(getattr(devmode, "Collate", None))
            options["Collate"] = self._make_option("Collate", "Collate", ["True", "False"], default)

        media_names = self._capability(printer_name, port, DC_MEDIATYPENAMES)
        if media_names:
            names = [n for n in (_clean(m) for m in media_names) if n]
            media_ids = self._capability(printer_name, port, DC_MEDIATYPES) or []
            default_media = getattr(devmode, "MediaType", None)
            default = None
            for media_id, media_name in zip(media_ids, names):
                if media_id == default_media:
                    default = media_name
            options["MediaType"] = self._make_option("MediaType", "Media Type", names, default)

        resolutions = self._capability(printer_name, port, DC_ENUMRESOLUTIONS)
        if resolutions:
            names = []
            for res in resolutions:
                try:
                    x, y = _resolution_pair(res)
                except (TypeError, ValueError, IndexError):
                    continue
                name = f"{x}dpi" if x == y else f"{x}x{y}dpi"
                if x > 0 and name not in names:
                    names.append(name)
            dx = getattr(devmode, "PrintQuality", None)
            dy = getattr(devmode, "YResolution", None) or dx
            default = None
            if isinstance(dx, int) and dx > 0:
                default = f"{dx}dpi" if dx == dy else f"{dx}x{dy}dpi"
            if names:
                options["Resolution"] = self._make_option("Resolution", "Resolution", names, default)

        default = {1: "Portrait", 2: "Landscape"}.get(getattr(devmode, "Orientation", None))
        options["Orientation"] = self._make_option(
            "Orientation", "Orientation", ["Portrait", "Landscape"], default
        )

        return options

    # =========================================================================
    # JOB SUBMISSION
    # =========================================================================

    def _gdi(self) -> Any:
        if win32gui is None:
            raise SpoolerUnavailableError(
                "pywin32 is required for printing on Windows. "
                "Install it with: pip install \"printer-craft[windows]\""
            )
        return win32gui

    def _build_devmode(self, printer_name: str, settings: Dict[str, Any]) -> Any:
        """Apply settings to the printer's default DEVMODE and let the driver validate them."""
        api = self._api()
        handle = api.OpenPrinter(printer_name)
        try:
            devmode = api.GetPrinter(handle, 2).get("pDevMode")
            if devmode is None:
                return None
            fields = int(getattr(devmode, "Fields", 0) or 0)
            for attr, value in settings.items():
                setattr(devmode, attr, value)
                fields |= DEVMODE_FIELD_FLAGS.get(attr, 0)
            devmode.Fields = fields
            api.DocumentProperties(0, handle, printer_name, devmode, devmode, DM_IN_BUFFER | DM_OUT_BUFFER)
            return devmode
        finally:
            api.ClosePrinter(handle)

    @staticmethod
    def _effective_options(opts: PrintJobOptions) -> Tuple[PrintJobOptions, Dict[str, str], bool]:
        """
        Split `raw_options` into: standard CUPS/IPP keys applied to a copy of the job
        options (so `-o sides=...`, `-o number-up=4`, ... behave as on CUPS), driver keys
        resolved against the DEVMODE (`InputSlot`, `MediaType`, `Resolution`, DEVMODE field
        names), and the `raw` flag. Unknown keys are logged and ignored.
        """
        eff = dataclasses.replace(opts, raw_options={})
        driver: Dict[str, str] = {}
        raw_mode = False
        for key, value in opts.raw_options.items():
            k = key.strip().lower()
            v = str(value).strip()
            try:
                if k == "raw":
                    raw_mode = _truthy(v)
                elif k in ("sides", "duplex"):
                    eff.duplex = DuplexMode.from_str(v)
                elif k in ("print-color-mode", "colormodel"):
                    eff.color_mode = ColorMode.from_str(v)
                elif k in ("media", "pagesize", "pageregion"):
                    eff.media = v
                elif k == "collate":
                    eff.collate = _truthy(v)
                elif k in ("orientation-requested", "orientation"):
                    eff.orientation = Orientation.from_str(v)
                elif k == "landscape":
                    if _truthy(v):
                        eff.orientation = Orientation.LANDSCAPE
                elif k in ("fit-to-page", "fitplot"):
                    eff.fit_to_page = _truthy(v)
                elif k == "print-scaling":
                    eff.scaling = PrintScaling(v.lower())
                elif k == "number-up":
                    eff.number_up = int(v)
                elif k == "page-ranges":
                    eff.page_ranges = v
                elif k == "copies":
                    eff.copies = int(v)
                elif k in DRIVER_OPTION_KEYS:
                    driver[DRIVER_OPTION_KEYS[k]] = v
                else:
                    logger.warning("Ignoring option %s=%s: not supported by the Windows backend", key, value)
            except (KeyError, ValueError):
                logger.warning("Ignoring option %s=%s: invalid value", key, value)
        return eff, driver, raw_mode

    def _printer_port(self, printer_name: str) -> str:
        return _clean(self._get_printer_info(printer_name).get("pPortName") or "")

    def _driver_settings(self, printer_name: str, driver: Dict[str, str]) -> Dict[str, Any]:
        """Resolve driver option names (tray / media type names, '600dpi', ...) to DEVMODE values."""
        settings: Dict[str, Any] = {}
        if not driver:
            return settings
        port = self._printer_port(printer_name)

        def caps(capability: int) -> List[Any]:
            return list(self._capability(printer_name, port, capability) or [])

        for key, value in driver.items():
            try:
                if key == "InputSlot":
                    settings["DefaultSource"] = _lookup_id(value, caps(DC_BINNAMES), caps(DC_BINS))
                elif key == "MediaType":
                    settings["MediaType"] = _lookup_id(value, caps(DC_MEDIATYPENAMES), caps(DC_MEDIATYPES))
                elif key == "Resolution":
                    settings["PrintQuality"], settings["YResolution"] = _parse_resolution(value)
                else:
                    settings[key] = int(value)
            except ValueError:
                logger.warning("Ignoring option %s=%s: not supported by printer '%s'", key, value, printer_name)
        return settings

    def _hardware_copies(self, printer_name: str) -> int:
        """Maximum copies the driver can produce itself (DC_COPIES); 1 if unknown."""
        try:
            value = self._capability(printer_name, self._printer_port(printer_name), DC_COPIES)
            return max(1, int(value)) if value else 1
        except SpoolerUnavailableError:
            raise
        except Exception:
            return 1

    def _geometry(self, hdc: Any) -> DeviceGeometry:
        api = self._api()

        def cap(index: int) -> int:
            return int(api.GetDeviceCaps(hdc, index) or 0)

        printable_w, printable_h = cap(HORZRES), cap(VERTRES)
        return DeviceGeometry(
            dpi_x=cap(LOGPIXELSX) or 300,
            dpi_y=cap(LOGPIXELSY) or 300,
            printable_w=printable_w,
            printable_h=printable_h,
            physical_w=cap(PHYSICALWIDTH) or printable_w,
            physical_h=cap(PHYSICALHEIGHT) or printable_h,
            offset_x=cap(PHYSICALOFFSETX),
            offset_y=cap(PHYSICALOFFSETY),
        )

    @staticmethod
    def _draw(hdc: Any, image: Any, rect: Tuple[int, int, int, int]) -> None:
        from PIL import ImageWin

        ImageWin.Dib(image).draw(int(hdc), rect)

    @staticmethod
    def _describe(
        printer: str,
        title: str,
        mode: str,
        settings: Dict[str, Any],
        extra: List[Tuple[str, Any]],
        source: Optional[str],
    ) -> List[str]:
        cmd = ["win32print", "-d", printer, "-t", title, "-o", "datatype=RAW" if mode == "raw" else "render=gdi"]
        for key, value in settings.items():
            cmd.extend(["-o", f"{key}={value}"])
        for key, value in extra:
            cmd.extend(["-o", f"{key}={value}"])
        if source is not None:
            cmd.append(source)
        return cmd

    @staticmethod
    def _layout_args(opts: PrintJobOptions, driver: Dict[str, str], emulated_copies: int) -> List[Tuple[str, Any]]:
        args: List[Tuple[str, Any]] = [("scaling", resolve_scaling(opts))]
        number_up = resolve_number_up(opts)
        if number_up > 1:
            args.append(("number-up", number_up))
        if opts.page_ranges:
            args.append(("page-ranges", opts.page_ranges))
        if opts.repeat and opts.repeat > 1:
            args.append(("repeat", opts.repeat))
        if emulated_copies > 1:
            args.append(("copies-emulated", emulated_copies))
        args.extend(driver.items())
        return args

    @staticmethod
    def _success(printer: str, job_id: Any, cmd: List[str]) -> PrintResult:
        request_id = f"{printer}-{job_id}"
        return PrintResult(
            success=True,
            printer=printer,
            job_id=request_id,
            command_run=cmd,
            output=f"request id is {request_id} (1 file(s))",
        )

    @staticmethod
    def _dry_run(printer: str, cmd: List[str], output: str) -> PrintResult:
        return PrintResult(
            success=True,
            printer=printer,
            job_id="DRY-RUN-0",
            command_run=cmd,
            output=output,
            dry_run=True,
        )

    # ---- RAW datatype (printer-language data: PostScript, PCL, or `-o raw`) ----

    def _spool(self, printer: str, title: str, settings: Dict[str, Any], payload: Union[bytes, Path],
               cmd: List[str]) -> PrintResult:
        api = self._api()
        try:
            devmode = self._build_devmode(printer, settings)
            defaults: Dict[str, Any] = {"DesiredAccess": PRINTER_ACCESS_USE, "pDatatype": "RAW"}
            if devmode is not None:
                defaults["pDevMode"] = devmode
            handle = api.OpenPrinter(printer, defaults)
        except Exception as e:
            return PrintResult(success=False, printer=printer, command_run=cmd, error=str(e))

        try:
            job_id = api.StartDocPrinter(handle, 1, (title, None, "RAW"))
            try:
                api.StartPagePrinter(handle)
                if isinstance(payload, Path):
                    with open(payload, "rb") as f:
                        for chunk in iter(lambda: f.read(_WRITE_CHUNK), b""):
                            api.WritePrinter(handle, chunk)
                else:
                    api.WritePrinter(handle, payload)
                api.EndPagePrinter(handle)
            finally:
                api.EndDocPrinter(handle)
        except Exception as e:
            return PrintResult(success=False, printer=printer, command_run=cmd, error=str(e))
        finally:
            api.ClosePrinter(handle)

        return self._success(printer, job_id, cmd)

    @staticmethod
    @contextmanager
    def _raw_page_selection(path: Path, opts: PrintJobOptions) -> Iterator[Path]:
        """Apply page ranges / repeat to a PDF before RAW spooling (pypdf)."""
        if not (opts.page_ranges or (opts.repeat and opts.repeat > 1)):
            yield path
            return
        if path.suffix.lower() != ".pdf":
            logger.warning("Page ranges / repeat are ignored for RAW %s data", path.suffix or "binary")
            yield path
            return
        try:
            import pypdf
        except ImportError:
            raise DocumentConversionError(
                "pypdf is required to select pages for RAW printing on Windows: pip install pypdf"
            )
        total = len(pypdf.PdfReader(str(path)).pages)
        order = select_pages(opts, total)
        if not order:
            raise DocumentConversionError("No pages selected for printing.")
        if order == list(range(1, total + 1)):
            yield path
            return
        with DocumentConverter.prepare_for_print(path, page_sequence=order) as selected:
            yield Path(selected)

    def _submit_file_raw(self, target_path: Path, opts: PrintJobOptions, title: str,
                         driver: Dict[str, str], force_pdf_conversion: bool) -> PrintResult:
        printer = opts.printer or ""
        force_pdf = force_pdf_conversion or target_path.suffix.lower() not in RAW_PASSTHROUGH_EXTENSIONS
        with DocumentConverter.prepare_for_print(target_path, force_pdf=force_pdf) as converted:
            with self._raw_page_selection(Path(converted), opts) as printable_path:
                settings = opts.build_devmode_settings()
                if opts.dry_run:
                    cmd = self._describe(printer, title, "raw", settings, list(driver.items()), str(printable_path))
                    return self._dry_run(printer, cmd, "Dry run executed successfully. No job sent to printer.")
                settings.update(self._driver_settings(printer, driver))
                cmd = self._describe(printer, title, "raw", settings, list(driver.items()), str(printable_path))
                return self._spool(printer, title, settings, printable_path, cmd)

    # ---- GDI rendering (PDF, images, text, Office documents) ----

    def _dry_run_gdi(self, printer: str, title: str, opts: PrintJobOptions, driver: Dict[str, str],
                     open_pages: Callable[[Tuple[float, float]], Any], source: Optional[str],
                     output: str) -> PrintResult:
        with open_pages(LETTER_PT) as pages:
            if not select_pages(opts, len(pages)):
                raise DocumentConversionError("No pages selected for printing.")
        cmd = self._describe(printer, title, "gdi", opts.build_devmode_settings(),
                             self._layout_args(opts, driver, 1), source)
        return self._dry_run(printer, cmd, output)

    def _print_gdi(self, printer: str, title: str, opts: PrintJobOptions, driver: Dict[str, str],
                   open_pages: Callable[[Tuple[float, float]], Any], source: Optional[str]) -> PrintResult:
        api = self._api()
        gdi = self._gdi()
        settings = opts.build_devmode_settings()
        settings.update(self._driver_settings(printer, driver))

        emulated_copies = 1
        if opts.copies > 1 and self._hardware_copies(printer) < opts.copies:
            emulated_copies = settings["Copies"]
            settings["Copies"] = 1
        cmd = self._describe(printer, title, "gdi", settings, self._layout_args(opts, driver, emulated_copies), source)

        try:
            devmode = self._build_devmode(printer, settings)
            hdc = gdi.CreateDC("WINSPOOL", printer, devmode)
        except Exception as e:
            return PrintResult(success=False, printer=printer, command_run=cmd, error=str(e))

        try:
            geom = self._geometry(hdc)
            with open_pages(geom.page_size_pt) as pages:
                order = select_pages(opts, len(pages))
                if not order:
                    raise DocumentConversionError("No pages selected for printing.")
                sheets = plan_sheets(
                    [pages[i - 1] for i in order],
                    resolve_number_up(opts),
                    copies=emulated_copies,
                    collate=opts.collate is not False,
                    duplex=opts.duplex in (DuplexMode.TWO_SIDED_LONG_EDGE, DuplexMode.TWO_SIDED_SHORT_EDGE),
                )
                grayscale = opts.color_mode == ColorMode.MONOCHROME
                job_id = api.StartDoc(hdc, (title, None, None, 0))
                try:
                    for sheet in sheets:
                        api.StartPage(hdc)
                        for placement in layout_sheet(sheet, geom, opts):
                            self._draw(hdc, render_placement(placement, geom, grayscale), placement.rect)
                        api.EndPage(hdc)
                    api.EndDoc(hdc)
                except Exception:
                    abort = getattr(api, "AbortDoc", None)
                    if abort is not None:
                        try:
                            abort(hdc)
                        except Exception:
                            pass
                    raise
        except DocumentConversionError:
            raise
        except Exception as e:
            return PrintResult(success=False, printer=printer, command_run=cmd, error=str(e))
        finally:
            try:
                gdi.DeleteDC(hdc)
            except Exception:
                pass

        return self._success(printer, job_id, cmd)

    def submit_file(
        self,
        target_path: Path,
        opts: PrintJobOptions,
        force_pdf_conversion: bool = False,
    ) -> PrintResult:
        printer = opts.printer or ""
        title = opts.title or target_path.name
        eff, driver, raw_mode = self._effective_options(opts)

        if raw_mode or target_path.suffix.lower() in RAW_EXTENSIONS:
            return self._submit_file_raw(target_path, eff, title, driver, force_pdf_conversion)

        path = target_path.expanduser().resolve()
        if not path.exists():
            raise FileNotFoundError(f"Document file does not exist: {path}")

        def open_pages(size: Tuple[float, float]) -> Any:
            return open_document(path, size)

        if eff.dry_run:
            return self._dry_run_gdi(printer, title, eff, driver, open_pages, str(path),
                                     "Dry run executed successfully. No job sent to printer.")
        return self._print_gdi(printer, title, eff, driver, open_pages, str(path))

    def submit_bytes(self, data: bytes, opts: PrintJobOptions) -> PrintResult:
        printer = opts.printer or ""
        title = opts.title or "Untitled Document"
        eff, driver, raw_mode = self._effective_options(opts)
        kind = None if raw_mode else sniff_bytes(data)

        if kind is None:
            settings = eff.build_devmode_settings()
            if eff.dry_run:
                cmd = self._describe(printer, title, "raw", settings, list(driver.items()), None)
                return self._dry_run(printer, cmd, "Dry run bytes submission.")
            settings.update(self._driver_settings(printer, driver))
            cmd = self._describe(printer, title, "raw", settings, list(driver.items()), None)
            return self._spool(printer, title, settings, data, cmd)

        def open_pages(size: Tuple[float, float]) -> Any:
            return open_bytes(data, kind)

        if eff.dry_run:
            return self._dry_run_gdi(printer, title, eff, driver, open_pages, None, "Dry run bytes submission.")
        return self._print_gdi(printer, title, eff, driver, open_pages, None)

    # =========================================================================
    # QUEUE & JOB MANAGEMENT
    # =========================================================================

    def _enum_jobs(self, printer_name: str) -> List[Dict[str, Any]]:
        api = self._api()
        handle = api.OpenPrinter(printer_name)
        try:
            return list(api.EnumJobs(handle, 0, -1, 2))
        finally:
            api.ClosePrinter(handle)

    def get_jobs(self, printer_name: Optional[str] = None) -> List[Dict[str, Any]]:
        names = [printer_name] if printer_name else [p.name for p in self.list_printers()]
        jobs: List[Dict[str, Any]] = []
        for name in names:
            try:
                entries = self._enum_jobs(name)
            except SpoolerUnavailableError:
                raise
            except Exception:
                continue
            for job in entries:
                queue = _clean(job.get("pPrinterName") or name)
                jobs.append({
                    "job_id": f"{queue}-{job.get('JobId')}",
                    "user": _clean(job.get("pUserName") or ""),
                    "size_bytes": str(job.get("Size", 0)),
                    "date": _format_time(job.get("Submitted")),
                })
        return jobs

    def _cancel(self, printer_name: str, job_ids: List[int]) -> bool:
        api = self._api()
        handle = api.OpenPrinter(printer_name)
        try:
            for job_id in job_ids:
                api.SetJob(handle, job_id, 0, None, JOB_CONTROL_CANCEL)
        finally:
            api.ClosePrinter(handle)
        return True

    def cancel_job(self, job_id_or_printer: str, purge_all: bool = False) -> bool:
        """
        Cancel a job given as "<printer>-<id>" (as returned by `get_jobs`) or a bare
        numeric id, or purge all jobs on a printer when `purge_all` is set.
        """
        self._api()
        try:
            if purge_all:
                job_ids = [int(j["JobId"]) for j in self._enum_jobs(job_id_or_printer)]
                return self._cancel(job_id_or_printer, job_ids)

            printer, sep, raw_id = job_id_or_printer.rpartition("-")
            if sep and printer and raw_id.isdigit():
                return self._cancel(printer, [int(raw_id)])

            if job_id_or_printer.isdigit():
                target = int(job_id_or_printer)
                for p in self.list_printers():
                    if any(int(j.get("JobId", -1)) == target for j in self._enum_jobs(p.name)):
                        return self._cancel(p.name, [target])
            return False
        except SpoolerUnavailableError:
            raise
        except Exception:
            return False
