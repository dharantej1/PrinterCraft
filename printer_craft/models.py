"""
Data models and enumerations for printer_craft.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


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
    fit_to_page: Optional[bool] = None
    scaling: Optional[PrintScaling] = None
    number_up: Optional[int] = None
    raw_options: Dict[str, str] = field(default_factory=dict)
    dry_run: bool = False

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
