#!/usr/bin/env python3
"""
Example: Discovering all available printers and inspecting hardware PPD capabilities.
"""

import sys
from pathlib import Path

# Add project root to path for standalone execution
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from printer_craft import PrinterManager


def main():
    mgr = PrinterManager()

    print("Querying system printers via CUPS...")
    printers = mgr.list_printers(load_options=True)

    if not printers:
        print("No printers found on this machine.")
        return

    print(f"\nDiscovered {len(printers)} printer(s):")
    for printer in printers:
        default_tag = " [SYSTEM DEFAULT]" if printer.is_default else ""
        print(f"\n==========================================")
        print(f"Printer: {printer.name}{default_tag}")
        print(f"Status:  {printer.status}")
        print(f"Options ({len(printer.options)} detected):")

        for key, opt in list(printer.options.items())[:6]:  # show first 6 options
            default_val = opt.default_choice.name if opt.default_choice else "None"
            choices = ", ".join(c.name for c in opt.choices[:5])
            if len(opt.choices) > 5:
                choices += f" ... (+{len(opt.choices) - 5} more)"
            print(f"  • {opt.keyword} ({opt.display_name}): default={default_val} [choices: {choices}]")


if __name__ == "__main__":
    main()
