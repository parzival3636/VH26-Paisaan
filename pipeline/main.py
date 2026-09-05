import asyncio
import logging
import os
import time
import json
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
from pipeline.inventory_lock import inventory_lock
from pipeline.lane_processor import lane_processor
from pipeline.benchmark import benchmark_simulator
from simulator.controller import SimulatorState
from simulator.metrics import SimulatorMetrics
from simulator.generator import generate_event


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

# Simulator state (controlled via /simulator/* endpoints)
_sim_state: SimulatorState = SimulatorState()
_sim_metrics: SimulatorMetrics = SimulatorMetrics()
_sim_task: asyncio.Task | None = None

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


async def _run_producer():
    """In-process event producer — scores events directly, no HTTP overhead."""
    last_time = time.monotonic()
    accumulator = 0.0

    while True:
        if not _sim_state.running:
            await asyncio.sleep(0.05)
            last_time = time.monotonic()
            continue

        now = time.monotonic()
        dt = now - last_time
        last_time = now

        lam = _sim_state.current_rate
        accumulator += dt * lam
        count = int(accumulator)
        if count > 0:
            accumulator -= count
            
            # For high loads, batch generate and route to avoid blocking
            if lam > 300:  # High load mode (> 18K req/min)
                # Calculate current system state once
                now_mono = time.monotonic()
                current_eps = len(_arrival_timestamps)
                queue_depth = min(current_eps / 150.0, 1.0)
                fast_lane_full = current_eps > 200
                
                # Determine threshold based on load - ensure proper lane distribution
                if lam < 500:
                    execute_threshold = 7.0  # High threshold for 18-30K req/min to force batching
                    # This creates proper distribution:
                    # score >= 7.0: Fast Lane (only very high value payments/orders)
                    # 3.0 <= score < 7.0: Standard Lane (BATCHING - most events land here)
                    # score < 3.0: Cold Lane
                else:
                    execute_threshold = pid_controller.current_execute_threshold
                
                thresholds = Thresholds(EXECUTE=execute_threshold)
                
                # Batch generate and route events
                for _ in range(count):
                    event = generate_event()
                    _sim_metrics.record_generated(event["event_type"])
                    _sim_metrics.record_sent()
                    
                    # Update arrival timestamps
                    _arrival_timestamps.append(now_mono)
                    while _arrival_timestamps and _arrival_timestamps[0] < now_mono - 1.0:
                        _arrival_timestamps.popleft()
                    
                    e_type = event["event_type"]
                    payload = event["payload"]
                    producer_id = payload.get("producer_id", "simulator")
                    
                    normalized_event = {
                        "event_id": event["event_id"],
                        "event_type": e_type,
                        "type": e_type,
                        "timestamp": event["timestamp"],
                        "payload": payload,
                    }
                    
                    system_state = SystemState(
                        queue_depth_normalised=queue_depth,
                        fast_lane_full=fast_lane_full,
                        queue_velocity=0.0,
                        producer_quotas={producer_id: True},
                    )
                    
                    if _baseline_mode:
                        action_key = "execute" if (_stats["total_ingested"] % 2 == 0) else "batch"
                        scoring_result = {
                            "intrinsic_score": 1.0,
                            "final_score": 1.0,
                            "display_band": "Standard",
                            "action": action_key,
                            "components": {},
                        }
                    else:
                        scoring_result = score_event(normalized_event, system_state, thresholds=thresholds)
                    
                    _stats["total_ingested"] += 1
                    action_key = scoring_result["action"]
                    if action_key in _stats["actions"]:
                        _stats["actions"][action_key] += 1
                    type_key = e_type if e_type in _stats["by_type"] else "other"
                    _stats["by_type"][type_key] += 1
                    
                    # Route immediately using put_nowait for high throughput
                    if action_key in ["execute", "batch", "defer"]:
                        try:
                            if action_key == "execute":
                                lane_processor.fast_queue.put_nowait(normalized_event)
                            elif action_key == "batch":
                                lane_processor.standard_queue.put_nowait(normalized_event)
                            else:
                                lane_processor.cold_queue.put_nowait(normalized_event)
                        except asyncio.QueueFull:
                            _stats["actions"]["backpressure"] = _stats["actions"].get("backpressure", 0) + 1
                    
                    event_record = {
                        "event_id": normalized_event["event_id"][:16],
                        "producer": producer_id,
                        "type": e_type,
                        "quota": True,
                        "intrinsic": scoring_result["intrinsic_score"],
                        "final_score": scoring_result["final_score"],
                        "band": scoring_result["display_band"],
                        "action": scoring_result["action"],
                        "ingestion_time": normalized_event["timestamp"],
                        "latency_ms": 0.0,
                        "components": scoring_result.get("components", {}),
                        "payload": payload,
                    }
                    _recent_events.append(event_record)
                    _sim_metrics.record_response(202, 0.0)
                
            else:  # Normal/low load mode - await each event
                for _ in range(count):
                    event = generate_event()
                    _sim_metrics.record_generated(event["event_type"])
                    _sim_metrics.record_sent()

                    now_mono = time.monotonic()
                    _arrival_timestamps.append(now_mono)
                    while _arrival_timestamps and _arrival_timestamps[0] < now_mono - 1.0:
                        _arrival_timestamps.popleft()

                current_eps = len(_arrival_timestamps)
                # More realistic queue depth: normalize against higher threshold
                # 1000 req/min = 16.7 req/sec should be light load (queue_depth ~ 0.15-0.2)
                # Scale: 0-150 eps = 0.0-1.0 queue depth (was 0-50, too sensitive)
                queue_depth = min(current_eps / 150.0, 1.0)
                fast_lane_full = current_eps > 200  # Raised from 120 to allow more fast lane routing

                e_type = event["event_type"]
                payload = event["payload"]
                producer_id = payload.get("producer_id", "simulator")

                normalized_event = {
                    "event_id": event["event_id"],
                    "event_type": e_type,
                    "type": e_type,
                    "timestamp": event["timestamp"],
                    "payload": payload,
                }

                system_state = SystemState(
                    queue_depth_normalised=queue_depth,
                    fast_lane_full=fast_lane_full,
                    queue_velocity=0.0,
                    producer_quotas={producer_id: True},
                )

                # Adaptive thresholds based on load - at higher loads, force more batching
                if lam < 30:  # Normal load (< 1800 req/min) - prioritize fast lane
                    execute_threshold = 2.5  # Very low threshold so most events qualify for fast lane
                elif lam < 100:  # Low-moderate load (< 6000 req/min)
                    execute_threshold = 4.0
                elif lam < 500:  # Moderate-high load (< 30K req/min) - force batching
                    execute_threshold = 7.0  # High threshold to push most events to Standard Lane for batching
                else:  # High load (>= 30K req/min) - use strict PID control
                    execute_threshold = pid_controller.current_execute_threshold
                
                thresholds = Thresholds(EXECUTE=execute_threshold)
                if _baseline_mode:
                    # Naive FIFO baseline: simple round-robin FIFO without priority scoring
                    action_key = "execute" if (_stats["total_ingested"] % 2 == 0) else "batch"
                    scoring_result = {
                        "intrinsic_score": 1.0,
                        "final_score": 1.0,
                        "display_band": "Standard",
                        "action": action_key,
                        "components": {
                            "monetary": 0.0,
                            "irreversibility": 0.0,
                            "scarcity": 0.0,
                            "deadline": 0.0,
                            "queue_pressure": 0.0,
                            "queue_velocity": 0.0,
                            "anti_starvation": 0.0,
                            "worker_adj": 0.0,
                            "quota_penalty": 0.0,
                            "health_boost": 0.0,
                        },
                    }
                else:
                    scoring_result = score_event(normalized_event, system_state, thresholds=thresholds)

                _stats["total_ingested"] += 1
                action_key = scoring_result["action"]
                if action_key in _stats["actions"]:
                    _stats["actions"][action_key] += 1
                type_key = e_type if e_type in _stats["by_type"] else "other"
                _stats["by_type"][type_key] += 1

                # Route to lane processor for actual queue processing
                if action_key in ["execute", "batch", "defer"]:
                    await lane_processor.route_event(normalized_event, action_key)

                event_record = {
                    "event_id": event["event_id"][:16],
                    "producer": producer_id,
                    "type": e_type,
                    "quota": True,
                    "intrinsic": scoring_result["intrinsic_score"],
                    "final_score": scoring_result["final_score"],
                    "band": scoring_result["display_band"],
                    "action": scoring_result["action"],
                    "ingestion_time": event["timestamp"],
                    "latency_ms": 0.0,
                    "components": scoring_result.get("components", {}),
                    "payload": payload,
                }
                _recent_events.append(event_record)
                _sim_metrics.record_response(202, 0.0)

                p0_latency = 18.0 + (queue_depth * 45.0) if scoring_result["action"] == "execute" else 80.0
                pid_controller.update(p0_latency)

        # Adaptive sleep based on rate - longer sleep allows accumulator to build up
        if lam > 1000:  # > 60K req/min (e.g., 100K = 1666 ev/s)
            await asyncio.sleep(0.05)  # 50ms = 20 iterations/sec, ~83 events/iteration
        elif lam > 300:  # > 18K req/min (e.g., 20K = 333 ev/s)
            await asyncio.sleep(0.02)  # 20ms = 50 iterations/sec, ~6.7 events/iteration
        elif lam > 80:  # > 4.8K req/min (e.g., 5K = 83 ev/s)
            await asyncio.sleep(0.005)  # 5ms = 200 iterations/sec, ~0.4 events/iteration
        else:  # Normal load (1K = 16.7 ev/s)
            await asyncio.sleep(0.002)  # 2ms = 500 iterations/sec, ~0.03 events/iteration


@app.on_event("startup")
async def startup_event():
    global _sim_task
    await kafka_client.start()
    asyncio.create_task(reconciler.start(redis_client=redis_client))
    
    # Start lane processor with DRR scheduling
    lane_processor.start()
    logger.info("Lane processor initialized with DRR (Deficit Round Robin) scheduling")
    
    # Auto-start simulator when launched via headless.py
    if os.environ.get("AUTO_START_SIMULATOR") == "1":
        _sim_state.start()
        _sim_task = asyncio.create_task(_run_producer())
        logger.info("Simulator auto-started (headless mode)")


@app.on_event("shutdown")
async def shutdown_event():
    lane_processor.stop()
    reconciler.stop()
    await kafka_client.stop()


@app.post("/ingest", status_code=status.HTTP_202_ACCEPTED)
async def ingest_event(
    event_in: Event,
    response: Response,
    x_source: Optional[str] = Header(None, alias="X-Source"),
) -> dict[str, Any]:
    ingestion_time = time.time()
    payload_dict = event_in.payload if isinstance(event_in.payload, dict) else {}
    producer_id = x_source or payload_dict.get("source") or payload_dict.get("producer_id") or "unknown-producer"

    now_mono = time.monotonic()
    _arrival_timestamps.append(now_mono)
    while _arrival_timestamps and _arrival_timestamps[0] < now_mono - 1.0:
        _arrival_timestamps.popleft()

    current_eps = len(_arrival_timestamps)
    # More realistic queue depth: normalize against higher threshold
    # 1000 req/min = 16.7 req/sec should be light load (queue_depth ~ 0.15-0.2)
    # Scale: 0-150 eps = 0.0-1.0 queue depth (was 0-50, too sensitive)
    queue_depth = min(current_eps / 150.0, 1.0)
    fast_lane_full = current_eps > 200  # Raised from 120 to allow more fast lane routing

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

    # Route to lane processor for actual queue processing with DRR
    if action_key in ["execute", "batch", "defer"]:
        await lane_processor.route_event(normalized_event, action_key)

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
        "payload": payload,
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


@app.get("/inventory/status")
async def get_inventory_status(product_id: str = "ps5-console") -> dict[str, Any]:
    stock = inventory_lock.get_stock(product_id)
    return {
        "product_id": product_id,
        "remaining_stock": stock,
        "is_sold_out": stock <= 0,
    }


@app.post("/inventory/seed")
async def seed_inventory(product_id: str = "ps5-console", stock_count: int = 1) -> dict[str, Any]:
    inventory_lock.set_stock(product_id, stock_count)
    return {
        "status": "seeded",
        "product_id": product_id,
        "stock_count": stock_count,
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


@app.get("/lanes/stats")
async def get_lane_stats() -> dict[str, Any]:
    """Get current lane processing statistics with DRR metrics"""
    return {
        "lanes": lane_processor.get_stats(),
        "scheduler": "Deficit Round Robin (DRR)",
        "description": "Fast lane: immediate | Standard/Cold: DRR with quantum 10:3"
    }


@app.get("/batches")
async def list_batch_files(limit: int = 50, lane: Optional[str] = None) -> dict[str, Any]:
    """List batch files with optional lane filter"""
    from pathlib import Path
    import os
    
    batch_dir = Path(__file__).parent.parent / "batch_files"
    if not batch_dir.exists():
        return {"batches": [], "total": 0}
    
    # Get all batch files
    files = []
    for f in batch_dir.glob("*.json"):
        try:
            stat = f.stat()
            file_info = {
                "filename": f.name,
                "batch_id": f.stem,
                "size_bytes": stat.st_size,
                "created": stat.st_mtime,
            }
            # Extract lane from filename (format: lane_timestamp_size.json)
            parts = f.stem.split('_')
            if len(parts) >= 1:
                file_info["lane"] = parts[0]
            files.append(file_info)
        except Exception:
            continue
    
    # Filter by lane if specified
    if lane:
        files = [f for f in files if f.get("lane") == lane]
    
    # Sort by created time (newest first)
    files.sort(key=lambda x: x["created"], reverse=True)
    
    # Limit results
    files = files[:limit]
    
    return {
        "batches": files,
        "total": len(files),
        "directory": str(batch_dir)
    }


@app.get("/batches/{batch_id}")
async def get_batch_file(batch_id: str) -> dict[str, Any]:
    """Get batch file content by ID"""
    from pathlib import Path
    
    batch_dir = Path(__file__).parent.parent / "batch_files"
    batch_file = batch_dir / f"{batch_id}.json"
    
    if not batch_file.exists():
        raise HTTPException(status_code=404, detail=f"Batch file {batch_id} not found")
    
    try:
        with open(batch_file, 'r') as f:
            return json.load(f)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to read batch file: {e}")


@app.delete("/batches")
async def clear_batch_files() -> dict[str, Any]:
    """Clear all batch files"""
    from pathlib import Path
    import os
    
    batch_dir = Path(__file__).parent.parent / "batch_files"
    if not batch_dir.exists():
        return {"deleted": 0}
    
    deleted = 0
    for f in batch_dir.glob("*.json"):
        try:
            f.unlink()
            deleted += 1
        except Exception:
            pass
    
    return {"deleted": deleted, "message": f"Deleted {deleted} batch files"}


@app.post("/benchmark/run")
async def run_benchmark(num_events: int = 10000, load_multiplier: int = 20) -> dict[str, Any]:
    """
    Run benchmark comparison: FIFO baseline vs Adaptive pipeline
    
    Simulates load_multiplier times normal traffic (20x = 20,000 req/min)
    Calculates energy cost (joules) and cloud compute cost (USD)
    """
    result = await benchmark_simulator.run_benchmark(num_events, load_multiplier)
    return result


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
            now_mono = time.monotonic()
            while _arrival_timestamps and _arrival_timestamps[0] < now_mono - 1.0:
                _arrival_timestamps.popleft()
            eps = float(len(_arrival_timestamps))
            uptime = now_mono - _start_time
            feed_data = {
                "timestamp": time.time(),
                "uptime": round(uptime, 1),
                "total_ingested": _stats["total_ingested"],
                "events_per_second": round(eps, 2),
                "requests_per_minute": round(eps * 60.0, 0),
                "quota_violations": _stats["quota_violations"],
                "actions": _stats["actions"],
                "by_type": _stats["by_type"],
                "recent_events": list(_recent_events)[-15:],
                "durability_mode": "kafka" if kafka_client.is_healthy() else "redis_emergency",
                "pid": pid_controller.get_status(),
                "baseline_mode": _baseline_mode,
                "simulator": {
                    "running": _sim_state.running,
                    "mode": _sim_state.mode,
                    "rate_per_min": round(_sim_state.rate_per_min, 0),
                },
                "scaler": {
                    "active_workers": worker_scaler.active_worker_count,
                    "min_workers": worker_scaler.min_workers,
                    "max_workers": worker_scaler.max_workers,
                },
                "lanes": lane_processor.get_stats(),  # Add lane processing stats
            }
            await websocket.send_json(feed_data)
            await asyncio.sleep(0.25)
    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception:
        manager.disconnect(websocket)


# ---------------------------------------------------------------------------
# Simulator Control Endpoints (additive — no existing logic changed)
# ---------------------------------------------------------------------------

@app.post("/simulator/start")
async def simulator_start() -> dict[str, Any]:
    global _sim_task
    if _sim_task and not _sim_task.done():
        return {"status": "already_running", "rate_per_min": _sim_state.rate_per_min}
    _sim_state.start()
    _sim_task = asyncio.create_task(_run_producer())
    return {"status": "started", "rate_per_min": _sim_state.rate_per_min}


@app.post("/simulator/stop")
async def simulator_stop() -> dict[str, Any]:
    global _sim_task
    _sim_state.stop()
    if _sim_task:
        _sim_task.cancel()
        _sim_task = None
    return {"status": "stopped"}


@app.post("/simulator/rate")
async def simulator_set_rate(body: dict[str, Any]) -> dict[str, Any]:
    global _sim_task
    rate = body.get("rate", 1000)
    _sim_state.set_rate(float(rate))
    _arrival_timestamps.clear()  # Instantly reflect rate changes in EPS calculation
    if not _sim_state.running:
        _sim_state.start()
        if not _sim_task or _sim_task.done():
            _sim_task = asyncio.create_task(_run_producer())
    return {"status": "rate_updated", "rate_per_min": _sim_state.rate_per_min, "mode": _sim_state.mode}


@app.post("/simulator/spike")
async def simulator_instant_spike(body: dict[str, Any]) -> dict[str, Any]:
    """
    Send an instant burst of N events to stress test the system.
    Events are generated directly in-memory and pushed to lane queues - no HTTP overhead.
    
    Args:
        count: Number of events to generate instantly (e.g., 20000, 100000)
    
    Returns:
        Status and timing information
    """
    count = body.get("count", 10000)
    if count > 200000:
        return {"status": "error", "message": "Count too high (max 200,000)"}
    
    logger.info(f"🔥 INSTANT SPIKE: Generating {count} events in-memory...")
    start_time = time.monotonic()
    
    # Track counts per lane
    lane_counts = {"execute": 0, "batch": 0, "defer": 0, "backpressure": 0}
    
    # Generate all events
    for i in range(count):
        event = generate_event()
        _sim_metrics.record_generated(event["event_type"])
        _sim_metrics.record_sent()
        
        # Calculate queue depth based on current load
        current_eps = len(_arrival_timestamps)
        queue_depth = min(current_eps / 150.0, 1.0)
        fast_lane_full = current_eps > 200
        
        e_type = event["event_type"]
        payload = event["payload"]
        
        normalized_event = {
            "event_id": event["event_id"],
            "event_type": e_type,
            "type": e_type,
            "timestamp": event["timestamp"],
            "payload": payload,
        }
        
        system_state = SystemState(
            queue_depth_normalised=queue_depth,
            fast_lane_full=fast_lane_full,
            queue_velocity=0.0,
            producer_quotas={"spike-generator": True},
        )
        
        thresholds = Thresholds(EXECUTE=pid_controller.current_execute_threshold)
        
        # Score event
        scoring_result = score_event(normalized_event, system_state, thresholds=thresholds)
        
        _stats["total_ingested"] += 1
        action_key = scoring_result["action"]
        if action_key in _stats["actions"]:
            _stats["actions"][action_key] += 1
        type_key = e_type if e_type in _stats["by_type"] else "other"
        _stats["by_type"][type_key] += 1
        
        # Route to lane processor using proper await (respects backpressure)
        if action_key in ["execute", "batch", "defer"]:
            routed = await lane_processor.route_event(normalized_event, action_key)
            if routed:
                lane_counts[action_key] += 1
            else:
                lane_counts["backpressure"] += 1
        
        event_record = {
            "event_id": event["event_id"][:16],
            "producer": "spike-generator",
            "type": e_type,
            "quota": True,
            "intrinsic": scoring_result["intrinsic_score"],
            "final_score": scoring_result["final_score"],
            "band": scoring_result["display_band"],
            "action": scoring_result["action"],
            "ingestion_time": event["timestamp"],
            "latency_ms": 0.0,
            "components": scoring_result.get("components", {}),
            "payload": payload,
        }
        _recent_events.append(event_record)
        _sim_metrics.record_response(202, 0.0)
        
        # Update arrival timestamps for accurate EPS calculation
        now_mono = time.monotonic()
        _arrival_timestamps.append(now_mono)
        # Keep only last 5000 timestamps to prevent memory bloat
        while len(_arrival_timestamps) > 5000:
            _arrival_timestamps.popleft()
        
        # Yield every 100 events to prevent blocking
        if i % 100 == 0:
            await asyncio.sleep(0)
    
    elapsed = time.monotonic() - start_time
    logger.info(f"✅ SPIKE COMPLETE: {count} events generated in {elapsed:.3f}s ({count/elapsed:.0f} ev/s)")
    
    return {
        "status": "spike_complete",
        "count": count,
        "elapsed_seconds": round(elapsed, 3),
        "events_per_second": round(count / elapsed, 0),
        "lane_distribution": lane_counts,
        "queue_sizes": {
            "fast": lane_processor.fast_queue.qsize(),
            "standard": lane_processor.standard_queue.qsize(),
            "cold": lane_processor.cold_queue.qsize(),
        },
        "message": f"Generated {count:,} events in {elapsed:.3f}s - routed to in-memory queues"
    }


@app.get("/simulator/status")
async def simulator_status() -> dict[str, Any]:
    return {
        "running": _sim_state.running,
        "mode": _sim_state.mode,
        "rate_per_min": round(_sim_state.rate_per_min, 0),
        "current_rate_per_sec": round(_sim_state.current_rate, 2),
        "metrics": _sim_metrics.snapshot(),
    }


# ---------------------------------------------------------------------------
# Chaos Engineering Control Panel Endpoints
# ---------------------------------------------------------------------------

@app.post("/chaos/kill-kafka")
async def chaos_kill_kafka() -> dict[str, Any]:
    """Simulate Kafka failure by disabling the client"""
    try:
        kafka_client._is_healthy = False  # Force unhealthy state
        logger.warning("🔥 CHAOS: Kafka has been killed")
        return {"status": "kafka_killed", "message": "Kafka marked as unhealthy - fallback to Redis activated"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.post("/chaos/kill-redis")
async def chaos_kill_redis() -> dict[str, Any]:
    """Simulate Redis failure"""
    try:
        # Store original client and replace with broken one
        global _redis_client
        from pipeline.redis_client import _redis_client as rc
        if rc:
            await rc.close()
        _redis_client = None
        logger.warning("🔥 CHAOS: Redis has been killed")
        return {"status": "redis_killed", "message": "Redis marked as unhealthy - fallback to local WAL"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.post("/chaos/kill-both")
async def chaos_kill_both() -> dict[str, Any]:
    """Kill both Kafka and Redis - force local WAL only"""
    try:
        kafka_client._is_healthy = False
        global _redis_client
        from pipeline.redis_client import _redis_client as rc
        if rc:
            await rc.close()
        _redis_client = None
        logger.warning("🔥🔥 CHAOS: Both Kafka AND Redis killed - local WAL only mode")
        return {"status": "both_killed", "message": "Both Kafka and Redis killed - using local WAL"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.post("/chaos/restore")
async def chaos_restore_all() -> dict[str, Any]:
    """Restore all services to healthy state"""
    try:
        # Restore Kafka
        if not kafka_client._is_healthy and kafka_client.producer:
            kafka_client._is_healthy = True
        elif not kafka_client.producer:
            await kafka_client.start()
        
        # Restore Redis by re-initializing connection
        from pipeline.redis_client import get_redis_client
        await get_redis_client()
        
        logger.info("✅ CHAOS: All services restored to healthy state")
        return {"status": "restored", "message": "All services restored - normal operation resumed"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.post("/chaos/inject-payment")
async def chaos_inject_high_value_payment() -> dict[str, Any]:
    """Inject a high-value ₹5,00,000 payment to demonstrate fast lane routing"""
    try:
        event = Event(
            event_id=f"CHAOS-PAY-{int(time.time() * 1000)}",
            event_type="payment",
            type="payment",
            timestamp=time.time(),
            payload={
                "amount": 500000,  # ₹5,00,000
                "currency": "INR",
                "has_monetary_value": True,
                "is_reversible": False,
                "producer_id": "chaos-injector",
                "source": "chaos-control-panel",
                "description": "High-value payment injection for demo",
            }
        )
        result = await ingest_event(event, Response(), "chaos-control-panel")
        logger.info(f"💰 CHAOS: Injected ₹5,00,000 payment - routed to {result.get('decision', {}).get('action', 'unknown')}")
        return {
            "status": "injected",
            "event_id": event.event_id,
            "amount": 500000,
            "routed_to": result.get("decision", {}).get("action", "unknown"),
            "score": result.get("decision", {}).get("final_score", 0),
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.post("/chaos/flood-fast")
async def chaos_flood_fast_lane() -> dict[str, Any]:
    """Flood the pipeline with 100 high-priority events rapidly"""
    try:
        injected = 0
        for i in range(100):
            event = Event(
                event_id=f"FLOOD-{int(time.time() * 1000000)}-{i}",
                event_type="payment",
                type="payment",
                timestamp=time.time(),
                payload={
                    "amount": 100000 + (i * 1000),
                    "currency": "INR",
                    "has_monetary_value": True,
                    "is_reversible": False,
                    "producer_id": "chaos-flood",
                    "source": "chaos-control-panel",
                }
            )
            await ingest_event(event, Response(), "chaos-control-panel")
            injected += 1
        logger.warning(f"🌊 CHAOS: Flooded pipeline with {injected} high-priority events")
        return {
            "status": "flooded",
            "events_injected": injected,
            "message": f"Injected {injected} high-value payments to stress-test fast lane"
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


if __name__ == "__main__":
    uvicorn.run("pipeline.main:app", host="127.0.0.1", port=8000, reload=True)
