import logging
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRAPER_APP = ROOT / "scraper-service" / "app"
if str(SCRAPER_APP) not in sys.path:
    sys.path.insert(0, str(SCRAPER_APP))

from core.formatter.markdown_formatter import MarkdownFormatter
import main as scraper_main


def test_markdown_formatter_adds_spacing_for_headings_and_sections():
    formatter = MarkdownFormatter()
    page = formatter.format_page(
        {"title": "Example Page", "followers": 1234, "about": "A short intro"},
        [{"caption": "First post", "likes": 2, "comments": 1}],
    )

    assert page.startswith("# Example Page\n\n")
    assert "**Followers:** 1,234" in page
    assert "A short intro" in page
    assert page.count("\n\n") >= 2


def test_build_logging_handlers_falls_back_when_log_file_is_unwritable(tmp_path):
    handlers = scraper_main.build_logging_handlers(str(tmp_path / "missing" / "scraper.log"))

    assert handlers
    assert any(isinstance(handler, logging.StreamHandler) for handler in handlers)
