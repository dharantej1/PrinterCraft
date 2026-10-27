# printer-craft 🖨️

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)
[![Platform](https://img.shields.io/badge/platform-macOS%20%7C%20Linux%20%7C%20Windows-lightgrey.svg)](#-platform-support)
[![Tests](https://github.com/dharantej1/PrinterCraft/actions/workflows/tests.yml/badge.svg)](https://github.com/dharantej1/PrinterCraft/actions/workflows/tests.yml)

**printer-craft** is a Python library and CLI tool for discovering printers, querying hardware/driver options, and submitting print jobs on **macOS and Linux** (via CUPS) and on **Windows** (via the Windows print spooler). The same `printer-craft` commands, the same Python API and the same `PrintResult` work on every platform.

The macOS/Linux communication architecture was **reverse-engineered from the native macOS desktop application `PdfCraft.app`**, extracting its exact CUPS subprocess pipeline, environment handling, PPD parser, and argument builder.

---

## 🧭 Platform Support

| | macOS | Linux / Unix | Windows 10 / 11 / Server |
| :--- | :--- | :--- | :--- |
| **Print system** | CUPS (`lp`, `lpstat`, `lpoptions`, `cancel`) | CUPS (`lp`, `lpstat`, `lpoptions`, `cancel`) | Windows print spooler (`win32print` / GDI via pywin32) |
| **Install** | `pip install .` | `pip install .` (+ `cups-client`) | `pip install ".[windows]"` |
| **Printers supported** | Any CUPS queue | Any CUPS queue | Any installed Windows printer driver (local, network, shared, virtual such as *Microsoft Print to PDF*) |
| **PDF** | Native | Native | Rendered with `pypdfium2` |
| **Images** (`png`, `jpg`, `tiff`, `gif`, `bmp`, `heic`, `webp`) | `sips` | CUPS filters | `Pillow` (HEIC needs `pillow-heif`) |
| **Text / source code** | `cupsfilter` | CUPS filters | Built-in monospace renderer (`Pillow`) |
| **Office** (`docx`, `doc`, `rtf`, `odt`, `html`, `xlsx`, `pptx`, ...) | `textutil` + `cupsfilter` | CUPS filters | LibreOffice (`soffice`) or `docx2pdf` + Microsoft Word |
| **PostScript / PCL / PRN** | Native | Native | Sent unchanged (RAW) |
| **Every option in the [parameter reference](#-complete-cli--api-parameters-reference)** | ✅ | ✅ | ✅ (see [how options map on Windows](#how-each-option-is-applied-on-windows)) |
| **Queue listing / cancel / purge** | ✅ | ✅ | ✅ |
| **Dry-run** | ✅ | ✅ | ✅ |

`PrinterManager` picks the backend automatically: `sys.platform == "win32"` → Windows backend, anything else → CUPS backend. On macOS and Linux the behaviour, commands and output are exactly the same as before Windows support was added.

---

## 🌟 Key Features

- **Reverse-Engineered CUPS Architecture**: Implements the identical printing pipeline found in native macOS desktop software (`craft_print`).
- **Native Windows Backend**: Uses the Windows print spooler directly through pywin32 — no Adobe Reader, no shell `print` verbs, no pop-up dialogs. Documents are rendered onto the printer's device context, so *any* Windows printer driver works.
- **Universal Document Support**: Prints **PDFs**, **Images** (`.png`, `.jpg`, `.tiff`, `.heic`), **Office docs** (`.docx`, `.rtf`, `.odt`), and **Source code / text** (`.txt`, `.py`, `.md`, `.log`) with automatic format conversion (native macOS utilities `cupsfilter`, `textutil`, `sips`; `pypdfium2`, `Pillow` and LibreOffice on Windows).
- **Passable Printing Options** (all platforms):
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
  - Custom hardware keys (`-o InputSlot=Manual`, `-o Resolution=600dpi`, `-o pjlDensity=3`)
- **Intelligent Page Imposition**: Automatically duplicates/rearranges PDF pages via native macOS `PDFKit` (JXA) when repeating pages, bypassing the CUPS `Bad page-ranges values` limitation. On Windows the same page sequences are laid out directly by printer-craft.
- **Safe Dry-Run Mode**: Inspect the generated print command without sending jobs to physical hardware.
- **Queue Management**: Inspect active print queues and cancel pending jobs.
- **Zero Heavy Dependencies on macOS/Linux**: Pure Python using the standard library and operating system CUPS binaries. The Windows extra adds only pywin32, pypdfium2, Pillow and pypdf.

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

**Requirements (all platforms):** Python 3.9 or newer and `pip`.

### 🍎 macOS

CUPS and all conversion tools (`lp`, `lpstat`, `cupsfilter`, `textutil`, `sips`) ship with macOS — nothing else to install.

```bash
git clone https://github.com/dharantej1/PrinterCraft.git
cd PrinterCraft
pip install .

# Optional: faster pure-Python page duplication/rearranging (otherwise PDFKit/JXA is used)
pip install ".[extras]"
```

### 🐧 Linux / Unix

Install the CUPS client tools (and the CUPS server if this machine hosts the printers), then install printer-craft:

```bash
# Debian / Ubuntu
sudo apt-get install cups-client          # add `cups` to run a local print server
# Fedora / RHEL
sudo dnf install cups-client
# Arch
sudo pacman -S cups

git clone https://github.com/dharantej1/PrinterCraft.git
cd PrinterCraft
pip install ".[extras]"                   # pypdf is used for repeated/re-ordered page sequences
```

Printers are managed with the usual CUPS tools (`lpadmin`, the web UI at <http://localhost:631>, or your desktop's printer settings).

### 🪟 Windows

Open **PowerShell** or **Command Prompt** and run:

```powershell
git clone https://github.com/dharantej1/PrinterCraft.git
cd PrinterCraft
py -m pip install ".[windows]"
```

The `windows` extra installs (only on Windows — it is a no-op on macOS/Linux):

| Package | Used for |
| :--- | :--- |
| `pywin32` | Windows print spooler access (`win32print`, `win32gui`) |
| `pypdfium2` | Rendering PDF pages for the printer driver |
| `Pillow` | Images, plain-text rendering and drawing on the printer device |
| `pypdf` | Page selection for RAW (`-o raw`) PDF jobs |

Optional extras on Windows:

- **Office documents** (`.docx`, `.doc`, `.rtf`, `.odt`, `.xlsx`, `.pptx`, `.html`, ...): install [LibreOffice](https://www.libreoffice.org/download/) (detected on `PATH` or in `C:\Program Files\LibreOffice`), **or** `py -m pip install docx2pdf` to convert Word files with an installed Microsoft Word.
- **HEIC/HEIF photos**: `py -m pip install pillow-heif`.

> If `pip install` puts `printer-craft.exe` in a Scripts folder that is not on `PATH`, either add it (pip prints the folder) or run the CLI as `py -m printer_craft.cli ...`.

### Editable Development Mode (any platform)

```bash
pip install -e ".[dev,extras]"            # add ,windows on Windows
```

### Verify the installation

```bash
printer-craft list                        # shows installed printers and the default one
printer-craft print some.pdf --dry-run    # shows what would be sent, without printing
```

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

### 5. Using the CLI on Windows

Every command and flag above works the same on Windows. A few practical notes:

- Windows printer names often contain spaces — quote them: `-d "HP LaserJet Pro M404"`. `printer-craft list` shows the exact names.
- PowerShell uses a backtick (`` ` ``) for line continuation instead of `\`; in Command Prompt use `^`.
- Job IDs have the same `<printer>-<id>` shape as on CUPS, e.g. `"HP LaserJet Pro M404-17"`.
- `printer-craft options` lists what the *driver* reports: `PageSize`, `InputSlot` (trays), `MediaType`, `Resolution`, `Duplex`, `ColorModel`, `Collate`, `Orientation`. Those names can be passed back with `-o`.

```powershell
# List printers and the default one
printer-craft list

# Driver capabilities (trays, paper sizes, resolutions, ...)
printer-craft options "HP LaserJet Pro M404"

# 2 copies, duplex, grayscale, A4, from the manual feed tray at 600 dpi
printer-craft print report.pdf -d "HP LaserJet Pro M404" `
  -n 2 --duplex two-sided-long-edge --color monochrome --media A4 `
  -o InputSlot="Manual Feed" -o Resolution=600dpi

# 4 copies of a one-page form, two per side
printer-craft print ApplicationForm.pdf --repeat 4 -N 2 --duplex two-sided-short-edge

# Images, text files and Word documents
printer-craft print photo.jpg --media A4 --orientation landscape
printer-craft print app.log -N 2
printer-craft print contract.docx            # needs LibreOffice or docx2pdf + Word

# Print to a PDF file with the built-in "Microsoft Print to PDF" printer (it asks for a file name)
printer-craft print slides.pdf -d "Microsoft Print to PDF" -N 4

# Send a PostScript/PCL file (or any file with -o raw) to the printer unchanged
printer-craft print label.prn -d "Zebra ZD420"
printer-craft print document.pdf -d "PDF Direct Printer" -o raw

# Preview without printing
printer-craft print report.pdf -n 3 -N 2 --dry-run

# Queue
printer-craft jobs
printer-craft cancel "HP LaserJet Pro M404-17"
printer-craft cancel "HP LaserJet Pro M404" --all
```

A Windows dry run prints a descriptive command instead of an `lp` command line, e.g.:

```text
=== DRY RUN MODE ===
Target Printer: HP LaserJet Pro M404
Command:
  win32print -d HP LaserJet Pro M404 -t report.pdf -o render=gdi -o Copies=3 -o scaling=fit -o number-up=2 C:\Users\me\report.pdf
Job was not sent to hardware.
```

---

## 🐍 Python API Usage

### 1. Setup — `PrinterManager`

`PrinterManager` is the main entry point and works the same on every platform.
On macOS/Linux it auto-discovers the CUPS binaries and lets you override them for
custom CUPS installations; on Windows it talks to the print spooler (the binary
overrides are accepted and ignored there).

```python
from printer_craft import PrinterManager

# Default: auto-discovers lp, lpstat, lpoptions, cancel from PATH / /usr/bin
mgr = PrinterManager()

# Which backend is in use? (CUPSBackend on macOS/Linux, Win32Backend on Windows)
print(type(mgr.backend).__name__)

# Override individual binaries (e.g. custom CUPS install; macOS/Linux only)
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
auto-converted using native macOS tools (`textutil`, `sips`, `cupsfilter`). On
Windows, PDFs, images and text are rendered directly and Office files are converted
with LibreOffice or docx2pdf — the examples below work unchanged.

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
identical to `PdfCraft::craft_print::submit_with_progress`. On Windows, PDF and
image bytes are rendered for the printer driver and any other data (PostScript,
PCL, ...) is spooled unchanged with the RAW datatype.

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
    # Raised when the CUPS daemon is not running or unreachable,
    # or on Windows when the spooler is unavailable / pywin32 is missing
    print(f"CUPS spooler is down: {e}")

except DocumentConversionError as e:
    # Raised when textutil / sips / cupsfilter conversion fails
    # (Windows: missing pypdfium2/Pillow/LibreOffice, unreadable file, empty page selection)
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
                    #                  (Windows: equivalent "win32print -d ... -o ..." description)
result.output       # str    — raw stdout from lp
                    #          (Windows: "request id is <printer>-<id> (1 file(s))")
result.error        # Optional[str]  — error message if success=False
result.dry_run      # bool   — True when options.dry_run was set
```

---

## 📋 Complete CLI & API Parameters Reference

### 1. `printer-craft print` Parameters

The *CUPS Flag Generated* column describes macOS/Linux. Every parameter is also supported on Windows — see [How each option is applied on Windows](#how-each-option-is-applied-on-windows).

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

## 🪟 Windows Details

### How printing works on Windows

`PrinterManager()` on Windows uses `printer_craft.backends.Win32Backend`. The public API, CLI and `PrintResult` fields are identical to macOS/Linux.

| Operation | Windows implementation |
| :--- | :--- |
| Discovery | `win32print.EnumPrinters` (local + network connections) and `GetDefaultPrinter` |
| Driver options | `DeviceCapabilities` (paper sizes, trays, media types, resolutions, duplex, color, collate) with defaults from the printer `DEVMODE` |
| Job settings | Applied to a `DEVMODE` and validated by the driver with `DocumentProperties` |
| Printing documents | Pages are rendered (PDF → `pypdfium2`, images/text → `Pillow`, Office → LibreOffice/docx2pdf → PDF) and drawn on a printer device context (`CreateDC` / `StartDoc` / `StartPage` / `EndPage` / `EndDoc`). Works with every Windows printer driver. |
| Printing printer-language data | `.ps`, `.eps`, `.pcl`, `.pxl`, `.prn`, `.raw` files, non-PDF/non-image `print_bytes` data, and any job with `-o raw` are spooled unchanged with `StartDocPrinter` / `WritePrinter` and the `RAW` datatype |
| Queue | `EnumJobs`; cancel with `SetJob(JOB_CONTROL_CANCEL)`; job ids are `<printer>-<id>` |

### How each option is applied on Windows

| Option | macOS / Linux (CUPS) | Windows |
| :--- | :--- | :--- |
| `-d, --printer` | `lp -d` | Target printer name (`printer-craft list`) |
| `-n, --copies` | `lp -n` | `DEVMODE.Copies`; if the driver cannot make copies itself (`DC_COPIES`), printer-craft prints the copies itself |
| `-t, --title` | `lp -t` | Spooler document name |
| `--collate` / `--no-collate` | `-o collate=` | `DEVMODE.Collate` (also honoured for software copies) |
| `--duplex` | `-o sides=` | `DEVMODE.Duplex` (simplex / vertical / horizontal). With software copies, each collated copy starts on a new sheet |
| `--color` | `-o print-color-mode=` | `DEVMODE.Color`; `monochrome` also renders pages in grayscale so color is never used |
| `-m, --media` | `-o media=` | `DEVMODE.PaperSize` for common names (`Letter`, `Legal`, `A3`, `A4`, `A5`, `A6`, `B4`, `B5`, `Executive`, `Tabloid`, `Ledger`, `Statement`, `Env10`, `EnvDL`, and their PWG names like `iso_a4_210x297mm`); any other value is used as a Windows form name (e.g. `"Photo 4x6"`) |
| `-p, --pages` | `-o page-ranges=` | Applied by printer-craft; supports `1-5`, `2,4,7`, `3-`, `-2` and repeated/re-ordered lists like `1,1,1,1` exactly like the CUPS path |
| `--orientation` | `-o orientation-requested=` | `DEVMODE.Orientation`; `reverse-*` additionally rotates the page 180° |
| `--fit-to-page` / `--no-fit-to-page` | `-o fit-to-page=` | Pages are scaled to the printable area (default) or printed at 100% centered on the sheet |
| `--scaling` | `-o print-scaling=` | `fit-to-page` (fit), `fill` (fill and crop), `none` (actual size), `auto` / `auto-fit` (shrink only if too large) — takes precedence over `--fit-to-page`, like CUPS |
| `-N, --number-up` | `-o number-up=` | Pages laid out in a grid (1×2, 2×2, 2×3, 3×3, 4×4), auto-rotated to fill each cell |
| `-R, --repeat` | Pre-spool PDF synthesis | Same semantics (repeats page 1 N times), applied by printer-craft |
| `-o KEY=VALUE` | `-o KEY=VALUE` | See below |
| `--force-pdf` | Pre-convert to PDF | Accepted; documents are always rendered on Windows. With `-o raw`, converts non-PDF input to PDF before sending |
| `--dry-run` | Shows the `lp` command | Shows the equivalent `win32print ...` description |

### `-o KEY=VALUE` on Windows

Windows drivers do not use PPD files, so `-o` values are interpreted as follows (keys are case-insensitive):

| Key | Example | Effect |
| :--- | :--- | :--- |
| Standard CUPS/IPP keys | `-o sides=two-sided-long-edge`, `-o number-up=4`, `-o media=A4`, `-o print-color-mode=monochrome`, `-o collate=false`, `-o orientation-requested=4`, `-o landscape`, `-o fit-to-page=false`, `-o print-scaling=fill`, `-o page-ranges=1-3`, `-o copies=2` | Same meaning as on CUPS |
| `InputSlot` | `-o InputSlot="Tray 2"` | Paper tray, by name from `printer-craft options` (or numeric bin id) |
| `MediaType` | `-o MediaType=Glossy` | Media type, by name from `printer-craft options` (or numeric id) |
| `Resolution` | `-o Resolution=600dpi`, `-o Resolution=1200x600dpi` | `DEVMODE.PrintQuality` / `YResolution` |
| `PageSize`, `Duplex`, `ColorModel`, `Collate`, `Orientation` | `-o Duplex=DuplexTumble`, `-o ColorModel=Gray` | Same values as listed by `printer-craft options` |
| Raw `DEVMODE` fields | `-o PrintQuality=300`, `-o DefaultSource=7`, `-o Scale=90`, `-o DitherType=2`, `-o PaperWidth=1000 -o PaperLength=1500` (tenths of mm) | Written directly to the `DEVMODE` |
| `raw` | `-o raw` | Send the file to the printer unchanged (RAW datatype), like `lp -o raw` |
| Anything else | `-o pjlDensity=3` | Logged as a warning and ignored (CUPS-only PPD option) |

### Windows troubleshooting

| Symptom | Fix |
| :--- | :--- |
| `pywin32 is required for printing on Windows` | `py -m pip install ".[windows]"` (or `pip install pywin32`) |
| `pypdfium2 is required to print PDFs on Windows` | `py -m pip install pypdfium2` |
| `Cannot convert report.docx to PDF on Windows` | Install LibreOffice, or `pip install docx2pdf` with Microsoft Word installed |
| `printer-craft` is not recognized | Add the Python `Scripts` folder to `PATH`, or use `py -m printer_craft.cli` |
| RAW job (`.ps`/`.pcl`/`.prn` or `-o raw`) stays in the queue with an error | RAW data bypasses the driver, so the printer must understand that language, and the driver must accept RAW jobs. Modern "v4"/class drivers (e.g. *Microsoft Print to PDF*, *Microsoft IPP Class Driver*) reject RAW — print the document normally (without `-o raw`) or use the manufacturer's PCL/PostScript driver |
| `Microsoft Print to PDF` asks where to save | That printer always prompts for a file name; use a real printer, or a printer whose port is a file path |
| A setting (duplex, tray, color) has no effect | The driver does not support it — check `printer-craft options "<printer>"`; settings the driver rejects are dropped by `DocumentProperties` |
| Job stuck in the queue | `printer-craft jobs` then `printer-craft cancel "<printer>-<id>"` or `printer-craft cancel "<printer>" --all` |

---

## 🧪 Testing

Run the test suite with Python's standard `unittest` (no external test runner needed):

```bash
# macOS / Linux
python3 -m unittest discover -s tests -v
```

```powershell
# Windows (the CUPS-specific tests in test_core/test_parser/test_cli assume a CUPS backend)
py -m unittest tests.test_models tests.test_backends tests.test_win32_backend tests.test_win32_render -v
```

The Windows backend tests mock `win32print`, so they also run on macOS and Linux (install `pypdf Pillow pypdfium2` to run the rendering tests too).

[CI](.github/workflows/tests.yml) runs the suite on Ubuntu, macOS and Windows for every pull request. On Windows it also runs an end-to-end smoke test ([`.github/scripts/windows_smoke.py`](.github/scripts/windows_smoke.py)) against the real print spooler. That test covers discovery, driver options, PDF/image/text/bytes printing, page ranges, repeat, N-up, media, orientation, copies, RAW, dry run, queue listing/cancel/purge, and the CLI, and checks the printed output.

---

## 📄 License

This project is licensed under the [MIT License](LICENSE).
