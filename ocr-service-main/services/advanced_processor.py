"""Advanced OCR processing combining images, tables, and multilingual support."""

from __future__ import annotations

import logging
from typing import Any

from postprocessing.table_parser import extract_all_tables
from utils.language_detector import LanguageDetector

logger = logging.getLogger(__name__)


class AdvancedOCRProcessor:
    """Post-process OCR results with table extraction and language detection."""

    def __init__(self) -> None:
        self._language_detector = LanguageDetector()

    def process_full_result(self, ocr_result: dict, raw_text: str) -> dict:
        """Process OCR result with advanced features.

        Args:
            ocr_result: Standard OCR result from engine
            raw_text: Raw extracted text

        Returns:
            Enhanced result with tables, language info, etc.
        """
        result = ocr_result.copy()

        # Detect language and add info
        language_info = self._language_detector.detect(raw_text)
        result["language_detection"] = language_info

        # Extract tables from text
        table_info = extract_all_tables(raw_text)
        result["tables"] = table_info

        # Add preprocessing hints for detected language
        if language_info.get("is_mixed"):
            # Extract language chunks
            chunks = self._language_detector.extract_mixed_language_chunks(raw_text)
            result["language_chunks"] = chunks
            logger.info(
                "Detected mixed language document with %d language chunks",
                len(chunks),
            )

        # Add language-specific preprocessing hints
        preprocessing_hints = self._language_detector.get_preprocessing_hints(
            language_info["primary_language"]
        )
        result["preprocessing_hints"] = preprocessing_hints

        logger.info(
            "Advanced processing complete - Language: %s, Tables: %d, Mixed: %s",
            language_info["primary_name"],
            table_info.get("total_tables", 0),
            language_info.get("is_mixed", False),
        )

        return result

    @staticmethod
    def format_for_export(result: dict, format_type: str = "json") -> str:
        """Format result for export in different formats.

        Args:
            result: Processed OCR result
            format_type: 'json', 'csv', 'markdown', 'html'

        Returns:
            Formatted string
        """
        if format_type == "markdown":
            return AdvancedOCRProcessor._to_markdown(result)
        elif format_type == "html":
            return AdvancedOCRProcessor._to_html(result)
        elif format_type == "csv":
            return AdvancedOCRProcessor._to_csv(result)
        else:
            import json
            return json.dumps(result, indent=2, ensure_ascii=False)

    @staticmethod
    def _to_markdown(result: dict) -> str:
        """Convert result to Markdown format."""
        lines = []

        # Header
        lines.append("# OCR Result")
        lines.append("")

        # Language info
        lang_info = result.get("language_detection", {})
        if lang_info:
            lines.append("## Language Detection")
            lines.append(f"- **Primary**: {lang_info.get('primary_name', 'Unknown')}")
            lines.append(f"- **Confidence**: {lang_info.get('confidence', 0):.1%}")
            lines.append(f"- **Mixed**: {'Yes' if lang_info.get('is_mixed') else 'No'}")
            lines.append("")

        # Tables
        tables_info = result.get("tables", {})
        if tables_info.get("total_tables", 0) > 0:
            lines.append("## Tables Detected")
            lines.append(f"Found **{tables_info['total_tables']}** table(s)")
            lines.append("")

        # Text
        if result.get("full_text"):
            lines.append("## Extracted Text")
            lines.append("```")
            lines.append(result["full_text"][:500])
            if len(result["full_text"]) > 500:
                lines.append("... (truncated)")
            lines.append("```")
            lines.append("")

        return "\n".join(lines)

    @staticmethod
    def _to_html(result: dict) -> str:
        """Convert result to HTML format."""
        html_parts = [
            "<html>",
            "<head><meta charset='utf-8'><title>OCR Result</title></head>",
            "<body>",
            "<h1>OCR Result</h1>",
        ]

        # Language info
        lang_info = result.get("language_detection", {})
        if lang_info:
            html_parts.append("<h2>Language Detection</h2>")
            html_parts.append("<ul>")
            html_parts.append(f"<li>Primary: {lang_info.get('primary_name', 'Unknown')}</li>")
            html_parts.append(
                f"<li>Confidence: {lang_info.get('confidence', 0):.1%}</li>"
            )
            html_parts.append(
                f"<li>Mixed: {'Yes' if lang_info.get('is_mixed') else 'No'}</li>"
            )
            html_parts.append("</ul>")

        # Tables
        tables_info = result.get("tables", {})
        if tables_info.get("total_tables", 0) > 0:
            html_parts.append("<h2>Tables</h2>")
            html_parts.append(f"<p>Found {tables_info['total_tables']} table(s)</p>")

        # Text
        if result.get("full_text"):
            html_parts.append("<h2>Extracted Text</h2>")
            html_parts.append("<pre>")
            html_parts.append(result["full_text"][:1000])
            html_parts.append("</pre>")

        html_parts.extend(["</body>", "</html>"])
        return "\n".join(html_parts)

    @staticmethod
    def _to_csv(result: dict) -> str:
        """Convert result to CSV format."""
        import csv
        import io

        output = io.StringIO()
        writer = csv.writer(output)

        # Header
        writer.writerow(["Field", "Value"])

        # Language
        lang_info = result.get("language_detection", {})
        if lang_info:
            writer.writerow(["Language", lang_info.get("primary_name", "Unknown")])
            writer.writerow(
                ["Language Confidence", f"{lang_info.get('confidence', 0):.1%}"]
            )
            writer.writerow(["Mixed Language", "Yes" if lang_info.get("is_mixed") else "No"])

        # Tables
        tables_info = result.get("tables", {})
        writer.writerow(["Tables Found", tables_info.get("total_tables", 0)])

        # Text
        if result.get("full_text"):
            writer.writerow(["Full Text", result["full_text"][:500]])

        return output.getvalue()
