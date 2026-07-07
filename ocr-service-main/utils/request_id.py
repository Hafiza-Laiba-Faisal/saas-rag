"""Request correlation ID generation for the OCR service.

Usage::

    from utils.request_id import generate_request_id

    request_id = generate_request_id()
    # e.g. "3f2504e0-4f89-11d3-9a0c-0305e82c3301"
"""

from __future__ import annotations

import uuid


def generate_request_id() -> str:
    """Generate a new, globally unique request correlation ID.

    Returns:
        A lowercase UUID4 string in canonical 8-4-4-4-12 hex format,
        e.g. ``"3f2504e0-4f89-11d3-9a0c-0305e82c3301"``.
    """
    return str(uuid.uuid4())
