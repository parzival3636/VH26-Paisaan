"""
pipeline/dedup.py — Ingestion-Level Redundant & Duplicate Event Detection

Provides sliding time-window deduplication (Layer 0) to prevent duplicate processing
when upstream producers retry requests or send duplicate payloads.
"""

import time
import logging
from typing import Optional, Set
from pipeline.redis_client import redis_client

logger = logging.getLogger("pipeline.dedup")

DEDUP_TTL_SECONDS = 300  # 5-minute deduplication window


class Deduplicator:
    def __init__(self, ttl_seconds: int = DEDUP_TTL_SECONDS):
        self.ttl_seconds = ttl_seconds
        self._local_cache: dict[str, float] = {}

    def is_duplicate(self, event_id: str, idempotency_key: Optional[str] = None) -> bool:
        key = idempotency_key or event_id
        if not key:
            return False

        # Try Redis first if healthy
        if redis_client.is_healthy() and redis_client.client:
            try:
                redis_key = f"dedup:{key}"
                # SETNX sets key only if it does not exist
                was_set = redis_client.client.set(redis_key, "1", ex=self.ttl_seconds, nx=True)
                if not was_set:
                    logger.warning(f"Duplicate event detected via Redis: {key}")
                    return True
                return False
            except Exception as e:
                logger.warning(f"Redis dedup check failed: {e}. Falling back to local cache.")

        # Fallback to local in-memory sliding cache
        now = time.monotonic()
        self._cleanup_local(now)

        if key in self._local_cache:
            if now - self._local_cache[key] < self.ttl_seconds:
                logger.warning(f"Duplicate event detected via Local Cache: {key}")
                return True

        self._local_cache[key] = now
        return False

    def _cleanup_local(self, now: float):
        if len(self._local_cache) > 5000:
            expired = [k for k, v in self._local_cache.items() if now - v > self.ttl_seconds]
            for k in expired:
                del self._local_cache[k]


# Global singleton deduplicator
deduplicator = Deduplicator()
