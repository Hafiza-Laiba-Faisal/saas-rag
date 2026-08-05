"""
ChangeStore — Persistent content hash storage for incremental crawling.

Tracks content hashes to detect which pages have changed since last crawl.
Redis-backed with JSON file fallback.
"""
from __future__ import annotations
import json
import os
from pathlib import Path
from typing import Optional


class ChangeStore:
    """
    Stores content hashes for change detection.
    """
    
    def __init__(self, domain: str, output_dir: Path, redis_client: Optional[any] = None):
        """
        Initialize ChangeStore.
        
        Args:
            domain: Domain name (for Redis key namespacing)
            output_dir: Crawl output directory (for JSON fallback)
            redis_client: Optional Redis client
        """
        self.domain = domain
        self.output_dir = Path(output_dir)
        self.redis_client = redis_client
        self.redis_enabled = redis_client is not None
        
        # Redis key
        self.redis_key = f"crawl:hashes:{domain}"
        
        # JSON fallback file
        self.json_file = self.output_dir / "content_hashes.json"
        
        # In-memory cache
        self._hashes: dict[str, str] = {}
        self._loaded = False
        
        # Load existing hashes
        self._load()
    
    def _load(self) -> None:
        """Load existing hashes from Redis or file."""
        if self._loaded:
            return
        
        if self.redis_enabled and self.redis_client:
            try:
                # Load from Redis
                hashes = self.redis_client.hgetall(self.redis_key)
                self._hashes = hashes if hashes else {}
                self._loaded = True
                return
            except Exception as e:
                print(f"Warning: Redis load failed, falling back to file: {e}")
        
        # Load from JSON file
        if self.json_file.exists():
            try:
                with open(self.json_file, "r", encoding="utf-8") as f:
                    self._hashes = json.load(f)
            except Exception as e:
                print(f"Warning: Could not load hashes from {self.json_file}: {e}")
                self._hashes = {}
        else:
            self._hashes = {}
        
        self._loaded = True
    
    def get(self, url: str) -> Optional[str]:
        """
        Get stored content hash for URL.
        
        Args:
            url: Page URL
            
        Returns:
            Content hash or None if not found
        """
        self._load()
        return self._hashes.get(url)
    
    def set(self, url: str, content_hash: str) -> None:
        """
        Store content hash for URL.
        
        Args:
            url: Page URL
            content_hash: SHA1 hash of cleaned content
        """
        self._load()
        self._hashes[url] = content_hash
        
        # Persist to Redis if available
        if self.redis_enabled and self.redis_client:
            try:
                self.redis_client.hset(self.redis_key, url, content_hash)
            except Exception as e:
                print(f"Warning: Redis set failed: {e}")
    
    def matching(self, url: str, content_hash: str) -> bool:
        """
        Check if stored hash matches current hash (page unchanged).
        
        Args:
            url: Page URL
            content_hash: Current content hash
            
        Returns:
            True if hashes match (page unchanged), False otherwise
        """
        stored_hash = self.get(url)
        if stored_hash is None:
            return False  # New page
        return stored_hash == content_hash
    
    def bulk_save(self) -> None:
        """Save all hashes to JSON file (fallback persistence)."""
        try:
            self.output_dir.mkdir(parents=True, exist_ok=True)
            with open(self.json_file, "w", encoding="utf-8") as f:
                json.dump(self._hashes, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"Warning: Could not save hashes to {self.json_file}: {e}")
    
    def bulk_load(self) -> dict[str, str]:
        """Load all hashes from storage."""
        self._load()
        return self._hashes.copy()
    
    def clear(self) -> None:
        """Clear all stored hashes."""
        self._hashes.clear()
        
        if self.redis_enabled and self.redis_client:
            try:
                self.redis_client.delete(self.redis_key)
            except Exception:
                pass
        
        if self.json_file.exists():
            try:
                self.json_file.unlink()
            except Exception:
                pass


def init_change_store(domain: str, output_dir: Path) -> ChangeStore:
    """
    Initialize ChangeStore with auto-detection of Redis.
    
    Args:
        domain: Domain name
        output_dir: Crawl output directory
        
    Returns:
        ChangeStore instance
    """
    redis_client = None
    redis_enabled = os.getenv("REDIS_ENABLED", "").lower() in ("1", "true", "yes")
    
    if redis_enabled:
        try:
            import redis as sync_redis
            host = os.getenv("REDIS_HOST", "redis")
            port = int(os.getenv("REDIS_PORT", "6379"))
            password = os.getenv("REDIS_PASSWORD", None)
            
            redis_client = sync_redis.Redis(
                host=host,
                port=port,
                password=password or None,
                decode_responses=True,
                socket_connect_timeout=2,
                socket_timeout=2
            )
            redis_client.ping()
        except Exception as e:
            print(f"Redis unavailable for ChangeStore, using file fallback: {e}")
            redis_client = None
    
    return ChangeStore(domain, output_dir, redis_client)
