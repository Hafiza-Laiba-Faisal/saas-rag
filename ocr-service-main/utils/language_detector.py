"""Detect language from text and provide language-specific OCR config."""

from __future__ import annotations

import re
from typing import Optional


class LanguageDetector:
    """Detect language from text and return OCR engine configuration."""

    # Language detection patterns
    LANGUAGE_PATTERNS = {
        "urdu": {
            "pattern": r"[\u0600-\u06FF]",  # Arabic/Urdu script
            "name": "Urdu",
            "code": "ur",
            "ocr_lang": "arabic",
            "confidence_threshold": 0.3,  # More lenient for RTL
        },
        "arabic": {
            "pattern": r"[\u0600-\u06FF]",
            "name": "Arabic",
            "code": "ar",
            "ocr_lang": "arabic",
            "confidence_threshold": 0.3,
        },
        "hindi": {
            "pattern": r"[\u0900-\u097F]",  # Devanagari script
            "name": "Hindi",
            "code": "hi",
            "ocr_lang": "hindi",
            "confidence_threshold": 0.35,
        },
        "chinese": {
            "pattern": r"[\u4E00-\u9FFF]",  # CJK Unified Ideographs
            "name": "Chinese",
            "code": "zh",
            "ocr_lang": "chinese",
            "confidence_threshold": 0.4,
        },
        "japanese": {
            "pattern": r"[\u3040-\u309F\u30A0-\u30FF\u4E00-\u9FFF]",  # Hiragana, Katakana, Kanji
            "name": "Japanese",
            "code": "ja",
            "ocr_lang": "japanese",
            "confidence_threshold": 0.35,
        },
        "english": {
            "pattern": r"[a-zA-Z]",
            "name": "English",
            "code": "en",
            "ocr_lang": "english",
            "confidence_threshold": 0.5,
        },
    }

    @classmethod
    def detect(cls, text: str) -> dict:
        """Detect language(s) in text.

        Returns top detected language and confidence.

        Args:
            text: Text to analyze

        Returns:
            Dict with:
            - primary_language: Most detected language
            - confidence: Detection confidence (0-1)
            - detected_languages: List of all detected languages with scores
            - is_mixed: True if multiple languages detected
            - config: OCR configuration for primary language
        """
        detected = {}

        # Score each language
        for lang_key, lang_config in cls.LANGUAGE_PATTERNS.items():
            pattern = lang_config["pattern"]
            matches = re.findall(pattern, text)
            if matches:
                detected[lang_key] = len(matches) / max(len(text), 1)

        if not detected:
            # Default to English if nothing detected
            detected["english"] = 1.0

        # Sort by confidence
        sorted_langs = sorted(detected.items(), key=lambda x: x[1], reverse=True)
        primary_lang, confidence = sorted_langs[0]

        # Check if mixed language (multiple > 20%)
        is_mixed = len([s for _, s in sorted_langs if s > 0.2]) > 1

        return {
            "primary_language": primary_lang,
            "primary_name": cls.LANGUAGE_PATTERNS[primary_lang]["name"],
            "primary_code": cls.LANGUAGE_PATTERNS[primary_lang]["code"],
            "confidence": confidence,
            "is_mixed": is_mixed,
            "detected_languages": [
                {
                    "language": lang,
                    "name": cls.LANGUAGE_PATTERNS[lang]["name"],
                    "code": cls.LANGUAGE_PATTERNS[lang]["code"],
                    "confidence": conf,
                }
                for lang, conf in sorted_langs
            ],
            "config": cls.LANGUAGE_PATTERNS[primary_lang],
        }

    @classmethod
    def is_rtl_language(cls, language: str) -> bool:
        """Check if language is right-to-left.

        Args:
            language: Language code or name

        Returns:
            True if RTL language
        """
        rtl_langs = ["urdu", "arabic"]
        return language.lower() in rtl_langs

    @classmethod
    def get_preprocessing_hints(cls, language: str) -> dict:
        """Get preprocessing recommendations for language.

        Args:
            language: Language code

        Returns:
            Dict with preprocessing hints
        """
        language = language.lower()

        hints = {
            "urdu": {
                "aggressive_denoise": True,
                "fix_shadows": True,
                "sharpen": True,
                "correct_exposure": True,
                "note": "Urdu text is RTL, may need more aggressive preprocessing",
            },
            "arabic": {
                "aggressive_denoise": True,
                "fix_shadows": True,
                "sharpen": True,
                "correct_exposure": True,
                "note": "Arabic text is RTL, requires good image quality",
            },
            "hindi": {
                "aggressive_denoise": True,
                "fix_shadows": True,
                "sharpen": True,
                "correct_exposure": False,
                "note": "Devanagari script needs strong denoising",
            },
            "chinese": {
                "aggressive_denoise": True,
                "fix_shadows": False,
                "sharpen": True,
                "correct_exposure": True,
                "note": "CJK characters benefit from sharpening",
            },
            "japanese": {
                "aggressive_denoise": True,
                "fix_shadows": False,
                "sharpen": True,
                "correct_exposure": True,
                "note": "Japanese text needs clarity",
            },
            "english": {
                "aggressive_denoise": False,
                "fix_shadows": False,
                "sharpen": False,
                "correct_exposure": False,
                "note": "Standard preprocessing sufficient",
            },
        }

        return hints.get(language, hints["english"])

    @classmethod
    def extract_mixed_language_chunks(cls, text: str) -> list[dict]:
        """Split text into chunks by language.

        Useful for processing mixed-language documents differently.

        Args:
            text: Mixed language text

        Returns:
            List of text chunks with language info
        """
        chunks = []
        current_chunk = ""
        current_lang = None

        for char in text:
            # Detect character language
            char_lang = None
            for lang_key, lang_config in cls.LANGUAGE_PATTERNS.items():
                if re.match(lang_config["pattern"], char):
                    char_lang = lang_key
                    break

            if char_lang and char_lang != current_lang:
                # Language changed
                if current_chunk:
                    chunks.append({
                        "text": current_chunk,
                        "language": current_lang,
                        "name": (
                            cls.LANGUAGE_PATTERNS[current_lang]["name"]
                            if current_lang
                            else "Unknown"
                        ),
                    })
                current_chunk = char
                current_lang = char_lang
            else:
                current_chunk += char

        # Add final chunk
        if current_chunk:
            chunks.append({
                "text": current_chunk,
                "language": current_lang,
                "name": (
                    cls.LANGUAGE_PATTERNS[current_lang]["name"]
                    if current_lang
                    else "Unknown"
                ),
            })

        return chunks
