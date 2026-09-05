import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config import settings


def test_resolve_output_dir_falls_back_when_target_is_not_writable(tmp_path, monkeypatch):
    restricted = tmp_path / "restricted"
    restricted.mkdir()
    restricted.chmod(0o555)

    monkeypatch.setenv("SCRAPER_OUTPUT_ROOT", str(restricted))
    import importlib
    importlib.reload(settings)

    out_dir = settings.resolve_output_dir("crawl_output", "example_site")

    assert out_dir.exists()
    assert out_dir.name == "example_site"
    assert out_dir != restricted / "example_site"
