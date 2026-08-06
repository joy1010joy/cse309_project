"""Cross-cutting service utilities and exceptions."""
from __future__ import annotations


class ServiceError(Exception):
    """Raised by services to signal a known error condition.

    Carries an HTTP status code so routers can simply ``raise`` and map to
    ``HTTPException`` without needing to inspect string messages.
    """

    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
