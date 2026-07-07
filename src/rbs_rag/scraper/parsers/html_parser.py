"""HTML content parser for web scraping"""
from __future__ import annotations

from typing import Optional
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup


class ParsedContent:
    """Parsed HTML content."""
    def __init__(
        self,
        title: str = "",
        text: str = "",
        html: str = "",
        links: list[str] = None,
        images: list[str] = None,
        metadata: dict = None,
    ):
        self.title = title
        self.text = text
        self.html = html
        self.links = links or []
        self.images = images or []
        self.metadata = metadata or {}


class HTMLParser:
    """Parse HTML content and extract text, links, and metadata."""

    def __init__(self):
        pass

    def parse(self, html_content: str, base_url: str = "") -> ParsedContent:
        """Parse HTML content."""
        soup = BeautifulSoup(html_content, "html.parser")
        
        # Remove script and style elements
        for script in soup(["script", "style", "nav", "footer", "header", "aside"]):
            script.decompose()
        
        title = self._extract_title(soup)
        text = self._extract_text(soup)
        links = self._extract_links(soup, base_url)
        images = self._extract_images(soup, base_url)
        metadata = self._extract_metadata(soup)
        
        return ParsedContent(
            title=title,
            text=text,
            html=str(soup),
            links=links,
            images=images,
            metadata=metadata,
        )

    def _extract_title(self, soup: BeautifulSoup) -> str:
        title = soup.title.string if soup.title else ""
        return title.strip() if title else ""

    def _extract_text(self, soup: BeautifulSoup) -> str:
        """Extract readable text from HTML."""
        text_parts = []
        
        # Extract main content first
        for tag in soup.find_all(["h1", "h2", "h3", "h4", "h5", "h6", "p", "li", "td", "th", "blockquote", "pre", "code"]):
            content = tag.get_text(strip=True)
            if content:
                text_parts.append(content)
        
        return "\n".join(text_parts)

    def _extract_links(self, soup: BeautifulSoup, base_url: str) -> list[str]:
        """Extract and normalize links from HTML."""
        links = []
        for a in soup.find_all("a", href=True):
            href = a["href"].strip()
            if base_url:
                href = urljoin(base_url, href)
            links.append(href)
        return links

    def _extract_images(self, soup: BeautifulSoup, base_url: str) -> list[str]:
        """Extract image URLs from HTML."""
        images = []
        for img in soup.find_all("img", src=True):
            src = img["src"].strip()
            if base_url:
                src = urljoin(base_url, src)
            images.append(src)
        return images

    def _extract_metadata(self, soup: BeautifulSoup) -> dict:
        """Extract metadata from HTML."""
        metadata = {}
        
        # Meta tags
        for meta in soup.find_all("meta"):
            name = meta.get("name", meta.get("property", "")).lower()
            content = meta.get("content", "")
            if name and content:
                metadata[name] = content
        
        # Open Graph
        for meta in soup.find_all("meta", property=True):
            prop = meta.get("property", "").lower()
            content = meta.get("content", "")
            if prop and content:
                metadata[prop] = content
        
        return metadata