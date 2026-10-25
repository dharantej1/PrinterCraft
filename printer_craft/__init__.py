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

__version__ = "0.1.0"
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
