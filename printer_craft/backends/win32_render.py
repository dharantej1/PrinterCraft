"""
Page selection, layout and rasterisation helpers for the Windows GDI print path.

Windows printer drivers consume GDI drawing calls rather than PDF, so documents are
rendered page by page (PDF via pypdfium2, images via Pillow, plain text via Pillow) and
laid out on the printable area of the device context. This module is pure Python and
platform independent; the Win32 backend supplies device geometry and does the drawing.
"""

from __future__ import annotations

import logging
import shutil
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator, List, Optional, Sequence, Tuple

from ..converter import IMAGE_EXTENSIONS, TEXTUTIL_EXTENSIONS, DocumentConverter
from ..exceptions import DocumentConversionError
from ..models import Orientation, PrintJobOptions, PrintScaling

logger = logging.getLogger(__name__)

POINTS_PER_INCH = 72.0
LETTER_PT = (612.0, 792.0)

# Documents converted to PDF with LibreOffice / docx2pdf before rendering.
OFFICE_EXTENSIONS = TEXTUTIL_EXTENSIONS | {
    ".odt", ".ods", ".odp", ".xls", ".xlsx", ".ppt", ".pptx", ".csv",
}

NUMBER_UP_VALUES = (1, 2, 4, 6, 9, 16)

# Largest resolution pages are rasterised at; the driver scales up to device DPI.
MAX_RENDER_DPI = 300

TEXT_FONT_SIZE_PT = 10.0
TEXT_LINE_SPACING = 1.2
TEXT_MARGIN_PT = 36.0
TEXT_TAB_SIZE = 8
_MONOSPACE_FONTS = (
    "consola.ttf",
    "cour.ttf",
    "DejaVuSansMono.ttf",
    "LiberationMono-Regular.ttf",
    "Menlo.ttc",
)


# =============================================================================
# PAGE SOURCES
# =============================================================================


class PageSource:
    """A single logical page that can be rasterised at any pixel size."""

    size_pt: Tuple[float, float] = LETTER_PT

    def render(self, width_px: int, height_px: int) -> Any:  # -> PIL.Image.Image
        raise NotImplementedError


class PdfPageSource(PageSource):
    def __init__(self, document: Any, index: int):
        self._document = document
        self._index = index
        w, h = document[index].get_size()
        self.size_pt = (float(w), float(h))

    def render(self, width_px: int, height_px: int) -> Any:
        page = self._document[self._index]
        try:
            bitmap = page.render(scale=width_px / self.size_pt[0])
            image = bitmap.to_pil()
        finally:
            page.close()
        image = image.convert("RGB")
        if image.size != (width_px, height_px):
            image = image.resize((width_px, height_px))
        return image


class ImagePageSource(PageSource):
    def __init__(self, image: Any, dpi: Tuple[float, float] = (POINTS_PER_INCH, POINTS_PER_INCH)):
        self._image = image
        dpi_x = float(dpi[0] or POINTS_PER_INCH)
        dpi_y = float(dpi[1] or POINTS_PER_INCH)
        self.size_pt = (
            image.width * POINTS_PER_INCH / dpi_x,
            image.height * POINTS_PER_INCH / dpi_y,
        )

    def render(self, width_px: int, height_px: int) -> Any:
        from PIL import Image

        resample = getattr(Image, "Resampling", Image).LANCZOS
        return self._image.resize((width_px, height_px), resample)


class TextPageSource(PageSource):
    def __init__(self, lines: List[str], size_pt: Tuple[float, float]):
        self._lines = lines
        self.size_pt = size_pt

    def render(self, width_px: int, height_px: int) -> Any:
        from PIL import Image, ImageDraw

        scale = width_px / self.size_pt[0]
        image = Image.new("RGB", (width_px, height_px), "white")
        draw = ImageDraw.Draw(image)
        font = _load_monospace_font(max(1, int(round(TEXT_FONT_SIZE_PT * scale))))
        line_height = TEXT_FONT_SIZE_PT * TEXT_LINE_SPACING * scale
        x = TEXT_MARGIN_PT * scale
        y = TEXT_MARGIN_PT * scale
        for line in self._lines:
            draw.text((x, y), line, fill="black", font=font)
            y += line_height
        return image


class BlankPageSource(PageSource):
    def __init__(self, size_pt: Tuple[float, float] = LETTER_PT):
        self.size_pt = size_pt

    def render(self, width_px: int, height_px: int) -> Any:
        from PIL import Image

        return Image.new("RGB", (width_px, height_px), "white")


def _load_monospace_font(size_px: int) -> Any:
    from PIL import ImageFont

    for name in _MONOSPACE_FONTS:
        try:
            return ImageFont.truetype(name, size_px)
        except OSError:
            continue
    try:
        return ImageFont.load_default(size=size_px)
    except TypeError:  # Pillow < 10.1
        return ImageFont.load_default()


def _require_pillow() -> None:
    try:
        import PIL  # noqa: F401
    except ImportError:
        raise DocumentConversionError(
            "Pillow is required to print on Windows: pip install Pillow"
        )


def _require_pdfium() -> Any:
    try:
        import pypdfium2
    except ImportError:
        raise DocumentConversionError(
            "pypdfium2 is required to print PDFs on Windows: pip install pypdfium2"
        )
    return pypdfium2


# =============================================================================
# DOCUMENT LOADING
# =============================================================================


@contextmanager
def _open_pdf(source: Any) -> Iterator[List[PageSource]]:
    pdfium = _require_pdfium()
    try:
        document = pdfium.PdfDocument(source)
    except Exception as e:
        raise DocumentConversionError(f"Failed to open PDF: {e}")
    try:
        yield [PdfPageSource(document, i) for i in range(len(document))]
    finally:
        document.close()


def _load_image_pages(image: Any) -> List[PageSource]:
    from PIL import ImageOps, ImageSequence

    dpi = image.info.get("dpi") or (POINTS_PER_INCH, POINTS_PER_INCH)
    pages: List[PageSource] = []
    for frame in ImageSequence.Iterator(image):
        frame = ImageOps.exif_transpose(frame)
        if frame.mode in ("RGBA", "LA", "P"):
            rgba = frame.convert("RGBA")
            from PIL import Image

            background = Image.new("RGB", rgba.size, "white")
            background.paste(rgba, mask=rgba.split()[-1])
            frame = background
        else:
            frame = frame.convert("RGB")
        pages.append(ImagePageSource(frame, dpi))
    return pages


def _open_image(source: Any, name: str) -> List[PageSource]:
    _require_pillow()
    from PIL import Image

    try:
        import pillow_heif  # type: ignore[import-not-found]

        pillow_heif.register_heif_opener()
    except ImportError:
        pass
    try:
        with Image.open(source) as image:
            return _load_image_pages(image)
    except Exception as e:
        raise DocumentConversionError(f"Failed to open image {name}: {e}")


def _decode_text(data: bytes) -> str:
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("latin-1", errors="replace")


def paginate_text(text: str, page_size_pt: Tuple[float, float] = LETTER_PT) -> List[PageSource]:
    """Lay out plain text in a 10pt monospace font with 0.5in margins."""
    _require_pillow()
    font = _load_monospace_font(100)
    try:
        char_width = font.getlength("M") / 100.0
    except Exception:
        char_width = 0.6
    usable_w = page_size_pt[0] - 2 * TEXT_MARGIN_PT
    usable_h = page_size_pt[1] - 2 * TEXT_MARGIN_PT
    chars_per_line = max(1, int(usable_w / (TEXT_FONT_SIZE_PT * (char_width or 0.6))))
    lines_per_page = max(1, int(usable_h / (TEXT_FONT_SIZE_PT * TEXT_LINE_SPACING)))

    lines: List[str] = []
    for raw in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        line = raw.expandtabs(TEXT_TAB_SIZE).replace("\f", "")
        if not line:
            lines.append("")
        while line:
            lines.append(line[:chars_per_line])
            line = line[chars_per_line:]
    while lines and lines[-1] == "":
        lines.pop()
    if not lines:
        lines = [""]

    return [
        TextPageSource(lines[i:i + lines_per_page], page_size_pt)
        for i in range(0, len(lines), lines_per_page)
    ]


@contextmanager
def open_document(path: Path, page_size_pt: Tuple[float, float] = LETTER_PT) -> Iterator[List[PageSource]]:
    """Yield the logical pages of a document file, converting Office formats to PDF first."""
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        with _open_pdf(str(path)) as pages:
            yield pages
        return

    if suffix in IMAGE_EXTENSIONS:
        yield _open_image(str(path), path.name)
        return

    if suffix in OFFICE_EXTENSIONS:
        temp_dir = tempfile.mkdtemp(prefix="printer_craft_win_")
        try:
            output_pdf = Path(temp_dir) / f"{path.stem}_converted.pdf"
            DocumentConverter._convert_office_to_pdf_windows(path, suffix, output_pdf)
            with _open_pdf(str(output_pdf)) as pages:
                yield pages
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)
        return

    if DocumentConverter._is_plain_text(path):
        yield paginate_text(_decode_text(path.read_bytes()), page_size_pt)
        return

    raise DocumentConversionError(
        f"Cannot print {path.name} on Windows: unsupported format '{suffix or 'unknown'}'."
    )


def sniff_bytes(data: bytes) -> Optional[str]:
    """Classify an in-memory document as 'pdf', 'image' or None (printer language / unknown)."""
    head = data[:16]
    if data[:1024].lstrip().startswith(b"%PDF"):
        return "pdf"
    image_magic = (
        b"\x89PNG", b"\xff\xd8\xff", b"GIF87a", b"GIF89a", b"BM", b"II*\x00", b"MM\x00*",
    )
    if head.startswith(image_magic) or (head[:4] == b"RIFF" and head[8:12] == b"WEBP"):
        return "image"
    return None


@contextmanager
def open_bytes(data: bytes, kind: str) -> Iterator[List[PageSource]]:
    if kind == "pdf":
        with _open_pdf(data) as pages:
            yield pages
        return
    import io

    yield _open_image(io.BytesIO(data), "<bytes>")


# =============================================================================
# PAGE SELECTION (mirrors CUPSBackend.submit_file + lp page-ranges semantics)
# =============================================================================


def page_sequence_from_ranges(page_ranges: Optional[str]) -> Optional[List[int]]:
    """
    Same detection as the CUPS backend: a plain comma list with repeated or
    descending pages (e.g. "1,1,1,1") becomes an explicit page sequence.
    """
    if not page_ranges:
        return None
    try:
        tokens = [t.strip() for t in page_ranges.split(",")]
        parsed: List[int] = []
        for t in tokens:
            if "-" in t:
                return None
            parsed.append(int(t))
        if parsed and (len(parsed) != len(set(parsed)) or parsed != sorted(parsed)):
            return parsed
    except Exception:
        pass
    return None


def expand_page_ranges(page_ranges: str, total: int) -> List[int]:
    """Expand CUPS page-ranges syntax ("1-3,5", "4-", "-2") into ascending page numbers."""
    selected = set()
    for token in (t.strip() for t in page_ranges.split(",")):
        if not token:
            continue
        try:
            if "-" in token:
                start_s, _, end_s = token.partition("-")
                start = int(start_s) if start_s.strip() else 1
                end = int(end_s) if end_s.strip() else total
            else:
                start = end = int(token)
        except ValueError:
            raise DocumentConversionError(f"Bad page-ranges value: '{page_ranges}'")
        selected.update(p for p in range(start, end + 1) if 1 <= p <= total)
    return sorted(selected)


def select_pages(opts: PrintJobOptions, total: int) -> List[int]:
    """
    Return the 1-based page order to print. `repeat` repeats page 1 and repeated /
    reordered page lists are honoured exactly as on the CUPS path; remaining page
    ranges are then applied to that page stream like `lp -o page-ranges`.
    """
    sequence = page_sequence_from_ranges(opts.page_ranges)
    page_ranges = None if sequence is not None else opts.page_ranges
    if sequence is None and opts.repeat and opts.repeat > 1:
        sequence = [1] * opts.repeat

    pages = [p for p in sequence if 1 <= p <= total] if sequence is not None else list(range(1, total + 1))
    if page_ranges:
        positions = expand_page_ranges(page_ranges, len(pages))
        pages = [pages[i - 1] for i in positions]
    return pages


# =============================================================================
# SHEET LAYOUT
# =============================================================================


@dataclass
class DeviceGeometry:
    """Printable area and physical sheet of a printer DC, in device pixels."""
    dpi_x: int
    dpi_y: int
    printable_w: int
    printable_h: int
    physical_w: int
    physical_h: int
    offset_x: int = 0
    offset_y: int = 0

    @property
    def page_size_pt(self) -> Tuple[float, float]:
        return (
            self.physical_w * POINTS_PER_INCH / self.dpi_x,
            self.physical_h * POINTS_PER_INCH / self.dpi_y,
        )

    @classmethod
    def letter(cls, dpi: int = 600) -> "DeviceGeometry":
        return cls(dpi, dpi, int(8.5 * dpi), 11 * dpi, int(8.5 * dpi), 11 * dpi)


@dataclass
class Placement:
    source: PageSource
    rect: Tuple[int, int, int, int]  # left, top, right, bottom in device pixels
    rotation: int  # counter-clockwise degrees applied to the rendered page


def resolve_scaling(opts: PrintJobOptions) -> str:
    """Map print-scaling / fit-to-page to one of 'fit', 'fill', 'none', 'auto-fit'."""
    if opts.scaling is not None:
        return {
            PrintScaling.AUTO: "auto-fit",
            PrintScaling.AUTO_FIT: "auto-fit",
            PrintScaling.FIT_TO_PAGE: "fit",
            PrintScaling.FILL: "fill",
            PrintScaling.NONE: "none",
        }[opts.scaling]
    if opts.fit_to_page is None:
        return "auto-fit"
    return "fit" if opts.fit_to_page else "none"


def resolve_number_up(opts: PrintJobOptions) -> int:
    return opts.number_up if opts.number_up in NUMBER_UP_VALUES else 1


def number_up_grid(number_up: int, landscape_sheet: bool) -> Tuple[int, int]:
    """(columns, rows) for an N-up sheet, matching CUPS' grid for each N."""
    cols, rows = {1: (1, 1), 2: (1, 2), 4: (2, 2), 6: (2, 3), 9: (3, 3), 16: (4, 4)}[number_up]
    return (rows, cols) if landscape_sheet else (cols, rows)


def _place(
    source: PageSource,
    cell: Tuple[int, int, int, int],
    geom: DeviceGeometry,
    mode: str,
    allow_rotate: bool,
    center_on_sheet: bool,
) -> Placement:
    left, top, right, bottom = cell
    cell_w, cell_h = right - left, bottom - top
    natural_w = source.size_pt[0] / POINTS_PER_INCH * geom.dpi_x
    natural_h = source.size_pt[1] / POINTS_PER_INCH * geom.dpi_y

    best = None
    for rotation in ((0, 90) if allow_rotate and mode != "none" else (0,)):
        w, h = (natural_w, natural_h) if rotation == 0 else (natural_h, natural_w)
        fit = min(cell_w / w, cell_h / h)
        if best is None or fit > best[1] + 1e-9:
            best = (rotation, fit, w, h)
    rotation, fit, w, h = best

    if mode == "fit":
        scale = fit
    elif mode == "fill":
        scale = max(cell_w / w, cell_h / h)
    elif mode == "auto-fit":
        scale = min(1.0, fit)
    else:
        scale = 1.0

    dest_w = max(1, int(round(w * scale)))
    dest_h = max(1, int(round(h * scale)))
    if center_on_sheet and scale == 1.0:
        x = (geom.physical_w - dest_w) // 2 - geom.offset_x
        y = (geom.physical_h - dest_h) // 2 - geom.offset_y
    else:
        x = left + (cell_w - dest_w) // 2
        y = top + (cell_h - dest_h) // 2
    return Placement(source, (x, y, x + dest_w, y + dest_h), rotation)


def layout_sheet(
    pages: Sequence[PageSource],
    geom: DeviceGeometry,
    opts: PrintJobOptions,
) -> List[Placement]:
    """Position up to N pages on one sheet according to number-up, scaling and orientation."""
    number_up = resolve_number_up(opts)
    mode = resolve_scaling(opts)
    allow_rotate = opts.orientation is None
    reverse = opts.orientation in (Orientation.REVERSE_LANDSCAPE, Orientation.REVERSE_PORTRAIT)

    if number_up == 1:
        cells = [(0, 0, geom.printable_w, geom.printable_h)]
    else:
        cols, rows = number_up_grid(number_up, geom.printable_w > geom.printable_h)
        cw, ch = geom.printable_w // cols, geom.printable_h // rows
        cells = [(c * cw, r * ch, (c + 1) * cw, (r + 1) * ch) for r in range(rows) for c in range(cols)]
        mode = "fit"

    placements = []
    for source, cell in zip(pages, cells):
        p = _place(source, cell, geom, mode, allow_rotate or number_up > 1, center_on_sheet=number_up == 1)
        if reverse:
            p.rotation = (p.rotation + 180) % 360
        placements.append(p)
    return placements


def plan_sheets(
    pages: Sequence[PageSource],
    number_up: int,
    copies: int = 1,
    collate: bool = True,
    duplex: bool = False,
) -> List[List[PageSource]]:
    """
    Group pages into sheets of N, then optionally emulate copies in software for
    drivers without hardware copy support. Collated duplex copies start on a new sheet.
    """
    sheets = [list(pages[i:i + number_up]) for i in range(0, len(pages), number_up)]
    if copies <= 1 or not sheets:
        return sheets
    if collate:
        one_copy = list(sheets)
        if duplex and len(one_copy) % 2 == 1:
            one_copy.append([])
        out = []
        for _ in range(copies):
            out.extend(one_copy)
        return out
    return [sheet for sheet in sheets for _ in range(copies)]


def render_placement(placement: Placement, geom: DeviceGeometry, grayscale: bool = False) -> Any:
    """Rasterise a placed page at (at most MAX_RENDER_DPI) and rotate it into position."""
    left, top, right, bottom = placement.rect
    w, h = right - left, bottom - top
    if placement.rotation in (90, 270):
        w, h = h, w
    factor = min(1.0, MAX_RENDER_DPI / float(min(geom.dpi_x, geom.dpi_y)))
    image = placement.source.render(max(1, int(round(w * factor))), max(1, int(round(h * factor))))
    if placement.rotation:
        image = image.rotate(placement.rotation, expand=True)
    if grayscale:
        image = image.convert("L")
    return image
