"""
URL scheduler with depth control, domain filtering, and robots.txt support.
"""
from __future__ import annotations
from typing import Optional
from .url_normalizer import URLNormalizer
from .robots_parser import RobotsHandler
from .queue import CrawlQueue


class URLScheduler:
    """
    Manages URL discovery and queue population.
    
    Features:
    - Depth limiting
    - Domain whitelisting/blacklisting
    - robots.txt compliance
    - URL normalization
    - Deduplication
    """

    def __init__(
        self,
        max_depth: int = 3,
        max_pages: int = 1000,
        allowed_domains: list[str] | None = None,
        blocked_domains: list[str] | None = None,
        respect_robots: bool = True,
        user_agent: str = "ScraperBot/1.0",
    ):
        self.max_depth = max_depth
        self.max_pages = max_pages
        self.allowed_domains = set(allowed_domains or [])
        self.blocked_domains = set(blocked_domains or [])
        self.respect_robots = respect_robots
        self.user_agent = user_agent

        self.normalizer = URLNormalizer()
        self.robots = RobotsHandler()
        self.queue = CrawlQueue(max_size=max_pages)

    def add_seed(self, url: str) -> bool:
        """Add initial seed URL."""
        normalized = self.normalizer.normalize(url)
        return self.queue.add(normalized, depth=0, priority=0)

    def add_discovered_urls(
        self, 
        urls: list[str], 
        parent_url: str, 
        current_depth: int
    ) -> int:
        """
        Add newly discovered URLs from a parent page.
        
        Args:
            urls: List of discovered URLs
            parent_url: URL of page where these were found
            current_depth: Depth of parent page
            
        Returns:
            Count of URLs added to queue
        """
        if current_depth >= self.max_depth:
            for url in urls:
                if url and url.startswith(("http://", "https://")):
                    self.queue.skip_max_depth()
            return 0

        next_depth = current_depth + 1
        added = 0

        for url in urls:
            if not url or not url.startswith(("http://", "https://")):
                continue

            # Normalize
            normalized = self.normalizer.normalize(
                url,
                remove_query_params=["utm_source", "utm_medium", "utm_campaign", "fbclid"]
            )

            # Domain filtering
            domain = self.normalizer.get_domain(normalized)
            
            if self.allowed_domains and domain not in self.allowed_domains:
                self.queue.skip_external()
                continue
            
            if domain in self.blocked_domains:
                self.queue.skip_external()
                continue

            # robots.txt check
            if self.respect_robots and not self.robots.can_fetch(normalized, self.user_agent):
                self.queue.skip_robots()
                continue

            # Add to queue
            if self.queue.add(normalized, depth=next_depth, parent_url=parent_url):
                added += 1
            else:
                self.queue.skip_duplicate()

        return added

    def get_next_url(self) -> Optional[tuple[str, int]]:
        """
        Get next URL to crawl.
        
        Returns:
            (url, depth) tuple or None if queue empty
        """
        item = self.queue.get()
        if item:
            return (item.url, item.depth)
        return None

    def mark_completed(self, url: str):
        """Mark URL as successfully crawled."""
        self.queue.mark_completed(url)

    def mark_failed(self, url: str, error: str = ""):
        """Mark URL as failed."""
        self.queue.mark_failed(url, error)

    def is_complete(self) -> bool:
        """Check if crawl is finished."""
        return self.queue.is_empty()

    def get_stats(self) -> dict:
        """Get crawl statistics."""
        return self.queue.stats()
