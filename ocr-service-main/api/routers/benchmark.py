"""Benchmark and export endpoints for production testing."""
from __future__ import annotations

import time
from pathlib import Path
from typing import Annotated

import cv2
import numpy as np
from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel

from api.dependencies import (
    get_image_service,
    get_pdf_service,
    get_settings,
)
from services.image_service import ImageOCRService
from services.pdf_service import PDFOCRService
from config.settings import Settings
from services.validator import FileValidator
from utils.request_id import generate_request_id

router = APIRouter(prefix="/ocr", tags=["Benchmark"])


class BenchmarkResult(BaseModel):
    request_id: str
    filename: str
    processing_time_ms: float
    ocr_duration_ms: float
    words_found: int
    regions_found: int
    avg_confidence: float
    min_confidence: float
    max_confidence: float
    image_width: int
    image_height: int
    image_size_kb: float
    chars_per_second: float
    pages: int
    runs: int


@router.post("/benchmark", response_model=BenchmarkResult)
async def benchmark_image(
    file: UploadFile = File(...),
    runs: int = Query(default=1, ge=1, le=3, description="Number of runs to average (1-3)"),
    image_service: ImageOCRService = Depends(get_image_service),
    settings: Settings = Depends(get_settings),
) -> BenchmarkResult:
    """Run OCR and return detailed performance + quality metrics."""
    request_id = generate_request_id()
    validator = FileValidator()
    content = await validator.validate_upload(file, settings)

    arr = np.frombuffer(content, np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        raise HTTPException(status_code=400, detail="Could not decode image")
    h, w = img.shape[:2]
    size_kb = len(content) / 1024

    all_times, all_ocr_times = [], []
    last_result = None
    for _ in range(runs):
        t0 = time.monotonic()
        result = image_service.process(content, file.filename or "benchmark", request_id)
        all_times.append((time.monotonic() - t0) * 1000)
        all_ocr_times.append(result.ocr_duration_ms)
        last_result = result

    avg_time = sum(all_times) / len(all_times)
    avg_ocr = sum(all_ocr_times) / len(all_ocr_times)

    page = last_result.pages[0] if last_result and last_result.pages else None
    regions = page.regions if page else []
    words = page.words if page else []
    total_chars = sum(len(r.text) for r in regions)
    confidences = [r.confidence for r in regions] if regions else [0.0]

    return BenchmarkResult(
        request_id=request_id,
        filename=file.filename or "benchmark",
        processing_time_ms=round(avg_time, 2),
        ocr_duration_ms=round(avg_ocr, 2),
        words_found=len(words),
        regions_found=len(regions),
        avg_confidence=round(sum(confidences) / len(confidences), 4),
        min_confidence=round(min(confidences), 4),
        max_confidence=round(max(confidences), 4),
        image_width=w,
        image_height=h,
        image_size_kb=round(size_kb, 2),
        chars_per_second=round(total_chars / (avg_time / 1000) if avg_time > 0 else 0, 1),
        pages=len(last_result.pages) if last_result else 0,
        runs=runs,
    )


@router.post("/export")
async def export_result(
    file: UploadFile = File(...),
    format: str = Query(default="txt", description="Export format: txt, json, csv, html"),
    image_service: ImageOCRService = Depends(get_image_service),
    pdf_service: PDFOCRService = Depends(get_pdf_service),
    settings: Settings = Depends(get_settings),
) -> Response:
    """Run OCR and download result in txt / json / csv / html format."""
    if format not in ("txt", "json", "csv", "html"):
        raise HTTPException(status_code=400, detail="Format must be one of: txt, json, csv, html")

    request_id = generate_request_id()
    validator = FileValidator()
    content = await validator.validate_upload(file, settings)

    ext = Path(file.filename or "").suffix.lower()
    if ext == ".pdf":
        result = pdf_service.process(content, file.filename or "export.pdf", request_id)
    else:
        result = image_service.process(content, file.filename or "export", request_id)

    fname = result.filename
    all_text = "\n\n".join(p.full_text for p in result.pages)

    if format == "txt":
        return Response(
            content=all_text.encode("utf-8"),
            media_type="text/plain; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{fname}.txt"'},
        )
    elif format == "json":
        return Response(
            content=result.model_dump_json(indent=2).encode("utf-8"),
            media_type="application/json",
            headers={"Content-Disposition": f'attachment; filename="{fname}.json"'},
        )
    elif format == "csv":
        lines = ["page,region_index,text,confidence,x_min,y_min,x_max,y_max"]
        for p in result.pages:
            for i, r in enumerate(p.regions):
                bb = r.bounding_box
                safe = r.text.replace('"', '""')
                lines.append(f'{p.page_number},{i},"{safe}",{r.confidence:.4f},{bb[0]},{bb[1]},{bb[2]},{bb[3]}')
        return Response(
            content="\n".join(lines).encode("utf-8"),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{fname}.csv"'},
        )
    else:  # html
        rows = ""
        for p in result.pages:
            safe_text = p.full_text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            rows += f'<h3>Page {p.page_number}</h3><pre>{safe_text}</pre>\n'
            ents = p.entities.urls + p.entities.emails + p.entities.phone_numbers
            if ents:
                rows += "<p><b>Entities:</b> " + " | ".join(ents) + "</p>\n"
        body = f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<title>OCR: {fname}</title>
<style>body{{font-family:sans-serif;max-width:900px;margin:auto;padding:20px}}
pre{{background:#f5f5f5;padding:12px;border-radius:4px;white-space:pre-wrap}}</style>
</head><body>
<h1>OCR Result: {fname}</h1>
<p>⏱️ {result.processing_time_ms:.0f}ms &nbsp; 📄 {len(result.pages)} page(s)</p>
{rows}</body></html>"""
        return Response(
            content=body.encode("utf-8"),
            media_type="text/html; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{fname}.html"'},
        )
