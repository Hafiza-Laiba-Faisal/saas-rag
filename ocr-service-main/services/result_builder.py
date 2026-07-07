"""Result builder service for assembling OCR output structures."""

from schemas.ocr import ExtractedEntities, OCRRegion, OCRResult, PageResult


class ResultBuilder:
    """Builds PageResult and OCRResult objects from raw OCR data."""

    def build_page_result(
        self,
        page_num: int,
        regions: list[OCRRegion],
        entities: ExtractedEntities,
        embedded_text: str = "",
    ) -> PageResult:
        """Build a PageResult from OCR regions and extracted entities.

        - full_text = "\\n".join(r.text for r in regions) + ("\\n" + embedded_text if embedded_text else "")
        - paragraphs = [p.strip() for p in full_text.split("\\n\\n") if p.strip()]
        - lines = [l.strip() for l in full_text.splitlines() if l.strip()]
        - words = full_text.split()
        """
        region_text = "\n".join(r.text for r in regions)
        full_text = region_text + ("\n" + embedded_text if embedded_text else "")

        paragraphs = [p.strip() for p in full_text.split("\n\n") if p.strip()]
        lines = [line.strip() for line in full_text.splitlines() if line.strip()]
        words = full_text.split()

        return PageResult(
            page_number=page_num,
            full_text=full_text,
            paragraphs=paragraphs,
            lines=lines,
            words=words,
            regions=regions,
            entities=entities,
        )

    def build_ocr_result(
        self,
        request_id: str,
        filename: str,
        pages: list[PageResult],
        processing_time_ms: float,
        ocr_duration_ms: float,
    ) -> OCRResult:
        """Assemble the final OCRResult from pages and metadata."""
        return OCRResult(
            request_id=request_id,
            filename=filename,
            pages=pages,
            processing_time_ms=processing_time_ms,
            ocr_duration_ms=ocr_duration_ms,
        )
