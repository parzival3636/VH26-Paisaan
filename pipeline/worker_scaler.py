"""
pipeline/worker_scaler.py — Dynamic Worker Auto-Scaler

Monitors queue depths (Fast + Standard + Cold) and dynamically scales active worker pool
up or down based on incoming queue pressure, enforcing min/max bounds.
"""

import math
import time
import logging
import asyncio
from typing import Dict, Any

logger = logging.getLogger("pipeline.scaler")

MIN_WORKERS = 2
MAX_WORKERS = 10
EVENTS_PER_WORKER_TARGET = 50  # Target ratio: 1 worker per 50 queued items


class DynamicWorkerScaler:
    def __init__(self, min_workers: int = MIN_WORKERS, max_workers: int = MAX_WORKERS):
        self.min_workers = min_workers
        self.max_workers = max_workers
        self.active_worker_count = min_workers
        self.scale_history: list[dict[str, Any]] = []

    def calculate_desired_workers(self, queue_depth: int) -> int:
        """Calculates optimal worker count based on real queue depth."""
        if queue_depth <= 0:
            return self.min_workers

        needed = math.ceil(queue_depth / EVENTS_PER_WORKER_TARGET)
        desired = max(self.min_workers, min(self.max_workers, needed))
        return desired

    def evaluate_scaling(self, current_queue_depth: int) -> Dict[str, Any]:
        desired = self.calculate_desired_workers(current_queue_depth)
        previous = self.active_worker_count

        if desired != previous:
            action = "SCALE_UP" if desired > previous else "SCALE_DOWN"
            logger.info(f"⚡ [WORKER SCALER] {action}: Queue Depth={current_queue_depth} | Active Workers {previous} -> {desired}")
            self.active_worker_count = desired
            record = {
                "timestamp": time.time(),
                "action": action,
                "previous_workers": previous,
                "active_workers": desired,
                "queue_depth": current_queue_depth
            }
            self.scale_history.append(record)
            return record

        return {
            "timestamp": time.time(),
            "action": "NO_CHANGE",
            "active_workers": self.active_worker_count,
            "queue_depth": current_queue_depth
        }


# Global singleton worker scaler
worker_scaler = DynamicWorkerScaler()
