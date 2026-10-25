# Reverse Engineering Report: `PdfCraft.app` Printer Subsystem

## 1. Executive Summary

This report documents the reverse engineering analysis of **`/Applications/PdfCraft.app`** (and references to `/System/Applications/PdfCraft.app`), with particular focus on how the application discovers, queries, configures, and communicates with printers connected to the macOS machine.

Using static binary analysis, symbol extraction, Mach-O disassembly, and Hopper/LLDB decompilation methods, we mapped out the internal printing pipeline from the UI down to the low-level UNIX/CUPS spooler communication.

---

## 2. Target Binary Identification

- **Application Path**: `/Applications/PdfCraft.app`
- **Binary Executable**: `/Applications/PdfCraft.app/Contents/MacOS/PdfCraft`
- **Binary Format**: Mach-O Universal Binary (`x86_64` + `arm64`)
- **Framework & Runtime**: Rust (using `egui` for the GUI and custom crates for PDF rendering, layout, and printing)
- **Crates Identified**:
  - `craft_print`: Core printing interface and CUPS subprocess management.
  - `pdfcraft_print`: PDF document pagination, n-up imposition, booklet layout, and raster spooling.
  - `pdfcraft_ui_egui::print_ui`: Print dialog UI, option bindings, and background threading.

---

## 3. Disassembly & Symbol Analysis

Inspection of exported and mangled Rust symbols revealed the key entry points and worker functions:

```text
craft_print::lpstat_with            (0x10047d394)
craft_print::parse_lpstat           (0x10047d4cc)
craft_print::parse_lpstat_e         (0x10047d788)
craft_print::parse_lpoptions        (0x10047dc90)
craft_print::printers               (0x10047fcec)
craft_print::lp_args                (0x10047f4f4)
craft_print::submit_with_progress   (0x10047e210)
pdfcraft_print::cups_media          (0x1010190d4)
pdfcraft_print::matching_paper      (0x10101a18c)
pdfcraft_print::impose              (0x10101c194)
```

---

## 4. Reverse-Engineered Communication Architecture

### Step 1: Printer Discovery (`craft_print::printers` & `lpstat_with`)

When the user triggers the Print action in `PdfCraft`, the application does **not** rely on proprietary vendor drivers or private IPC endpoints. Instead, it interacts directly with macOS's native **CUPS (Common Unix Printing System)** spooler daemon via command-line utilities.

#### Environment Setup:
To prevent localized string formatting from breaking output parsing, `craft_print::lpstat_with` explicitly sets:
```bash
LC_ALL=C
LANG=C
```

#### Command Invocations:
1. `lpstat -p -d`:
   - Queries both printer status (`-p`) and the system default destination (`-d`).
   - Output pattern parsed:
     - `printer <Printer_Name> is idle. enabled since ...`
     - `system default destination: <Default_Printer_Name>`
2. Fallback / Modern Enumeration: `lpstat -e`:
   - Returns a newline-separated list of all available CUPS destinations (including AirPrint/IPP printers).

```arm64
PdfCraft`craft_print::lpstat_with:
  ...
  bl   <std::sys::process::unix::common::Command>::new("lpstat")
  bl   <std::sys::process::unix::common::Command>::arg("-p")
  bl   <std::sys::process::unix::common::Command>::arg("-d")
  bl   <std::sys::process::env::CommandEnv>::set("LC_ALL", "C")
```

---

### Step 2: Printer Capabilities & PPD Options (`craft_print::parse_lpoptions`)

To populate the Print Dialog with exact hardware capabilities (supported paper sizes, duplexing, resolution, trays):

1. **Invocation**:
   ```bash
   lpoptions -p <printer_name> -l
   ```
2. **Parser Logic (`parse_lpoptions`)**:
   The output from `lpoptions -l` uses the standard PostScript Printer Description (PPD) format:
   ```text
   PageSize/Media Size: *Letter Legal A4 Executive 8.5x13Custom A5 A6 B5JIS
   Duplex/2-Sided Printing: *None DuplexNoTumble DuplexTumble
   Resolutions/Resolution: *600x400dpi 600x600dpi
   MediaType/Media Type: *Paper Heavy111-130g TransparencyPaper LabelsPaper
   ```
   - Each option line begins with `Keyword/Human Readable Title: Choice1 *Choice2 Choice3`.
   - The choice prefixed with an asterisk (`*`) represents the current default setting.

---

### Step 3: Argument Assembly (`craft_print::lp_args`)

Disassembling `craft_print::lp_args` reveals how user selections in the UI are converted into CUPS `lp` command arguments:

| Option Category | Setting Value | Formatted CLI Flag |
| :--- | :--- | :--- |
| **Destination** | Printer Name | `-d <printer_name>` |
| **Copies** | `1..999` | `-n <copies>` |
| **Job Title** | Document Name | `-t "<title>"` |
| **Collation** | On / Off | `-o collate=true` / `-o collate=false` |
| **Duplex** | Off (One-Sided) | `-o sides=one-sided` |
| **Duplex** | Two-Sided Long Edge | `-o sides=two-sided-long-edge` |
| **Duplex** | Two-Sided Short Edge | `-o sides=two-sided-short-edge` |
| **Color Mode** | Monochrome / Grayscale | `-o print-color-mode=monochrome` |
| **Color Mode** | Full Color | `-o print-color-mode=color` |
| **Page Scaling** | Auto-fit / Fit to Page | `-o fit-to-page=false` or `-o print-scaling=auto-fit` |
| **Page Ranges** | E.g. `1-3,5` | `-o page-ranges=<range>` |
| **Orientation** | Portrait / Landscape | `-o orientation-requested=3` (or `4`, `5`, `6`) |
| **Custom PPD** | `Key=Value` | `-o <Key>=<Value>` |

Assembly snippet from `craft_print::lp_args` confirming the hardcoded flag generation:
```arm64
PdfCraft`craft_print::lp_args:
  ...
  mov  w8, #0x642d       ; = "-d" (little-endian: 0x2d '-', 0x64 'd')
  ...
  mov  w8, #0x6e2d       ; = "-n"
  ...
  mov  w8, #0x742d       ; = "-t"
  ...
  mov  w8, #0x6f2d       ; = "-o"
  ...
  ; Formats: "collate=true", "sides=two-sided-long-edge", "print-color-mode=monochrome", etc.
```

---

### Step 4: Spooling & Job Submission (`craft_print::submit_with_progress`)

1. Spawns `/usr/bin/lp` with the assembled arguments.
2. Directs output of the rendered PDF into the child process's standard input (`stdin`).
3. If an error occurs (such as the spooler daemon being paused or an invalid paper size), parses `stderr` (e.g. `the print spooler is not available: ...` or `the print job was refused`).
4. On success, extracts the CUPS job ID from `stdout` (e.g. `request id is HP_LaserJet_Professional_M1136_MFP-104 (1 file(s))`).

---

## 5. Architectural Takeaway

The reverse engineering reveals that `PdfCraft.app`:
1. Uses macOS standard CUPS utilities (`lpstat`, `lpoptions`, `lp`) instead of fragile Cocoa private APIs or driver-specific SDKs.
2. Can reliably print to any printer installed on macOS (local USB, networked, AirPrint, or virtual PDF printers).
3. Supports rich options via `-o key=value` pairs matching CUPS specifications and PPD capabilities.

This clean, robust architecture can be fully codified and expanded into a reusable Python library and CLI tool.
