"""
pipeline/main.py

Minimal FastAPI receiver — a test sink for the Request Simulator.

This application:
  1. Validates incoming events via Pydantic.
  2. Logs basic event metadata.
  3. Returns an "accepted" acknowledgement.

It intentionally contains NO pipeline processing logic.
Add processing, queueing, priority routing, etc. in separate components later.
"""

import logging
import time
from typing import Any, Literal

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

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
        "Minimal HTTP event receiver used to test the Request Simulator. "
        "Validates events via Pydantic and returns an accepted response. "
        "No downstream processing is implemented here."
    ),
    version="0.1.0",
)

# ---------------------------------------------------------------------------
# Event schema (Pydantic v2)
# ---------------------------------------------------------------------------

EVENT_TYPES = Literal["order", "payment", "inventory", "click", "log"]


class Event(BaseModel):
    """
    Contract for every event produced by the simulator.

    Fields:
      event_id   — UUID4 string, unique per event.
      event_type — One of the five recognised types.
      timestamp  — Unix epoch float, set at event creation time.
      payload    — Type-specific dictionary of synthetic data.
    """

    event_id: str = Field(..., description="UUID4 unique event identifier")
    event_type: EVENT_TYPES = Field(..., description="Event category")
    timestamp: float = Field(..., description="Unix epoch timestamp (creation time)")
    payload: dict[str, Any] = Field(..., description="Event-type-specific data")


# ---------------------------------------------------------------------------
# In-memory counters (per-process stats only — no persistence)
# ---------------------------------------------------------------------------

_stats: dict[str, int] = {
    "total_received": 0,
    "order": 0,
    "payment": 0,
    "inventory": 0,
    "click": 0,
    "log": 0,
}
_start_time: float = time.monotonic()


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@app.post("/events", summary="Receive a single event from the simulator")
async def receive_event(event: Event) -> dict[str, str]:
    """
    Accept an event from the Request Simulator.

    - Validates the event against the Event schema.
    - Increments per-type counters.
    - Logs a one-liner for every event (fine at 16/sec; acceptable at 333/sec
      because uvicorn buffers stdout; keep for visibility during demos).
    - Returns ``{"status": "accepted", "event_id": "..."}``.
    """
    _stats["total_received"] += 1
    _stats[event.event_type] += 1

    logger.info(
        "received  type=%-12s  id=%s  lag=%.3fs",
        event.event_type,
        event.event_id,
        time.time() - event.timestamp,
    )

    return {"status": "accepted", "event_id": event.event_id}


@app.get("/stats", summary="Per-process ingestion stats")
async def get_stats() -> dict:
    """
    Return basic per-process counters and uptime.
    Useful for quick sanity checks during simulator runs.
    """
    uptime = time.monotonic() - _start_time
    return {
        "uptime_seconds": round(uptime, 1),
        "total_received": _stats["total_received"],
        "by_type": {k: v for k, v in _stats.items() if k != "total_received"},
        "events_per_second": round(_stats["total_received"] / max(uptime, 1), 2),
    }


@app.get("/health", summary="Health check")
async def health() -> dict[str, str]:
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Dev entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    uvicorn.run("pipeline.main:app", host="127.0.0.1", port=8000, reload=True)
