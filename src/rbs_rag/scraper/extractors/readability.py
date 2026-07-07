"""Content extraction for web scraping - readability-based text extraction"""
from __future__ import annotations

from typing import Optional
from bs4 import BeautifulSoup


def extract_readable_content(html: str, base_url: str = "") -> str:
    """Extract readable article-style content from HTML."""
    soup = BeautifulSoup(html, "html.parser")

    for tag in soup(["script", "style", "nav", "footer", "header", "aside", "form", "noscript"]):
        tag.decompose()

    # Try common article containers
    for selector in ["article", "main", ".content", ".post", ".article", ".entry-content",
                     "#content", "#main", ".entry", ".post-content"]:
        container = soup.select_one(selector)
        if container:
            return _extract_text_from_element(container)

    return _extract_text_from_element(soup)


def _extract_text_from_element(element) -> str:
    """Extract text from a BeautifulSoup element, preserving structure."""
    parts = []
    for tag in element.find_all(["h1", "h2", "h3", "h4", "h5", "h6", "p", "li", "td",
                                 "th", "blockquote", "pre", "code", "div"]):
        text = tag.get_text(strip=True)
        if text:
            parts.append(text)
    return "\n".join(parts)