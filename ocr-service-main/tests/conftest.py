"""Shared pytest fixtures for the OCR service test suite."""
import io
import pytest
from unittest.mock import MagicMock
from fastapi.testclient import TestClient
from config.settings import Settings
from schemas.ocr import OCRRegion, ExtractedEntities


@pytest.fixture
def settings_fixture():
    """Settings with test-safe values (small file size, no GPU)."""
    return Settings(
        _env_file=None,
        max_file_size_mb=10,
        min_text_chars_threshold=20,
        use_gpu=False,
        log_level="ERROR",  # suppress logs in tests
    )


@pytest.fixture
def mock_ocr_engine():
    """MagicMock OCREngine returning 2 fake OCRRegions."""
    engine = MagicMock()
    engine.run.return_value = [
        OCRRegion(text="Hello World", confidence=0.99, bounding_box=[0, 0, 100, 20]),
        OCRRegion(text="Test OCR text", confidence=0.95, bounding_box=[0, 25, 200, 45]),
    ]
    return engine


@pytest.fixture
def sample_image_bytes():
    """Minimal synthetic PNG image bytes."""
    from PIL import Image
    img = Image.new("RGB", (100, 100), color=(255, 255, 255))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


@pytest.fixture
def sample_pdf_bytes():
    """Minimal single-page digital PDF bytes."""
    import fitz
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((50, 50), "Sample PDF text for testing OCR service.")
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


@pytest.fixture
def test_client(mock_ocr_engine, settings_fixture):
    """FastAPI TestClient with mocked OCREngine injected, lifespan bypassed."""
    from contextlib import asynccontextmanager
    import main as main_module
    from api.dependencies import get_ocr_engine, get_settings

    # Patch the lifespan to avoid loading the real OCREngine
    @asynccontextmanager
    async def _noop_lifespan(app):
        app.state.ocr_engine = mock_ocr_engine
        yield

    main_module.app.router.lifespan_context = _noop_lifespan

    app = main_module.app
    app.state.ocr_engine = mock_ocr_engine
    app.dependency_overrides[get_ocr_engine] = lambda: mock_ocr_engine
    app.dependency_overrides[get_settings] = lambda: settings_fixture

    with TestClient(app, raise_server_exceptions=False) as client:
        yield client

    app.dependency_overrides.clear()
