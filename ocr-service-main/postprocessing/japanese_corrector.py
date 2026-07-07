"""Japanese OCR post-processing and spell correction.

This module provides Japanese character correction, handling common OCR
misrecognition patterns for hiragana, katakana, and kanji.

Common OCR mistakes:
  コンビュー夕 → コンピュータ (Personal computer)
  テジタル → デジタル (Digital)
  ロCR → OCR
  バターン → パターン (Pattern)
  フアイル → ファイル (File)
  光学文学認識 → 光学文字認識 (Optical character recognition)
"""

from __future__ import annotations


class JapaneseCorrectionDictionary:
    """Common OCR error corrections for Japanese text."""

    # Common character-level substitutions
    CHAR_CORRECTIONS = {
        # Katakana confusions
        "ュー": "ュー",  # Already correct (example placeholder)
        "夕": "タ",  # タ vs 夕 (Ta character confusion)
        "テ": "テ",  # Already correct
        "ジ": "ジ",  # Already correct
        "ル": "ル",  # Already correct (but sometimes read as ロ)
        "ロ": "ル",  # Common: ロ (O) → ル (Ru)
        "バ": "パ",  # Common: バ → パ
        "フア": "ファ",  # Common: フア → ファ (Fa)
        "フオ": "フォ",  # Common: フオ → フォ (Fo)
        "シ": "シ",  # Already correct
        "ッ": "ッ",  # Already correct
    }

    # Common word-level corrections (more reliable than character-level)
    WORD_CORRECTIONS = {
        # Computer science terms
        "コンビュー夕": "コンピュータ",
        "コンビュータ": "コンピュータ",
        "コンぴゅー多": "コンピュータ",
        "テジタル": "デジタル",
        "デジダル": "デジタル",
        "ロCR": "OCR",
        "OCR": "OCR",  # Already correct
        "バターン": "パターン",
        "フアイル": "ファイル",
        
        # Document processing
        "光学文学認識": "光学文字認識",
        "光学文字認識": "光学文字認識",  # Already correct
        "光学文学認識": "光学文字認識",
        "文学": "文字",  # 学 vs 字
        
        # Common mistranscriptions
        "レクノロジー": "テクノロジー",
        "テクノロジ": "テクノロジー",
        "インターネット": "インターネット",  # Already correct
        "インターネッ": "インターネット",
        "データベース": "データベース",  # Already correct
        "データべース": "データベース",
    }

    @classmethod
    def correct_japanese_text(cls, text: str) -> str:
        """Apply Japanese OCR corrections to the given text.

        This method applies word-level corrections first (more reliable),
        then character-level substitutions for remaining issues.

        Args:
            text: Raw OCR output text containing Japanese characters.

        Returns:
            Corrected text with known OCR errors fixed.
        """
        if not text:
            return text

        # Apply word-level corrections first (higher priority)
        corrected = text
        for error, correction in cls.WORD_CORRECTIONS.items():
            corrected = corrected.replace(error, correction)

        # Apply character-level corrections (only for unmapped characters)
        # This is more conservative to avoid over-correcting
        for error, correction in cls.CHAR_CORRECTIONS.items():
            # Only apply if we're confident (check context if needed)
            corrected = corrected.replace(error, correction)

        return corrected


class JapanesePostProcessor:
    """Post-process OCR output for Japanese documents.

    Handles:
    - Vertical text orientation (reading order correction if needed)
    - Hiragana/Katakana/Kanji normalization
    - Common OCR error patterns
    """

    def __init__(self):
        self._dictionary = JapaneseCorrectionDictionary()

    def process(self, text: str, is_vertical: bool = False) -> str:
        """Post-process Japanese OCR output.

        Args:
            text: Raw OCR output text
            is_vertical: Whether the text was originally vertical

        Returns:
            Corrected and post-processed text
        """
        if not text:
            return text

        # Apply spell corrections
        corrected = self._dictionary.correct_japanese_text(text)

        # For vertical text, preserve line breaks but clean up spacing
        if is_vertical:
            lines = corrected.split('\n')
            # Remove excessive spacing but preserve line structure
            lines = [line.strip() for line in lines if line.strip()]
            corrected = '\n'.join(lines)

        return corrected.strip()

    def batch_process(self, texts: list[str], is_vertical: bool = False) -> list[str]:
        """Apply post-processing to multiple text strings.

        Args:
            texts: List of OCR output texts
            is_vertical: Whether the texts were originally vertical

        Returns:
            List of corrected texts
        """
        return [self.process(text, is_vertical) for text in texts]
