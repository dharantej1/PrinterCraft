"""
Custom exceptions for the printer_craft package.
"""

class PrinterError(Exception):
    """Base exception for all printer-related errors."""
    pass


class PrinterNotFoundError(PrinterError):
    """Raised when a specified printer does not exist or cannot be found."""
    pass


class SpoolerUnavailableError(PrinterError):
    """Raised when the CUPS printing spooler daemon is not running or unreachable."""
    pass


class DocumentConversionError(PrinterError):
    """Raised when a document cannot be converted to a printable format."""
    pass


class PrintExecutionError(PrinterError):
    """Raised when the lp command exits with an error status."""
    def __init__(self, message: str, return_code: int = -1, command: list[str] | None = None):
        super().__init__(message)
        self.return_code = return_code
        self.command = command or []
