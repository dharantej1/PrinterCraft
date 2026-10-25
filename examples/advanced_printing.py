#!/usr/bin/env python3
"""
Example: Advanced printing options including N-Up layout, raw PPD keys,
and streaming raw PDF bytes directly to the CUPS spooler.
"""

import sys
from pathlib import Path

# Add project root to path for standalone execution
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from printer_craft import (
    ColorMode,
    DuplexMode,
    PrinterManager,
    PrintJobOptions,
    PrintScaling,
)


def main():
    mgr = PrinterManager()

    # Minimal 1-page sample PDF byte stream
    minimal_pdf = b"""%PDF-1.4
1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj
2 0 obj << /Type /Pages /Kids [3 0 R] /Count 1 >> endobj
3 0 obj << /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >> endobj
4 0 obj << /Length 44 >> stream
BT /F1 24 Tf 100 700 Td (Hello from Printer Craft!) Tj ET
endstream endobj
5 0 obj << /Type /Font /Subtype /Type1 /BaseFont /Helvetica >> endobj
xref
0 6
0000000000 65535 f 
0000000009 00000 n 
0000000058 00000 n 
0000000115 00000 n 
0000000244 00000 n 
0000000339 00000 n 
trailer << /Root 1 0 R /Size 6 >>
startxref
416
%%EOF"""

    options = PrintJobOptions(
        copies=2,
        duplex=DuplexMode.TWO_SIDED_LONG_EDGE,
        color_mode=ColorMode.MONOCHROME,
        number_up=2,  # 2 pages per sheet
        raw_options={
            "InputSlot": "Manual",
            "pjlDensity": "3",
        },
        dry_run=True,  # Preview without submitting
    )

    print("Printing PDF bytes stream with 2-up layout and custom PPD options...")
    res = mgr.print_bytes(minimal_pdf, title="Generated In-Memory Document", options=options)

    print(f"Target Printer: {res.printer}")
    print(f"Command:\n  {' '.join(res.command_run)}")


if __name__ == "__main__":
    main()
