"""
Core CUPS printer management and job submission engine, reverse-engineered
from macOS PdfCraft.app architecture.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

from .converter import DocumentConverter
from .exceptions import (
    DocumentConversionError,
    PrinterNotFoundError,
    PrintExecutionError,
    SpoolerUnavailableError,
)
from .models import (
    PrintJobOptions,
    PrintResult,
    Printer,
    PrinterOption,
    PrinterOptionChoice,
)


class PrinterManager:
    """
    High-level manager for discovering local/network printers, querying PPD
    capabilities, and submitting print jobs via CUPS.
    """

    def __init__(
        self,
        lp_bin: Optional[str] = None,
        lpstat_bin: Optional[str] = None,
        lpoptions_bin: Optional[str] = None,
        cancel_bin: Optional[str] = None,
    ):
        self.lp_bin = lp_bin or shutil.which("lp") or "/usr/bin/lp"
        self.lpstat_bin = lpstat_bin or shutil.which("lpstat") or "/usr/bin/lpstat"
        self.lpoptions_bin = lpoptions_bin or shutil.which("lpoptions") or "/usr/bin/lpoptions"
        self.cancel_bin = cancel_bin or shutil.which("cancel") or "/usr/bin/cancel"

    def _get_cups_env(self) -> Dict[str, str]:
        """
        Return the standardized environment variables required to prevent
        locale-dependent output changes (identified in PdfCraft::craft_print::lpstat_with).
        """
        env = os.environ.copy()
        env["LC_ALL"] = "C"
        env["LANG"] = "C"
        return env

    def _run_cmd(
        self,
        cmd: List[str],
        check: bool = False,
        timeout: Optional[float] = 5.0,
    ) -> Tuple[int, str, str]:
        """Execute a sub-process with sanitized CUPS environment variables and timeout protection."""
        try:
            res = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=self._get_cups_env(),
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            err = f"Command timed out after {timeout}s: {' '.join(cmd)}"
            if check:
                raise PrintExecutionError(err, return_code=124, command=cmd)
            return 124, "", err
        except FileNotFoundError:
            err = f"Command binary not found: {cmd[0]}"
            if check:
                raise SpoolerUnavailableError(err)
            return 127, "", err

        if check and res.returncode != 0:
            err = res.stderr.strip() or res.stdout.strip()
            if "spooler is not running" in err.lower() or "server-error" in err.lower():
                raise SpoolerUnavailableError(f"CUPS spooler is not responding: {err}")
            raise PrintExecutionError(
                f"Command failed ({res.returncode}): {' '.join(cmd)}\n{err}",
                return_code=res.returncode,
                command=cmd,
            )
        return res.returncode, res.stdout, res.stderr

    # =========================================================================
    # PRINTER DISCOVERY & ENUMERATION
    # =========================================================================

    def list_printers(self, load_options: bool = False) -> List[Printer]:
        """
        Discover all installed printers and their status on macOS.
        Replicates the dual-phase discovery logic of `PdfCraft::craft_print::printers`.
        """
        code, stdout, stderr = self._run_cmd([self.lpstat_bin, "-p", "-d"])
        if code != 0 and not stdout:
            if "spooler is not running" in stderr.lower() or "server-error" in stderr.lower():
                raise SpoolerUnavailableError(f"CUPS print spooler error: {stderr.strip()}")
            if code == 127 or "not found" in stderr.lower():
                return []

        printers_dict: Dict[str, Printer] = {}
        default_printer_name: Optional[str] = None

        # 1. Parse `lpstat -p -d`
        for line in stdout.splitlines():
            line = line.strip()
            if not line:
                continue

            # Check default printer line: "system default destination: HP_LaserJet_..."
            if line.startswith("system default destination:"):
                parts = line.split(":", 1)
                if len(parts) == 2:
                    default_printer_name = parts[1].strip()
                continue

            # Check printer status: "printer HP_LaserJet... is idle. enabled since ..."
            if line.startswith("printer "):
                # regex: printer (\S+) (is idle|disabled|printing)
                match = re.match(r"^printer\s+([^\s]+)\s+(.+)$", line)
                if match:
                    p_name = match.group(1)
                    p_status = match.group(2)
                    printers_dict[p_name] = Printer(
                        name=p_name,
                        status=p_status,
                        is_default=False,
                    )

        # 2. Supplementary enumeration via `lpstat -e` (modern CUPS available destinations)
        code_e, stdout_e, _ = self._run_cmd([self.lpstat_bin, "-e"])
        if code_e == 0 and stdout_e:
            for p_name in stdout_e.splitlines():
                p_name = p_name.strip()
                if p_name and p_name not in printers_dict:
                    printers_dict[p_name] = Printer(
                        name=p_name,
                        status="ready",
                        is_default=False,
                    )

        # 3. Mark the default printer
        if default_printer_name and default_printer_name in printers_dict:
            printers_dict[default_printer_name].is_default = True
        elif printers_dict and not default_printer_name:
            # If default wasn't found but printers exist, pick first
            first_printer = next(iter(printers_dict.values()))
            first_printer.is_default = True

        # Optionally load hardware options for each printer
        if load_options:
            for p in printers_dict.values():
                p.options = self.get_printer_options(p.name)

        return list(printers_dict.values())

    def get_default_printer(self) -> Optional[Printer]:
        """Return the default system printer, or None if no printers exist."""
        printers = self.list_printers(load_options=False)
        for p in printers:
            if p.is_default:
                return p
        return printers[0] if printers else None

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
        """
        Query available hardware options and supported values for a printer
        by executing and parsing `lpoptions -p <printer_name> -l`.
        """
        code, stdout, stderr = self._run_cmd(
            [self.lpoptions_bin, "-p", printer_name, "-l"], timeout=3.0
        )
        if code != 0:
            return {}

        options: Dict[str, PrinterOption] = {}
        for line in stdout.splitlines():
            line = line.strip()
            if not line or ":" not in line:
                continue

            header_part, choices_part = line.split(":", 1)
            # header format: "Keyword/Human Readable Title" or "Keyword"
            if "/" in header_part:
                keyword, display_name = header_part.split("/", 1)
            else:
                keyword, display_name = header_part, header_part

            keyword = keyword.strip()
            display_name = display_name.strip()

            choice_tokens = choices_part.strip().split()
            choices: List[PrinterOptionChoice] = []

            for token in choice_tokens:
                is_def = token.startswith("*")
                name = token[1:] if is_def else token
                choices.append(
                    PrinterOptionChoice(
                        name=name,
                        display_text=name,
                        is_default=is_def,
                    )
                )

            options[keyword] = PrinterOption(
                keyword=keyword,
                display_name=display_name,
                choices=choices,
            )

        return options

    # =========================================================================
    # JOB SUBMISSION
    # =========================================================================

    def print_document(
        self,
        file_path: Union[str, Path],
        options: Optional[PrintJobOptions] = None,
        force_pdf_conversion: bool = False,
    ) -> PrintResult:
        """
        Print a document of any supported type (PDF, DOCX, RTF, images, text).
        Handles conversion automatically if required, builds arguments matching
        `PdfCraft` specifications, and submits to the CUPS spooler via `/usr/bin/lp`.
        """
        opts = options or PrintJobOptions()
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

        # Detect repeated/non-monotonic page ranges (e.g. "1,1,1,1")
        # CUPS lp throws "Bad page-ranges" if pages repeat or aren't strictly increasing.
        # We handle this transparently by duplicating pages via PDFKit before spooling.
        page_sequence = None
        if opts.page_ranges:
            try:
                tokens = [t.strip() for t in opts.page_ranges.split(",")]
                parsed_pages = []
                is_simple_list = True
                for t in tokens:
                    if "-" in t:
                        is_simple_list = False
                        break
                    parsed_pages.append(int(t))
                if is_simple_list and parsed_pages:
                    # Check if there are duplicates or descending order
                    if len(parsed_pages) != len(set(parsed_pages)) or parsed_pages != sorted(parsed_pages):
                        page_sequence = parsed_pages
                        # Clear from lp options so lp receives clean file
                        opts.page_ranges = None
            except Exception:
                pass

        if opts.repeat and opts.repeat > 1 and page_sequence is None:
            # Repeat the document page(s)
            page_sequence = [1] * opts.repeat

        with DocumentConverter.prepare_for_print(
            target_path, force_pdf=force_pdf_conversion, page_sequence=page_sequence
        ) as printable_path:
            lp_args = opts.build_lp_args()
            cmd = [self.lp_bin] + lp_args + [str(printable_path)]

            if opts.dry_run:
                return PrintResult(
                    success=True,
                    printer=target_printer,
                    job_id="DRY-RUN-0",
                    command_run=cmd,
                    output="Dry run executed successfully. No job sent to printer.",
                    dry_run=True,
                )

            code, stdout, stderr = self._run_cmd(cmd)

            if code != 0:
                err_msg = stderr.strip() or stdout.strip()
                if "spooler is not running" in err_msg.lower():
                    raise SpoolerUnavailableError(f"CUPS spooler is down: {err_msg}")
                return PrintResult(
                    success=False,
                    printer=target_printer,
                    command_run=cmd,
                    output=stdout.strip(),
                    error=err_msg,
                )

            # Extract CUPS request id: "request id is HP_LaserJet_Professional_M1136_MFP-104 (1 file(s))"
            job_id: Optional[str] = None
            match = re.search(r"request id is ([^\s]+)", stdout)
            if match:
                job_id = match.group(1)

            return PrintResult(
                success=True,
                printer=target_printer,
                job_id=job_id,
                command_run=cmd,
                output=stdout.strip(),
            )

    def print_bytes(
        self,
        data: bytes,
        title: str = "Untitled Document",
        options: Optional[PrintJobOptions] = None,
    ) -> PrintResult:
        """
        Print raw bytes (e.g. PDF or PostScript binary stream) directly to `/usr/bin/lp` stdin,
        identical to `PdfCraft::craft_print::submit_with_progress`.
        """
        opts = options or PrintJobOptions()
        target_printer = opts.printer or (self.get_default_printer() or Printer(name="")).name
        if not target_printer:
            raise PrinterNotFoundError("No printer available.")

        opts.printer = target_printer
        opts.title = title

        cmd = [self.lp_bin] + opts.build_lp_args()

        if opts.dry_run:
            return PrintResult(
                success=True,
                printer=target_printer,
                job_id="DRY-RUN-0",
                command_run=cmd,
                output="Dry run bytes submission.",
                dry_run=True,
            )

        res = subprocess.run(
            cmd,
            input=data,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=self._get_cups_env(),
        )

        stdout = res.stdout.decode("utf-8", errors="ignore").strip()
        stderr = res.stderr.decode("utf-8", errors="ignore").strip()

        if res.returncode != 0:
            return PrintResult(
                success=False,
                printer=target_printer,
                command_run=cmd,
                output=stdout,
                error=stderr,
            )

        job_id = None
        match = re.search(r"request id is ([^\s]+)", stdout)
        if match:
            job_id = match.group(1)

        return PrintResult(
            success=True,
            printer=target_printer,
            job_id=job_id,
            command_run=cmd,
            output=stdout,
        )

    # =========================================================================
    # QUEUE & JOB MANAGEMENT
    # =========================================================================

    def get_jobs(self, printer_name: Optional[str] = None) -> List[Dict[str, Any]]:
        """List active print jobs from the CUPS queue."""
        cmd = [self.lpstat_bin, "-o"]
        if printer_name:
            cmd.append(printer_name)

        code, stdout, stderr = self._run_cmd(cmd)
        jobs: List[Dict[str, Any]] = []

        # Example output: "HP_LaserJet-104 user 1024 Sun Oct 25 18:00:00 2026"
        for line in stdout.splitlines():
            parts = line.strip().split()
            if len(parts) >= 4:
                jobs.append({
                    "job_id": parts[0],
                    "user": parts[1],
                    "size_bytes": parts[2],
                    "date": " ".join(parts[3:]),
                })
        return jobs

    def cancel_job(self, job_id_or_printer: str, purge_all: bool = False) -> bool:
        """Cancel a specific print job or purge all jobs for a printer."""
        if purge_all:
            cmd = [self.cancel_bin, "-a", job_id_or_printer]
        else:
            cmd = [self.cancel_bin, job_id_or_printer]

        code, _, _ = self._run_cmd(cmd)
        return code == 0
