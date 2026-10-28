"""
Data models and enumerations for printer_craft.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Tuple


class DuplexMode(str, Enum):
    """Duplex / 2-sided printing modes."""
    ONE_SIDED = "one-sided"
    TWO_SIDED_LONG_EDGE = "two-sided-long-edge"
    TWO_SIDED_SHORT_EDGE = "two-sided-short-edge"

    @classmethod
    def from_str(cls, value: str) -> DuplexMode:
        norm = value.lower().replace("_", "-")
        if norm in ("simplex", "one-sided", "1", "false", "off", "none"):
            return cls.ONE_SIDED
        if norm in ("duplex", "two-sided", "long-edge", "two-sided-long-edge", "duplexnotumble"):
            return cls.TWO_SIDED_LONG_EDGE
        if norm in ("short-edge", "two-sided-short-edge", "tumble", "duplextumble"):
            return cls.TWO_SIDED_SHORT_EDGE
        raise ValueError(f"Unknown duplex mode: {value}")


class ColorMode(str, Enum):
    """Color mode for print jobs."""
    MONOCHROME = "monochrome"
    COLOR = "color"
    AUTO = "auto"

    @classmethod
    def from_str(cls, value: str) -> ColorMode:
        norm = value.lower()
        if norm in ("mono", "monochrome", "grayscale", "gray", "black-white", "bw"):
            return cls.MONOCHROME
        if norm in ("color", "colour", "rgb", "cmyk"):
            return cls.COLOR
        if norm in ("auto", "default"):
            return cls.AUTO
        raise ValueError(f"Unknown color mode: {value}")


class Orientation(str, Enum):
    """Page orientation flags (CUPS orientation-requested values)."""
    PORTRAIT = "3"
    LANDSCAPE = "4"
    REVERSE_LANDSCAPE = "5"
    REVERSE_PORTRAIT = "6"

    @classmethod
    def from_str(cls, value: str) -> Orientation:
        norm = value.lower().replace("_", "-")
        if norm in ("portrait", "3", "p"):
            return cls.PORTRAIT
        if norm in ("landscape", "4", "l"):
            return cls.LANDSCAPE
        if norm in ("reverse-landscape", "5", "rl"):
            return cls.REVERSE_LANDSCAPE
        if norm in ("reverse-portrait", "6", "rp"):
            return cls.REVERSE_PORTRAIT
        raise ValueError(f"Unknown orientation: {value}")


class PrintScaling(str, Enum):
    """CUPS print-scaling option values."""
    AUTO = "auto"
    AUTO_FIT = "auto-fit"
    FIT_TO_PAGE = "fit-to-page"
    FILL = "fill"
    NONE = "none"


@dataclass
class PrinterOptionChoice:
    """A selectable choice for a PPD printer option."""
    name: str
    display_text: str
    is_default: bool = False


@dataclass
class PrinterOption:
    """A configurable hardware/driver option supported by a printer."""
    keyword: str
    display_name: str
    choices: List[PrinterOptionChoice] = field(default_factory=list)

    @property
    def default_choice(self) -> Optional[PrinterOptionChoice]:
        for choice in self.choices:
            if choice.is_default:
                return choice
        return None


@dataclass
class Printer:
    """Represents a discovered printer and its current state."""
    name: str
    status: str = "idle"
    is_default: bool = False
    description: str = ""
    location: str = ""
    options: Dict[str, PrinterOption] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status,
            "is_default": self.is_default,
            "description": self.description,
            "location": self.location,
            "options": {
                opt.keyword: {
                    "display_name": opt.display_name,
                    "default": opt.default_choice.name if opt.default_choice else None,
                    "choices": [c.name for c in opt.choices],
                }
                for opt in self.options.values()
            },
        }


@dataclass
class PrintJobOptions:
    """Comprehensive options for submitting a print job."""
    printer: Optional[str] = None
    copies: int = 1
    title: Optional[str] = None
    duplex: Optional[DuplexMode] = None
    collate: Optional[bool] = None
    color_mode: Optional[ColorMode] = None
    media: Optional[str] = None
    page_ranges: Optional[str] = None
    orientation: Optional[Orientation] = None
    fit_to_page: Optional[bool] = True
    scaling: Optional[PrintScaling] = None
    number_up: Optional[int] = None
    repeat: Optional[int] = None
    raw_options: Dict[str, str] = field(default_factory=dict)
    dry_run: bool = False
    dpi: Optional[int] = None
    progress_callback: Optional[Callable[[int, int], None]] = None

    def build_lp_args(self) -> List[str]:
        """
        Assemble the list of CLI arguments for `/usr/bin/lp`, mirroring
        the exact parameter construction of `PdfCraft::craft_print::lp_args`.
        """
        args: List[str] = []

        # Target printer
        if self.printer:
            args.extend(["-d", self.printer])

        # Number of copies
        if self.copies > 1:
            args.extend(["-n", str(min(max(1, self.copies), 999))])

        # Job / Document Title
        if self.title:
            args.extend(["-t", self.title])

        # Collation
        if self.collate is not None:
            args.extend(["-o", f"collate={'true' if self.collate else 'false'}"])

        # Duplex / Two-sided
        if self.duplex is not None:
            args.extend(["-o", f"sides={self.duplex.value}"])

        # Color mode
        if self.color_mode is not None and self.color_mode != ColorMode.AUTO:
            args.extend(["-o", f"print-color-mode={self.color_mode.value}"])

        # Media / Paper Size
        if self.media:
            args.extend(["-o", f"media={self.media}"])

        # Page Ranges
        if self.page_ranges:
            args.extend(["-o", f"page-ranges={self.page_ranges}"])

        # Orientation
        if self.orientation is not None:
            args.extend(["-o", f"orientation-requested={self.orientation.value}"])

        # Fit to page
        if self.fit_to_page is not None:
            args.extend(["-o", f"fit-to-page={'true' if self.fit_to_page else 'false'}"])

        # Print scaling
        if self.scaling is not None:
            args.extend(["-o", f"print-scaling={self.scaling.value}"])

        # Number up (n-up printing, e.g. 2, 4, 6, 9, 16 pages per sheet)
        if self.number_up is not None and self.number_up in (1, 2, 4, 6, 9, 16):
            args.extend(["-o", f"number-up={self.number_up}"])

        # Raw / Custom PPD Options
        for key, value in self.raw_options.items():
            args.extend(["-o", f"{key}={value}"])

        return args

    def build_devmode_settings(self) -> Dict[str, Any]:
        """
        Translate options into Windows DEVMODE field values (used only by the
        Win32 backend). Keys are pywin32 `PyDEVMODE` attribute names.
        `raw_options`, `fit_to_page`, `scaling`, `number_up` and `page_ranges`
        have no DEVMODE equivalent and are not included.
        """
        settings: Dict[str, Any] = {"Copies": min(max(1, self.copies), 999)}

        if self.collate is not None:
            settings["Collate"] = _DMCOLLATE_TRUE if self.collate else _DMCOLLATE_FALSE

        if self.duplex is not None:
            settings["Duplex"] = _WIN32_DUPLEX[self.duplex]

        if self.color_mode is not None and self.color_mode != ColorMode.AUTO:
            settings["Color"] = _WIN32_COLOR[self.color_mode]

        if self.orientation is not None:
            settings["Orientation"] = _WIN32_ORIENTATION[self.orientation]

        if self.media:
            paper_size = _WIN32_PAPER_SIZES.get(self.media.strip().lower())
            if paper_size is not None:
                settings["PaperSize"] = paper_size
            else:
                settings["FormName"] = self.media

        return settings


# Windows DEVMODE constants (wingdi.h)
_DMCOLLATE_FALSE = 0
_DMCOLLATE_TRUE = 1

_WIN32_DUPLEX = {
    DuplexMode.ONE_SIDED: 1,  # DMDUP_SIMPLEX
    DuplexMode.TWO_SIDED_LONG_EDGE: 2,  # DMDUP_VERTICAL
    DuplexMode.TWO_SIDED_SHORT_EDGE: 3,  # DMDUP_HORIZONTAL
}

_WIN32_COLOR = {
    ColorMode.MONOCHROME: 1,  # DMCOLOR_MONOCHROME
    ColorMode.COLOR: 2,  # DMCOLOR_COLOR
}

# DEVMODE only supports portrait/landscape; reverse variants map to their base orientation.
_WIN32_ORIENTATION = {
    Orientation.PORTRAIT: 1,  # DMORIENT_PORTRAIT
    Orientation.REVERSE_PORTRAIT: 1,
    Orientation.LANDSCAPE: 2,  # DMORIENT_LANDSCAPE
    Orientation.REVERSE_LANDSCAPE: 2,
}

# CUPS/PWG media names -> DMPAPER_* values. Unknown names are passed as a form name.
_WIN32_PAPER_SIZES = {
    "letter": 1,
    "na_letter_8.5x11in": 1,
    "us letter": 1,
    "tabloid": 3,
    "na_ledger_11x17in": 3,
    "ledger": 4,
    "legal": 5,
    "na_legal_8.5x14in": 5,
    "us legal": 5,
    "statement": 6,
    "na_invoice_5.5x8.5in": 6,
    "executive": 7,
    "na_executive_7.25x10.5in": 7,
    "a3": 8,
    "iso_a3_297x420mm": 8,
    "a4": 9,
    "iso_a4_210x297mm": 9,
    "a5": 11,
    "iso_a5_148x210mm": 11,
    "b4": 12,
    "jis_b4_257x364mm": 12,
    "b5": 13,
    "jis_b5_182x257mm": 13,
    "env10": 20,
    "na_number-10_4.125x9.5in": 20,
    "csheet": 24,
    "c-sheet": 24,
    "ansi c": 24,
    "ansi_c": 24,
    "dsheet": 25,
    "d-sheet": 25,
    "ansi d": 25,
    "ansi_d": 25,
    "esheet": 26,
    "e-sheet": 26,
    "ansi e": 26,
    "ansi_e": 26,
    "envdl": 27,
    "iso_dl_110x220mm": 27,
    "a2": 66,
    "iso_a2_420x594mm": 66,
    "a6": 70,
    "iso_a6_105x148mm": 70,
}

# Standard paper sizes in points (width, height) in portrait orientation.
# Used for tolerance-based paper matching (0.25 mm ~ 0.71 pt tolerance).
STANDARD_PAPER_SIZES: Dict[str, Tuple[float, float]] = {
    "letter": (612.0, 792.0),
    "legal": (612.0, 1008.0),
    "tabloid": (792.0, 1224.0),
    "ledger": (792.0, 1224.0),
    "statement": (396.0, 612.0),
    "executive": (522.0, 756.0),
    "a6": (297.64, 419.53),
    "a5": (419.53, 595.28),
    "a4": (595.28, 841.89),
    "a3": (841.89, 1190.55),
    "a2": (1190.55, 1683.78),
    "a1": (1683.78, 2383.94),
    "a0": (2383.94, 3370.39),
    "b5": (515.91, 728.50),
    "b4": (728.50, 1031.89),
    "arch_a": (648.0, 864.0),
    "arch_b": (864.0, 1296.0),
    "arch_c": (1296.0, 1728.0),
    "arch_d": (1728.0, 2592.0),
    "arch_e1": (2160.0, 3024.0),
    "arch_e": (2592.0, 3456.0),
    "ansi_c": (1224.0, 1584.0),
    "ansi_d": (1584.0, 2448.0),
    "ansi_e": (2448.0, 3168.0),
}


@dataclass
class PrintResult:
    """The result returned after executing or dry-running a print job."""
    success: bool
    printer: str
    job_id: Optional[str] = None
    command_run: List[str] = field(default_factory=list)
    output: str = ""
    error: Optional[str] = None
    dry_run: bool = False
