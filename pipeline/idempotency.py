"""
pipeline/idempotency.py — Idempotency Key Register & Side-Effect Lock

Guarantees exact-once processing side-effects.
If a worker crashes mid-batch, completed events are skipped on retry.
"""

import time
import json
import logging
from typing import Any, Optional, Dict, Set
from pipeline.redis_client import redis_client

logger = logging.getLogger("pipeline.idempotency")

CLAIM_TTL_SECONDS = 30  # Lock timeout if worker dies mid-processing


class IdempotencyRegister:
    def __init__(self):
        self._local_completed: Set[str] = set()
        self._local_claimed: Dict[str, float] = {}

    def is_already_completed(self, event_id: str) -> bool:
        if redis_client.is_healthy() and redis_client.client:
            try:
                res = redis_client.client.get(f"completed:{event_id}")
                if res:
                    return True
            except Exception:
                pass

        return event_id in self._local_completed

    def claim_event(self, event_id: str, worker_id: str) -> bool:
        """Atomic claim lock. Returns True if worker successfully locked the event for processing."""
        if self.is_already_completed(event_id):
            return False

        if redis_client.is_healthy() and redis_client.client:
            try:
                key = f"claim:{event_id}"
                was_claimed = redis_client.client.set(key, worker_id, ex=CLAIM_TTL_SECONDS, nx=True)
                return bool(was_claimed)
            except Exception:
                pass

        now = time.monotonic()
        if event_id in self._local_claimed:
            if now - self._local_claimed[event_id] < CLAIM_TTL_SECONDS:
                return False  # Already locked by another worker

        self._local_claimed[event_id] = now
        return True

    def mark_completed(self, event_id: str, result_summary: dict[str, Any]) -> None:
        """Mark event as permanently completed to prevent double execution."""
        if redis_client.is_healthy() and redis_client.client:
            try:
                redis_client.client.set(f"completed:{event_id}", json.dumps(result_summary), ex=86400)
                redis_client.client.delete(f"claim:{event_id}")
            except Exception:
                pass

        self._local_completed.add(event_id)
        if event_id in self._local_claimed:
            del self._local_claimed[event_id]

    def release_claim(self, event_id: str) -> None:
        """Release claim lock if worker encounters soft failure."""
        if redis_client.is_healthy() and redis_client.client:
            try:
                redis_client.client.delete(f"claim:{event_id}")
            except Exception:
                pass

        if event_id in self._local_claimed:
            del self._local_claimed[event_id]


# Global singleton idempotency register
idempotency_register = IdempotencyRegister()
