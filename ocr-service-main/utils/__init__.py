"""Utility helpers for the OCR service.

Exported symbols
----------------
get_logger
    Factory that returns a JSON-configured :class:`logging.Logger`.
generate_request_id
    Returns a new UUID4-based request correlation string.
"""

from utils.logger import get_logger
from utils.request_id import generate_request_id

__all__ = ["get_logger", "generate_request_id"]
