"""
Command-Line Interface for printer_craft.
Supports all printable options for PDFs or any document format,
with dry-run preview and printer capability inspection.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import List, Optional

from .core import PrinterManager
from .models import ColorMode, DuplexMode, Orientation, PrintJobOptions, PrintScaling


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="printer-craft",
        description="Universal CLI printing tool for macOS/Linux (reverse-engineered from PdfCraft.app)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Print a PDF with 2 copies, two-sided, in grayscale:
  printer-craft print document.pdf -n 2 --duplex two-sided-long-edge --color monochrome

  # Print any document type (Word doc, image, or text):
  printer-craft print report.docx -d HP_LaserJet --media A4 --fit-to-page

  # Dry-run to see exact CUPS command generated:
  printer-craft print invoice.pdf --dry-run

  # List all available printers on the machine:
  printer-craft list

  # Inspect hardware capabilities and paper trays of a printer:
  printer-craft options HP_LaserJet_Professional_M1136_MFP
""",
    )

    subparsers = parser.add_subparsers(dest="command", help="Available sub-commands")

    # ================= PRINT SUBCOMMAND =================
    print_parser = subparsers.add_parser("print", help="Print a document with passable options")
    _add_print_arguments(print_parser)

    # ================= LIST SUBCOMMAND =================
    list_parser = subparsers.add_parser("list", help="List all available printers on the machine")
    list_parser.add_argument("--json", action="store_true", help="Output results in JSON format")

    # ================= OPTIONS SUBCOMMAND =================
    opt_parser = subparsers.add_parser(
        "options", help="Display all PPD hardware options for a printer"
    )
    opt_parser.add_argument("printer", nargs="?", help="Printer name (defaults to system default)")
    opt_parser.add_argument("--json", action="store_true", help="Output options in JSON format")

    # ================= JOBS SUBCOMMAND =================
    jobs_parser = subparsers.add_parser("jobs", help="List active jobs in the print queue")
    jobs_parser.add_argument("printer", nargs="?", help="Filter jobs by printer name")

    # ================= CANCEL SUBCOMMAND =================
    cancel_parser = subparsers.add_parser("cancel", help="Cancel a pending print job")
    cancel_parser.add_argument("job_id", help="CUPS Job ID (or printer name if --all is set)")
    cancel_parser.add_argument(
        "-a", "--all", action="store_true", help="Purge all jobs for the specified printer"
    )

    return parser


def _add_print_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("document", help="Path to PDF or document of any type to print")
    parser.add_argument("-d", "--printer", help="Target printer name (default: system default)")
    parser.add_argument("-n", "--copies", type=int, default=1, help="Number of copies (1..999)")
    parser.add_argument("-t", "--title", help="Print job / document title")

    # Duplex
    parser.add_argument(
        "--duplex",
        choices=["one-sided", "two-sided-long-edge", "two-sided-short-edge"],
        help="Duplex printing mode",
    )

    # Collate
    collate_group = parser.add_mutually_exclusive_group()
    collate_group.add_argument("--collate", dest="collate", action="store_true", help="Collate multiple copies")
    collate_group.add_argument("--no-collate", dest="collate", action="store_false", help="Do not collate")
    parser.set_defaults(collate=None)

    # Color
    parser.add_argument(
        "--color",
        choices=["monochrome", "color", "auto"],
        help="Color mode (monochrome / grayscale vs full color)",
    )

    # Media / Page size
    parser.add_argument(
        "-m", "--media", "--page-size",
        dest="media",
        help="Paper size name (e.g. Letter, Legal, A4, A3, Executive)",
    )

    # Page range
    parser.add_argument(
        "-p", "--pages", "--page-ranges",
        dest="page_ranges",
        help="Page ranges to print (e.g. '1-5', '1,3,7', '2-')",
    )

    # Orientation
    parser.add_argument(
        "--orientation",
        choices=["portrait", "landscape", "reverse-landscape", "reverse-portrait"],
        help="Page orientation",
    )

    # Fit to page
    fit_group = parser.add_mutually_exclusive_group()
    fit_group.add_argument("--fit-to-page", dest="fit_to_page", action="store_true", help="Scale document to fit sheet")
    fit_group.add_argument("--no-fit-to-page", dest="fit_to_page", action="store_false", help="Disable fit to page")
    parser.set_defaults(fit_to_page=None)

    # Scaling
    parser.add_argument(
        "--scaling",
        choices=["auto", "auto-fit", "fit-to-page", "fill", "none"],
        help="CUPS print scaling algorithm",
    )

    # Number Up (N-Up)
    parser.add_argument(
        "-N", "--number-up",
        type=int,
        choices=[1, 2, 4, 6, 9, 16],
        help="Print multiple pages per sheet (1, 2, 4, 6, 9, 16)",
    )

    # Custom PPD options
    parser.add_argument(
        "-o", "--option",
        action="append",
        dest="raw_options",
        metavar="KEY=VALUE",
        help="Additional printer/PPD option (e.g. -o InputSlot=Manual)",
    )

    # Pre-conversion flag
    parser.add_argument(
        "--force-pdf",
        action="store_true",
        help="Force pre-conversion of document to PDF before spooling",
    )

    # Dry-run
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Display the exact CUPS command without submitting the job",
    )


def handle_print(args: argparse.Namespace, mgr: PrinterManager) -> int:
    doc_path = Path(args.document).expanduser()
    if not doc_path.exists():
        print(f"Error: Document not found: {doc_path}", file=sys.stderr)
        return 1

    # Parse raw options list ["KEY=VALUE", ...] into dict
    raw_dict = {}
    if args.raw_options:
        for item in args.raw_options:
            if "=" in item:
                k, v = item.split("=", 1)
                raw_dict[k.strip()] = v.strip()
            else:
                raw_dict[item.strip()] = "true"

    opts = PrintJobOptions(
        printer=args.printer,
        copies=args.copies,
        title=args.title,
        duplex=DuplexMode.from_str(args.duplex) if args.duplex else None,
        collate=args.collate,
        color_mode=ColorMode.from_str(args.color) if args.color else None,
        media=args.media,
        page_ranges=args.page_ranges,
        orientation=Orientation.from_str(args.orientation) if args.orientation else None,
        fit_to_page=args.fit_to_page,
        scaling=PrintScaling(args.scaling) if args.scaling else None,
        number_up=args.number_up,
        raw_options=raw_dict,
        dry_run=args.dry_run,
    )

    try:
        result = mgr.print_document(doc_path, options=opts, force_pdf_conversion=args.force_pdf)
    except Exception as e:
        print(f"Print failed: {e}", file=sys.stderr)
        return 1

    if result.dry_run:
        print("\n=== DRY RUN MODE ===")
        print(f"Target Printer: {result.printer}")
        print(f"Command:\n  {' '.join(result.command_run)}")
        print("Job was not sent to hardware.\n")
        return 0

    if result.success:
        print(f"Success! Sent to '{result.printer}'.")
        if result.job_id:
            print(f"Job ID: {result.job_id}")
        return 0
    else:
        print(f"Failed to submit print job: {result.error}", file=sys.stderr)
        return 1


def handle_list(args: argparse.Namespace, mgr: PrinterManager) -> int:
    printers = mgr.list_printers(load_options=False)
    if args.json:
        print(json.dumps([p.to_dict() for p in printers], indent=2))
        return 0

    if not printers:
        print("No printers found on this system.")
        return 0

    print(f"\nFound {len(printers)} printer(s):")
    print("-" * 65)
    for p in printers:
        default_tag = " [DEFAULT]" if p.is_default else ""
        print(f" • {p.name}{default_tag}")
        print(f"   Status: {p.status}")
    print("-" * 65)
    return 0


def handle_options(args: argparse.Namespace, mgr: PrinterManager) -> int:
    printer_name = args.printer
    if not printer_name:
        def_p = mgr.get_default_printer()
        if not def_p:
            print("No printers found on this system.", file=sys.stderr)
            return 1
        printer_name = def_p.name

    options = mgr.get_printer_options(printer_name)
    if args.json:
        out = {
            keyword: {
                "display_name": opt.display_name,
                "default": opt.default_choice.name if opt.default_choice else None,
                "choices": [c.name for c in opt.choices],
            }
            for keyword, opt in options.items()
        }
        print(json.dumps(out, indent=2))
        return 0

    if not options:
        print(f"No options found for printer: {printer_name}")
        return 0

    print(f"\nHardware Options for '{printer_name}':")
    print("=" * 70)
    for opt in options.values():
        default_str = f" (default: {opt.default_choice.name})" if opt.default_choice else ""
        choices_str = ", ".join(
            f"*{c.name}" if c.is_default else c.name for c in opt.choices
        )
        print(f"{opt.keyword} [{opt.display_name}]{default_str}")
        print(f"  Choices: {choices_str}\n")
    print("=" * 70)
    return 0


def handle_jobs(args: argparse.Namespace, mgr: PrinterManager) -> int:
    jobs = mgr.get_jobs(args.printer)
    if not jobs:
        print("No active print jobs in the queue.")
        return 0

    print("\nActive Print Jobs:")
    print("-" * 60)
    for j in jobs:
        print(f"Job ID: {j['job_id']} | User: {j['user']} | Size: {j['size_bytes']} bytes | Time: {j['date']}")
    print("-" * 60)
    return 0


def handle_cancel(args: argparse.Namespace, mgr: PrinterManager) -> int:
    success = mgr.cancel_job(args.job_id, purge_all=args.all)
    if success:
        print(f"Successfully cancelled: {args.job_id}")
        return 0
    else:
        print(f"Failed to cancel: {args.job_id}", file=sys.stderr)
        return 1


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()

    # If first argument looks like a file and isn't a known subcommand, default to 'print'
    args_list = sys.argv[1:] if argv is None else argv
    if args_list and args_list[0] not in ("print", "list", "options", "jobs", "cancel", "-h", "--help"):
        args_list = ["print"] + args_list

    parsed = parser.parse_args(args_list)
    if not parsed.command:
        parser.print_help()
        return 0

    mgr = PrinterManager()

    if parsed.command == "print":
        return handle_print(parsed, mgr)
    elif parsed.command == "list":
        return handle_list(parsed, mgr)
    elif parsed.command == "options":
        return handle_options(parsed, mgr)
    elif parsed.command == "jobs":
        return handle_jobs(parsed, mgr)
    elif parsed.command == "cancel":
        return handle_cancel(parsed, mgr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
