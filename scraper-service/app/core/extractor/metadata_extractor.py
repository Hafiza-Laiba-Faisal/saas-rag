"""
Metadata extractor — pulls title, description, og:* tags from a BeautifulSoup tree.
"""

from __future__ import annotations
from typing import Any
from .base import MetadataExtractor


class DefaultMetadataExtractor(MetadataExtractor):

    def extract(self, tree: Any, url: str = "") -> dict:
        meta: dict = {"url": url}

        # Title
        title_tag = tree.find("title")
        meta["title"] = title_tag.get_text(strip=True) if title_tag else ""

        # Open Graph
        for tag in tree.find_all("meta"):
            prop    = tag.get("property", "") or tag.get("name", "")
            content = tag.get("content", "")
            if not prop or not content:
                continue
            if prop == "og:title":
                meta["og_title"] = content
            elif prop == "og:description":
                meta["og_description"] = content
            elif prop == "og:image":
                meta["og_image"] = content
            elif prop == "og:url":
                meta["og_url"] = content
            elif prop == "og:type":
                meta["og_type"] = content
            elif prop in ("description", "og:site_name"):
                meta[prop.replace(":", "_")] = content

        # Canonical
        canonical = tree.find("link", rel="canonical")
        if canonical:
            meta["canonical"] = canonical.get("href", "")

        return meta
