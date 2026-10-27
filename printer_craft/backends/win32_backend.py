"""
Windows print spooler backend built on pywin32's `win32print`.

Documents are spooled with the RAW datatype, so the target printer must understand
the submitted format (e.g. PDF-direct or PostScript printers). Non-native formats are
converted to PDF first via `DocumentConverter`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Union

try:
    import win32print  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover - exercised implicitly on non-Windows platforms
    win32print = None

from ..converter import DocumentConverter
from ..exceptions import DocumentConversionError, SpoolerUnavailableError
from ..models import (
    PrintJobOptions,
    PrintResult,
    Printer,
    PrinterOption,
    PrinterOptionChoice,
)
from .base import PrinterBackend

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
DC_PAPERNAMES = 16
DC_COLLATE = 22
DC_COLORDEVICE = 32

DEVMODE_FIELD_FLAGS = {
    "Orientation": 0x00000001,  # DM_ORIENTATION
    "PaperSize": 0x00000002,  # DM_PAPERSIZE
    "Copies": 0x00000100,  # DM_COPIES
    "Color": 0x00000800,  # DM_COLOR
    "Duplex": 0x00001000,  # DM_DUPLEX
    "Collate": 0x00008000,  # DM_COLLATE
    "FormName": 0x00010000,  # DM_FORMNAME
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

# Formats spooled as-is with the RAW datatype; everything else is converted to PDF.
RAW_PASSTHROUGH_EXTENSIONS = {".pdf", ".ps", ".eps", ".prn", ".pcl", ".pxl", ".txt", ".text", ".log"}

_WRITE_CHUNK = 64 * 1024


def _status_text(status: int) -> str:
    for flag, text in _STATUS_TEXT:
        if status & flag:
            return text
    return "is idle."


def _clean(value: Any) -> str:
    return str(value).split("\x00", 1)[0].strip()


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

        default = {1: "Portrait", 2: "Landscape"}.get(getattr(devmode, "Orientation", None))
        options["Orientation"] = self._make_option(
            "Orientation", "Orientation", ["Portrait", "Landscape"], default
        )

        return options

    # =========================================================================
    # JOB SUBMISSION
    # =========================================================================

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
    def _describe(printer: str, title: str, settings: Dict[str, Any], source: Optional[str]) -> List[str]:
        cmd = ["win32print", "-d", printer, "-t", title, "-o", "datatype=RAW"]
        for key, value in settings.items():
            cmd.extend(["-o", f"{key}={value}"])
        if source is not None:
            cmd.append(source)
        return cmd

    def _spool(self, printer: str, title: str, opts: PrintJobOptions, payload: Union[bytes, Path]) -> PrintResult:
        api = self._api()
        settings = opts.build_devmode_settings()
        source = str(payload) if isinstance(payload, Path) else None
        cmd = self._describe(printer, title, settings, source)

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

        request_id = f"{printer}-{job_id}"
        return PrintResult(
            success=True,
            printer=printer,
            job_id=request_id,
            command_run=cmd,
            output=f"request id is {request_id} (1 file(s))",
        )

    @staticmethod
    def _page_sequence(opts: PrintJobOptions) -> Optional[List[int]]:
        """Expand page ranges / repeat into an explicit page list (DEVMODE has no page ranges)."""
        if opts.page_ranges:
            pages: List[int] = []
            for token in (t.strip() for t in opts.page_ranges.split(",")):
                if not token:
                    continue
                if "-" in token:
                    start, _, end = token.partition("-")
                    if not start.strip() or not end.strip():
                        raise DocumentConversionError(
                            f"Open-ended page range '{token}' is not supported on Windows."
                        )
                    pages.extend(range(int(start), int(end) + 1))
                else:
                    pages.append(int(token))
            return pages or None
        if opts.repeat and opts.repeat > 1:
            return [1] * opts.repeat
        return None

    def submit_file(
        self,
        target_path: Path,
        opts: PrintJobOptions,
        force_pdf_conversion: bool = False,
    ) -> PrintResult:
        target_printer = opts.printer or ""
        title = opts.title or target_path.name
        page_sequence = self._page_sequence(opts)
        force_pdf = force_pdf_conversion or target_path.suffix.lower() not in RAW_PASSTHROUGH_EXTENSIONS

        with DocumentConverter.prepare_for_print(
            target_path, force_pdf=force_pdf, page_sequence=page_sequence
        ) as printable_path:
            if opts.dry_run:
                return PrintResult(
                    success=True,
                    printer=target_printer,
                    job_id="DRY-RUN-0",
                    command_run=self._describe(
                        target_printer, title, opts.build_devmode_settings(), str(printable_path)
                    ),
                    output="Dry run executed successfully. No job sent to printer.",
                    dry_run=True,
                )
            return self._spool(target_printer, title, opts, Path(printable_path))

    def submit_bytes(self, data: bytes, opts: PrintJobOptions) -> PrintResult:
        target_printer = opts.printer or ""
        title = opts.title or "Untitled Document"
        if opts.dry_run:
            return PrintResult(
                success=True,
                printer=target_printer,
                job_id="DRY-RUN-0",
                command_run=self._describe(target_printer, title, opts.build_devmode_settings(), None),
                output="Dry run bytes submission.",
                dry_run=True,
            )
        return self._spool(target_printer, title, opts, data)

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
