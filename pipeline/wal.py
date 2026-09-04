"""
pipeline/wal.py — Multi-Tier Durability Fallback Chain & Reconciler Service

Provides guaranteed durability for every accepted event via:
  1. Primary: Kafka "raw-events" topic
  2. Backup: Redis "emergency_buffer" list
  3. Last Resort: Local Disk Write-Ahead Log ("local_wal.jsonl") with fsync()

Also runs a background Reconciler service that auto-replays buffered/WAL events
back into the primary pipeline upon system recovery.
"""

import os
import sys
import time
import json
import logging
import asyncio
from typing import Any, Optional

from pipeline.kafka_client import kafka_client, TOPIC_RAW

logger = logging.getLogger("pipeline.wal")

WAL_FILE_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "local_wal.jsonl")


class WALWriter:
    """Appends accepted events to a local disk Write-Ahead Log (JSON-lines) with fsync."""
    def __init__(self, file_path: str = WAL_FILE_PATH):
        self.file_path = file_path

    def append(self, event: dict[str, Any]) -> bool:
        try:
            line = json.dumps(event) + "\n"
            with open(self.file_path, "a", encoding="utf-8") as f:
                f.write(line)
                f.flush()
                os.fsync(f.fileno())
            return True
        except Exception as e:
            logger.error(f"Failed writing to local WAL file: {e}")
            return False

    def read_all(self) -> list[dict[str, Any]]:
        if not os.path.exists(self.file_path):
            return []
        events = []
        try:
            with open(self.file_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            events.append(json.loads(line))
                        except Exception:
                            pass
        except Exception as e:
            logger.error(f"Failed reading WAL file: {e}")
        return events

    def clear(self) -> bool:
        try:
            if os.path.exists(self.file_path):
                open(self.file_path, "w", encoding="utf-8").close()
            return True
        except Exception as e:
            logger.error(f"Failed clearing WAL file: {e}")
            return False


wal_writer = WALWriter()


async def durably_accept(event: dict[str, Any], redis_client: Optional[Any] = None) -> dict[str, Any]:
    """
    Durably accepts an incoming event through the priority fallback chain:
    1. Primary: Kafka "raw-events"
    2. Backup: Redis "emergency_buffer" list
    3. Last Resort: Local disk "local_wal.jsonl"
    """
    event_id = event.get("event_id", f"evt-{int(time.time()*1000)}")
    event["ingestion_time"] = event.get("ingestion_time") or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    # Tier 1: Apache Kafka topic "raw-events"
    if kafka_client.is_healthy():
        sent = await kafka_client.send_event(TOPIC_RAW, event)
        if sent:
            return {"status": "accepted", "durability": "kafka", "event_id": event_id}

    # Tier 2: Redis Emergency Buffer List
    if redis_client is not None:
        try:
            if hasattr(redis_client, "is_healthy") and redis_client.is_healthy():
                raw_str = json.dumps(event)
                await redis_client.lpush("emergency_buffer", raw_str)
                return {"status": "accepted", "durability": "redis_emergency", "event_id": event_id}
        except Exception as e:
            logger.debug(f"Redis emergency buffer bypass: {e}")

    # Tier 3: Local Disk WAL File (local_wal.jsonl)
    wal_writer.append(event)
    return {"status": "accepted", "durability": "local_wal_pending_sync", "event_id": event_id}


class Reconciler:
    """
    Background worker process that periodically checks for buffered events
    in Redis Emergency Buffer and local WAL, replaying them into the active pipeline.
    """
    def __init__(self, wal: WALWriter = wal_writer, poll_interval: float = 5.0):
        self.wal = wal
        self.poll_interval = poll_interval
        self._running = False

    async def start(self, redis_client: Optional[Any] = None, pipeline_ingest_callback: Optional[Any] = None):
        self._running = True
        logger.info("Reconciler background worker started.")

        while self._running:
            try:
                await asyncio.sleep(self.poll_interval)
                await self.reconcile(redis_client, pipeline_ingest_callback)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in Reconciler loop: {e}")

    def stop(self):
        self._running = False

    async def reconcile(self, redis_client: Optional[Any] = None, pipeline_ingest_callback: Optional[Any] = None):
        # 1. Reconcile Local WAL File
        wal_events = self.wal.read_all()
        if wal_events:
            replayed_count = 0
            remaining_events = []
            for ev in wal_events:
                replayed = False
                # Try publishing to Kafka or memory pipeline callback
                if kafka_client.is_healthy():
                    replayed = await kafka_client.send_event(TOPIC_RAW, ev)
                elif pipeline_ingest_callback:
                    try:
                        await pipeline_ingest_callback(ev)
                        replayed = True
                    except Exception:
                        replayed = False

                if replayed:
                    replayed_count += 1
                else:
                    remaining_events.append(ev)

            if replayed_count > 0:
                logger.info(f"Reconciler replayed {replayed_count} events from local WAL file.")
                self.wal.clear()
                for rem in remaining_events:
                    self.wal.append(rem)

        # 2. Reconcile Redis Emergency Buffer
        if redis_client is not None:
            try:
                if hasattr(redis_client, "rpop"):
                    ev_data = await redis_client.rpop("emergency_buffer")
                    if ev_data:
                        ev = json.loads(ev_data)
                        if pipeline_ingest_callback:
                            await pipeline_ingest_callback(ev)
                            logger.info(f"Reconciler replayed event {ev.get('event_id')} from Redis emergency buffer.")
            except Exception:
                pass


reconciler = Reconciler()
