"""Configuration management for the OCR service.

Loads settings from environment variables and/or a .env file using
pydantic-settings. All numeric fields are range-validated at startup so
the service fails fast on bad configuration rather than at request time.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application-wide settings loaded from environment variables / .env.

    Attributes:
        max_file_size_mb: Maximum accepted upload size in megabytes.
        min_text_chars_threshold: Minimum embedded-text character count
            below which a PDF page is considered scanned and rendered.
        page_render_dpi: DPI used when rendering a PDF page to an image.
        ocr_languages: Language codes passed to PaddleOCR.
        log_level: Python logging level (DEBUG, INFO, WARNING, ERROR).
        use_gpu: Whether to enable GPU inference in PaddleOCR.
        min_image_dpi: Minimum DPI below which an image is upscaled.
        service_version: Reported service version string.
    """

    max_file_size_mb: int = 50
    min_text_chars_threshold: int = 20
    page_render_dpi: int = 150
    ocr_languages: str = "en,ur,ar"
    log_level: str = "INFO"
    use_gpu: bool = False
    min_image_dpi: int = 150
    service_version: str = "1.0.0"
    
    # OCR Engine Strategy
    primary_ocr_engine: str = "mistral"
    mistral_api_key: str = ""

    model_config = SettingsConfigDict(env_file=".env")

    # ------------------------------------------------------------------
    # Field validators
    # ------------------------------------------------------------------

    @field_validator("max_file_size_mb")
    @classmethod
    def max_file_size_must_be_positive(cls, v: int) -> int:
        """Ensure max_file_size_mb is strictly positive."""
        if v <= 0:
            raise ValueError(
                f"max_file_size_mb must be greater than 0, got {v}"
            )
        return v

    @field_validator("min_text_chars_threshold")
    @classmethod
    def min_text_threshold_must_be_non_negative(cls, v: int) -> int:
        """Ensure min_text_chars_threshold is non-negative."""
        if v < 0:
            raise ValueError(
                f"min_text_chars_threshold must be >= 0, got {v}"
            )
        return v

    @field_validator("page_render_dpi")
    @classmethod
    def page_render_dpi_must_be_positive(cls, v: int) -> int:
        """Ensure page_render_dpi is strictly positive."""
        if v <= 0:
            raise ValueError(
                f"page_render_dpi must be greater than 0, got {v}"
            )
        return v

    @field_validator("min_image_dpi")
    @classmethod
    def min_image_dpi_must_be_positive(cls, v: int) -> int:
        """Ensure min_image_dpi is strictly positive."""
        if v <= 0:
            raise ValueError(
                f"min_image_dpi must be greater than 0, got {v}"
            )
        return v

    @field_validator("log_level")
    @classmethod
    def log_level_must_be_valid(cls, v: str) -> str:
        """Ensure log_level is one of the standard Python logging levels."""
        valid = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        normalized = v.upper()
        if normalized not in valid:
            raise ValueError(
                f"log_level must be one of {sorted(valid)}, got {v!r}"
            )
        return normalized



@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the cached singleton Settings instance.

    Uses :func:`functools.lru_cache` so that the Settings object (and
    therefore the .env file / environment variable parsing) happens only
    once per process lifetime.

    Returns:
        The application :class:`Settings` instance.
    """
    return Settings()
