"""
robots.txt parser and sitemap discovery.
"""
from __future__ import annotations
import logging
import threading
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser
import httpx

logger = logging.getLogger(__name__)


class RobotsHandler:
    """Parse robots.txt and check crawl permissions."""

    def __init__(self):
        # Cache maps: domain -> dict of {
        #   "crawl_delay": float or None,
        #   "sitemaps": list[str],
        #   "parser": RobotFileParser or None
        # }
        self._cache: dict[str, dict] = {}
        self._lock = threading.Lock()

    def _get_robots_data(self, url: str) -> dict:
        parsed = urlparse(url)
        domain = parsed.netloc.lower()

        with self._lock:
            if domain in self._cache:
                return self._cache[domain]

        base_url = f"{parsed.scheme}://{parsed.netloc}"
        robots_url = urljoin(base_url, "/robots.txt")

        data = {
            "crawl_delay": None,
            "sitemaps": [],
            "parser": None
        }

        try:
            with httpx.Client(timeout=10, follow_redirects=True) as client:
                resp = client.get(robots_url)
                if resp.status_code == 200:
                    content = resp.text
                    lines = content.splitlines()

                    rp = RobotFileParser()
                    rp.parse(lines)
                    data["parser"] = rp

                    # Parse Crawl-delay and Sitemap manually
                    current_agent = "*"
                    for line in lines:
                        if "#" in line:
                            line = line.split("#", 1)[0]
                        line = line.strip()
                        if not line:
                            continue

                        parts = line.split(":", 1)
                        if len(parts) == 2:
                            key = parts[0].strip().lower()
                            val = parts[1].strip()

                            if key == "user-agent":
                                current_agent = val.lower()
                            elif key == "crawl-delay":
                                try:
                                    delay = float(val)
                                    if current_agent in ["*", "scraperbot/1.0", "scraperbot"]:
                                        data["crawl_delay"] = delay
                                except ValueError:
                                    pass
                            elif key == "sitemap":
                                if val not in data["sitemaps"]:
                                    data["sitemaps"].append(val)

                    # Merge robot parser found sitemaps
                    if rp.site_maps():
                        for sm in rp.site_maps():
                            if sm not in data["sitemaps"]:
                                data["sitemaps"].append(sm)

                    # Merge robot parser found crawl delay
                    try:
                        rp_delay = rp.crawl_delay("*") or rp.crawl_delay("ScraperBot/1.0")
                        if rp_delay and not data["crawl_delay"]:
                            data["crawl_delay"] = float(rp_delay)
                    except Exception:
                        pass
        except Exception as e:
            logger.warning(f"Failed to fetch robots.txt from {robots_url}: {e}")

        with self._lock:
            self._cache[domain] = data
        return data

    def can_fetch(self, url: str, user_agent: str = "*") -> bool:
        """
        Check if URL is allowed by robots.txt.
        """
        data = self._get_robots_data(url)
        parser = data["parser"]
        if parser is None:
            return True
        return parser.can_fetch(user_agent, url)

    def get_crawl_delay(self, url: str, user_agent: str = "*") -> float | None:
        """
        Get Crawl-Delay for the domain.
        """
        data = self._get_robots_data(url)
        return data["crawl_delay"]

    def get_sitemaps(self, base_url: str) -> list[str]:
        """
        Extract sitemap URLs from robots.txt.
        """
        data = self._get_robots_data(base_url)
        return data["sitemaps"]

