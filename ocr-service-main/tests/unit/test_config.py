"""Unit tests for config/settings.py.

Covers default values, range validation, log-level normalisation,
.env override via monkeypatch, and the lru_cache singleton behaviour.
"""

from __future__ import annotations

import importlib

import pytest
from pydantic import ValidationError

from config.settings import Settings, get_settings


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def fresh_settings(**overrides) -> Settings:
    """Create a Settings instance with env-file loading disabled."""
    # Passing _env_file=None prevents pydantic-settings from reading .env
    return Settings(_env_file=None, **overrides)


# ---------------------------------------------------------------------------
# Default values
# ---------------------------------------------------------------------------

class TestDefaults:
    def test_max_file_size_mb_default(self):
        s = fresh_settings()
        assert s.max_file_size_mb == 50

    def test_min_text_chars_threshold_default(self):
        s = fresh_settings()
        assert s.min_text_chars_threshold == 20

    def test_page_render_dpi_default(self):
        s = fresh_settings()
        assert s.page_render_dpi == 300

    def test_ocr_languages_default(self):
        s = fresh_settings()
        assert s.ocr_languages == ["en", "ur", "ar"]

    def test_log_level_default(self):
        s = fresh_settings()
        assert s.log_level == "INFO"

    def test_use_gpu_default(self):
        s = fresh_settings()
        assert s.use_gpu is False

    def test_min_image_dpi_default(self):
        s = fresh_settings()
        assert s.min_image_dpi == 150

    def test_service_version_default(self):
        s = fresh_settings()
        assert s.service_version == "1.0.0"


# ---------------------------------------------------------------------------
# Range validation — invalid values
# ---------------------------------------------------------------------------

class TestRangeValidation:
    def test_max_file_size_zero_raises(self):
        with pytest.raises(ValidationError, match="max_file_size_mb"):
            fresh_settings(max_file_size_mb=0)

    def test_max_file_size_negative_raises(self):
        with pytest.raises(ValidationError, match="max_file_size_mb"):
            fresh_settings(max_file_size_mb=-1)

    def test_page_render_dpi_zero_raises(self):
        with pytest.raises(ValidationError, match="page_render_dpi"):
            fresh_settings(page_render_dpi=0)

    def test_page_render_dpi_negative_raises(self):
        with pytest.raises(ValidationError, match="page_render_dpi"):
            fresh_settings(page_render_dpi=-100)

    def test_min_image_dpi_zero_raises(self):
        with pytest.raises(ValidationError, match="min_image_dpi"):
            fresh_settings(min_image_dpi=0)

    def test_min_image_dpi_negative_raises(self):
        with pytest.raises(ValidationError, match="min_image_dpi"):
            fresh_settings(min_image_dpi=-1)

    def test_min_text_chars_threshold_negative_raises(self):
        with pytest.raises(ValidationError, match="min_text_chars_threshold"):
            fresh_settings(min_text_chars_threshold=-1)

    def test_min_text_chars_threshold_zero_is_valid(self):
        # Zero is allowed — means every page is treated as scanned
        s = fresh_settings(min_text_chars_threshold=0)
        assert s.min_text_chars_threshold == 0


# ---------------------------------------------------------------------------
# Range validation — valid boundary values
# ---------------------------------------------------------------------------

class TestBoundaryValues:
    def test_max_file_size_one_is_valid(self):
        s = fresh_settings(max_file_size_mb=1)
        assert s.max_file_size_mb == 1

    def test_page_render_dpi_one_is_valid(self):
        s = fresh_settings(page_render_dpi=1)
        assert s.page_render_dpi == 1

    def test_min_image_dpi_one_is_valid(self):
        s = fresh_settings(min_image_dpi=1)
        assert s.min_image_dpi == 1


# ---------------------------------------------------------------------------
# Log-level validation
# ---------------------------------------------------------------------------

class TestLogLevel:
    @pytest.mark.parametrize("level", ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"])
    def test_valid_log_levels_accepted(self, level: str):
        s = fresh_settings(log_level=level)
        assert s.log_level == level

    def test_log_level_normalised_to_uppercase(self):
        s = fresh_settings(log_level="debug")
        assert s.log_level == "DEBUG"

    def test_invalid_log_level_raises(self):
        with pytest.raises(ValidationError, match="log_level"):
            fresh_settings(log_level="VERBOSE")


# ---------------------------------------------------------------------------
# Environment variable override
# ---------------------------------------------------------------------------

class TestEnvOverride:
    def test_env_var_overrides_default(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("MAX_FILE_SIZE_MB", "100")
        s = Settings(_env_file=None)
        assert s.max_file_size_mb == 100

    def test_env_var_dpi_override(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("PAGE_RENDER_DPI", "72")
        s = Settings(_env_file=None)
        assert s.page_render_dpi == 72

    def test_env_var_use_gpu_true(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("USE_GPU", "true")
        s = Settings(_env_file=None)
        assert s.use_gpu is True


# ---------------------------------------------------------------------------
# Singleton / lru_cache behaviour
# ---------------------------------------------------------------------------

class TestGetSettings:
    def test_get_settings_returns_settings_instance(self):
        get_settings.cache_clear()
        s = get_settings()
        assert isinstance(s, Settings)

    def test_get_settings_is_singleton(self):
        get_settings.cache_clear()
        s1 = get_settings()
        s2 = get_settings()
        assert s1 is s2

    def test_cache_clear_allows_new_instance(self):
        get_settings.cache_clear()
        s1 = get_settings()
        get_settings.cache_clear()
        s2 = get_settings()
        # Both are valid Settings objects; after clearing the cache a new
        # object is created, so identity should differ.
        assert isinstance(s1, Settings)
        assert isinstance(s2, Settings)
        assert s1 is not s2
