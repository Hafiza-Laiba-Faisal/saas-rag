"""
Links extractor — pulls all anchor hrefs from a BeautifulSoup tree.
"""

from __future__ import annotations
from typing import Any
from urllib.parse import urljoin, urlparse
from .base import LinksExtractor


class DefaultLinksExtractor(LinksExtractor):

    def extract(self, tree: Any, url: str = "") -> dict:
        links = []
        seen  = set()

        for a in tree.find_all("a", href=True):
            href = a["href"].strip()
            if not href or href.startswith(("javascript:", "mailto:", "tel:")):
                continue
            abs_url = urljoin(url, href)
            if abs_url in seen:
                continue
            seen.add(abs_url)
            parsed = urlparse(abs_url)
            links.append({
                "url":    abs_url,
                "text":   a.get_text(strip=True)[:200],
                "domain": parsed.netloc,
                "is_pdf": abs_url.lower().endswith(".pdf"),
            })

        return {"links": links, "count": len(links)}
