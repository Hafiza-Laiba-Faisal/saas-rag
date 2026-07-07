"""OCR endpoints: /ocr/image, /ocr/pdf, /ocr/batch"""
import sys
from typing import Annotated, Optional
from fastapi import APIRouter, Depends, File, Query, UploadFile
from config.settings import Settings
from schemas.ocr import BatchResult, OCRResult
from services.batch_service import BatchProcessor
from services.image_service import ImageOCRService
from services.pdf_service import PDFOCRService
from services.validator import FileValidator
from utils.request_id import generate_request_id
from api.dependencies import get_batch_processor, get_image_service, get_pdf_service, get_settings

router = APIRouter(prefix="/ocr", tags=["OCR"])
validator = FileValidator()


@router.post("/image", response_model=OCRResult)
async def ocr_image(
    file: UploadFile = File(...),
    image_service: ImageOCRService = Depends(get_image_service),
    settings: Settings = Depends(get_settings),
) -> OCRResult:
    request_id = generate_request_id()
    content = await validator.validate_upload(file, settings)
    return image_service.process(content, file.filename or "image", request_id)


@router.post("/pdf", response_model=OCRResult)
async def ocr_pdf(
    file: UploadFile = File(...),
    pdf_service: PDFOCRService = Depends(get_pdf_service),
    settings: Settings = Depends(get_settings),
) -> OCRResult:
    request_id = generate_request_id()
    content = await validator.validate_upload(file, settings)
    return pdf_service.process(content, file.filename or "document.pdf", request_id)


@router.post("/batch", response_model=BatchResult)
async def ocr_batch(
    files: list[UploadFile] = File(default=[]),
    directory: Optional[str] = Query(default=None, description="Directory path to scan"),
    recursive: bool = Query(default=False),
    batch_processor: BatchProcessor = Depends(get_batch_processor),
) -> BatchResult:
    from pathlib import Path
    request_id = generate_request_id()
    if directory:
        return batch_processor.process_directory(Path(directory), recursive, request_id)
    return await batch_processor.process_files(files, request_id)
