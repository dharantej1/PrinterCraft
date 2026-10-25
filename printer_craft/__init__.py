"""
printer_craft: A modern, reverse-engineered CUPS printing library and CLI for macOS and Unix.
"""

from .converter import DocumentConverter
from .core import PrinterManager
from .exceptions import (
    DocumentConversionError,
    PrinterError,
    PrinterNotFoundError,
    PrintExecutionError,
    SpoolerUnavailableError,
)
from .models import (
    ColorMode,
    DuplexMode,
    Orientation,
    Printer,
    PrinterOption,
    PrinterOptionChoice,
    PrintJobOptions,
    PrintResult,
    PrintScaling,
)

try:
    from ._version import version as __version__
except ImportError:
    try:
        from importlib.metadata import version as _pkg_version
        __version__ = _pkg_version("printer-craft")
    except Exception:
        __version__ = "unknown"
__all__ = [
    "PrinterManager",
    "DocumentConverter",
    "PrintJobOptions",
    "PrintResult",
    "Printer",
    "PrinterOption",
    "PrinterOptionChoice",
    "DuplexMode",
    "ColorMode",
    "Orientation",
    "PrintScaling",
    "PrinterError",
    "PrinterNotFoundError",
    "SpoolerUnavailableError",
    "DocumentConversionError",
    "PrintExecutionError",
]
