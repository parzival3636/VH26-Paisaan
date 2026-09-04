"""
pipeline/main.py

Ingestion Gateway — Public API Entry Point for Events.

This application implements Phase 2: Sub-component 1 (Ingestion Gateway):
  1. Accepts POST /ingest requests from producer microservices or simulator.
  2. Validates incoming payload schema (Pydantic v2). Returns 422 if invalid.
  3. Producer Quota Check (X-Source header) using Redis / in-memory rate limiter.
  4. Timestamp stamping (ingestion_time attached for latency calculations).
  5. In-process handoff to Dynamic Criticality Scoring Engine (scoring.py).
  6. Returns 202 Accepted acknowledgement with queue admission & initial decision.
"""

import logging
import time
from collections import deque
from typing import Any, Literal, Optional

import uvicorn
from fastapi import FastAPI, Header, Response, status, HTTPException
from pydantic import BaseModel, Field, ConfigDict

from pipeline.redis_client import check_producer_quota
from pipeline.scoring import SystemState, score_event

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [PIPELINE] %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("pipeline")

# ---------------------------------------------------------------------------
# Application
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Intelligent Data Pipeline — Ingestion Gateway",
    description=(
        "Public-facing ingestion entry point for events. "
        "Performs schema validation, producer quota tracking (X-Source), "
        "timestamping, and dynamic priority scoring."
    ),
    version="0.2.0",
)

# ---------------------------------------------------------------------------
# Event Schemas (Pydantic v2)
# ---------------------------------------------------------------------------

EVENT_TYPES = Literal["order", "payment", "inventory", "click", "log"]


class Event(BaseModel):
    """Contract for standard event structure sent by simulator or internal services."""

    model_config = ConfigDict(extra="allow")

    event_id: str = Field(..., description="UUID4 or unique event identifier")
    event_type: Optional[EVENT_TYPES] = Field(None, description="Event category name")
    type: Optional[str] = Field(None, description="Alternative event type field")
    timestamp: float = Field(default_factory=time.time, description="Unix epoch timestamp (creation time)")
    payload: Optional[dict[str, Any]] = Field(None, description="Nested type-specific payload data")


# ---------------------------------------------------------------------------
# In-memory stats
# ---------------------------------------------------------------------------

_stats: dict[str, Any] = {
    "total_ingested": 0,
    "quota_violations": 0,
    "actions": {"execute": 0, "batch": 0, "defer": 0, "shed": 0, "backpressure": 0},
    "by_type": {"order": 0, "payment": 0, "inventory": 0, "click": 0, "log": 0, "other": 0},
}
_start_time: float = time.monotonic()
_recent_events: deque = deque(maxlen=50)  # Ring buffer for live dashboard feed


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@app.post("/ingest", status_code=status.HTTP_202_ACCEPTED, summary="Ingest event from producer")
async def ingest_event(
    event_in: Event,
    response: Response,
    x_source: Optional[str] = Header(None, alias="X-Source"),
) -> dict[str, Any]:
    """
    Sub-component 1: Ingestion Gateway endpoint.

    Step 1: Schema validation (handled automatically by FastAPI/Pydantic).
    Step 2: Producer Quota Check using X-Source header and Redis/In-Memory counter.
            If over quota, flag is_within_quota=False to penalize score downstream.
    Step 3: Attach ingestion_time timestamp.
    Step 4: Handoff to Dynamic Criticality Scoring Engine (in-process).
    """
    ingestion_time = time.time()
    producer_id = x_source or "unknown-producer"

    # Step 2: Quota check
    is_within_quota = await check_producer_quota(producer_id)
    if not is_within_quota:
        _stats["quota_violations"] += 1
        logger.warning("Producer %s exceeded quota! Applying score penalty.", producer_id)

    # Standardize event structure & payload for Scoring Engine
    e_type = event_in.event_type or event_in.type or "log"

    if event_in.payload is not None:
        payload = dict(event_in.payload)
    else:
        # If payload was sent flat, extract non-standard fields as payload
        payload = event_in.model_dump(exclude={"event_id", "event_type", "type", "timestamp", "payload"})
        if not payload:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Payload must be provided as a dictionary or flat fields.",
            )

    # Ensure payload contains producer_id and timestamping
    payload["producer_id"] = producer_id
    payload["ingestion_time"] = ingestion_time
    payload["is_within_quota"] = is_within_quota

    # Map flat schema fields if present
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

    # Step 4: Call Scoring Engine with current system state
    system_state = SystemState(
        producer_quotas={producer_id: is_within_quota}
    )

    scoring_result = score_event(normalized_event, system_state)

    # Update stats
    _stats["total_ingested"] += 1
    action_key = scoring_result["action"]
    if action_key in _stats["actions"]:
        _stats["actions"][action_key] += 1

    type_key = e_type if e_type in _stats["by_type"] else "other"
    _stats["by_type"][type_key] += 1

    # Track for live dashboard feed
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

    logger.info(
        "INGEST  id=%s  src=%-18s  type=%-10s  quota=%-5s  score=%.2f  action=%s",
        event_in.event_id,
        producer_id,
        e_type,
        is_within_quota,
        scoring_result["final_score"],
        scoring_result["action"],
    )

    return {
        "status": "accepted",
        "event_id": event_in.event_id,
        "producer_id": producer_id,
        "is_within_quota": is_within_quota,
        "ingestion_time": ingestion_time,
        "decision": scoring_result,
    }


@app.post("/events", status_code=status.HTTP_200_OK, summary="Legacy events endpoint")
async def receive_event(event_in: Event, x_source: Optional[str] = Header(None, alias="X-Source"), response: Response = None) -> dict[str, Any]:
    """Redirect legacy /events endpoint to /ingest handler for backwards compatibility."""
    res = await ingest_event(event_in=event_in, response=response, x_source=x_source)
    return res


@app.get("/stats", summary="Per-process ingestion stats")
async def get_stats() -> dict:
    """Return pipeline ingestion & scoring counters."""
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


@app.get("/recent", summary="Recent event feed for live dashboard")
async def recent_events() -> list[dict]:
    """Return the last 50 scored events for dashboard display."""
    return list(_recent_events)


@app.get("/health", summary="Health check")
async def health() -> dict[str, str]:
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Dev entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    uvicorn.run("pipeline.main:app", host="127.0.0.1", port=8000, reload=True)
