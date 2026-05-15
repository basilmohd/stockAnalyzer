"""
Redis wrapper with graceful degradation when Redis is unavailable.
"""
import json
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
            self._client = redis.Redis.from_url(
                url, decode_responses=True, socket_connect_timeout=2
            )
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

    # ── Chat history management ───────────────────────────────────────────────

    def get_chat_history(self, user_id: str, max_messages: int = 10) -> list[dict]:
        """
        Retrieve conversation history for a user as list of {'role': str, 'content': str} dicts.
        Returns empty list if unavailable or not found.
        """
        if not self.available:
            return []
        try:
            import config
            key = f"chat:{user_id}:messages"
            data = self._client.get(key)
            if data is None:
                return []
            messages = json.loads(data)
            # Return last max_messages items in chronological order
            return messages[-max_messages:] if isinstance(messages, list) else []
        except Exception as exc:
            logger.warning("Redis get_chat_history error: %s", exc)
            return []

    def append_chat_message(
        self, user_id: str, role: str, content: str
    ) -> bool:
        """
        Append a message to user's conversation history in Redis.
        Keeps only the last CHAT_HISTORY_MAX_MESSAGES items.
        Resets TTL to CHAT_HISTORY_TTL on each append (sliding window).
        Returns True on success, False on error or unavailable.
        """
        if not self.available:
            return False
        try:
            import config
            key = f"chat:{user_id}:messages"
            
            # Get existing history
            data = self._client.get(key)
            messages = json.loads(data) if data else []
            
            # Append new message
            messages.append({"role": role, "content": content})
            
            # Keep only last N messages
            max_len = config.CHAT_HISTORY_MAX_MESSAGES
            messages = messages[-max_len:]
            
            # Store back with TTL
            ttl = config.CHAT_HISTORY_TTL
            self._client.setex(key, ttl, json.dumps(messages))
            return True
        except Exception as exc:
            logger.warning("Redis append_chat_message error: %s", exc)
            return False

    def get_daily_chat_count(self, user_id: str) -> int:
        """
        Get and increment the daily chat query count for a user.
        Returns current count (after incrementing).
        Counter auto-expires after 24 hours.
        """
        if not self.available:
            return 0
        try:
            import config
            key = f"chat:{user_id}:daily_count"
            
            # Increment counter
            count = self._client.incr(key)
            
            # Set expiry if this is the first increment
            if count == 1:
                ttl = config.CHAT_HISTORY_TTL  # 24 hours
                self._client.expire(key, ttl)
            
            return count
        except Exception as exc:
            logger.warning("Redis get_daily_chat_count error: %s", exc)
            return 0

    def reset_daily_chat_count(self, user_id: str) -> bool:
        """Delete the daily chat count for a user (called at midnight reset)."""
        if not self.available:
            return False
        try:
            key = f"chat:{user_id}:daily_count"
            self._client.delete(key)
            return True
        except Exception as exc:
            logger.warning("Redis reset_daily_chat_count error: %s", exc)
            return False

