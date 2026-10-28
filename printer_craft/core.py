"""
Core printer management API, reverse-engineered from macOS PdfCraft.app architecture.
`PrinterManager` dispatches to a platform backend: CUPS on macOS/Unix, win32print on Windows.
"""

from __future__ import annotations

import dataclasses
import sys
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Union

from .backends.base import PrinterBackend
from .backends.cups_backend import CUPSBackend
from .backends.win32_backend import Win32Backend
from .exceptions import PrinterNotFoundError
from .models import (
    PrintJobOptions,
    PrintResult,
    Printer,
    PrinterOption,
)


def _backend_attr(name: str) -> property:
    """Expose a backend attribute (e.g. CUPS binary paths) as a read/write manager attribute."""

    def fget(self: "PrinterManager") -> Any:
        try:
            return getattr(self._backend, name)
        except AttributeError:
            raise AttributeError(
                f"'{name}' is not available on the {type(self._backend).__name__} backend"
            ) from None

    def fset(self: "PrinterManager", value: Any) -> None:
        setattr(self._backend, name, value)

    return property(fget, fset)


class PrinterManager:
    """
    High-level manager for discovering local/network printers, querying PPD
    capabilities, and submitting print jobs via CUPS (macOS/Unix) or the
    Windows print spooler.
    """

    lp_bin = _backend_attr("lp_bin")
    lpstat_bin = _backend_attr("lpstat_bin")
    lpoptions_bin = _backend_attr("lpoptions_bin")
    cancel_bin = _backend_attr("cancel_bin")
    _get_cups_env = _backend_attr("_get_cups_env")
    _run_cmd = _backend_attr("_run_cmd")

    def __init__(
        self,
        lp_bin: Optional[str] = None,
        lpstat_bin: Optional[str] = None,
        lpoptions_bin: Optional[str] = None,
        cancel_bin: Optional[str] = None,
        backend: Optional[PrinterBackend] = None,
    ):
        self._backend: PrinterBackend
        if backend is not None:
            self._backend = backend
        elif sys.platform == "win32":
            self._backend = Win32Backend()
        else:
            self._backend = CUPSBackend(
                lp_bin=lp_bin,
                lpstat_bin=lpstat_bin,
                lpoptions_bin=lpoptions_bin,
                cancel_bin=cancel_bin,
            )

    @property
    def backend(self) -> PrinterBackend:
        """The platform backend this manager dispatches to."""
        return self._backend

    # =========================================================================
    # PRINTER DISCOVERY & ENUMERATION
    # =========================================================================

    def list_printers(self, load_options: bool = False) -> List[Printer]:
        """Discover all installed printers and their status."""
        return self._backend.list_printers(load_options=load_options)

    def get_default_printer(self) -> Optional[Printer]:
        """Return the default system printer, or None if no printers exist."""
        return self._backend.get_default_printer()

    def get_printer(self, name: str, load_options: bool = True) -> Optional[Printer]:
        """Find a printer by name."""
        printers = self.list_printers(load_options=False)
        for p in printers:
            if p.name == name:
                if load_options:
                    p.options = self.get_printer_options(p.name)
                return p
        return None

    # =========================================================================
    # PPD OPTIONS INSPECTION
    # =========================================================================

    def get_printer_options(self, printer_name: str) -> Dict[str, PrinterOption]:
        """Query available hardware/driver options and supported values for a printer."""
        return self._backend.get_printer_options(printer_name)

    # =========================================================================
    # JOB SUBMISSION
    # =========================================================================

    def print_document(
        self,
        file_path: Union[str, Path],
        options: Optional[PrintJobOptions] = None,
        force_pdf_conversion: bool = False,
        progress_callback: Optional[Callable[[int, int], None]] = None,
    ) -> PrintResult:
        """
        Print a document of any supported type (PDF, DOCX, RTF, images, text).
        Handles conversion automatically if required, builds arguments matching
        `PdfCraft` specifications, and submits to the spooler via `/usr/bin/lp` or Win32.
        """
        opts = options or PrintJobOptions()
        if progress_callback:
            opts.progress_callback = progress_callback
        target_path = Path(file_path).expanduser().resolve()
        if not target_path.exists():
            raise FileNotFoundError(f"Cannot print non-existent file: {target_path}")

        # Resolve destination printer
        target_printer = opts.printer
        if not target_printer:
            def_p = self.get_default_printer()
            if not def_p:
                if opts.dry_run:
                    target_printer = "DefaultPrinter"
                    opts.printer = target_printer
                else:
                    raise PrinterNotFoundError(
                        "No default printer configured and no printer specified in options."
                    )
            else:
                target_printer = def_p.name
                opts.printer = target_printer

        # If title is not set, default to document filename
        if not opts.title:
            opts.title = target_path.name

        return self._backend.submit_file(
            target_path, opts, force_pdf_conversion=force_pdf_conversion
        )

    # Alias for convenience matching common naming
    print_file = print_document

    def print_bytes(
        self,
        data: bytes,
        title: str = "Untitled Document",
        options: Optional[PrintJobOptions] = None,
        progress_callback: Optional[Callable[[int, int], None]] = None,
    ) -> PrintResult:
        """
        Print raw bytes (e.g. PDF or PostScript binary stream) directly to the spooler,
        matching `PdfCraft::craft_print::submit_with_progress`.
        """
        opts = options or PrintJobOptions()
        if progress_callback:
            opts.progress_callback = progress_callback
        target_printer = opts.printer or (self.get_default_printer() or Printer(name="")).name
        if not target_printer:
            raise PrinterNotFoundError("No printer available.")

        opts.printer = target_printer
        opts.title = title

        return self._backend.submit_bytes(data, opts)

    def command_preview(
        self,
        target_path_or_bytes: Union[str, Path, bytes],
        options: Optional[PrintJobOptions] = None,
        title: Optional[str] = None,
    ) -> List[str]:
        """
        Preview the exact command line or backend descriptor that would be executed,
        without sending anything to the printer or starting a print job.
        Matches `craft_print::command_preview`.
        """
        base_opts = options or PrintJobOptions()
        dry_opts = dataclasses.replace(base_opts, dry_run=True)
        if isinstance(target_path_or_bytes, (str, Path)):
            result = self.print_file(target_path_or_bytes, options=dry_opts)
        else:
            result = self.print_bytes(target_path_or_bytes, title=title or "Preview", options=dry_opts)
        return result.command_run

    def open_printer_preferences(self, printer_name: Optional[str] = None) -> bool:
        """
        Open the native system printer preferences or properties dialog for a printer.
        On Windows, opens the driver's printing preferences (printui.dll /e).
        On macOS/Linux, opens system printer settings or CUPS web admin.
        """
        target = printer_name or (self.get_default_printer() or Printer(name="")).name
        if not target:
            raise PrinterNotFoundError("No printer specified or available.")
        return self._backend.open_printer_preferences(target)

    # =========================================================================
    # QUEUE & JOB MANAGEMENT
    # =========================================================================

    def get_jobs(self, printer_name: Optional[str] = None) -> List[Dict[str, Any]]:
        """List active print jobs from the system queue."""
        return self._backend.get_jobs(printer_name)

    def cancel_job(self, job_id_or_printer: str, purge_all: bool = False) -> bool:
        """Cancel a specific print job or purge all jobs for a printer."""
        return self._backend.cancel_job(job_id_or_printer, purge_all=purge_all)
