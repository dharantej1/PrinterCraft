# printer-craft 🖨️

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)
[![Platform](https://img.shields.io/badge/platform-macOS%20%7C%20Linux%20%7C%20Windows-lightgrey.svg)](https://www.cups.org/)

**printer-craft** is a Python library and CLI tool for discovering printers, querying hardware PPD options, and submitting print jobs on macOS and Unix systems (via CUPS) and on Windows (via the Windows print spooler).

The core communication architecture was **reverse-engineered from the native macOS desktop application `PdfCraft.app`**, extracting its exact CUPS subprocess pipeline, environment handling, PPD parser, and argument builder.

---

## 🌟 Key Features

- **Reverse-Engineered CUPS Architecture**: Implements the identical printing pipeline found in native macOS desktop software (`craft_print`).
- **Universal Document Support**: Prints **PDFs**, **Images** (`.png`, `.jpg`, `.tiff`, `.heic`), **Office docs** (`.docx`, `.rtf`, `.odt`), and **Source code / text** (`.txt`, `.py`, `.md`, `.log`) with automatic format conversion using native macOS utilities (`cupsfilter`, `textutil`, `sips`).
- **Passable Printing Options**:
  - Copies (`-n 1..999`)
  - Duplex (`one-sided`, `two-sided-long-edge`, `two-sided-short-edge`)
  - Collation (`--collate` / `--no-collate`)
  - Color mode (`monochrome` / `color`)
  - Paper size (`Letter`, `Legal`, `A4`, `A3`, `Custom`, etc.)
  - Page ranges & sequences (`1-5`, `2,4,8`, or repeated `1,1,1,1`)
  - Page repetition & imposition (`--repeat 4` / `-R 4` for multi-copy n-up)
  - Orientation (`portrait`, `landscape`, `reverse-landscape`, `reverse-portrait`)
  - N-Up printing (`1`, `2`, `4`, `6`, `9`, `16` pages per sheet)
  - Scaling & fit-to-page (`auto-fit`, `fit-to-page`, `fill`)
  - Custom hardware PPD keys (`-o InputSlot=Manual`, `-o pjlDensity=3`)
- **Intelligent Page Imposition**: Automatically duplicates/rearranges PDF pages via native macOS `PDFKit` (JXA) when repeating pages, bypassing the CUPS `Bad page-ranges values` limitation.
- **Safe Dry-Run Mode**: Inspect generated CUPS commands without sending jobs to physical hardware.
- **Queue Management**: Inspect active print queues and cancel pending jobs.
- **Zero Heavy Dependencies**: Pure Python using standard library and operating system CUPS binaries.

---

## 🔬 Reverse Engineering Background

A deep-dive disassembly of `/Applications/PdfCraft.app` (Mach-O ARM64/x86_64 Rust binary) was performed to analyze how native applications interact with printers on macOS. Key findings from `craft_print`:

1. **Discovery (`craft_print::lpstat_with`)**: Uses `/usr/bin/lpstat -p -d` with `LC_ALL=C` and `LANG=C` to retrieve localized status cleanly.
2. **Hardware Capabilities (`craft_print::parse_lpoptions`)**: Executes `/usr/bin/lpoptions -p <name> -l` and parses the PostScript Printer Description (PPD) key/value definitions.
3. **Option Assembly (`craft_print::lp_args`)**: Maps options to CUPS `-o key=value` arguments (`sides=two-sided-long-edge`, `collate=true`, `print-color-mode=monochrome`, `print-scaling=auto-fit`).
4. **Spooling (`craft_print::submit_with_progress`)**: Submits print data directly to `/usr/bin/lp` stdin or file arguments.

Full disassembly and instruction analysis is documented in [REVERSE_ENGINEERING.md](REVERSE_ENGINEERING.md).

---

## 🚀 Installation

### From Source
```bash
git clone https://github.com/dharantej1/PrinterCraft.git
cd PrinterCraft
pip install .
```

### Editable Development Mode
```bash
pip install -e .
```

### Windows
```bash
pip install ".[windows]"
```
The `windows` extra installs `pywin32` (plus `pypdf` and `Pillow` for document
conversion) and is a no-op on macOS/Linux. See [Windows Support](#-windows-support).

---

## 🖥️ Command-Line Interface (CLI)

The package installs the `printer-craft` (or `printcraft`) command-line utility.

### 1. Print Documents with All Passable Options

```bash
# Print a PDF in monochrome, 2 copies, two-sided long-edge:
printer-craft print report.pdf \
  -n 2 \
  --duplex two-sided-long-edge \
  --color monochrome \
  --media A4

# Print 4 copies of a 1-page document back-to-back on 1 sheet (2 copies per side):
printer-craft print ApplicationForm.pdf \
  --repeat 4 \
  -N 2 \
  --duplex two-sided-short-edge \
  --fit-to-page

# Alternatively using page sequence:
printer-craft print ApplicationForm.pdf --pages 1,1,1,1 -N 2 --duplex two-sided-short-edge

# Print specific pages with 2-up layout:
printer-craft print slides.pdf --pages 1-10 -N 2 --orientation landscape

# Print Word document or text file directly:
printer-craft print contract.docx --fit-to-page

# Pass custom printer-specific hardware options:
printer-craft print label.pdf -o InputSlot=Manual -o pjlDensity=4

# Dry-run preview (generates the exact CUPS lp command without printing):
printer-craft print document.pdf -n 3 --duplex two-sided-short-edge --dry-run
```

### 2. Discover Available Printers

```bash
printer-craft list
```
Output:
```text
Found 2 printer(s):
-----------------------------------------------------------------
 • HP_LaserJet_Professional_M1136_MFP [DEFAULT]
   Status: is idle. enabled since Sun Oct 25 16:02:51 2026
 • HP_LaserJet_Professional_M1136_MFP_Network
   Status: ready
-----------------------------------------------------------------
```

### 3. Inspect Printer Hardware Options

```bash
printer-craft options HP_LaserJet_Professional_M1136_MFP
```
Output:
```text
Hardware Options for 'HP_LaserJet_Professional_M1136_MFP':
======================================================================
PageSize [Media Size] (default: Letter)
  Choices: *Letter, Legal, A4, Executive, A5, A6, Custom.WIDTHxHEIGHT

Duplex [2-Sided Printing] (default: None)
  Choices: *None, DuplexNoTumble, DuplexTumble

MediaType [Media Type] (default: Paper)
  Choices: *Paper, Heavy111-130g, TransparencyPaper, LabelsPaper

Resolutions [Resolution] (default: 600x400dpi)
  Choices: *600x400dpi, 600x600dpi
======================================================================
```

### 4. Check Queue & Cancel Jobs

```bash
# List active jobs in print queue:
printer-craft jobs

# Cancel a specific job:
printer-craft cancel HP_LaserJet_Professional_M1136_MFP-104

# Purge all jobs for a printer:
printer-craft cancel HP_LaserJet_Professional_M1136_MFP --all
```

---

## 🐍 Python API Usage

### 1. Setup — `PrinterManager`

`PrinterManager` is the main entry point. It auto-discovers CUPS binaries but
allows you to override them for custom CUPS installations.

```python
from printer_craft import PrinterManager

# Default: auto-discovers lp, lpstat, lpoptions, cancel from PATH / /usr/bin
mgr = PrinterManager()

# Override individual binaries (e.g. custom CUPS install)
mgr = PrinterManager(
    lp_bin="/opt/cups/bin/lp",
    lpstat_bin="/opt/cups/bin/lpstat",
    lpoptions_bin="/opt/cups/bin/lpoptions",
    cancel_bin="/opt/cups/bin/cancel",
)
```

---

### 2. Discovering Printers

#### `list_printers(load_options=False)` → `List[Printer]`

Returns all installed printers. Pass `load_options=True` to eagerly load each
printer's PPD hardware options in a single call.

```python
from printer_craft import PrinterManager

mgr = PrinterManager()

# Basic list (fast — no PPD option loading)
printers = mgr.list_printers()
for p in printers:
    print(f"{p.name}  status={p.status}  default={p.is_default}")

# With hardware options pre-loaded
printers = mgr.list_printers(load_options=True)
for p in printers:
    print(f"\n{p.name}  [default={p.is_default}]")
    for key, opt in p.options.items():
        default_val = opt.default_choice.name if opt.default_choice else "None"
        choices     = ", ".join(c.name for c in opt.choices)
        print(f"  {opt.keyword} ({opt.display_name}): default={default_val}  choices=[{choices}]")
```

#### `get_default_printer()` → `Optional[Printer]`

Returns the system default printer, or `None` if no printers are configured.

```python
default = mgr.get_default_printer()
if default:
    print(f"Default printer: {default.name}")
else:
    print("No printers configured.")
```

#### `get_printer(name, load_options=True)` → `Optional[Printer]`

Look up a single printer by its exact CUPS name.

```python
printer = mgr.get_printer("HP_LaserJet_Professional_M1136_MFP")
if printer:
    print(f"Found: {printer.name}  status={printer.status}")
else:
    print("Printer not found.")
```

---

### 3. Inspecting PPD Hardware Options

#### `get_printer_options(printer_name)` → `Dict[str, PrinterOption]`

Executes `lpoptions -p <name> -l` and parses the printer's PostScript Printer
Description (PPD) key→value table. Each `PrinterOption` contains its keyword,
human-readable display name, and a list of `PrinterOptionChoice` objects.

```python
from printer_craft import PrinterManager

mgr     = PrinterManager()
options = mgr.get_printer_options("HP_LaserJet_Professional_M1136_MFP")

for keyword, opt in options.items():
    default = opt.default_choice
    print(f"{opt.keyword} [{opt.display_name}]")
    print(f"  Default : {default.name if default else 'None'}")
    for choice in opt.choices:
        marker = " *" if choice.is_default else "  "
        print(f"  {marker} {choice.name}")
```

You can also get options through a `Printer` object when `load_options=True`:

```python
printer = mgr.get_printer("HP_LaserJet_Professional_M1136_MFP", load_options=True)
page_size_opt = printer.options.get("PageSize")
if page_size_opt:
    print("Supported paper sizes:", [c.name for c in page_size_opt.choices])
```

Serialize all options to a plain dict (e.g. for JSON output):

```python
import json
printer = mgr.get_printer("HP_LaserJet_Professional_M1136_MFP", load_options=True)
print(json.dumps(printer.to_dict(), indent=2))
```

---

### 4. `PrintJobOptions` — All Parameters

`PrintJobOptions` is a dataclass that holds every configurable option for a
print job. All fields are optional (with sensible defaults).

```python
from printer_craft import (
    PrintJobOptions,
    DuplexMode,
    ColorMode,
    Orientation,
    PrintScaling,
)

options = PrintJobOptions(
    # Target printer (None → system default)
    printer="HP_LaserJet_Professional_M1136_MFP",

    # Number of copies (1–999)
    copies=2,

    # Job title shown in CUPS queue
    title="Q4 Financial Report",

    # Two-sided printing
    # DuplexMode.ONE_SIDED | TWO_SIDED_LONG_EDGE | TWO_SIDED_SHORT_EDGE
    duplex=DuplexMode.TWO_SIDED_LONG_EDGE,

    # Collation across multiple copies
    # True  → sets in order: 1,2,3 | 1,2,3
    # False → grouped:       1,1   | 2,2   | 3,3
    collate=True,

    # Color mode
    # ColorMode.MONOCHROME | COLOR | AUTO
    color_mode=ColorMode.MONOCHROME,

    # Paper size (must match a PPD PageSize choice)
    media="A4",

    # Page ranges — standard CUPS syntax
    # Examples: "1-5", "2,4,7", "1-3,5", "3-"
    # Non-monotonic sequences like "1,1,1,1" are handled automatically via PDFKit
    page_ranges="1-10",

    # Page orientation
    # Orientation.PORTRAIT | LANDSCAPE | REVERSE_LANDSCAPE | REVERSE_PORTRAIT
    orientation=Orientation.PORTRAIT,

    # Scale document to fit printable area (default True, mirrors PdfCraft.app)
    fit_to_page=True,

    # CUPS IPP print-scaling policy (separate from fit_to_page)
    # PrintScaling.AUTO | AUTO_FIT | FIT_TO_PAGE | FILL | NONE
    scaling=PrintScaling.AUTO_FIT,

    # N-Up: pages per physical sheet (1, 2, 4, 6, 9, or 16)
    number_up=2,

    # Repeat: duplicate the document N times before spooling
    # Useful with number_up (e.g. repeat=4, number_up=4 → 4 IDs on one sheet)
    repeat=1,

    # Raw PPD / driver-specific key=value overrides
    raw_options={
        "InputSlot": "Manual",
        "Resolution": "600dpi",
        "pjlDensity": "3",
    },

    # Dry-run: build and return the lp command without sending to hardware
    dry_run=False,
)
```

---

### 5. Printing a Document File

#### `print_document(file_path, options=None, force_pdf_conversion=False)` → `PrintResult`

Accepts any supported file type (`.pdf`, `.docx`, `.rtf`, `.odt`, `.png`,
`.jpg`, `.tiff`, `.heic`, `.txt`, `.py`, `.md`). Non-PDF formats are
auto-converted using native macOS tools (`textutil`, `sips`, `cupsfilter`).

```python
from printer_craft import (
    PrinterManager, PrintJobOptions,
    DuplexMode, ColorMode, Orientation, PrintScaling,
)

mgr = PrinterManager()

# --- Example 1: Simple one-sided monochrome PDF ---
result = mgr.print_document(
    "invoice.pdf",
    options=PrintJobOptions(
        copies=1,
        duplex=DuplexMode.ONE_SIDED,
        color_mode=ColorMode.MONOCHROME,
        media="A4",
        fit_to_page=True,
    ),
)
if result.success:
    print(f"Job submitted → {result.printer}  ID: {result.job_id}")
else:
    print(f"Failed: {result.error}")


# --- Example 2: Two-sided, 2-up landscape handout (pages 1–20) ---
result = mgr.print_document(
    "slides.pdf",
    options=PrintJobOptions(
        copies=30,
        duplex=DuplexMode.TWO_SIDED_LONG_EDGE,
        collate=True,
        media="A4",
        page_ranges="1-20",
        number_up=2,
        orientation=Orientation.LANDSCAPE,
    ),
)


# --- Example 3: Print 4 copies of a 1-page ID card on one sheet ---
# repeat=4 duplicates the page 4 times before spooling;
# number_up=4 arranges all 4 on a single physical sheet.
result = mgr.print_document(
    "id_card.pdf",
    options=PrintJobOptions(
        repeat=4,
        number_up=4,
        duplex=DuplexMode.ONE_SIDED,
        fit_to_page=True,
    ),
)


# --- Example 4: Non-monotonic page sequence (handled automatically) ---
# Prints page 1 four times; PDFKit pre-synthesizes the repeated PDF
# so CUPS never sees "Bad page-ranges values".
result = mgr.print_document(
    "application_form.pdf",
    options=PrintJobOptions(
        page_ranges="1,1,1,1",
        number_up=2,
        duplex=DuplexMode.TWO_SIDED_SHORT_EDGE,
    ),
)


# --- Example 5: Word / RTF / text file (auto-converted before spooling) ---
result = mgr.print_document(
    "contract.docx",
    options=PrintJobOptions(fit_to_page=True),
)


# --- Example 6: Custom PPD hardware overrides ---
result = mgr.print_document(
    "label.pdf",
    options=PrintJobOptions(
        media="Custom.62x100mm",
        raw_options={"InputSlot": "Manual", "pjlDensity": "4"},
    ),
)


# --- Example 7: Force intermediate PDF conversion ---
result = mgr.print_document(
    "photo.heic",
    options=PrintJobOptions(media="A4"),
    force_pdf_conversion=True,
)


# --- Example 8: Dry-run — inspect the lp command without printing ---
result = mgr.print_document(
    "document.pdf",
    options=PrintJobOptions(
        copies=3,
        duplex=DuplexMode.TWO_SIDED_SHORT_EDGE,
        dry_run=True,
    ),
)
print("Would run:", " ".join(result.command_run))
```

---

### 6. Printing Raw Bytes (In-Memory PDF Stream)

#### `print_bytes(data, title, options=None)` → `PrintResult`

Streams a bytes object (PDF or PostScript) directly to `/usr/bin/lp` stdin,
identical to `PdfCraft::craft_print::submit_with_progress`.

```python
from printer_craft import PrinterManager, PrintJobOptions, DuplexMode, ColorMode

mgr = PrinterManager()

# Minimal valid 1-page PDF
minimal_pdf = b"""%PDF-1.4
1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj
2 0 obj << /Type /Pages /Kids [3 0 R] /Count 1 >> endobj
3 0 obj << /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792]
           /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >> endobj
4 0 obj << /Length 44 >> stream
BT /F1 24 Tf 100 700 Td (Hello, Printer!) Tj ET
endstream endobj
5 0 obj << /Type /Font /Subtype /Type1 /BaseFont /Helvetica >> endobj
xref
0 6
0000000000 65535 f
0000000009 00000 n
0000000058 00000 n
0000000115 00000 n
0000000266 00000 n
0000000360 00000 n
trailer << /Root 1 0 R /Size 6 >>
startxref
441
%%EOF"""

result = mgr.print_bytes(
    minimal_pdf,
    title="Generated Invoice #1042",
    options=PrintJobOptions(
        copies=2,
        duplex=DuplexMode.TWO_SIDED_LONG_EDGE,
        color_mode=ColorMode.MONOCHROME,
        number_up=2,
        raw_options={"InputSlot": "Manual", "pjlDensity": "3"},
        dry_run=True,  # Remove to actually print
    ),
)

print(f"Printer : {result.printer}")
print(f"Job ID  : {result.job_id}")
print(f"Command : {' '.join(result.command_run)}")
```

---

### 7. Queue Management

#### `get_jobs(printer_name=None)` → `List[Dict]`

Lists active CUPS jobs. Pass a printer name to filter by printer.

```python
from printer_craft import PrinterManager

mgr  = PrinterManager()
jobs = mgr.get_jobs()  # all printers

for job in jobs:
    print(f"  {job['job_id']}  user={job['user']}  size={job['size_bytes']}B  date={job['date']}")

# Filter to a specific printer
jobs = mgr.get_jobs("HP_LaserJet_Professional_M1136_MFP")
```

#### `cancel_job(job_id_or_printer, purge_all=False)` → `bool`

Cancel a single job by its CUPS job ID, or purge all jobs for a printer.

```python
# Cancel a specific job
cancelled = mgr.cancel_job("HP_LaserJet_Professional_M1136_MFP-104")
print("Cancelled:", cancelled)

# Purge all pending jobs for a printer
mgr.cancel_job("HP_LaserJet_Professional_M1136_MFP", purge_all=True)
```

---

### 8. Error Handling

All exceptions inherit from `PrinterError`. Catch them individually for
granular recovery, or catch the base class for a catch-all.

```python
from printer_craft import (
    PrinterManager, PrintJobOptions,
    PrinterError,
    PrinterNotFoundError,
    SpoolerUnavailableError,
    DocumentConversionError,
    PrintExecutionError,
)

mgr = PrinterManager()

try:
    result = mgr.print_document(
        "report.pdf",
        options=PrintJobOptions(printer="NonExistentPrinter"),
    )
except PrinterNotFoundError as e:
    # Raised when no printer is found / specified printer doesn't exist
    print(f"Printer not found: {e}")

except SpoolerUnavailableError as e:
    # Raised when the CUPS daemon is not running or unreachable
    print(f"CUPS spooler is down: {e}")

except DocumentConversionError as e:
    # Raised when textutil / sips / cupsfilter conversion fails
    print(f"Could not convert document: {e}")

except PrintExecutionError as e:
    # Raised when /usr/bin/lp exits with a non-zero return code
    print(f"lp command failed (exit {e.return_code}): {e}")
    print(f"Command: {' '.join(e.command)}")

except FileNotFoundError as e:
    # Raised by print_document when the input file doesn't exist
    print(f"File not found: {e}")

except PrinterError as e:
    # Catch-all for any other printer_craft error
    print(f"Printer error: {e}")
```

---

### 9. Enum Reference

```python
from printer_craft import DuplexMode, ColorMode, Orientation, PrintScaling

# DuplexMode
DuplexMode.ONE_SIDED            # → sides=one-sided
DuplexMode.TWO_SIDED_LONG_EDGE  # → sides=two-sided-long-edge  (portrait book flip)
DuplexMode.TWO_SIDED_SHORT_EDGE # → sides=two-sided-short-edge (notepad / calendar flip)

# Parse from string (case-insensitive, accepts aliases)
DuplexMode.from_str("duplex")          # → TWO_SIDED_LONG_EDGE
DuplexMode.from_str("tumble")          # → TWO_SIDED_SHORT_EDGE
DuplexMode.from_str("one-sided")       # → ONE_SIDED

# ColorMode
ColorMode.MONOCHROME  # → print-color-mode=monochrome
ColorMode.COLOR       # → print-color-mode=color
ColorMode.AUTO        # (no -o flag generated)

ColorMode.from_str("gray")    # → MONOCHROME
ColorMode.from_str("colour")  # → COLOR

# Orientation  (CUPS orientation-requested numeric values)
Orientation.PORTRAIT          # → orientation-requested=3
Orientation.LANDSCAPE         # → orientation-requested=4  (90° CCW)
Orientation.REVERSE_LANDSCAPE # → orientation-requested=5  (90° CW)
Orientation.REVERSE_PORTRAIT  # → orientation-requested=6  (180°)

Orientation.from_str("landscape") # → LANDSCAPE

# PrintScaling
PrintScaling.AUTO        # → print-scaling=auto
PrintScaling.AUTO_FIT    # → print-scaling=auto-fit
PrintScaling.FIT_TO_PAGE # → print-scaling=fit-to-page
PrintScaling.FILL        # → print-scaling=fill
PrintScaling.NONE        # → print-scaling=none
```

---

### 10. Inspecting `PrintResult`

Every `print_document` / `print_bytes` call returns a `PrintResult` dataclass.

```python
from printer_craft import PrinterManager, PrintJobOptions

mgr    = PrinterManager()
result = mgr.print_document("doc.pdf", options=PrintJobOptions(dry_run=True))

result.success      # bool   — True if job submitted (or dry-run)
result.printer      # str    — resolved target printer name
result.job_id       # Optional[str]  — e.g. "HP_LaserJet-104"  (None on dry-run)
result.command_run  # List[str]      — exact argv passed to /usr/bin/lp
result.output       # str    — raw stdout from lp
result.error        # Optional[str]  — error message if success=False
result.dry_run      # bool   — True when options.dry_run was set
```

---

## 📋 Complete CLI & API Parameters Reference

### 1. `printer-craft print` Parameters

| Parameter / Flag | Python Type | Default Value | Allowed Values | CUPS Flag Generated | Description |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **`document`** *(positional)* | `str` / `Path` | *(Required)* | Any valid file path (`.pdf`, `.docx`, `.png`, `.jpg`, `.txt`, etc.) | Direct file path argument | Path to the document or image to print. PDF files are spooled directly; other formats (Word, RTF, images, text) are automatically converted via macOS native tools (`cupsfilter`, `textutil`, `sips`). |
| **`-d, --printer`** | `Optional[str]` | `None` *(resolves to system default)* | Any installed CUPS printer name (e.g. `HP_LaserJet_Professional_M1136_MFP`) | `-d <name>` | Destination printer name. Run `printer-craft list` to view all available printers on your machine. |
| **`-n, --copies`** | `int` | `1` | `1` to `999` | `-n <int>` *(when > 1)* | Number of copies of the document to print. |
| **`-t, --title`** | `Optional[str]` | `None` *(defaults to file name)* | Any text string (e.g. `"Q4 Report"`) | `-t "<title>"` | Print job title displayed in CUPS queues, active job monitors, and banner/cover pages. |
| **`--fit-to-page`<br>`--no-fit-to-page`** | `Optional[bool]` | **`True`** *(Enabled by default)* | `--fit-to-page`<br>`--no-fit-to-page`<br>*(aliases: `--fit-to-pages`, `--no-fit-to-pages`)* | `-o fit-to-page=true`<br>`-o fit-to-page=false` | **Scale document to fit sheet.** Enabled by default (matching `PdfCraft.app`). Scales oversized documents (such as digital Aadhaar cards or long banners) or undersized pages proportionally so all content fits inside the printable area without being clipped or zoomed in. Use `--no-fit-to-page` to force 100% actual size unscaled output. |
| **`--duplex`** | `Optional[DuplexMode]` | `None` *(printer PPD default, usually one-sided)* | `one-sided`<br>`two-sided-long-edge`<br>`two-sided-short-edge` | `-o sides=one-sided`<br>`-o sides=two-sided-long-edge`<br>`-o sides=two-sided-short-edge` | Two-sided printing mode: flips along the long edge (standard portrait book/turn) or short edge (notepad/calendar flip). |
| **`--collate`<br>`--no-collate`** | `Optional[bool]` | `None` *(driver default: collates)* | `--collate`<br>`--no-collate` | `-o collate=true`<br>`-o collate=false` | Collation mode when printing multiple copies. Collated prints sets in order (`1,2,3; 1,2,3`); uncollated prints grouped pages (`1,1; 2,2; 3,3`). |
| **`--color`** | `Optional[ColorMode]` | `None` *(printer default)* | `monochrome`<br>`color`<br>`auto` | `-o print-color-mode=monochrome`<br>`-o print-color-mode=color` | Color mode. `monochrome` forces grayscale printing on color-capable printers to conserve color toner. |
| **`-m, --media`<br>`--page-size`** | `Optional[str]` | `None` *(printer PPD default: Letter or A4)* | Any paper size supported by your printer: `A4`, `Letter`, `Legal`, `Executive`, `A3`, `A5`, `Custom.WIDTHxHEIGHT`, etc. | `-o media=<size>` | Physical paper sheet size. Run `printer-craft options` to inspect the exact paper sizes supported by your printer hardware. |
| **`-p, --pages`<br>`--page-ranges`** | `Optional[str]` | `None` *(all pages: `1-end`)* | Range strings: `'1-5'`, `'2,4,7'`, `'3-'`, `'1-3,5'`, or repeated sequences: `'1,1,1,1'` | `-o page-ranges=<range>` | Specific page numbers or ranges to print. Non-monotonic or repeated page sequences (e.g. `'1,1,1,1'`) are automatically pre-replicated via macOS `PDFKit` (JXA) to prevent CUPS `Bad page-ranges values` errors. |
| **`--orientation`** | `Optional[Orientation]` | `None` *(Portrait / Auto)* | `portrait` (0°)<br>`landscape` (90° CCW)<br>`reverse-landscape` (90° CW)<br>`reverse-portrait` (180°) | `-o orientation-requested=3`<br>`-o orientation-requested=4`<br>`-o orientation-requested=5`<br>`-o orientation-requested=6` | Page orientation and rotation on the physical sheet. |
| **`--scaling`** | `Optional[PrintScaling]` | `None` | `auto`<br>`auto-fit`<br>`fit-to-page`<br>`fill`<br>`none` | `-o print-scaling=<mode>` | CUPS IPP print scaling policy. *(Note: On macOS, `--fit-to-page` is the primary flag processed by Apple's `cgpdftoraster` filter).* |
| **`-N, --number-up`** | `Optional[int]` | `None` *(1 page per sheet)* | `1`, `2`, `4`, `6`, `9`, `16` | `-o number-up=<int>` | **N-Up printing.** Prints multiple logical pages arranged in a grid onto a single physical sheet. |
| **`-R, --repeat`** | `Optional[int]` | `None` *(1 copy)* | Any positive integer (e.g. `2`, `4`, `8`) | Pre-spool PDF synthesis | Repeats the document/pages N times by synthesizing a multi-page PDF before spooling. Useful with `-N` (e.g. `--repeat 4 -N 4` to print 4 copies of an ID badge or card on a single page). |
| **`-o, --option`** | `Dict[str, str]` | `[]` *(empty)* | `KEY=VALUE` (repeatable, e.g. `-o InputSlot=Manual -o Resolution=600dpi`) | `-o <KEY>=<VALUE>` | Direct PPD hardware driver overrides. Run `printer-craft options` to discover valid keys for your printer (e.g. `InputSlot`, `MediaType`, `Resolution`, `EconoMode`, `pjlDensity`). |
| **`--force-pdf`** | `bool` | `False` | Flag: present (`True`) or absent (`False`) | *(Local pre-conversion)* | Forces pre-conversion of non-PDF documents or images into an intermediate PDF before spooling. |
| **`--dry-run`** | `bool` | `False` | Flag: present (`True`) or absent (`False`) | *(None — preview only)* | Safe preview mode. Generates and displays the exact `/usr/bin/lp` command line without submitting the job to physical printer hardware. |

---

### 2. Additional Subcommands Reference

#### `printer-craft list`
| Flag | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| **`--json`** | Flag | `False` | Outputs discovered local and network printers with their statuses (`idle`, `printing`, `disabled`) and default status in JSON format. |

#### `printer-craft options [printer]`
| Parameter / Flag | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| **`printer`** | `str` (optional) | `None` *(system default)* | Name of the printer whose hardware options should be queried. |
| **`--json`** | Flag | `False` | Outputs all parsed PPD hardware options, current defaults (marked with `*`), and available choices in JSON format. |

#### `printer-craft jobs [printer]`
| Parameter / Flag | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| **`printer`** | `str` (optional) | `None` *(all printers)* | Filter the active print job queue to show only jobs for the specified printer. |

#### `printer-craft cancel <job_id>`
| Parameter / Flag | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| **`job_id`** | `str` (positional) | *(Required)* | CUPS Job ID to cancel (e.g. `HP_LaserJet_Professional_M1136_MFP-104`), or printer name when `-a` is set. |
| **`-a, --all`** | Flag | `False` | Purges and cancels all pending print jobs in the queue for the specified printer. |

---

## 🪟 Windows Support

On Windows (`sys.platform == "win32"`), `PrinterManager` dispatches to
`printer_craft.backends.Win32Backend` instead of the CUPS backend. The public API
and `PrintResult` shape are the same; on macOS/Linux nothing changes.

| Operation | Windows implementation |
| --- | --- |
| Discovery | `win32print.EnumPrinters` / `GetDefaultPrinter` |
| Driver options | `DeviceCapabilities` (paper sizes, trays, duplex, color, collate) with defaults from the printer `DEVMODE` |
| Printing | `StartDocPrinter` / `WritePrinter` with the `RAW` datatype; options applied via `DocumentProperties` on the job `DEVMODE` |
| Queue | `EnumJobs` / `SetJob(JOB_CONTROL_CANCEL)`; job ids look like `<printer>-<id>` |
| Conversion | `pypdf` (page ranges/repetition), `Pillow` (images), LibreOffice `soffice --convert-to pdf` or `docx2pdf` (Office docs) |

Notes and limitations:
- `RAW` spooling sends the document bytes unchanged, so the printer must understand
  the format (PDF-direct or PostScript printers). Images and Office documents are converted to PDF first.
- Supported options: copies, collate, duplex, color mode, orientation (reverse variants map to
  portrait/landscape) and media (common CUPS/PWG names such as `A4`, `Letter`,
  `iso_a4_210x297mm`; other values are used as a Windows form name).
  Page ranges are applied by rewriting the PDF with `pypdf`; open-ended ranges like `3-` are not supported.
- `raw_options`, `fit_to_page`, `scaling` and `number_up` are CUPS-only and ignored on Windows.
- The `lp_bin` / `lpstat_bin` / `lpoptions_bin` / `cancel_bin` overrides only apply to the CUPS backend.

---

## 🧪 Testing

Run the test suite using Python's standard `unittest`:

```bash
python3 -m unittest discover -s tests -v
```

All unit tests run with zero external test runner requirements. The Windows backend tests mock `win32print`, so they run on any OS.

---

## 📄 License

This project is licensed under the [MIT License](LICENSE).
