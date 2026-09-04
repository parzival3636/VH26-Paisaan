"""
pipeline/redis_client.py

Producer Quota & Rate Limiter Manager.

Uses Redis fixed-window counter (`INCR` + `EXPIRE`) to check if a producer (identified by X-Source header)
is within its allowed quota.

If Redis is unreachable or not running, falls back seamlessly to an in-memory dictionary-based
fixed-window rate limiter, guaranteeing robust execution in all environments.
"""

import logging
import os
import time

try:
    import redis.asyncio as aioredis
    HAS_REDIS = True
except ImportError:
    HAS_REDIS = False

logger = logging.getLogger("pipeline.redis")

# Default Quota configuration: 100 requests per 10-second window per producer
DEFAULT_QUOTA_LIMIT = int(os.environ.get("PRODUCER_QUOTA_LIMIT", 100))
DEFAULT_QUOTA_WINDOW = int(os.environ.get("PRODUCER_QUOTA_WINDOW", 10))
REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379")

# Global Redis client instance
_redis_client = None
_redis_disabled = False

# In-memory fallback rate limiter storage: producer_id -> (window_start_timestamp, count)
_in_memory_quotas: dict[str, tuple[float, int]] = {}


async def get_redis_client():
    """Get or initialize the async Redis client instance."""
    global _redis_client, _redis_disabled
    if _redis_disabled or not HAS_REDIS:
        return None

    if _redis_client is None:
        try:
            client = aioredis.from_url(
                REDIS_URL,
                decode_responses=True,
                socket_connect_timeout=0.5,
                socket_timeout=0.5,
            )
            await client.ping()
            _redis_client = client
            logger.info("Connected to Redis at %s for producer quota tracking.", REDIS_URL)
        except Exception as exc:
            logger.warning(
                "Redis connection failed (%s). Falling back to in-memory producer quota tracking.",
                exc,
            )
            _redis_disabled = True
            return None

    return _redis_client


async def check_producer_quota(
    producer_id: str,
    limit: int = DEFAULT_QUOTA_LIMIT,
    window_seconds: int = DEFAULT_QUOTA_WINDOW,
) -> bool:
    """
    Check if a producer (X-Source) is within its allowed request quota.

    Args:
        producer_id: Name/ID of the sending producer service (e.g. 'checkout-service')
        limit: Max requests allowed per window
        window_seconds: Duration of the fixed window in seconds

    Returns:
        True if within quota (count <= limit), False if over quota.
    """
    if not producer_id:
        producer_id = "unknown"

    client = await get_redis_client()

    if client is not None:
        try:
            # Fixed-window key in Redis
            current_window = int(time.time() // window_seconds)
            key = f"quota:{producer_id}:{current_window}"

            # Increment request counter
            count = await client.incr(key)
            if count == 1:
                # Set expiration slightly longer than window duration
                await client.expire(key, window_seconds + 2)

            return count <= limit
        except Exception as exc:
            logger.warning("Error performing Redis quota check: %s. Using in-memory fallback.", exc)

    # --- In-memory fallback ---
    now = time.time()
    current_window_idx = int(now // window_seconds)

    if producer_id in _in_memory_quotas:
        last_window_idx, count = _in_memory_quotas[producer_id]
        if last_window_idx == current_window_idx:
            new_count = count + 1
            _in_memory_quotas[producer_id] = (last_window_idx, new_count)
            return new_count <= limit

    # New window for producer
    _in_memory_quotas[producer_id] = (current_window_idx, 1)
    return 1 <= limit
