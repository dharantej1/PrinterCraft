"""
Platform printing backends: CUPS (macOS/Unix) and the Windows print spooler (win32print).
"""

from .base import PrinterBackend
from .cups_backend import CUPSBackend
from .win32_backend import Win32Backend

__all__ = ["PrinterBackend", "CUPSBackend", "Win32Backend"]
