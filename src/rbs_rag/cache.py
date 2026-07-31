from __future__ import annotations

import json
import logging
import os
import time
from typing import Any

log = logging.getLogger(__name__)


class RedisClient:
    """Redis client with connection pooling and graceful degradation.
    Supports both async (for request handlers) and sync (for background tasks).
    """

    def __init__(self):
        self._async_client = None
        self._sync_client = None
        self._enabled = False
        self._init()

    def _get_config(self):
        return {
            "host": os.getenv("RAG_REDIS_HOST", "redis"),
            "port": int(os.getenv("RAG_REDIS_PORT", "6379")),
            "password": os.getenv("RAG_REDIS_PASSWORD", None) or None,
        }

    def _init(self):
        cfg = self._get_config()
        try:
            import redis.asyncio as aioredis
            self._async_client = aioredis.Redis(
                host=cfg["host"], port=cfg["port"], password=cfg["password"],
                decode_responses=True, socket_connect_timeout=2, socket_timeout=2,
                retry_on_timeout=False, health_check_interval=30,
            )
            self._enabled = True
            log.info("Redis async client initialized at %s:%s", cfg["host"], cfg["port"])
        except Exception as e:
            self._enabled = False
            log.warning("Redis async client unavailable: %s", e)
        try:
            import redis as sync_redis
            self._sync_client = sync_redis.Redis(
                host=cfg["host"], port=cfg["port"], password=cfg["password"],
                decode_responses=True, socket_connect_timeout=2, socket_timeout=2,
                retry_on_timeout=False, health_check_interval=30,
            )
        except Exception as e:
            log.warning("Redis sync client unavailable: %s", e)

    @property
    def enabled(self) -> bool:
        return self._enabled

    # ── Async methods (for request handlers) ──────────────────────────────────

    async def aget(self, key: str) -> str | None:
        if not self._async_client:
            return None
        try:
            return await self._async_client.get(key)
        except Exception as e:
            log.warning("Redis aget(%s) failed: %s", key, e)
            return None

    async def aset(self, key: str, value: str, ttl: int | None = None) -> bool:
        if not self._async_client:
            return False
        try:
            if ttl is not None:
                await self._async_client.setex(key, ttl, value)
            else:
                await self._async_client.set(key, value)
            return True
        except Exception as e:
            log.warning("Redis aset(%s) failed: %s", key, e)
            return False

    async def adelete(self, key: str) -> bool:
        if not self._async_client:
            return False
        try:
            await self._async_client.delete(key)
            return True
        except Exception as e:
            log.warning("Redis adelete(%s) failed: %s", key, e)
            return False

    async def ahset(self, name: str, key: str, value: str) -> bool:
        if not self._async_client:
            return False
        try:
            await self._async_client.hset(name, key, value)
            return True
        except Exception as e:
            log.warning("Redis ahset(%s, %s) failed: %s", name, key, e)
            return False

    async def ahget(self, name: str, key: str) -> str | None:
        if not self._async_client:
            return None
        try:
            return await self._async_client.hget(name, key)
        except Exception as e:
            log.warning("Redis ahget(%s, %s) failed: %s", name, key, e)
            return None

    async def ahgetall(self, name: str) -> dict[str, str]:
        if not self._async_client:
            return {}
        try:
            return await self._async_client.hgetall(name)
        except Exception as e:
            log.warning("Redis ahgetall(%s) failed: %s", name, e)
            return {}

    async def ahdel(self, name: str, key: str) -> bool:
        if not self._async_client:
            return False
        try:
            await self._async_client.hdel(name, key)
            return True
        except Exception as e:
            log.warning("Redis ahdel(%s, %s) failed: %s", name, key, e)
            return False

    async def aexpire(self, name: str, ttl: int) -> bool:
        if not self._async_client:
            return False
        try:
            await self._async_client.expire(name, ttl)
            return True
        except Exception as e:
            log.warning("Redis aexpire(%s) failed: %s", name, e)
            return False

    async def aincr(self, key: str) -> int | None:
        if not self._async_client:
            return None
        try:
            return await self._async_client.incr(key)
        except Exception as e:
            log.warning("Redis aincr(%s) failed: %s", key, e)
            return None

    async def asliding_window(self, key: str, max_requests: int, window_seconds: int = 60) -> bool:
        if not self._async_client:
            return True
        try:
            now = time.time()
            pipe = self._async_client.pipeline()
            pipe.zremrangebyscore(key, 0, now - window_seconds)
            pipe.zcard(key)
            pipe.zadd(key, {str(now): now})
            pipe.expire(key, window_seconds + 1)
            results = await pipe.execute()
            count = results[1]
            return count < max_requests
        except Exception as e:
            log.warning("Redis asliding_window(%s) failed: %s", key, e)
            return True

    async def aget_json(self, key: str) -> Any | None:
        val = await self.aget(key)
        if val is None:
            return None
        try:
            return json.loads(val)
        except json.JSONDecodeError:
            return val

    async def aset_json(self, key: str, value: Any, ttl: int | None = None) -> bool:
        return await self.aset(key, json.dumps(value, default=str), ttl=ttl)

    # ── Sync methods (for background tasks) ───────────────────────────────────

    def sget(self, key: str) -> str | None:
        if not self._sync_client:
            return None
        try:
            return self._sync_client.get(key)
        except Exception as e:
            log.warning("Redis sget(%s) failed: %s", key, e)
            return None

    def sset(self, key: str, value: str, ttl: int | None = None) -> bool:
        if not self._sync_client:
            return False
        try:
            if ttl is not None:
                self._sync_client.setex(key, ttl, value)
            else:
                self._sync_client.set(key, value)
            return True
        except Exception as e:
            log.warning("Redis sset(%s) failed: %s", key, e)
            return False

    def shset(self, name: str, key: str, value: str) -> bool:
        if not self._sync_client:
            return False
        try:
            self._sync_client.hset(name, key, value)
            return True
        except Exception as e:
            log.warning("Redis shset(%s, %s) failed: %s", name, key, e)
            return False

    def shgetall(self, name: str) -> dict[str, str]:
        if not self._sync_client:
            return {}
        try:
            return self._sync_client.hgetall(name)
        except Exception as e:
            log.warning("Redis shgetall(%s) failed: %s", name, e)
            return {}

    def shdel(self, name: str, key: str) -> bool:
        if not self._sync_client:
            return False
        try:
            self._sync_client.hdel(name, key)
            return True
        except Exception as e:
            log.warning("Redis shdel(%s, %s) failed: %s", name, key, e)
            return False

    def shget(self, name: str, key: str) -> str | None:
        if not self._sync_client:
            return None
        try:
            return self._sync_client.hget(name, key)
        except Exception as e:
            log.warning("Redis shget(%s, %s) failed: %s", name, key, e)
            return None

    def sexpire(self, name: str, ttl: int) -> bool:
        if not self._sync_client:
            return False
        try:
            self._sync_client.expire(name, ttl)
            return True
        except Exception as e:
            log.warning("Redis sexpire(%s) failed: %s", name, e)
            return False

    def sget_json(self, key: str) -> Any | None:
        val = self.sget(key)
        if val is None:
            return None
        try:
            return json.loads(val)
        except json.JSONDecodeError:
            return val

    def sset_json(self, key: str, value: Any, ttl: int | None = None) -> bool:
        return self.sset(key, json.dumps(value, default=str), ttl=ttl)

    def sdelete(self, key: str) -> bool:
        if not self._sync_client:
            return False
        try:
            self._sync_client.delete(key)
            return True
        except Exception as e:
            log.warning("Redis sdelete(%s) failed: %s", key, e)
            return False

    # ── Lifecycle ──────────────────────────────────────────────────────────────

    async def close(self):
        if self._async_client:
            try:
                await self._async_client.close()
            except Exception:
                pass
        if self._sync_client:
            try:
                self._sync_client.close()
            except Exception:
                pass


redis_client = RedisClient()
