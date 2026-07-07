"""Entity extractor for post-processing OCR output text.

This module provides the :class:`EntityExtractor` class, which uses compiled
regular expressions to identify and extract URLs, email addresses, and phone
numbers from arbitrary text produced by the OCR pipeline.
"""

from __future__ import annotations

import re

from schemas.ocr import ExtractedEntities


class EntityExtractor:
    """Extract structured entities (URLs, emails, phone numbers) from OCR text.

    Patterns are compiled once at the class level for performance — they are
    shared across all instances and never recompiled.

    Example::

        extractor = EntityExtractor()
        entities = extractor.extract(
            "Email test@example.com or visit https://example.com"
        )
        # entities.emails  == ["test@example.com"]
        # entities.urls    == ["https://example.com"]
    """

    # ------------------------------------------------------------------
    # Compiled class-level patterns
    # ------------------------------------------------------------------

    #: Standard http/https URLs, including paths and query strings.
    _URL_PATTERN: re.Pattern[str] = re.compile(
        r'https?://[^\s<>"{}|\\^`\[\]]+'
    )

    #: Bare ``www.`` links that are not already captured by _URL_PATTERN.
    _URL_BARE_PATTERN: re.Pattern[str] = re.compile(
        r'(?<!\w)www\.[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}(?:/[^\s]*)?'
    )

    #: RFC-5322-inspired email pattern.
    _EMAIL_PATTERN: re.Pattern[str] = re.compile(
        r'[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}'
    )

    #: Phone number pattern supporting international and local formats:
    #:   +1-800-555-0100  |  (800) 555-0100  |  +92 300 1234567  |  03001234567
    #:
    #: Two alternation branches are used so that parenthetical area codes
    #: (e.g. ``(800) 555-0100``) are captured as a single match rather than
    #: the bare-digit branch swallowing only the trailing digits.
    _PHONE_PATTERN: re.Pattern[str] = re.compile(
        r'(?:'
        r'\(\d{1,4}\)[\s\-]?\d{3,4}[\s\-]?\d{4}'          # (NNN) NNN-NNNN
        r'|'
        r'(?:\+\d{1,3}[\s\-]?)?\d{3,4}[\s\-]?\d{3,4}[\s\-]?\d{3,4}'  # +CC-NNN-NNN-NNNN
        r')'
    )

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def extract(self, text: str) -> ExtractedEntities:
        """Extract entities from *text* and return an :class:`ExtractedEntities` object.

        The method runs each compiled pattern against the input and collects all
        non-overlapping matches.  When a bare ``www.`` URL is found that is not
        already part of an ``http``/``https`` match it is included in the URL
        list.  Empty lists (never ``None``) are returned for entity types that
        have no matches.

        Args:
            text: Raw text string from which entities should be extracted.
                  May be empty — an :class:`ExtractedEntities` with three
                  empty lists is returned in that case.

        Returns:
            :class:`~schemas.ocr.ExtractedEntities` containing three lists:
            ``urls``, ``emails``, and ``phone_numbers``.  All lists are
            guaranteed to be non-null.
        """
        if not text:
            return ExtractedEntities()

        urls: list[str] = self._extract_urls(text)
        emails: list[str] = self._EMAIL_PATTERN.findall(text)
        phone_numbers: list[str] = self._extract_phones(text)

        return ExtractedEntities(
            urls=urls,
            emails=emails,
            phone_numbers=phone_numbers,
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _extract_urls(self, text: str) -> list[str]:
        """Return all URLs found in *text*, merging http/https and bare www matches.

        Bare ``www.`` matches that overlap with an already-captured ``http``/``https``
        URL are deduplicated so the same link is not reported twice.

        Args:
            text: Input string to search.

        Returns:
            Ordered list of unique URL strings.
        """
        # Collect http/https URLs first.
        full_urls: list[str] = self._URL_PATTERN.findall(text)

        # Collect bare www. links, skipping any that are substrings of a full URL.
        bare_urls: list[str] = [
            match
            for match in self._URL_BARE_PATTERN.findall(text)
            if not any(match in full for full in full_urls)
        ]

        return full_urls + bare_urls

    def _extract_phones(self, text: str) -> list[str]:
        """Return all phone numbers found in *text*.

        Very short digit sequences (fewer than 7 digits total) are filtered out
        to avoid false positives from plain numbers that happen to match the
        structural pattern.

        Args:
            text: Input string to search.

        Returns:
            Ordered list of phone number strings.
        """
        candidates: list[str] = self._PHONE_PATTERN.findall(text)
        results: list[str] = []
        for candidate in candidates:
            # Count only digits; require at least 7 to be a plausible phone number.
            digit_count = sum(ch.isdigit() for ch in candidate)
            if digit_count >= 7:
                results.append(candidate)
        return results
