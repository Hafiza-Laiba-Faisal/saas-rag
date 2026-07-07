"""
Sitemap XML parser for extracting seed/crawled URLs, supporting sitemap indexes,
image/news sitemaps, and namespace-agnostic element parsing.
"""
from __future__ import annotations
import logging
import xml.etree.ElementTree as ET
from urllib.parse import urlparse
import httpx

logger = logging.getLogger(__name__)


class SitemapParser:
    """
    Lightweight XML parser to parse standard sitemaps, sitemap indexes,
    and specialized (image, news) sitemaps.
    """

    def __init__(self, timeout: int = 15, max_depth: int = 5):
        self.timeout = timeout
        self.max_depth = max_depth
        self.visited_sitemaps: set[str] = set()

    def parse(self, sitemap_url: str) -> list[str]:
        """
        Recursively parses a sitemap URL, following nested sitemap indexes.
        Returns a flat list of unique page/media URLs.
        """
        self.visited_sitemaps.clear()
        return self._parse_recursive(sitemap_url, depth=0)

    def _parse_recursive(self, url: str, depth: int) -> list[str]:
        if depth > self.max_depth or url in self.visited_sitemaps:
            return []

        self.visited_sitemaps.add(url)
        logger.info(f"Parsing sitemap: {url}")

        try:
            with httpx.Client(timeout=self.timeout, follow_redirects=True) as client:
                resp = client.get(url)
                if resp.status_code != 200:
                    logger.warning(f"Failed to fetch sitemap {url}: status {resp.status_code}")
                    return []
                xml_content = resp.text
        except Exception as e:
            logger.error(f"Error fetching sitemap {url}: {e}")
            return []

        page_urls, child_sitemaps = self._parse_xml(xml_content)

        all_urls = list(page_urls)
        for child_url in child_sitemaps:
            all_urls.extend(self._parse_recursive(child_url, depth + 1))

        # Deduplicate preserving order
        seen = set()
        unique_urls = []
        for u in all_urls:
            if u not in seen:
                seen.add(u)
                unique_urls.append(u)
        return unique_urls

    def _parse_xml(self, xml_content: str) -> tuple[list[str], list[str]]:
        page_urls = []
        sitemap_urls = []
        try:
            # Parse XML with support for encoding headers
            root = ET.fromstring(xml_content.encode("utf-8", errors="ignore"))
        except Exception as e:
            logger.error(f"XML parsing failed: {e}")
            return page_urls, sitemap_urls

        root_tag = root.tag.split("}")[-1]

        if root_tag == "sitemapindex":
            for sitemap_node in root:
                sitemap_tag = sitemap_node.tag.split("}")[-1]
                if sitemap_tag == "sitemap":
                    for child in sitemap_node:
                        child_tag = child.tag.split("}")[-1]
                        if child_tag == "loc" and child.text:
                            sitemap_urls.append(child.text.strip())
        elif root_tag == "urlset":
            for url_node in root:
                url_tag = url_node.tag.split("}")[-1]
                if url_tag == "url":
                    for child in url_node:
                        child_tag = child.tag.split("}")[-1]
                        if child_tag == "loc" and child.text:
                            page_urls.append(child.text.strip())
                        elif child_tag == "image":
                            for img_child in child:
                                img_tag = img_child.tag.split("}")[-1]
                                if img_tag == "loc" and img_child.text:
                                    page_urls.append(img_child.text.strip())
                        elif child_tag == "news":
                            for news_child in child:
                                news_tag = news_child.tag.split("}")[-1]
                                if news_tag == "loc" and news_child.text:
                                    page_urls.append(news_child.text.strip())
        else:
            # Fallback namespace-agnostic search for loc elements
            for elem in root.iter():
                tag = elem.tag.split("}")[-1]
                if tag == "loc" and elem.text:
                    val = elem.text.strip()
                    if val.endswith(".xml") or val.endswith(".xml.gz") or "sitemap" in val.lower():
                        sitemap_urls.append(val)
                    else:
                        page_urls.append(val)

        return page_urls, sitemap_urls
