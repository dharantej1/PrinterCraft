#!/usr/bin/env python3
"""
Example: Printing a document with passable arguments (duplex, copies, color, media).
"""

import sys
from pathlib import Path

# Add project root to path for standalone execution
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from printer_craft import (
    ColorMode,
    DuplexMode,
    Orientation,
    PrinterManager,
    PrintJobOptions,
    PrintScaling,
)


def main():
    if len(sys.argv) < 2:
        print("Usage: python print_document.py <path_to_document>")
        print("Example: python print_document.py my_document.pdf")
        return

    doc_path = Path(sys.argv[1])
    mgr = PrinterManager()

    # Configure job options
    options = PrintJobOptions(
        copies=1,
        title="Sample Print Job",
        duplex=DuplexMode.ONE_SIDED,
        color_mode=ColorMode.MONOCHROME,
        media="Letter",
        scaling=PrintScaling.AUTO_FIT,
        fit_to_page=True,
        orientation=Orientation.PORTRAIT,
        dry_run=True,  # Set to False to actually send to printer!
    )

    print(f"Submitting '{doc_path.name}' with configured options (DRY-RUN)...")
    result = mgr.print_document(doc_path, options=options)

    if result.dry_run:
        print("\n--- Dry Run Completed ---")
        print(f"Command: {' '.join(result.command_run)}")
    elif result.success:
        print(f"Print job submitted successfully! Job ID: {result.job_id}")
    else:
        print(f"Print failed: {result.error}")


if __name__ == "__main__":
    main()
