"""
Redis wrapper with graceful degradation when Redis is unavailable.
"""
import logging
from typing import Any, Callable, Optional

import redis

logger = logging.getLogger(__name__)


class RedisClient:
    """Thread-safe Redis wrapper. Falls back gracefully if Redis is down."""

    def __init__(self, url: str) -> None:
        """
        Connect to Redis at *url*. Sets self.available = False on failure
        instead of raising so callers can treat Redis as optional.
        """
        self.available = False
        try:
            self._client = redis.Redis.from_url(url, decode_responses=True)
            self._client.ping()
            self.available = True
            logger.info("Redis connected: %s", url)
        except Exception as exc:
            logger.warning("Redis unavailable (%s) — caching disabled", exc)

    # ── primitives ────────────────────────────────────────────────────────────

    def get(self, key: str) -> Optional[str]:
        """Return the string value for *key*, or None if missing / unavailable."""
        if not self.available:
            return None
        try:
            return self._client.get(key)
        except Exception as exc:
            logger.warning("Redis GET error: %s", exc)
            return None

    def set(self, key: str, value: Any) -> bool:
        """Persist *value* under *key* with no expiry. Returns True on success."""
        if not self.available:
            return False
        try:
            self._client.set(key, value)
            return True
        except Exception as exc:
            logger.warning("Redis SET error: %s", exc)
            return False

    def setex(self, key: str, seconds: int, value: Any) -> bool:
        """Persist *value* under *key* with a TTL of *seconds*. Returns True on success."""
        if not self.available:
            return False
        try:
            self._client.setex(key, seconds, value)
            return True
        except Exception as exc:
            logger.warning("Redis SETEX error: %s", exc)
            return False

    def delete(self, key: str) -> bool:
        """Delete *key*. Returns True on success."""
        if not self.available:
            return False
        try:
            self._client.delete(key)
            return True
        except Exception as exc:
            logger.warning("Redis DELETE error: %s", exc)
            return False

    def ping(self) -> bool:
        """Return True if Redis responds to PING."""
        if not self.available:
            return False
        try:
            return self._client.ping()
        except Exception:
            return False

    # ── cache-aside helper ────────────────────────────────────────────────────

    def get_or_compute(
        self,
        key: str,
        compute_fn: Callable[[], Any],
        ttl: int,
    ) -> Any:
        """
        Return cached value for *key* if present; otherwise call *compute_fn*,
        store the result with *ttl* seconds expiry, and return it.
        Always returns the computed value even when Redis is unavailable.
        """
        cached = self.get(key)
        if cached is not None:
            return cached
        result = compute_fn()
        if result is not None:
            self.setex(key, ttl, result)
        return result
