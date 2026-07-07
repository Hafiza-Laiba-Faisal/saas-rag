"""Parse ASCII and formatted tables from OCR text."""

from __future__ import annotations

import re
from typing import Optional


class ASCIITableParser:
    """Detect and parse ASCII-formatted tables from text."""

    # Pattern: +---+---+ or |xxx|yyy|
    BORDER_PATTERN = re.compile(r'^\s*[\+\-\|\s]+$')
    ROW_PATTERN = re.compile(r'^\s*\|(.+)\|?\s*$')
    DASH_TABLE_PATTERN = re.compile(r'^\s*[\+\-]+[\+\-\s]*$')

    @classmethod
    def detect_table(cls, text: str) -> bool:
        """Check if text contains an ASCII table.

        Args:
            text: OCR text to check

        Returns:
            True if table detected
        """
        lines = text.split('\n')
        border_count = 0
        row_count = 0

        for line in lines:
            if cls.BORDER_PATTERN.match(line):
                border_count += 1
            elif cls.ROW_PATTERN.match(line):
                row_count += 1

        # Table needs at least border-row-border pattern
        return border_count >= 2 and row_count >= 1

    @classmethod
    def parse(cls, text: str) -> Optional[list[list[str]]]:
        """Parse ASCII table to CSV rows.

        Handles:
        - |cell|cell| format
        - +---+---+ borders
        - Alignment variations

        Args:
            text: Text containing ASCII table

        Returns:
            List of rows (each row is list of cells), or None if not a table
        """
        if not cls.detect_table(text):
            return None

        lines = text.split('\n')
        rows = []
        current_row = []

        for line in lines:
            # Skip border lines
            if cls.DASH_TABLE_PATTERN.match(line):
                continue

            # Parse data rows
            match = cls.ROW_PATTERN.match(line)
            if match:
                cells_str = match.group(1)
                cells = cls._split_cells(cells_str)
                if cells:
                    rows.append(cells)

        return rows if rows else None

    @classmethod
    def _split_cells(cls, cells_str: str) -> list[str]:
        """Split cell string by | delimiter, clean up whitespace.

        Args:
            cells_str: String like "cell1|cell2|cell3"

        Returns:
            List of cleaned cell values
        """
        cells = cells_str.split('|')
        # Clean and remove empty leading/trailing
        cells = [c.strip() for c in cells if c.strip()]
        return cells

    @classmethod
    def extract_tables(cls, text: str) -> list[list[list[str]]]:
        """Extract all ASCII tables from text.

        Args:
            text: Text potentially containing multiple tables

        Returns:
            List of tables, each table is list of rows
        """
        tables = []

        # Split by double newlines to find table sections
        sections = re.split(r'\n\s*\n', text)

        for section in sections:
            table = cls.parse(section)
            if table:
                tables.append(table)

        return tables


class StructuredTextTableParser:
    """Parse aligned text that looks like a table (columns separated by spaces)."""

    @classmethod
    def detect_aligned_table(cls, text: str) -> bool:
        """Check if text is aligned columns (spaces align vertically).

        Args:
            text: Text to check

        Returns:
            True if aligned column structure detected
        """
        lines = [l for l in text.split('\n') if l.strip()]
        if len(lines) < 2:
            return False

        # Check if multiple lines have similar structure (spaces at same positions)
        first_line_spaces = cls._find_space_positions(lines[0])
        if len(first_line_spaces) < 2:
            return False

        # Check consistency in next lines
        consistent = 0
        for line in lines[1:]:
            line_spaces = cls._find_space_positions(line)
            if line_spaces and abs(len(line_spaces) - len(first_line_spaces)) <= 1:
                consistent += 1

        return consistent >= len(lines) - 2

    @classmethod
    def parse_aligned_table(cls, text: str) -> Optional[list[list[str]]]:
        """Parse aligned column table.

        Example:
            Product    Qty  Price
            Apple      10   50.00
            Orange     5    30.00

        Args:
            text: Aligned text to parse

        Returns:
            List of rows as list of cells
        """
        if not cls.detect_aligned_table(text):
            return None

        lines = [l for l in text.split('\n') if l.strip()]
        if not lines:
            return None

        # Find column boundaries by looking at space groups
        boundaries = cls._find_column_boundaries(lines)

        rows = []
        for line in lines:
            cells = cls._extract_cells_by_boundaries(line, boundaries)
            rows.append(cells)

        return rows

    @classmethod
    def _find_space_positions(cls, line: str) -> list[int]:
        """Find positions where multiple spaces occur (column separators)."""
        positions = []
        in_spaces = False
        space_start = 0

        for i, char in enumerate(line):
            if char == ' ':
                if not in_spaces:
                    space_start = i
                    in_spaces = True
            else:
                if in_spaces and (i - space_start) >= 2:
                    positions.append(i)
                in_spaces = False

        return positions

    @classmethod
    def _find_column_boundaries(cls, lines: list[str]) -> list[int]:
        """Find column boundaries from multiple lines."""
        # Collect all space positions from all lines
        all_positions = set()
        for line in lines:
            all_positions.update(cls._find_space_positions(line))

        return sorted(all_positions)

    @classmethod
    def _extract_cells_by_boundaries(
        cls, line: str, boundaries: list[int]
    ) -> list[str]:
        """Extract cells using column boundaries."""
        if not boundaries:
            return [line.strip()]

        cells = []
        prev = 0

        for boundary in boundaries:
            cell = line[prev:boundary].strip()
            if cell:
                cells.append(cell)
            prev = boundary

        # Last cell
        if prev < len(line):
            cell = line[prev:].strip()
            if cell:
                cells.append(cell)

        return cells

    @classmethod
    def extract_aligned_tables(cls, text: str) -> list[list[list[str]]]:
        """Extract all aligned column tables from text."""
        tables = []
        sections = re.split(r'\n\s*\n', text)

        for section in sections:
            table = cls.parse_aligned_table(section)
            if table and len(table) > 1:  # At least header + 1 row
                tables.append(table)

        return tables


def extract_all_tables(text: str) -> dict:
    """Extract all types of tables from OCR text.

    Args:
        text: OCR extracted text

    Returns:
        Dict with:
        - ascii_tables: Parsed ASCII tables
        - aligned_tables: Parsed aligned column tables
        - raw_text: Original text
    """
    return {
        "ascii_tables": ASCIITableParser.extract_tables(text),
        "aligned_tables": StructuredTextTableParser.extract_aligned_tables(text),
        "total_tables": (
            len(ASCIITableParser.extract_tables(text))
            + len(StructuredTextTableParser.extract_aligned_tables(text))
        ),
    }
