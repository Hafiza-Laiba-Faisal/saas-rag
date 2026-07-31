"""
Redis-backed cache with TTL expiration.
Drop-in replacement for MemoryCache — same BaseCache interface.
"""

from __future__ import annotations
import json
import os
import logging
from typing import Any
from .base import BaseCache

log = logging.getLogger(__name__)


class RedisCache(BaseCache):

    def __init__(self, prefix: str = "scraper_cache:"):
        self._client = None
        self._enabled = False
        self._prefix = prefix
        self._init()

    def _init(self):
        host = os.getenv("REDIS_HOST", "redis")
        port = int(os.getenv("REDIS_PORT", "6379"))
        password = os.getenv("REDIS_PASSWORD", None)
        try:
            import redis as sync_redis
            self._client = sync_redis.Redis(
                host=host, port=port, password=password or None,
                decode_responses=True, socket_connect_timeout=2, socket_timeout=2,
                retry_on_timeout=False, health_check_interval=30,
            )
            self._client.ping()
            self._enabled = True
            log.info("RedisCache initialized at %s:%s", host, port)
        except Exception as e:
            self._enabled = False
            log.warning("RedisCache unavailable — fallback: %s", e)

    def _key(self, key: str) -> str:
        return f"{self._prefix}{key}"

    def _serialize(self, value: Any) -> str:
        if isinstance(value, (str, bytes)):
            return value if isinstance(value, str) else value.decode()
        return json.dumps(value, default=str)

    def _deserialize(self, raw: str | None) -> Any | None:
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return raw

    def get(self, key: str) -> Any | None:
        if not self._enabled or not self._client:
            return None
        try:
            raw = self._client.get(self._key(key))
            return self._deserialize(raw)
        except Exception as e:
            log.warning("RedisCache.get(%s) failed: %s", key, e)
            return None

    def set(self, key: str, value: Any, ttl_seconds: int = 300) -> None:
        if not self._enabled or not self._client:
            return
        try:
            raw = self._serialize(value)
            self._client.setex(self._key(key), ttl_seconds, raw)
        except Exception as e:
            log.warning("RedisCache.set(%s) failed: %s", key, e)

    def delete(self, key: str) -> None:
        if not self._enabled or not self._client:
            return
        try:
            self._client.delete(self._key(key))
        except Exception as e:
            log.warning("RedisCache.delete(%s) failed: %s", key, e)

    def clear(self) -> None:
        if not self._enabled or not self._client:
            return
        try:
            keys = self._client.keys(f"{self._prefix}*")
            if keys:
                self._client.delete(*keys)
        except Exception as e:
            log.warning("RedisCache.clear() failed: %s", e)

    def size(self) -> int:
        if not self._enabled or not self._client:
            return 0
        try:
            keys = self._client.keys(f"{self._prefix}*")
            return len(keys)
        except Exception:
            return 0
