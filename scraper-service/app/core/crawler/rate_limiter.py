import asyncio
import time
import random
from typing import Dict
from urllib.parse import urlparse

class AsyncDomainRateLimiter:
    def __init__(self, default_delay: float = 1.0, max_backoff: float = 60.0):
        self.default_delay = default_delay
        self.max_backoff = max_backoff
        self._last_request_time: Dict[str, float] = {}
        self._backoff_attempts: Dict[str, int] = {}
        self._locks: Dict[str, asyncio.Lock] = {}
        self._retry_after_time: Dict[str, float] = {}

    def _get_domain(self, url: str) -> str:
        parsed = urlparse(url)
        return parsed.netloc or url

    def _get_lock(self, domain: str) -> asyncio.Lock:
        if domain not in self._locks:
            self._locks[domain] = asyncio.Lock()
        return self._locks[domain]

    async def acquire(self, url: str, crawl_delay: float = 0.0):
        domain = self._get_domain(url)
        lock = self._get_lock(domain)
        
        async with lock:
            now = time.time()
            
            # Check if we are blocked by Retry-After
            if domain in self._retry_after_time:
                wait_time = self._retry_after_time[domain] - now
                if wait_time > 0:
                    await asyncio.sleep(wait_time)
                else:
                    del self._retry_after_time[domain]
            
            # Calculate backoff if any
            attempts = self._backoff_attempts.get(domain, 0)
            backoff_delay = 0.0
            if attempts > 0:
                base_delay = min(self.max_backoff, (2 ** attempts))
                jitter = random.uniform(0, 0.1 * base_delay)
                backoff_delay = base_delay + jitter
                
            # Use max of crawl_delay, default_delay, and backoff
            delay = max(crawl_delay, self.default_delay, backoff_delay)
            
            last_time = self._last_request_time.get(domain, 0.0)
            elapsed = time.time() - last_time
            if elapsed < delay:
                await asyncio.sleep(delay - elapsed)
                
            self._last_request_time[domain] = time.time()

    def record_response(self, url: str, status_code: int, headers: dict):
        domain = self._get_domain(url)
        
        if status_code in (429, 403):
            # Record backoff
            self._backoff_attempts[domain] = self._backoff_attempts.get(domain, 0) + 1
            
            # Check for Retry-After header
            retry_after = headers.get("Retry-After", headers.get("retry-after"))
            if retry_after:
                try:
                    delay = float(retry_after)
                    self._retry_after_time[domain] = time.time() + delay
                except ValueError:
                    pass
        elif status_code < 400:
            # Reset backoff on success
            if domain in self._backoff_attempts:
                self._backoff_attempts[domain] = 0
