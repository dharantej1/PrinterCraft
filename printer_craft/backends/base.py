"""
Abstract printer backend interface implemented by each platform's spooler integration.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..models import PrintJobOptions, PrintResult, Printer, PrinterOption


class PrinterBackend(ABC):
    """Platform-specific printing operations dispatched to by `PrinterManager`."""

    @abstractmethod
    def list_printers(self, load_options: bool = False) -> List[Printer]:
        """Discover all installed printers and their status."""

    @abstractmethod
    def get_default_printer(self) -> Optional[Printer]:
        """Return the default system printer, or None if no printers exist."""

    @abstractmethod
    def get_printer_options(self, printer_name: str) -> Dict[str, PrinterOption]:
        """Query driver/hardware options and supported values for a printer."""

    @abstractmethod
    def submit_file(
        self,
        target_path: Path,
        opts: PrintJobOptions,
        force_pdf_conversion: bool = False,
    ) -> PrintResult:
        """Submit a file. `opts.printer` and `opts.title` are already resolved by the caller."""

    @abstractmethod
    def submit_bytes(self, data: bytes, opts: PrintJobOptions) -> PrintResult:
        """Submit an in-memory document. `opts.printer` and `opts.title` are already resolved."""

    @abstractmethod
    def get_jobs(self, printer_name: Optional[str] = None) -> List[Dict[str, Any]]:
        """List active print jobs as dicts with job_id, user, size_bytes and date keys."""

    @abstractmethod
    def cancel_job(self, job_id_or_printer: str, purge_all: bool = False) -> bool:
        """Cancel a specific print job or purge all jobs for a printer."""
