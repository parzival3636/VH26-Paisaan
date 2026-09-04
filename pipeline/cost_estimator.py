"""
pipeline/cost_estimator.py — Infrastructure Cost Estimation & ROI Engine

Compares infrastructure cost under extreme load spikes:
1. Naive Baseline Strategy: Fixed 20 Max Workers running 24/7 @ $0.05/hr/worker + No Batching
2. Adaptive Pipeline Strategy: Dynamic 2-8 Workers + Cold Deferral Batching
"""

import time
import logging
from typing import Dict, Any
from pipeline.worker_scaler import worker_scaler

logger = logging.getLogger("pipeline.cost")

# Infrastructure cost constants (AWS EC2 / Cloud compute rates)
WORKER_COST_PER_HOUR = 0.05       # $0.05 per worker container / hour
LAMBDA_INGEST_COST_PER_1K = 0.002 # $0.002 per 1,000 API requests
NAIVE_FIXED_WORKERS = 20          # Fixed max scale-up baseline pool


class InfrastructureCostEstimator:
    def __init__(self):
        self.start_time = time.monotonic()
        self.total_ingested_events = 0
        self.total_deferred_events = 0

    def update_metrics(self, ingested_count: int, deferred_count: int):
        self.total_ingested_events = ingested_count
        self.total_deferred_events = deferred_count

    def calculate_cost_comparison(self) -> Dict[str, Any]:
        elapsed_seconds = max(1.0, time.monotonic() - self.start_time)
        elapsed_hours = elapsed_seconds / 3600.0

        # Naive Strategy: Fixed 20 workers running constantly + 0 batching savings
        naive_compute_cost = NAIVE_FIXED_WORKERS * WORKER_COST_PER_HOUR * elapsed_hours
        naive_api_cost = (self.total_ingested_events / 1000.0) * LAMBDA_INGEST_COST_PER_1K
        total_naive_cost = naive_compute_cost + naive_api_cost

        # Adaptive Strategy: Dynamic active workers + 40% batching savings on deferred cold items
        adaptive_workers = worker_scaler.active_worker_count
        adaptive_compute_cost = adaptive_workers * WORKER_COST_PER_HOUR * elapsed_hours
        # Cold queue micro-batching saves compute API overhead
        batched_events = self.total_deferred_events
        adaptive_api_cost = ((self.total_ingested_events - (batched_events * 0.5)) / 1000.0) * LAMBDA_INGEST_COST_PER_1K
        total_adaptive_cost = adaptive_compute_cost + adaptive_api_cost

        savings_usd = max(0.0, total_naive_cost - total_adaptive_cost)
        savings_percent = 0.0
        if total_naive_cost > 0:
            savings_percent = (savings_usd / total_naive_cost) * 100.0

        return {
            "elapsed_seconds": round(elapsed_seconds, 1),
            "total_ingested": self.total_ingested_events,
            "active_adaptive_workers": adaptive_workers,
            "fixed_naive_workers": NAIVE_FIXED_WORKERS,
            "cost_naive_usd": round(total_naive_cost, 4),
            "cost_adaptive_usd": round(total_adaptive_cost, 4),
            "savings_usd": round(savings_usd, 4),
            "savings_percent": round(savings_percent, 1),
            "strategy_breakdown": {
                "naive_hourly_rate": round(NAIVE_FIXED_WORKERS * WORKER_COST_PER_HOUR, 3),
                "adaptive_hourly_rate": round(adaptive_workers * WORKER_COST_PER_HOUR, 3),
            }
        }


# Global singleton cost estimator
cost_estimator = InfrastructureCostEstimator()
