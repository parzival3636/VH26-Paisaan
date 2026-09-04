import asyncio
import logging
import time
from collections import deque
from typing import Any, Literal, Optional

import uvicorn
from fastapi import FastAPI, Header, Response, status, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, ConfigDict

from pipeline.redis_client import check_producer_quota, store_event_decision, redis_client
from pipeline.kafka_client import kafka_client
from pipeline.wal import durably_accept, reconciler, wal_writer
from pipeline.scoring import SystemState, score_event, ScoringWeights, Thresholds
from pipeline.controller import pid_controller, cold_rescorer
from pipeline.db_sink import db_sink
from pipeline.dedup import deduplicator
from pipeline.worker_scaler import worker_scaler
from pipeline.cost_estimator import cost_estimator
from pipeline.predictor import predictor

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [PIPELINE] %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("pipeline")

app = FastAPI(
    title="Intelligent Data Pipeline — Production-Grade Gateway",
    version="1.0.0",
)

# Enable CORS for React Web Dashboard
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
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
_recent_events: deque = deque(maxlen=100)
_event_store: dict[str, dict[str, Any]] = {}  # In-memory score X-Ray lookup store

_arrival_timestamps: deque = deque(maxlen=5000)
_queue_depth_history: deque = deque(maxlen=20)
_baseline_mode: bool = False

# WebSocket Connection Manager
class ConnectionManager:
    def __init__(self):
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, message: dict):
        for connection in list(self.active_connections):
            try:
                await connection.send_json(message)
            except Exception:
                self.disconnect(connection)

manager = ConnectionManager()


@app.on_event("startup")
async def startup_event():
    await kafka_client.start()
    asyncio.create_task(reconciler.start(redis_client=redis_client))


@app.on_event("shutdown")
async def shutdown_event():
    reconciler.stop()
    await kafka_client.stop()


@app.post("/ingest", status_code=status.HTTP_202_ACCEPTED)
async def ingest_event(
    event_in: Event,
    response: Response,
    x_source: Optional[str] = Header(None, alias="X-Source"),
) -> dict[str, Any]:
    ingestion_time = time.time()
    producer_id = x_source or event_in.payload.get("source") if event_in.payload else "unknown-producer"

    now_mono = time.monotonic()
    _arrival_timestamps.append(now_mono)
    while _arrival_timestamps and _arrival_timestamps[0] < now_mono - 1.0:
        _arrival_timestamps.popleft()

    current_eps = len(_arrival_timestamps)
    queue_depth = min(current_eps / 50.0, 1.0)
    fast_lane_full = current_eps > 120

    # Calculate queue velocity (rate of change over last 3 seconds)
    _queue_depth_history.append((now_mono, queue_depth))
    three_sec_ago = now_mono - 3.0
    while len(_queue_depth_history) > 2 and _queue_depth_history[0][0] < three_sec_ago:
        _queue_depth_history.popleft()
    
    q_velocity = 0.0
    if len(_queue_depth_history) >= 2:
        dt = _queue_depth_history[-1][0] - _queue_depth_history[0][0]
        if dt > 0.1:
            q_velocity = (_queue_depth_history[-1][1] - _queue_depth_history[0][1]) / dt

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

    payload["source"] = producer_id
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
        "type": e_type,
        "timestamp": event_in.timestamp,
        "payload": payload,
    }

    # Layer 0: Duplicate Event Check
    idempotency_key = (event_in.payload or {}).get("idempotency_key") if isinstance(event_in.payload, dict) else None
    if deduplicator.is_duplicate(event_in.event_id, idempotency_key=idempotency_key):
        _stats["total_ingested"] += 1
        return {
            "status": "duplicate_ignored",
            "event_id": event_in.event_id,
            "message": "Duplicate event detected and dropped (Exact-Once Guarantee)."
        }

    # Execute Persistence Fallback Chain (Kafka -> Redis -> WAL)
    durability_info = await durably_accept(normalized_event, redis_client=redis_client)

    system_state = SystemState(
        queue_depth_normalised=queue_depth,
        fast_lane_full=fast_lane_full,
        queue_velocity=q_velocity,
        producer_quotas={producer_id: is_within_quota},
    )

    if _baseline_mode:
        # Naive FIFO Baseline Mode (No scoring, execute all in order)
        scoring_result = {
            "event_id": event_in.event_id,
            "intrinsic_score": 0.0,
            "final_score": 0.0,
            "display_band": "Standard",
            "action": "execute",
            "components": {},
        }
    else:
        thresholds = Thresholds(EXECUTE=pid_controller.current_execute_threshold)
        scoring_result = score_event(normalized_event, system_state, thresholds=thresholds)

    # Evaluate dynamic worker auto-scaling
    scaler_status = worker_scaler.evaluate_scaling(int(queue_depth * 100))

    # PID Threshold Controller Update (simulate P0 fast lane latency tracking)
    p0_latency = 18.0 + (queue_depth * 45.0) if scoring_result["action"] == "execute" else 80.0
    pid_controller.update(p0_latency)

    _stats["total_ingested"] += 1
    action_key = scoring_result["action"]
    if action_key in _stats["actions"]:
        _stats["actions"][action_key] += 1

    # Cost Estimator Update
    cost_estimator.update_metrics(
        ingested_count=_stats["total_ingested"],
        deferred_count=_stats["actions"].get("defer", 0)
    )

    type_key = e_type if e_type in _stats["by_type"] else "other"
    _stats["by_type"][type_key] += 1

    event_record = {
        "event_id": event_in.event_id[:16],
        "full_event_id": event_in.event_id,
        "producer": producer_id,
        "type": e_type,
        "quota": is_within_quota,
        "durability": durability_info.get("durability", "unknown"),
        "intrinsic": scoring_result["intrinsic_score"],
        "final_score": scoring_result["final_score"],
        "band": scoring_result["display_band"],
        "action": scoring_result["action"],
        "ingestion_time": ingestion_time,
        "latency_ms": round((time.time() - event_in.timestamp) * 1000, 1),
        "components": scoring_result.get("components", {}),
    }
    _recent_events.append(event_record)
    _event_store[event_in.event_id] = event_record
    if len(_event_store) > 500:
        oldest = next(iter(_event_store))
        del _event_store[oldest]

    asyncio.create_task(store_event_decision(event_record))
    asyncio.create_task(asyncio.to_thread(db_sink.record_transaction, event_record))

    return {
        "status": "accepted",
        "durability": durability_info.get("durability"),
        "event_id": event_in.event_id,
        "producer_id": producer_id,
        "is_within_quota": is_within_quota,
        "ingestion_time": ingestion_time,
        "decision": scoring_result,
        "active_workers": scaler_status.get("active_workers", worker_scaler.active_worker_count),
    }


@app.get("/metrics/cost")
async def get_cost_metrics() -> dict[str, Any]:
    return cost_estimator.calculate_cost_comparison()


@app.get("/scaler/status")
async def get_scaler_status() -> dict[str, Any]:
    return {
        "active_workers": worker_scaler.active_worker_count,
        "min_workers": worker_scaler.min_workers,
        "max_workers": worker_scaler.max_workers,
        "scale_history": worker_scaler.scale_history[-20:]
    }


@app.get("/history")
async def get_order_history(limit: int = 50, event_type: Optional[str] = None) -> dict[str, Any]:
    records = await asyncio.to_thread(db_sink.query_history, limit, event_type)
    total_count = await asyncio.to_thread(db_sink.get_total_orders_count)
    return {
        "total_permanent_records": total_count,
        "returned_count": len(records),
        "history": records,
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
        "baseline_mode": _baseline_mode,
        "pid_status": pid_controller.get_status(),
    }


@app.get("/recent")
async def recent_events() -> list[dict]:
    return list(_recent_events)


@app.get("/health")
async def health() -> dict[str, Any]:
    redis_ok = False
    try:
        redis_ok = redis_client.is_healthy() if hasattr(redis_client, "is_healthy") else True
    except Exception:
        pass

    return {
        "status": "ok",
        "kafka_healthy": kafka_client.is_healthy(),
        "redis_healthy": redis_ok,
        "wal_healthy": True,
        "durability_mode": "kafka" if kafka_client.is_healthy() else ("redis_emergency" if redis_ok else "local_wal_pending_sync"),
    }


@app.get("/metrics/live")
async def get_live_metrics() -> dict[str, Any]:
    uptime = time.monotonic() - _start_time
    eps = _stats["total_ingested"] / max(uptime, 1)
    q_depth = min(eps / 50.0, 1.0)
    return {
        "uptime_seconds": round(uptime, 1),
        "total_ingested": _stats["total_ingested"],
        "events_per_second": round(eps, 2),
        "requests_per_minute": round(eps * 60.0, 0),
        "queue_depth_normalized": round(q_depth, 3),
        "actions": _stats["actions"],
        "pid_controller": pid_controller.get_status(),
        "baseline_mode": _baseline_mode,
    }


@app.get("/metrics/event/{event_id}")
async def get_event_xray(event_id: str) -> dict[str, Any]:
    if event_id in _event_store:
        return _event_store[event_id]
    for ev in _recent_events:
        if ev.get("event_id") == event_id or ev.get("full_event_id") == event_id:
            return ev
    raise HTTPException(status_code=404, detail=f"Event ID {event_id} not found in live memory buffer.")


@app.get("/baseline/toggle")
@app.post("/baseline/toggle")
async def toggle_baseline_mode() -> dict[str, Any]:
    global _baseline_mode
    _baseline_mode = not _baseline_mode
    mode_name = "Naive FIFO Baseline" if _baseline_mode else "Intelligent Adaptive Pipeline"
    logger.info(f"Pipeline mode toggled to: {mode_name}")
    return {"baseline_mode": _baseline_mode, "mode_name": mode_name}


@app.websocket("/dashboard/feed")
async def websocket_dashboard_feed(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            uptime = time.monotonic() - _start_time
            eps = _stats["total_ingested"] / max(uptime, 1)
            feed_data = {
                "timestamp": time.time(),
                "uptime": round(uptime, 1),
                "total_ingested": _stats["total_ingested"],
                "events_per_second": round(eps, 2),
                "requests_per_minute": round(eps * 60.0, 0),
                "actions": _stats["actions"],
                "by_type": _stats["by_type"],
                "recent_events": list(_recent_events)[-15:],
                "durability_mode": "kafka" if kafka_client.is_healthy() else "redis_emergency",
                "pid": pid_controller.get_status(),
                "baseline_mode": _baseline_mode,
            }
            await websocket.send_json(feed_data)
            await asyncio.sleep(0.25)
    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception:
        manager.disconnect(websocket)


if __name__ == "__main__":
    uvicorn.run("pipeline.main:app", host="127.0.0.1", port=8000, reload=True)

    uvicorn.run("pipeline.main:app", host="127.0.0.1", port=8000, reload=True)
