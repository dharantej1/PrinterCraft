"""
Document converter supporting seamless printing of any document or image type.
Uses native macOS utilities (cupsfilter, textutil, sips) without third-party bloat.
On Windows, falls back to pypdf, Pillow and LibreOffice/docx2pdf.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Generator, Optional, Union

from .exceptions import DocumentConversionError

# File extensions natively accepted by modern macOS CUPS
NATIVE_CUPS_EXTENSIONS = {
    ".pdf",
    ".ps",
    ".eps",
    ".txt",
    ".text",
    ".log",
    ".png",
    ".jpg",
    ".jpeg",
    ".tiff",
    ".tif",
    ".gif",
    ".bmp",
}

# Image extensions that can be converted via macOS `sips`
IMAGE_EXTENSIONS = {
    ".png",
    ".jpg",
    ".jpeg",
    ".tiff",
    ".tif",
    ".bmp",
    ".gif",
    ".heic",
    ".webp",
    ".ico",
}

# Text / Document formats that can be converted via macOS `textutil`
TEXTUTIL_EXTENSIONS = {
    ".rtf",
    ".rtfd",
    ".doc",
    ".docx",
    ".odt",
    ".html",
    ".htm",
    ".webarchive",
}


class DocumentConverter:
    """Converts diverse file formats into print-ready PDF/CUPS formats."""

    @staticmethod
    def is_natively_supported(path: Path) -> bool:
        """Check if CUPS can consume the file directly without pre-processing."""
        return path.suffix.lower() in NATIVE_CUPS_EXTENSIONS

    @classmethod
    @contextmanager
    def prepare_for_print(
        cls,
        file_path: Union[str, Path],
        force_pdf: bool = False,
        page_sequence: Optional[List[int]] = None,
    ) -> Generator[Path, None, None]:
        """
        Context manager that yields a path to a printable file.
        If conversion or page duplication is needed, a temporary file is created and cleaned up on exit.
        """
        path = Path(file_path).expanduser().resolve()
        if not path.exists():
            raise FileNotFoundError(f"Document file does not exist: {path}")

        suffix = path.suffix.lower()

        # If page sequence is requested (e.g. repeating pages), always generate a new PDF
        if page_sequence is not None and len(page_sequence) > 0:
            temp_dir = tempfile.mkdtemp(prefix="printer_craft_seq_")
            output_pdf = Path(temp_dir) / f"{path.stem}_seq.pdf"
            try:
                # If source is already PDF, duplicate directly
                if suffix == ".pdf":
                    cls.duplicate_pdf_pages(path, output_pdf, page_sequence)
                else:
                    # Convert to PDF first, then duplicate
                    temp_pdf = Path(temp_dir) / f"{path.stem}_base.pdf"
                    cls._convert_to_base_pdf(path, suffix, temp_pdf)
                    cls.duplicate_pdf_pages(temp_pdf, output_pdf, page_sequence)
                yield output_pdf
            finally:
                shutil.rmtree(temp_dir, ignore_errors=True)
            return

        # If it's already a PDF, return it directly
        if suffix == ".pdf":
            yield path
            return

        # If it's natively supported and user did not force conversion to PDF, yield directly
        if not force_pdf and cls.is_natively_supported(path):
            yield path
            return

        # Needs conversion to PDF
        temp_dir = tempfile.mkdtemp(prefix="printer_craft_")
        output_pdf = Path(temp_dir) / f"{path.stem}_converted.pdf"

        try:
            cls._convert_to_base_pdf(path, suffix, output_pdf)
            yield output_pdf
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    @classmethod
    def _convert_to_base_pdf(cls, path: Path, suffix: str, output_pdf: Path) -> None:
        if sys.platform == "win32":
            cls._convert_to_base_pdf_windows(path, suffix, output_pdf)
            return
        if suffix in TEXTUTIL_EXTENSIONS:
            cls._convert_textutil_to_pdf(path, output_pdf)
        elif suffix in IMAGE_EXTENSIONS:
            cls._convert_image_to_pdf(path, output_pdf)
        elif cls._is_plain_text(path):
            cls._convert_text_to_pdf(path, output_pdf)
        else:
            cls._convert_via_cupsfilter(path, output_pdf)

    @staticmethod
    def duplicate_pdf_pages(input_path: Path, output_path: Path, page_sequence: List[int]) -> None:
        """
        Duplicate or rearrange pages in a PDF using pypdf (if installed)
        or native macOS PDFKit (via JXA), avoiding CUPS 'Bad page-ranges' error.
        """
        # 1. Try pure-Python pypdf if available
        try:
            import pypdf
            reader = pypdf.PdfReader(str(input_path))
            writer = pypdf.PdfWriter()
            total_pages = len(reader.pages)
            for page_num in page_sequence:
                idx = page_num - 1
                if 0 <= idx < total_pages:
                    writer.add_page(reader.pages[idx])
            with open(output_path, "wb") as f_out:
                writer.write(f_out)
            return
        except ImportError:
            if sys.platform == "win32":
                raise DocumentConversionError(
                    "pypdf is required to duplicate/rearrange pages on Windows: pip install pypdf"
                )

        # 2. Fallback to native macOS PDFKit via JXA (zero-dependency)
        import json
        script = f"""
        ObjC.import('PDFKit');
        var inDoc = $.PDFDocument.alloc.initWithURL($.NSURL.fileURLWithPath('{input_path}'));
        var outDoc = $.PDFDocument.alloc.init;
        var seq = {json.dumps([p - 1 for p in page_sequence])};
        for (var i = 0; i < seq.length; i++) {{
            var page = inDoc.pageAtIndex(seq[i]);
            if (page) {{
                outDoc.insertPageAtIndex(page.copy, i);
            }}
        }}
        outDoc.writeToFile('{output_path}');
        """
        res = subprocess.run(
            ["osascript", "-l", "JavaScript", "-e", script],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        if res.returncode != 0 or not output_path.exists():
            raise DocumentConversionError(f"Failed to duplicate PDF pages: {res.stderr.strip()}")

    @staticmethod
    def _convert_image_to_pdf(input_path: Path, output_pdf: Path) -> None:
        """Convert any image to PDF using macOS native `sips`."""
        sips_bin = shutil.which("sips")
        if not sips_bin:
            raise DocumentConversionError("sips utility not found on macOS system.")

        cmd = [sips_bin, "-s", "format", "pdf", str(input_path), "--out", str(output_pdf)]
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if res.returncode != 0 or not output_pdf.exists():
            raise DocumentConversionError(
                f"Failed to convert image {input_path.name} to PDF: {res.stderr.strip()}"
            )

    @staticmethod
    def _convert_textutil_to_pdf(input_path: Path, output_pdf: Path) -> None:
        """
        Convert Office / RTF / HTML documents to PDF using macOS `textutil` + `cupsfilter`.
        """
        textutil_bin = shutil.which("textutil")
        if not textutil_bin:
            raise DocumentConversionError("textutil utility not found on macOS system.")

        # textutil cannot output PDF directly in older versions, but can convert to HTML/RTF,
        # which cupsfilter converts into PDF cleanly.
        temp_html = output_pdf.with_suffix(".html")
        cmd_textutil = [
            textutil_bin,
            "-convert",
            "html",
            str(input_path),
            "-output",
            str(temp_html),
        ]
        res1 = subprocess.run(
            cmd_textutil, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
        )
        if res1.returncode != 0 or not temp_html.exists():
            raise DocumentConversionError(
                f"textutil failed converting {input_path.name}: {res1.stderr.strip()}"
            )

        try:
            DocumentConverter._convert_via_cupsfilter(temp_html, output_pdf)
        finally:
            if temp_html.exists():
                temp_html.unlink(missing_ok=True)

    @staticmethod
    def _convert_text_to_pdf(input_path: Path, output_pdf: Path) -> None:
        """Convert source code / plain text to PDF via cupsfilter."""
        DocumentConverter._convert_via_cupsfilter(input_path, output_pdf)

    @staticmethod
    def _convert_via_cupsfilter(input_path: Path, output_pdf: Path) -> None:
        """Run cupsfilter to convert any recognized input stream to PDF."""
        cupsfilter_bin = shutil.which("cupsfilter") or "/usr/sbin/cupsfilter"
        if not os.path.exists(cupsfilter_bin):
            raise DocumentConversionError("cupsfilter utility not found at /usr/sbin/cupsfilter.")

        with open(output_pdf, "wb") as out_f:
            cmd = [cupsfilter_bin, "-m", "application/pdf", str(input_path)]
            res = subprocess.run(cmd, stdout=out_f, stderr=subprocess.PIPE)
            if res.returncode != 0 or output_pdf.stat().st_size == 0:
                err_msg = res.stderr.decode("utf-8", errors="ignore").strip()
                raise DocumentConversionError(
                    f"cupsfilter conversion failed for {input_path.name}: {err_msg}"
                )

    @staticmethod
    def _is_plain_text(path: Path) -> bool:
        """Heuristic check if a file is plain text / code."""
        try:
            with open(path, "rb") as f:
                chunk = f.read(1024)
                return b"\x00" not in chunk
        except Exception:
            return False

    # =========================================================================
    # WINDOWS FALLBACKS (only used when sys.platform == "win32")
    # =========================================================================

    @classmethod
    def _convert_to_base_pdf_windows(cls, path: Path, suffix: str, output_pdf: Path) -> None:
        if suffix in IMAGE_EXTENSIONS:
            cls._convert_image_to_pdf_pillow(path, output_pdf)
        elif suffix in TEXTUTIL_EXTENSIONS or cls._is_plain_text(path):
            cls._convert_office_to_pdf_windows(path, suffix, output_pdf)
        else:
            raise DocumentConversionError(
                f"Cannot convert {path.name} to PDF on Windows: unsupported format '{suffix}'."
            )

    @staticmethod
    def _convert_image_to_pdf_pillow(input_path: Path, output_pdf: Path) -> None:
        """Convert an image (all frames for multi-page TIFF/GIF) to PDF using Pillow."""
        try:
            from PIL import Image, ImageSequence
        except ImportError:
            raise DocumentConversionError(
                "Pillow is required to print images on Windows: pip install Pillow"
            )
        try:
            with Image.open(input_path) as img:
                frames = [frame.convert("RGB") for frame in ImageSequence.Iterator(img)]
            frames[0].save(output_pdf, "PDF", save_all=True, append_images=frames[1:])
        except Exception as e:
            raise DocumentConversionError(f"Failed to convert image {input_path.name} to PDF: {e}")
        if not output_pdf.exists() or output_pdf.stat().st_size == 0:
            raise DocumentConversionError(f"Failed to convert image {input_path.name} to PDF.")

    @staticmethod
    def _find_soffice() -> Optional[str]:
        found = shutil.which("soffice") or shutil.which("soffice.exe")
        if found:
            return found
        for env_var in ("PROGRAMFILES", "PROGRAMFILES(X86)"):
            base = os.environ.get(env_var)
            if base:
                candidate = Path(base) / "LibreOffice" / "program" / "soffice.exe"
                if candidate.exists():
                    return str(candidate)
        return None

    @classmethod
    def _convert_office_to_pdf_windows(cls, input_path: Path, suffix: str, output_pdf: Path) -> None:
        """Convert Office/RTF/HTML/text documents via LibreOffice headless, or docx2pdf (MS Word)."""
        soffice = cls._find_soffice()
        if soffice:
            out_dir = Path(tempfile.mkdtemp(prefix="soffice_", dir=str(output_pdf.parent)))
            try:
                cmd = [soffice, "--headless", "--convert-to", "pdf", "--outdir", str(out_dir), str(input_path)]
                res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                produced = out_dir / f"{input_path.stem}.pdf"
                if res.returncode != 0 or not produced.exists():
                    raise DocumentConversionError(
                        f"LibreOffice failed converting {input_path.name}: "
                        f"{res.stderr.strip() or res.stdout.strip()}"
                    )
                shutil.move(str(produced), str(output_pdf))
            finally:
                shutil.rmtree(out_dir, ignore_errors=True)
            return

        if suffix in (".docx", ".doc"):
            try:
                from docx2pdf import convert as docx2pdf_convert
            except ImportError:
                docx2pdf_convert = None
            if docx2pdf_convert is not None:
                try:
                    docx2pdf_convert(str(input_path), str(output_pdf))
                except Exception as e:
                    raise DocumentConversionError(f"docx2pdf failed converting {input_path.name}: {e}")
                if not output_pdf.exists():
                    raise DocumentConversionError(f"docx2pdf failed converting {input_path.name}.")
                return

        raise DocumentConversionError(
            f"Cannot convert {input_path.name} to PDF on Windows: install LibreOffice "
            "(soffice) or, for Word documents, docx2pdf with Microsoft Word."
        )
