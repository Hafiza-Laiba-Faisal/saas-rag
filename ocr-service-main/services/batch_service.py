"""Batch processing service for handling multiple files in a single request."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Union

from fastapi import UploadFile

from config.settings import Settings
from schemas.ocr import BatchResult, FileErrorResult, OCRResult
from utils.logger import get_logger
from utils.request_id import generate_request_id

if TYPE_CHECKING:
    from services.image_service import ImageOCRService
    from services.pdf_service import PDFOCRService

SUPPORTED_IMAGE_EXTS = frozenset({".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tiff", ".tif"})
SUPPORTED_PDF_EXTS = frozenset({".pdf"})
SUPPORTED_EXTS = SUPPORTED_IMAGE_EXTS | SUPPORTED_PDF_EXTS

logger = get_logger(__name__)


class BatchProcessor:
    """Processes multiple image or PDF files in a single batch operation.

    Dispatches each file to the appropriate OCR service based on its
    extension, collects results (or errors) in order, and returns a
    :class:`~schemas.ocr.BatchResult` summary.
    """

    def __init__(
        self,
        image_service: "ImageOCRService",
        pdf_service: "PDFOCRService",
        settings: Settings,
    ) -> None:
        self._image_service = image_service
        self._pdf_service = pdf_service
        self._settings = settings

    async def process_files(
        self,
        files: list[UploadFile],
        request_id: str,
    ) -> BatchResult:
        """Process multiple :class:`~fastapi.UploadFile` objects.

        For each file:
        - Determines type from extension.
        - Reads content via ``await file.read()``.
        - Dispatches to :meth:`image_service.process` or
          :meth:`pdf_service.process` based on the extension.
        - On any :class:`Exception`, appends a
          :class:`~schemas.ocr.FileErrorResult` with
          ``error_code="PROCESSING_ERROR"``.
        - Preserves the original file order in the returned results.

        Args:
            files: Uploaded files to process.
            request_id: Correlation ID for this batch request.

        Returns:
            A :class:`~schemas.ocr.BatchResult` with per-file results and
            aggregate counts.
        """
        results: list[Union[OCRResult, FileErrorResult]] = []

        for file in files:
            filename = file.filename or ""
            ext = Path(filename).suffix.lower()
            try:
                content = await file.read()
                if ext in SUPPORTED_IMAGE_EXTS:
                    result = self._image_service.process(content, filename, request_id)
                elif ext in SUPPORTED_PDF_EXTS:
                    result = self._pdf_service.process(content, filename, request_id)
                else:
                    raise ValueError(f"Unsupported file extension: {ext!r}")
                results.append(result)
                logger.info(
                    "File processed successfully",
                    extra={"request_id": request_id, "file_name": filename},
                )
            except Exception as e:
                logger.warning(
                    "File processing failed",
                    extra={
                        "request_id": request_id,
                        "file_name": filename,
                        "error": str(e),
                    },
                )
                results.append(
                    FileErrorResult(
                        filename=filename,
                        error=str(e),
                        error_code="PROCESSING_ERROR",
                    )
                )

        successful = sum(1 for r in results if isinstance(r, OCRResult))
        failed = sum(1 for r in results if isinstance(r, FileErrorResult))

        return BatchResult(
            request_id=request_id,
            results=results,
            total_files=len(files),
            successful=successful,
            failed=failed,
        )

    def process_directory(
        self,
        dir_path: Path,
        recursive: bool,
        request_id: str,
    ) -> BatchResult:
        """Scan a directory for supported files and process each synchronously.

        - Uses ``dir_path.rglob("*")`` if *recursive*, else
          ``dir_path.glob("*")``.
        - Filters to :data:`SUPPORTED_EXTS`.
        - Dispatches each file to the appropriate service.
        - Same error handling as :meth:`process_files`.

        Args:
            dir_path: Root directory to scan.
            recursive: Whether to descend into subdirectories.
            request_id: Correlation ID for this batch request.

        Returns:
            A :class:`~schemas.ocr.BatchResult` with per-file results and
            aggregate counts.
        """
        pattern_fn = dir_path.rglob if recursive else dir_path.glob
        file_paths = [p for p in pattern_fn("*") if p.is_file() and p.suffix.lower() in SUPPORTED_EXTS]

        results: list[Union[OCRResult, FileErrorResult]] = []

        for file_path in file_paths:
            filename = file_path.name
            ext = file_path.suffix.lower()
            try:
                content = file_path.read_bytes()
                if ext in SUPPORTED_IMAGE_EXTS:
                    result = self._image_service.process(content, filename, request_id)
                else:
                    result = self._pdf_service.process(content, filename, request_id)
                results.append(result)
                logger.info(
                    "Directory file processed successfully",
                    extra={"request_id": request_id, "file_name": filename},
                )
            except Exception as e:
                logger.warning(
                    "Directory file processing failed",
                    extra={
                        "request_id": request_id,
                        "file_name": filename,
                        "error": str(e),
                    },
                )
                results.append(
                    FileErrorResult(
                        filename=filename,
                        error=str(e),
                        error_code="PROCESSING_ERROR",
                    )
                )

        successful = sum(1 for r in results if isinstance(r, OCRResult))
        failed = sum(1 for r in results if isinstance(r, FileErrorResult))

        return BatchResult(
            request_id=request_id,
            results=results,
            total_files=len(file_paths),
            successful=successful,
            failed=failed,
        )
