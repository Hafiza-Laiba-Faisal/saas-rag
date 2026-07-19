from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)


class WordPressExtractor:
    """Extract content from WordPress sites via REST API or HTML fallback."""

    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")

    async def extract_posts_via_api(self, max_pages: int = 10, timeout: int = 30) -> list[dict]:
        """Fetch posts from WP REST API with pagination & embedded media."""
        posts = []
        for page in range(1, max_pages + 1):
            url = (
                f"{self.base_url}/wp-json/wp/v2/posts"
                f"?per_page=100&page={page}&_embed=true"
            )
            try:
                async with httpx.AsyncClient(timeout=timeout) as client:
                    resp = await client.get(url)
                if resp.status_code != 200:
                    break
                data = resp.json()
                if not data:
                    break
            except Exception as e:
                logger.warning("WP API posts page %d failed: %s", page, e)
                break

            for post in data:
                embedded = post.get("_embedded", {})
                featured = (embedded.get("wp:featuredmedia") or [{}])[0]
                categories = []
                terms = embedded.get("wp:term", [])
                if terms:
                    for term_list in terms:
                        categories = [t.get("name", "") for t in term_list]
                        break
                posts.append({
                    "id": post["id"],
                    "title": post.get("title", {}).get("rendered", ""),
                    "content": post.get("content", {}).get("rendered", ""),
                    "excerpt": post.get("excerpt", {}).get("rendered", ""),
                    "slug": post.get("slug", ""),
                    "date": post.get("date", ""),
                    "link": post.get("link", ""),
                    "image": featured.get("source_url", ""),
                    "categories": categories,
                })
        return posts

    async def extract_pages_via_api(self, timeout: int = 30) -> list[dict]:
        """Fetch pages from WP REST API."""
        url = f"{self.base_url}/wp-json/wp/v2/pages?per_page=100&_embed=true"
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.get(url)
            if resp.status_code != 200:
                return []
            data = resp.json()
        except Exception as e:
            logger.warning("WP API pages failed: %s", e)
            return []

        pages = []
        for page in data:
            embedded = page.get("_embedded", {})
            featured = (embedded.get("wp:featuredmedia") or [{}])[0]
            pages.append({
                "id": page["id"],
                "title": page.get("title", {}).get("rendered", ""),
                "content": page.get("content", {}).get("rendered", ""),
                "slug": page.get("slug", ""),
                "link": page.get("link", ""),
                "image": featured.get("source_url", ""),
            })
        return pages

    async def extract_media_via_api(self, mime_type: str = "", timeout: int = 30) -> list[dict]:
        """Fetch media library from WP REST API. Filter by mime_type for PDFs."""
        url = f"{self.base_url}/wp-json/wp/v2/media?per_page=100"
        if mime_type:
            url += f"&mime_type={mime_type}"
        media = []
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.get(url)
            if resp.status_code != 200:
                return []
            data = resp.json()
        except Exception as e:
            logger.warning("WP API media failed: %s", e)
            return []

        for item in data:
            media.append({
                "id": item["id"],
                "title": item.get("title", {}).get("rendered", ""),
                "url": item.get("source_url", ""),
                "mime": item.get("mime_type", ""),
                "slug": item.get("slug", ""),
                "alt": item.get("alt_text", ""),
            })
        return media

    def extract_posts_from_html(self, tree: BeautifulSoup) -> list[dict]:
        """Fallback: extract posts from HTML using common WP theme selectors."""
        posts = []
        candidates = tree.find_all("article")
        if not candidates:
            candidates = tree.select(".post")
        if not candidates:
            candidates = tree.select(".entry-content")

        for article in candidates:
            title_tag = article.find("h1") or article.find("h2") or article.find("h3")
            link_tag = title_tag.find("a") if title_tag else None
            excerpt_tag = (
                article.find(class_="excerpt")
                or article.find(class_="entry-summary")
                or article.find("p")
            )
            posts.append({
                "title": title_tag.get_text(strip=True) if title_tag else "",
                "url": (
                    urljoin(self.base_url, link_tag["href"])
                    if link_tag and link_tag.get("href")
                    else ""
                ),
                "excerpt": (
                    excerpt_tag.get_text(strip=True)[:500] if excerpt_tag else ""
                ),
            })
        return posts
