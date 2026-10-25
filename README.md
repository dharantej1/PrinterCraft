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

## 🧪 Testing

Run the test suite using Python's standard `unittest`:

```bash
python3 -m unittest discover -s tests -v
```

All 11 unit tests run with zero external test runner requirements.

---

## 📄 License

This project is licensed under the [MIT License](LICENSE).
