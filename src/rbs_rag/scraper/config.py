"""Scraper configuration"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass
class ScraperConfig:
    """Configuration for the web scraper."""
    request_timeout: int = 60
    max_concurrent_requests: int = 5
    max_download_size: int = 100 * 1024 * 1024  # 100MB
    user_agent: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
    follow_redirects: bool = True
    verify_ssl: bool = True
    default_max_pages: int = 50
    default_max_depth: int = 3
    respect_robots_txt: bool = True
    delay_between_requests: float = 1.0
    
    # Browser settings (for JavaScript-heavy sites)
    use_browser: bool = False
    browser_type: str = "chromium"
    browser_headless: bool = True


def get_config() -> ScraperConfig:
    """Get scraper configuration from environment variables."""
    return ScraperConfig(
        request_timeout=int(os.getenv("SCRAPER_TIMEOUT", "60")),
        max_concurrent_requests=int(os.getenv("SCRAPER_MAX_CONCURRENT", "5")),
        max_download_size=int(os.getenv("SCRAPER_MAX_DOWNLOAD", str(100 * 1024 * 1024))),
        user_agent=os.getenv("SCRAPER_USER_AGENT", ScraperConfig.user_agent),
        follow_redirects=os.getenv("SCRAPER_FOLLOW_REDIRECTS", "true").lower() == "true",
        verify_ssl=os.getenv("SCRAPER_VERIFY_SSL", "true").lower() == "true",
        default_max_pages=int(os.getenv("SCRAPER_MAX_PAGES", "50")),
        default_max_depth=int(os.getenv("SCRAPER_MAX_DEPTH", "3")),
        respect_robots_txt=os.getenv("SCRAPER_RESPECT_ROBOTS", "true").lower() == "true",
        delay_between_requests=float(os.getenv("SCRAPER_DELAY", "1.0")),
        use_browser=os.getenv("SCRAPER_USE_BROWSER", "false").lower() == "true",
        browser_type=os.getenv("SCRAPER_BROWSER_TYPE", "chromium"),
        browser_headless=os.getenv("SCRAPER_BROWSER_HEADLESS", "true").lower() == "true",
    )