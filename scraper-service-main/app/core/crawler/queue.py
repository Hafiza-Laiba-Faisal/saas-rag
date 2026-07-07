"""
Thread-safe in-memory crawl queue with priority support.
Future: Replace with Redis for distributed crawling.
"""
from __future__ import annotations
import threading
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional
import heapq


class URLStatus(str, Enum):
    """URL processing status."""
    PENDING = "pending"
    FETCHING = "fetching"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass(order=True)
class QueueItem:
    """Single URL in crawl queue with priority."""
    priority: int = field(compare=True)  # Lower number = higher priority
    url: str = field(compare=False)
    depth: int = field(default=0, compare=False)
    parent_url: Optional[str] = field(default=None, compare=False)
    status: URLStatus = field(default=URLStatus.PENDING, compare=False)
    added_at: datetime = field(default_factory=datetime.utcnow, compare=False)
    attempts: int = field(default=0, compare=False)


class CrawlQueue:
    """
    Thread-safe priority queue for crawler.
    
    Features:
    - Priority-based fetching
    - Deduplication (seen URLs)
    - Status tracking
    - Thread-safe operations
    """

    def __init__(self, max_size: int = 10000):
        self._lock = threading.RLock()
        self._heap: list[QueueItem] = []
        self._seen: set[str] = set()  # All URLs ever seen
        self._in_progress: set[str] = set()  # Currently being fetched
        self._completed: set[str] = set()
        self._failed: dict[str, str] = {}  # url -> error message
        self.max_size = max_size
        self.duplicates_skipped: int = 0
        self.external_skipped: int = 0
        self.robots_skipped: int = 0
        self.max_depth_reached: int = 0

    def add(self, url: str, depth: int = 0, parent_url: str | None = None, 
            priority: int = 10) -> bool:
        """
        Add URL to queue if not seen before.
        
        Args:
            url: Normalized URL
            depth: Crawl depth from seed
            parent_url: Parent page URL
            priority: Lower = higher priority (0-100)
            
        Returns:
            True if added, False if duplicate or queue full
        """
        with self._lock:
            if url in self._seen:
                return False
            
            if len(self._heap) >= self.max_size:
                return False
            
            self._seen.add(url)
            item = QueueItem(
                priority=priority,
                url=url,
                depth=depth,
                parent_url=parent_url,
            )
            heapq.heappush(self._heap, item)
            return True

    def add_bulk(self, urls: list[str], depth: int = 0, parent_url: str | None = None) -> int:
        """Add multiple URLs. Returns count of newly added."""
        added = 0
        for url in urls:
            if self.add(url, depth=depth, parent_url=parent_url):
                added += 1
        return added

    def get(self) -> QueueItem | None:
        """Get highest priority pending URL."""
        with self._lock:
            while self._heap:
                item = heapq.heappop(self._heap)
                if item.url not in self._in_progress and item.url not in self._completed:
                    self._in_progress.add(item.url)
                    return item
            return None

    def mark_completed(self, url: str):
        """Mark URL as successfully processed."""
        with self._lock:
            self._in_progress.discard(url)
            self._completed.add(url)

    def mark_failed(self, url: str, error: str = ""):
        """Mark URL as failed."""
        with self._lock:
            self._in_progress.discard(url)
            self._failed[url] = error

    def is_empty(self) -> bool:
        """Check if queue has pending items."""
        with self._lock:
            return len(self._heap) == 0 and len(self._in_progress) == 0

    def skip_duplicate(self):
        with self._lock:
            self.duplicates_skipped += 1

    def skip_external(self):
        with self._lock:
            self.external_skipped += 1

    def skip_robots(self):
        with self._lock:
            self.robots_skipped += 1

    def skip_max_depth(self):
        with self._lock:
            self.max_depth_reached += 1

    def stats(self) -> dict:
        """Get queue statistics."""
        with self._lock:
            return {
                "pending": len(self._heap),
                "in_progress": len(self._in_progress),
                "completed": len(self._completed),
                "failed": len(self._failed),
                "total_seen": len(self._seen),
                "duplicates_skipped": self.duplicates_skipped,
                "external_skipped": self.external_skipped,
                "robots_skipped": self.robots_skipped,
                "max_depth_reached": self.max_depth_reached,
            }
