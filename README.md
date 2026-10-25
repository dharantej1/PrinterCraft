# printer-craft 🖨️

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)
[![Platform](https://img.shields.io/badge/platform-macOS%20%7C%20Linux-lightgrey.svg)](https://www.cups.org/)

**printer-craft** is a Python library and CLI tool for discovering printers, querying hardware PPD options, and submitting print jobs on macOS and Unix systems.

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
  - Page ranges (`1-5`, `2,4,8`)
  - Orientation (`portrait`, `landscape`, `reverse-landscape`, `reverse-portrait`)
  - N-Up printing (`1`, `2`, `4`, `6`, `9`, `16` pages per sheet)
  - Scaling & fit-to-page (`auto-fit`, `fit-to-page`, `fill`)
  - Custom hardware PPD keys (`-o InputSlot=Manual`, `-o pjlDensity=3`)
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
git clone https://github.com/example/printer-craft.git
cd printer-craft
pip install .
```

### Editable Development Mode
```bash
pip install -e .
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

### Basic Printing

```python
from printer_craft import PrinterManager, PrintJobOptions, DuplexMode, ColorMode

mgr = PrinterManager()

# Submit a print job
options = PrintJobOptions(
    copies=1,
    duplex=DuplexMode.TWO_SIDED_LONG_EDGE,
    color_mode=ColorMode.MONOCHROME,
    media="A4",
    fit_to_page=True,
    dry_run=False,
)

result = mgr.print_document("invoice.pdf", options=options)
if result.success:
    print(f"Printed to {result.printer}, Job ID: {result.job_id}")
else:
    print(f"Error: {result.error}")
```

### Querying Printers and Options

```python
from printer_craft import PrinterManager

mgr = PrinterManager()

# Discover all printers
printers = mgr.list_printers(load_options=True)
for printer in printers:
    print(f"Printer: {printer.name} (Default: {printer.is_default})")
    for key, opt in printer.options.items():
        default_val = opt.default_choice.name if opt.default_choice else "None"
        print(f"  {opt.keyword}: default={default_val}")
```

### Streaming In-Memory PDF Bytes

```python
from printer_craft import PrinterManager, PrintJobOptions

mgr = PrinterManager()
pdf_data = b"%PDF-1.4 ... binary data ..."

result = mgr.print_bytes(
    pdf_data,
    title="In-Memory Report",
    options=PrintJobOptions(copies=1),
)
```

---

## 📋 Passable Options Reference

| Argument / Parameter | CLI Flag | Python Enum / Type | CUPS Flag Generated |
| :--- | :--- | :--- | :--- |
| **Printer** | `-d, --printer <name>` | `options.printer = str` | `-d <name>` |
| **Copies** | `-n, --copies <int>` | `options.copies = int` | `-n <int>` |
| **Title** | `-t, --title <str>` | `options.title = str` | `-t "<title>"` |
| **Duplex** | `--duplex <mode>` | `DuplexMode.ONE_SIDED`<br>`DuplexMode.TWO_SIDED_LONG_EDGE`<br>`DuplexMode.TWO_SIDED_SHORT_EDGE` | `-o sides=one-sided`<br>`-o sides=two-sided-long-edge`<br>`-o sides=two-sided-short-edge` |
| **Collation** | `--collate` / `--no-collate` | `options.collate = bool` | `-o collate=true / false` |
| **Color Mode** | `--color <mode>` | `ColorMode.MONOCHROME`<br>`ColorMode.COLOR` | `-o print-color-mode=monochrome`<br>`-o print-color-mode=color` |
| **Paper Size** | `-m, --media <size>` | `options.media = str` | `-o media=<size>` |
| **Page Range** | `-p, --pages <range>` | `options.page_ranges = str` | `-o page-ranges=<range>` |
| **Orientation** | `--orientation <orient>` | `Orientation.PORTRAIT`<br>`Orientation.LANDSCAPE`<br>`Orientation.REVERSE_LANDSCAPE`<br>`Orientation.REVERSE_PORTRAIT` | `-o orientation-requested=3`<br>`-o orientation-requested=4`<br>`-o orientation-requested=5`<br>`-o orientation-requested=6` |
| **Fit to Page** | `--fit-to-page` | `options.fit_to_page = bool` | `-o fit-to-page=true / false` |
| **Scaling** | `--scaling <mode>` | `PrintScaling.AUTO_FIT`<br>`PrintScaling.FIT_TO_PAGE`<br>`PrintScaling.FILL` | `-o print-scaling=<mode>` |
| **N-Up (Pages/Sheet)** | `-N, --number-up <int>` | `options.number_up = 1,2,4,6,9,16` | `-o number-up=<int>` |
| **Custom PPD Options** | `-o <key>=<value>` | `options.raw_options = dict` | `-o <key>=<value>` |
| **Dry Run** | `--dry-run` | `options.dry_run = bool` | *(Prints command without executing)* |

---

## 🧪 Testing

Run the test suite using Python's standard `unittest`:

```bash
python3 -m unittest discover -s tests -v
```

All 11 unit tests run with zero external test runner requirements.

---

## 📄 License

This project is licensed under the [MIT License](LICENSE).
