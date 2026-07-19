from __future__ import annotations

from .base import BaseDetector

_WP_HTML_MARKERS = [
    "wp-content",
    "wp-json",
    "wp-block-library",
    'name="generator" content="WordPress',
    "wp-emoji-release",
    "/wp-includes/",
]

_WP_URL_MARKERS = ["/wp-", "?p=", "/?page_id="]


class WordPressDetector(BaseDetector):
    name = "wordpress"

    def detect(self, html: str, url: str = "") -> bool:
        lower = html.lower()
        for m in _WP_HTML_MARKERS:
            if m.lower() in lower:
                return True
        url_lower = url.lower()
        for m in _WP_URL_MARKERS:
            if m in url_lower:
                return True
        return False
