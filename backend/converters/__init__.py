"""
ConvertX converter modules.

Each converter is a self-contained module with a single public function
that takes Path input(s) and returns Path output(s).

All converters raise ConversionError on failure — the route layer
catches these and converts them to appropriate HTTP responses.
"""


class ConversionError(Exception):
    """
    Raised when a file conversion cannot be completed.

    Attributes:
        message: Short, user-facing error description.
        detail: Optional extended detail for debugging (not shown to end users).
    """

    def __init__(self, message: str, detail: str = ""):
        self.message = message
        self.detail = detail
        super().__init__(message)
