"""
End-to-end check of printer_craft against the real Windows print spooler.

Expects a printer named "PrinterCraftTest" using the "Microsoft Print To PDF" driver whose
port is the file in PRINTER_CRAFT_OUTPUT, so every job lands in that file.
"""

import io
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import pypdf
import win32print
from PIL import Image

from printer_craft import ColorMode, Orientation, PrinterManager, PrintJobOptions
from printer_craft.backends import Win32Backend

PRINTER = "PrinterCraftTest"
OUTPUT = Path(os.environ["PRINTER_CRAFT_OUTPUT"])
WORK = Path(tempfile.mkdtemp(prefix="pc_smoke_"))
mgr = PrinterManager()
failures = []


def check(name, condition, detail=""):
    print(("PASS " if condition else "FAIL ") + name + (f" ({detail})" if detail else ""))
    if not condition:
        failures.append(name)


def make_pdf(name, pages, size=(612, 792)):
    writer = pypdf.PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=size[0], height=size[1])
    path = WORK / name
    with open(path, "wb") as f:
        writer.write(f)
    return path


def wait_for_output(timeout=90):
    deadline = time.time() + timeout
    last_size = -1
    while time.time() < deadline:
        if OUTPUT.exists() and not mgr.get_jobs(PRINTER):
            size = OUTPUT.stat().st_size
            if size > 0 and size == last_size:
                return OUTPUT.read_bytes()
            last_size = size
        time.sleep(1)
    raise TimeoutError("print job did not complete")


def run_job(name, submit):
    if OUTPUT.exists():
        OUTPUT.unlink()
    result = submit()
    check(f"{name}: submitted", result.success, result.error or result.job_id)
    if not result.success:
        return None, result
    return wait_for_output(), result


def pdf_pages(name, submit, expected_pages, check_page=None):
    data, result = run_job(name, submit)
    if data is None:
        return
    reader = pypdf.PdfReader(io.BytesIO(data))
    check(f"{name}: {expected_pages} page(s)", len(reader.pages) == expected_pages, f"got {len(reader.pages)}")
    if check_page:
        box = reader.pages[0].mediabox
        check(f"{name}: page geometry", check_page(float(box.width), float(box.height)),
              f"{float(box.width):.0f}x{float(box.height):.0f}pt")


def opts(**kw):
    return PrintJobOptions(printer=PRINTER, **kw)


check("Win32Backend selected", isinstance(mgr.backend, Win32Backend))
printers = {p.name: p for p in mgr.list_printers()}
check("printer discovered", PRINTER in printers, ", ".join(printers))
options = mgr.get_printer_options(PRINTER)
check("driver options read", "PageSize" in options, ", ".join(options))
print("options:", {k: [c.name for c in v.choices][:6] for k, v in options.items()})

three = make_pdf("three.pdf", 3)
one = make_pdf("one.pdf", 1)

pdf_pages("pdf", lambda: mgr.print_document(three, options=opts()), 3)
pdf_pages("repeat 4 + 2-up", lambda: mgr.print_document(one, options=opts(repeat=4, number_up=2)), 2)
pdf_pages("page ranges 2-", lambda: mgr.print_document(three, options=opts(page_ranges="2-")), 2)
pdf_pages("page sequence 3,1,1", lambda: mgr.print_document(three, options=opts(page_ranges="3,1,1")), 3)
pdf_pages("4-up", lambda: mgr.print_document(make_pdf("eight.pdf", 8), options=opts(number_up=4)), 2)
pdf_pages("media A4", lambda: mgr.print_document(one, options=opts(media="A4")), 1,
          lambda w, h: abs(w - 595) < 3 and abs(h - 842) < 3)
pdf_pages("landscape", lambda: mgr.print_document(one, options=opts(orientation=Orientation.LANDSCAPE)), 1,
          lambda w, h: w > h)
pdf_pages("monochrome, no fit", lambda: mgr.print_document(
    one, options=opts(color_mode=ColorMode.MONOCHROME, fit_to_page=False)), 1)


def copies_job():
    return mgr.print_document(three, options=opts(copies=2, collate=True))


data, result = run_job("copies 2", copies_job)
if data is not None:
    pages = len(pypdf.PdfReader(io.BytesIO(data)).pages)
    emulated = any(part.startswith("copies-emulated") for part in result.command_run)
    check("copies 2: pages", pages == (6 if emulated else pages), f"{pages} pages, emulated={emulated}")

img = WORK / "photo.png"
Image.new("RGB", (1200, 800), (200, 30, 30)).save(img)
pdf_pages("image", lambda: mgr.print_document(img, options=opts()), 1)

txt = WORK / "notes.txt"
txt.write_text("\n".join(f"line {i}" for i in range(120)), encoding="utf-8")
pdf_pages("text file", lambda: mgr.print_document(txt, options=opts()), 2)

pdf_pages("print_bytes pdf", lambda: mgr.print_bytes(three.read_bytes(), title="bytes", options=opts()), 3)

raw_payload = b"%!PS-Adobe-3.0\n%% printer_craft raw smoke test\nshowpage\n"
data, _ = run_job("RAW bytes", lambda: mgr.print_bytes(raw_payload, title="raw", options=opts()))
check("RAW bytes: written unchanged", data == raw_payload)

dry = mgr.print_document(three, options=opts(copies=2, number_up=2, dry_run=True))
check("dry run", dry.success and dry.dry_run and "number-up=2" in dry.command_run, " ".join(dry.command_run))

# Queue: pause the printer, submit, list and cancel.
handle = win32print.OpenPrinter(PRINTER, {"DesiredAccess": win32print.PRINTER_ALL_ACCESS})
win32print.SetPrinter(handle, 0, None, win32print.PRINTER_CONTROL_PAUSE)
try:
    queued = mgr.print_document(one, options=opts(title="queued"))
    jobs = mgr.get_jobs(PRINTER)
    check("jobs listed", any(j["job_id"] == queued.job_id for j in jobs), str(jobs))
    check("cancel job", mgr.cancel_job(queued.job_id))
    mgr.print_document(one, options=opts(title="purge-1"))
    mgr.print_document(one, options=opts(title="purge-2"))
    check("purge all", mgr.cancel_job(PRINTER, purge_all=True))
    time.sleep(2)
    check("queue empty", not mgr.get_jobs(PRINTER), str(mgr.get_jobs(PRINTER)))
finally:
    win32print.SetPrinter(handle, 0, None, win32print.PRINTER_CONTROL_RESUME)
    win32print.ClosePrinter(handle)

for args in (["list"], ["list", "--json"], ["options", PRINTER], ["jobs"],
             ["print", str(three), "-d", PRINTER, "-n", "2", "-N", "2", "--dry-run"]):
    proc = subprocess.run(["printer-craft", *args], capture_output=True, text=True)
    check("cli " + " ".join(args[:2]), proc.returncode == 0, (proc.stdout + proc.stderr).strip()[:300])

if OUTPUT.exists():
    OUTPUT.unlink()
proc = subprocess.run(["printer-craft", "print", str(three), "-d", PRINTER, "--pages", "1-2"],
                      capture_output=True, text=True)
check("cli print", proc.returncode == 0, proc.stdout.strip())
if proc.returncode == 0:
    check("cli print: 2 pages", len(pypdf.PdfReader(io.BytesIO(wait_for_output())).pages) == 2)

print(f"\n{len(failures)} failure(s)")
sys.exit(1 if failures else 0)
