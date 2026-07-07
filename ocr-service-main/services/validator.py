"""File validation for OCR service uploads.

Validates uploaded files in a strict order:
  1. MIME type and file extension (UNSUPPORTED_FORMAT → 422)
  2. File size against configured limit (FILE_TOO_LARGE → 413)
  3. Empty file — zero bytes (EMPTY_FILE → 422)
  4. File corruption — tries to open with Pillow (images) or PyMuPDF (PDFs)
     (CORRUPTED_FILE → 422)
  5. PDF password protection (ENCRYPTED_PDF → 422)

Returns the raw file bytes so the caller does not need to re-read the upload.
"""

from __future__ import annotations

import io
from pathlib import Path

import fitz  # PyMuPDF
from fastapi import HTTPException, UploadFile
from PIL import Image, UnidentifiedImageError

from config.settings import Settings
from schemas.errors import ErrorResponse

# ---------------------------------------------------------------------------
# Supported format tables
# ---------------------------------------------------------------------------

SUPPORTED_EXTENSIONS: frozenset[str] = frozenset(
    {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tiff", ".tif", ".pdf"}
)

SUPPORTED_MIME_TYPES: frozenset[str] = frozenset(
    {
        "image/png",
        "image/jpeg",
        "image/webp",
        "image/bmp",
        "image/tiff",
        "application/pdf",
    }
)


class FileValidator:
    """Validates an uploaded file before passing it to the processing pipeline."""

    async def validate_upload(
        self, file: UploadFile, settings: Settings
    ) -> bytes:
        """Validate *file* and return its raw bytes.

        Checks are applied in this order:
          1. MIME type / extension
          2. File size
          3. Empty file
          4. Corruption (image: Pillow; PDF: PyMuPDF)
          5. PDF password protection

        Args:
            file: The FastAPI ``UploadFile`` received from the endpoint.
            settings: Application settings (used for ``max_file_size_mb``).

        Returns:
            The raw bytes of the file (already consumed; caller need not
            re-read).

        Raises:
            HTTPException: With an appropriate status code and
                :class:`~schemas.errors.ErrorResponse` detail for every
                validation failure.
        """
        # ------------------------------------------------------------------
        # 1. MIME type and extension check
        # ------------------------------------------------------------------
        self._check_format(file)

        # ------------------------------------------------------------------
        # 2–5. Read bytes, then check size / emptiness / corruption
        # ------------------------------------------------------------------
        content: bytes = await file.read()
        await file.seek(0)

        self._check_not_empty(content)
        self._check_size(content, settings)

        filename = file.filename or ""
        ext = Path(filename).suffix.lower()
        if ext == ".pdf":
            self._check_pdf_integrity(content)
        else:
            self._check_image_integrity(content)

        return content

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _error(status_code: int, error_type: str, message: str) -> HTTPException:
        """Build an :class:`HTTPException` with a structured body."""
        return HTTPException(
            status_code=status_code,
            detail=ErrorResponse(
                request_id="",
                error_type=error_type,
                message=message,
            ).model_dump(),
        )

    def _check_format(self, file: UploadFile) -> None:
        """Reject files whose MIME type *and* extension are not supported."""
        filename = file.filename or ""
        ext = Path(filename).suffix.lower()
        mime = (file.content_type or "").lower()

        mime_ok = mime in SUPPORTED_MIME_TYPES
        ext_ok = ext in SUPPORTED_EXTENSIONS

        if not mime_ok or not ext_ok:
            raise self._error(
                status_code=422,
                error_type="UNSUPPORTED_FORMAT",
                message=(
                    f"Unsupported file format. "
                    f"Extension '{ext or '(none)'}' / MIME type '{mime or '(none)'}' "
                    f"is not accepted. Supported formats: "
                    f"PNG, JPG, JPEG, WEBP, BMP, TIFF, PDF."
                ),
            )

    def _check_size(self, content: bytes, settings: Settings) -> None:
        """Reject files that exceed the configured size limit."""
        max_bytes = settings.max_file_size_mb * 1024 * 1024
        if len(content) > max_bytes:
            raise self._error(
                status_code=413,
                error_type="FILE_TOO_LARGE",
                message=(
                    f"File size {len(content) / (1024 * 1024):.2f} MB exceeds "
                    f"the maximum allowed size of {settings.max_file_size_mb} MB."
                ),
            )

    def _check_not_empty(self, content: bytes) -> None:
        """Reject zero-byte files."""
        if len(content) == 0:
            raise self._error(
                status_code=422,
                error_type="EMPTY_FILE",
                message="The uploaded file is empty (0 bytes).",
            )

    def _check_image_integrity(self, content: bytes) -> None:
        """Try to open the image bytes with Pillow; raise on failure."""
        try:
            with Image.open(io.BytesIO(content)) as img:
                img.verify()  # checks headers without fully decoding
        except (UnidentifiedImageError, Exception):
            raise self._error(
                status_code=422,
                error_type="CORRUPTED_FILE",
                message="The uploaded image file appears to be corrupted or unreadable.",
            )

    def _check_pdf_integrity(self, content: bytes) -> None:
        """Open the PDF with PyMuPDF; check for corruption and encryption."""
        try:
            doc = fitz.open(stream=content, filetype="pdf")
        except Exception:
            raise self._error(
                status_code=422,
                error_type="CORRUPTED_FILE",
                message="The uploaded PDF file appears to be corrupted or unreadable.",
            )

        if doc.is_encrypted:
            doc.close()
            raise self._error(
                status_code=422,
                error_type="ENCRYPTED_PDF",
                message=(
                    "The uploaded PDF is password-protected. "
                    "Please provide an unencrypted PDF."
                ),
            )

        doc.close()
