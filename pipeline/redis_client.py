import logging
import os
import time

try:
    import redis.asyncio as aioredis
    HAS_REDIS = True
except ImportError:
    HAS_REDIS = False

logger = logging.getLogger("pipeline.redis")

DEFAULT_QUOTA_LIMIT = int(os.environ.get("PRODUCER_QUOTA_LIMIT", 100))
DEFAULT_QUOTA_WINDOW = int(os.environ.get("PRODUCER_QUOTA_WINDOW", 10))
REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379")

_redis_client = None
_in_memory_quotas: dict[str, tuple[float, int]] = {}


async def get_redis_client():
    global _redis_client
    if not HAS_REDIS:
        return None

    if _redis_client is None:
        try:
            client = aioredis.from_url(
                REDIS_URL,
                decode_responses=True,
                socket_connect_timeout=2.0,
                socket_timeout=2.0,
            )
            await client.ping()
            _redis_client = client
        except Exception:
            return None

    return _redis_client


async def check_producer_quota(
    producer_id: str,
    limit: int = DEFAULT_QUOTA_LIMIT,
    window_seconds: int = DEFAULT_QUOTA_WINDOW,
) -> bool:
    if not producer_id:
        producer_id = "unknown"

    client = await get_redis_client()

    if client is not None:
        try:
            current_window = int(time.time() // window_seconds)
            key = f"quota:{producer_id}:{current_window}"
            count = await client.incr(key)
            if count == 1:
                await client.expire(key, window_seconds + 2)
            return count <= limit
        except Exception:
            pass

    now = time.time()
    current_window_idx = int(now // window_seconds)

    if producer_id in _in_memory_quotas:
        last_window_idx, count = _in_memory_quotas[producer_id]
        if last_window_idx == current_window_idx:
            new_count = count + 1
            _in_memory_quotas[producer_id] = (last_window_idx, new_count)
            return new_count <= limit

    _in_memory_quotas[producer_id] = (current_window_idx, 1)
    return 1 <= limit


async def store_event_decision(event_record: dict) -> None:
    client = await get_redis_client()
    if client is None:
        return

    try:
        eid = event_record.get("event_id", "unknown")
        action = event_record.get("action", "unknown")
        score = event_record.get("final_score", 0.0)
        producer = event_record.get("producer", "unknown")
        etype = event_record.get("type", "unknown")

        key = f"event:{eid}"
        mapping = {
            "producer": producer,
            "type": etype,
            "score": str(score),
            "lane": action,
            "band": event_record.get("band", "Best-effort"),
        }
        await client.hset(key, mapping=mapping)
        await client.expire(key, 60)

        lane_key = f"lane:{action}"
        await client.lpush(lane_key, f"{eid}:{score}:{producer}")
        await client.ltrim(lane_key, 0, 99)
        await client.expire(lane_key, 60)
    except Exception:
        pass
