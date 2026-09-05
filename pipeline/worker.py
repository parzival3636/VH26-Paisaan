"""
pipeline/worker.py — Resilient Worker Process & Batch Processor

Processes batches of events with item-level idempotency and crash recovery.
If a worker crashes mid-batch (e.g. after item 2 of 5), retry worker ONLY processes items 3, 4, 5.
"""

import hashlib
import time
import logging
import asyncio
from typing import Any, List, Dict
from pipeline.idempotency import idempotency_register

logger = logging.getLogger("pipeline.worker")


class BatchWorker:
    def __init__(self, worker_id: str):
        self.worker_id = worker_id
        self.processed_count = 0
        self.skipped_duplicates_count = 0
        self.is_alive = True

    async def process_batch(self, batch: List[Dict[str, Any]], simulate_crash_after: int = -1) -> Dict[str, Any]:
        """
        Processes a batch of events with item-level idempotency checks.
        If simulate_crash_after > 0, worker intentionally 'crashes' (raises Exception)
        after processing that number of items to test fault tolerance.
        """
        results = []
        processed_in_this_run = 0

        for idx, event in enumerate(batch):
            if not self.is_alive:
                raise RuntimeError(f"Worker {self.worker_id} killed mid-execution!")

            eid = event.get("event_id") or event.get("full_event_id")
            if not eid:
                continue

            # Idempotency Check: Skip if already completed by a previous worker
            if idempotency_register.is_already_completed(eid):
                self.skipped_duplicates_count += 1
                results.append({"event_id": eid, "status": "skipped_already_completed"})
                continue

            # Claim Lock Check
            if not idempotency_register.claim_event(eid, self.worker_id):
                results.append({"event_id": eid, "status": "claimed_by_other_worker"})
                continue

            # Simulated computation (SHA256 hash work per event)
            hash_val = hashlib.sha256(str(eid).encode('utf-8')).hexdigest()
            processed_in_this_run += 1
            self.processed_count += 1

            # Mark item as PERMANENTLY completed immediately after execution
            idempotency_register.mark_completed(eid, {
                "worker_id": self.worker_id,
                "timestamp": time.time(),
                "status": "executed",
                "hash": hash_val[:8],
            })
            results.append({"event_id": eid, "status": "executed"})

            # Simulate worker crash mid-batch if requested
            if simulate_crash_after > 0 and processed_in_this_run >= simulate_crash_after:
                self.is_alive = False
                logger.error(f"💣 [CRASH SIMULATION] Worker {self.worker_id} DIED unexpectedly after item {idx+1}/{len(batch)}!")
                raise RuntimeError(f"Worker {self.worker_id} crashed mid-batch after item {idx+1}!")

        return {
            "worker_id": self.worker_id,
            "processed": processed_in_this_run,
            "skipped": self.skipped_duplicates_count,
            "items": results
        }
