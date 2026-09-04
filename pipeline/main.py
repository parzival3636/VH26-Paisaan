import asyncio
import logging
import time
from collections import deque
from typing import Any, Literal, Optional

import uvicorn
from fastapi import FastAPI, Header, Response, status, HTTPException
from pydantic import BaseModel, Field, ConfigDict

from pipeline.redis_client import check_producer_quota, store_event_decision
from pipeline.scoring import SystemState, score_event, ScoringWeights, Thresholds

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [PIPELINE] %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("pipeline")

app = FastAPI(
    title="Intelligent Data Pipeline — Ingestion Gateway",
    version="0.2.0",
)

EVENT_TYPES = Literal["order", "payment", "inventory", "click", "log"]


class Event(BaseModel):
    model_config = ConfigDict(extra="allow")

    event_id: str = Field(...)
    event_type: Optional[EVENT_TYPES] = Field(None)
    type: Optional[str] = Field(None)
    timestamp: float = Field(default_factory=time.time)
    payload: Optional[dict[str, Any]] = Field(None)


_stats: dict[str, Any] = {
    "total_ingested": 0,
    "quota_violations": 0,
    "actions": {"execute": 0, "batch": 0, "defer": 0, "shed": 0, "backpressure": 0},
    "by_type": {"order": 0, "payment": 0, "inventory": 0, "click": 0, "log": 0, "other": 0},
}
_start_time: float = time.monotonic()
_recent_events: deque = deque(maxlen=50)


@app.post("/ingest", status_code=status.HTTP_202_ACCEPTED)
async def ingest_event(
    event_in: Event,
    response: Response,
    x_source: Optional[str] = Header(None, alias="X-Source"),
) -> dict[str, Any]:
    ingestion_time = time.time()
    producer_id = x_source or "unknown-producer"

    is_within_quota = await check_producer_quota(producer_id)
    if not is_within_quota:
        _stats["quota_violations"] += 1

    e_type = event_in.event_type or event_in.type or "log"

    if event_in.payload is not None:
        payload = dict(event_in.payload)
    else:
        payload = event_in.model_dump(exclude={"event_id", "event_type", "type", "timestamp", "payload"})
        if not payload:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Payload must be provided as a dictionary or flat fields.",
            )

    payload["producer_id"] = producer_id
    payload["ingestion_time"] = ingestion_time
    payload["is_within_quota"] = is_within_quota

    if "amount" in payload and "has_monetary_value" not in payload:
        payload["has_monetary_value"] = payload["amount"] is not None and payload["amount"] > 0
    if "reversible" in payload and "is_reversible" not in payload:
        payload["is_reversible"] = payload["reversible"]

    normalized_event = {
        "event_id": event_in.event_id,
        "event_type": e_type,
        "timestamp": event_in.timestamp,
        "payload": payload,
    }

    system_state = SystemState(
        producer_quotas={producer_id: is_within_quota}
    )

    scoring_result = score_event(normalized_event, system_state)

    _stats["total_ingested"] += 1
    action_key = scoring_result["action"]
    if action_key in _stats["actions"]:
        _stats["actions"][action_key] += 1

    type_key = e_type if e_type in _stats["by_type"] else "other"
    _stats["by_type"][type_key] += 1

    event_record = {
        "event_id": event_in.event_id[:16],
        "producer": producer_id,
        "type": e_type,
        "quota": is_within_quota,
        "intrinsic": scoring_result["intrinsic_score"],
        "final_score": scoring_result["final_score"],
        "band": scoring_result["display_band"],
        "action": scoring_result["action"],
        "ingestion_time": ingestion_time,
        "latency_ms": round((time.time() - event_in.timestamp) * 1000, 1),
        "components": scoring_result.get("components", {}),
    }
    _recent_events.append(event_record)
    asyncio.create_task(store_event_decision(event_record))

    return {
        "status": "accepted",
        "event_id": event_in.event_id,
        "producer_id": producer_id,
        "is_within_quota": is_within_quota,
        "ingestion_time": ingestion_time,
        "decision": scoring_result,
    }


@app.post("/events", status_code=status.HTTP_200_OK)
async def receive_event(event_in: Event, x_source: Optional[str] = Header(None, alias="X-Source"), response: Response = None) -> dict[str, Any]:
    res = await ingest_event(event_in=event_in, response=response, x_source=x_source)
    return res


@app.get("/stats")
async def get_stats() -> dict:
    uptime = time.monotonic() - _start_time
    return {
        "uptime_seconds": round(uptime, 1),
        "total_received": _stats["total_ingested"],
        "total_ingested": _stats["total_ingested"],
        "quota_violations": _stats["quota_violations"],
        "actions": _stats["actions"],
        "by_type": _stats["by_type"],
        "events_per_second": round(_stats["total_ingested"] / max(uptime, 1), 2),
    }


@app.get("/recent")
async def recent_events() -> list[dict]:
    return list(_recent_events)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


if __name__ == "__main__":
    uvicorn.run("pipeline.main:app", host="127.0.0.1", port=8000, reload=True)
