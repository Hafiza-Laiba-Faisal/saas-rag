"""
Metadata extractor — pulls title, description, og:* tags from a BeautifulSoup tree.
Includes RichMetadataExtractor for production-grade hotel/hospitality sites.
"""

from __future__ import annotations
import json
import re
import hashlib
from typing import Any
from urllib.parse import urlparse
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



class RichMetadataExtractor(DefaultMetadataExtractor):
    """
    Enhanced metadata extractor with hotel/hospitality-specific fields:
    - JSON-LD structured data
    - Section detection from URL
    - Booking URL identification
    - Internal/external link split
    - Content hash computation
    """
    
    # Booking URL patterns (case-insensitive)
    BOOKING_PATTERNS = re.compile(
        r'/(booking|book-|reservations|prenota|verticalbooking|/book/|reserve)',
        re.IGNORECASE
    )
    
    # Section mapping from URL patterns
    SECTION_KEYWORDS = {
        'rooms': ['room', 'stanza', 'camera', 'zimmer', 'chambre', 'habitacion'],
        'dining': ['restaurant', 'dining', 'ristorante', 'cucina', 'food', 'bar'],
        'meetings': ['meeting', 'event', 'conference', 'riunioni', 'eventi'],
        'spa': ['spa', 'wellness', 'benessere'],
        'offers': ['offer', 'special', 'package', 'offerta', 'promozione'],
        'about': ['about', 'hotel', 'storia', 'history'],
        'contact': ['contact', 'location', 'contatti', 'info'],
        'gallery': ['gallery', 'photo', 'image', 'galleria', 'foto'],
    }
    
    def __init__(self):
        super().__init__()
        from core.crawler.url_normalizer import URLNormalizer
        self.normalizer = URLNormalizer()
    
    def extract(
        self,
        tree: Any,
        url: str = "",
        clean_text: str = "",
        parent_url: str = "",
        crawl_depth: int = 0,
        images: list[str] | None = None,
        pdfs: list[str] | None = None,
    ) -> dict:
        """
        Extract rich metadata from page.
        
        Args:
            tree: BeautifulSoup tree
            url: Page URL
            clean_text: Cleaned markdown/text content
            parent_url: Parent page URL
            crawl_depth: Depth in crawl tree
            images: List of image URLs
            pdfs: List of PDF URLs
            
        Returns:
            Rich metadata dictionary
        """
        # Start with base metadata
        meta = super().extract(tree, url)
        
        # Generate page ID
        normalized_url = self.normalizer.normalize(url)
        page_id = hashlib.sha1(normalized_url.encode("utf-8")).hexdigest()[:8]
        meta["page_id"] = page_id
        
        # Add crawl context
        meta["parent_url"] = parent_url
        meta["crawl_depth"] = crawl_depth
        
        # Language detection
        meta["language"] = self._detect_language(tree, url)
        
        # Section detection
        meta["section"] = self._detect_section(url, tree)
        
        # Content metrics
        if clean_text:
            meta["word_count"] = len(clean_text.split())
            meta["content_hash"] = hashlib.sha1(clean_text.encode("utf-8")).hexdigest()
        else:
            meta["word_count"] = 0
            meta["content_hash"] = ""
        
        # Images and PDFs
        meta["images"] = images or []
        meta["pdfs"] = pdfs or []
        
        # Extract all links and split internal/external
        internal_links, external_links = self._extract_links(tree, url)
        meta["internal_links"] = internal_links
        meta["external_links"] = external_links
        
        # Booking URLs
        meta["booking_urls"] = self._find_booking_urls(tree, url)
        
        # JSON-LD structured data
        meta["json_ld"] = self._extract_json_ld(tree)
        
        # Timestamp
        from datetime import datetime
        meta["last_crawled"] = datetime.utcnow().isoformat() + "Z"
        
        # Paths (filled by PageStore)
        meta["raw_html"] = f"raw_html/{page_id}.html"
        meta["clean_text"] = f"clean_text/{page_id}.md"
        
        return meta
    
    def _detect_language(self, tree: Any, url: str) -> str:
        """Detect page language from URL or HTML lang attribute."""
        # Check HTML lang attribute
        html_tag = tree.find("html")
        if html_tag and html_tag.get("lang"):
            lang = html_tag["lang"].split("-")[0].lower()
            return lang
        
        # Check URL path for language code
        path = urlparse(url).path.strip("/")
        if path:
            first_seg = path.split("/")[0].lower()
            known_langs = {"it", "fr", "de", "en", "es", "pt", "ru", "zh", "ja", "ko", "ar", "nl", "pl", "tr", "sv"}
            if first_seg in known_langs:
                return first_seg
        
        return "default"
    
    def _detect_section(self, url: str, tree: Any) -> str:
        """
        Detect content section from URL path or breadcrumbs.
        """
        path = urlparse(url).path.lower()
        
        # Check each section's keywords
        for section, keywords in self.SECTION_KEYWORDS.items():
            for keyword in keywords:
                if keyword in path:
                    return section
        
        # Try breadcrumbs
        breadcrumb = tree.find("nav", {"aria-label": re.compile("breadcrumb", re.I)})
        if not breadcrumb:
            breadcrumb = tree.find("ol", {"class": re.compile("breadcrumb", re.I)})
        
        if breadcrumb:
            crumbs = [a.get_text(strip=True).lower() for a in breadcrumb.find_all("a")]
            if len(crumbs) >= 2:
                # Second crumb often indicates section
                second_crumb = crumbs[1]
                for section, keywords in self.SECTION_KEYWORDS.items():
                    if any(kw in second_crumb for kw in keywords):
                        return section
        
        return "General"
    
    def _extract_links(self, tree: Any, base_url: str) -> tuple[list[str], list[str]]:
        """
        Extract and categorize all links as internal or external.
        """
        from urllib.parse import urljoin
        
        internal = []
        external = []
        seen = set()
        
        for a_tag in tree.find_all("a", href=True):
            href = a_tag["href"].strip()
            if not href or href.startswith(("#", "javascript:", "mailto:", "tel:")):
                continue
            
            absolute_url = urljoin(base_url, href)
            
            if absolute_url in seen:
                continue
            seen.add(absolute_url)
            
            if self.normalizer.is_same_domain(absolute_url, base_url):
                internal.append(absolute_url)
            else:
                external.append(absolute_url)
        
        return internal, external
    
    def _find_booking_urls(self, tree: Any, base_url: str) -> list[str]:
        """
        Find booking/reservation URLs using pattern matching.
        """
        from urllib.parse import urljoin
        
        booking_urls = []
        seen = set()
        
        for a_tag in tree.find_all("a", href=True):
            href = a_tag["href"].strip()
            if not href:
                continue
            
            absolute_url = urljoin(base_url, href)
            
            if absolute_url in seen:
                continue
            
            # Check if URL matches booking patterns
            if self.BOOKING_PATTERNS.search(absolute_url):
                booking_urls.append(absolute_url)
                seen.add(absolute_url)
        
        return booking_urls
    
    def _extract_json_ld(self, tree: Any) -> list[dict]:
        """
        Extract JSON-LD structured data.
        """
        json_ld_data = []
        
        for script in tree.find_all("script", type="application/ld+json"):
            try:
                data = json.loads(script.string)
                # Handle both single objects and arrays
                if isinstance(data, list):
                    json_ld_data.extend(data)
                else:
                    json_ld_data.append(data)
            except (json.JSONDecodeError, TypeError, AttributeError):
                continue
        
        return json_ld_data
