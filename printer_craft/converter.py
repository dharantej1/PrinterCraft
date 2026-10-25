"""
Document converter supporting seamless printing of any document or image type.
Uses native macOS utilities (cupsfilter, textutil, sips) without third-party bloat.
"""

from __future__ import annotations

import os
import shutil
import subprocess
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
    ) -> Generator[Path, None, None]:
        """
        Context manager that yields a path to a printable file.
        If conversion is needed, a temporary file is created and cleaned up on exit.
        """
        path = Path(file_path).expanduser().resolve()
        if not path.exists():
            raise FileNotFoundError(f"Document file does not exist: {path}")

        suffix = path.suffix.lower()

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
            if suffix in TEXTUTIL_EXTENSIONS:
                cls._convert_textutil_to_pdf(path, output_pdf)
            elif suffix in IMAGE_EXTENSIONS:
                cls._convert_image_to_pdf(path, output_pdf)
            elif cls._is_plain_text(path):
                cls._convert_text_to_pdf(path, output_pdf)
            else:
                # Attempt cupsfilter fallback
                cls._convert_via_cupsfilter(path, output_pdf)

            yield output_pdf
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

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
