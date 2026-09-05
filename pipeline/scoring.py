from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any
from pipeline.inventory_lock import inventory_lock


def clamp(val: float, min_val: float = 0.0, max_val: float = 1.0) -> float:
    return max(min_val, min(max_val, val))


@dataclass(frozen=True)
class ScoringWeights:
    W1: float = 0.8    # Monetary amount weight (log(amount+1) * 0.8)
    W2: float = 1.5    # Physical scarcity weight
    W3: float = 3.0    # Irreversibility weight
    W4: float = 1.0    # Deadline urgency weight
    W5: float = 0.8    # Queue depth normalized weight
    W6: float = 0.5    # Anti-starvation waiting time weight
    W7: float = -0.5   # Worker availability weight
    W8: float = -1.5   # Over-quota penalty weight
    W9: float = 0.8    # Queue velocity predictive weight
    W_MAX: float = 9.0 # Infrastructure health check max override


@dataclass(frozen=True)
class Thresholds:
    EXECUTE: float = 6.0
    BATCH: float = 3.0
    DEFER: float = 1.0


class DisplayBand(str, Enum):
    CRITICAL = "Critical"
    STANDARD = "Standard"
    BEST_EFFORT = "Best-effort"


def get_display_band(score: float) -> DisplayBand:
    if score >= 6.0:
        return DisplayBand.CRITICAL
    elif score >= 3.0:
        return DisplayBand.STANDARD
    else:
        return DisplayBand.BEST_EFFORT


class Action(str, Enum):
    EXECUTE = "execute"
    BATCH = "batch"
    DEFER = "defer"
    SHED = "shed"          # Retained for legacy visualization tags
    BACKPRESSURE = "backpressure"


@dataclass
class SystemState:
    queue_depth_normalised: float = 0.0
    worker_availability: float = 1.0
    fast_lane_full: bool = False
    queue_velocity: float = 0.0
    producer_quotas: dict[str, bool] = field(default_factory=dict)


def compute_intrinsic_criticality(
    payload: dict[str, Any],
    weights: ScoringWeights = ScoringWeights(),
) -> float:
    score = 0.0

    # 1. Monetary Value ($$$)
    has_monetary = payload.get("has_monetary_value")
    if has_monetary is None:
        has_monetary = payload.get("amount") is not None and payload.get("amount", 0) > 0

    if has_monetary:
        amount = payload.get("amount") or 0.0
        score += weights.W1 * math.log(amount + 1.0)

    # 2. Physical Scarcity (Graded)
    affects_scarcity = payload.get("affects_physical_scarcity")
    if affects_scarcity is None:
        affects_scarcity = payload.get("affects_scarcity", False)

    if affects_scarcity:
        stock = payload.get("stock_remaining")
        scarcity_factor = 1.0 if stock is None else clamp(1.0 - (float(stock) / 100.0))
        score += weights.W2 * scarcity_factor

    # 3. Irreversibility
    is_reversible = payload.get("is_reversible")
    if is_reversible is None:
        is_reversible = payload.get("reversible", True)

    if not is_reversible:
        score += weights.W3

    # 4. Deadline Urgency (Graded SLA)
    has_deadline = payload.get("has_explicit_deadline")
    if has_deadline is None:
        has_deadline = payload.get("deadline") is not None

    if has_deadline:
        deadline_val = payload.get("deadline_epoch") or payload.get("deadline")
        if deadline_val is not None:
            try:
                if isinstance(deadline_val, (int, float)):
                    secs_left = max(float(deadline_val) - time.time(), 0.0)
                else:
                    secs_left = 60.0  # Fallback default for ISO string parsing
                urgency = clamp(1.0 - (secs_left / 600.0))
                score += weights.W4 * urgency
            except Exception:
                pass

    return clamp(score, 0.0, 10.0)


def compute_final_score(
    intrinsic: float,
    payload: dict[str, Any],
    state: SystemState,
    time_waiting: float = 0.0,
    weights: ScoringWeights = ScoringWeights(),
) -> float:
    score = intrinsic
    score += state.queue_depth_normalised * weights.W5
    score += time_waiting * weights.W6
    score += state.worker_availability * weights.W7
    score += state.queue_velocity * weights.W9

    producer_id = payload.get("source") or payload.get("producer_id", "")
    is_within_quota = payload.get("is_within_quota", True)
    if producer_id and not state.producer_quotas.get(producer_id, is_within_quota):
        score += weights.W8  # W8 is negative (-1.5)

    if payload.get("is_health_check", False):
        score += weights.W_MAX

    return min(10.0, score)


def determine_action(
    score: float,
    payload: dict[str, Any],
    state: SystemState,
    thresholds: Thresholds = Thresholds(),
) -> Action:
    # Rule 1: High Urgency -> Execute (Fast Lane)
    if score >= thresholds.EXECUTE:
        if state.fast_lane_full:
            has_monetary = payload.get("has_monetary_value") or (payload.get("amount") is not None and payload.get("amount", 0) > 0)
            is_reversible = payload.get("is_reversible") if payload.get("is_reversible") is not None else payload.get("reversible", True)
            is_irreversible = not is_reversible
            if has_monetary or is_irreversible:
                return Action.EXECUTE
            # Spill over non-monetary high priority events to Micro-Batch lane instead of false backpressure drop
            return Action.BATCH
        return Action.EXECUTE

    # Rule 2: Moderate Urgency -> Micro-Batch Lane
    if score >= thresholds.BATCH:
        return Action.BATCH

    # Rule 3: Low / Negative Urgency -> Cold Lane / Defer (NO SHEDDING POLICY)
    # Events are never dropped; under sustained overload, low-priority events sit in cold queue.
    return Action.DEFER


def score_event(
    event: dict[str, Any],
    state: SystemState,
    time_waiting: float = 0.0,
    weights: ScoringWeights = ScoringWeights(),
    thresholds: Thresholds = Thresholds(),
) -> dict[str, Any]:
    # Extract payload or normalized top-level dictionary fields
    payload = event.get("payload")
    if not payload:
        payload = event

    # Intrinsic calculation
    c_monetary = 0.0
    has_monetary = payload.get("has_monetary_value") or (payload.get("amount") is not None and payload.get("amount", 0) > 0)
    if has_monetary:
        amt = float(payload.get("amount") or 0.0)
        c_monetary = weights.W1 * math.log(amt + 1.0)

    affects_scarcity = payload.get("affects_physical_scarcity")
    if affects_scarcity is None:
        affects_scarcity = payload.get("affects_scarcity", False)
    
    stock = payload.get("stock_remaining")
    scarcity_factor = 1.0 if stock is None else clamp(1.0 - (float(stock) / 100.0))
    c_scarcity = (weights.W2 * scarcity_factor) if affects_scarcity else 0.0

    is_reversible = payload.get("is_reversible")
    if is_reversible is None:
        is_reversible = payload.get("reversible", True)
    c_irreversibility = weights.W3 if not is_reversible else 0.0

    c_deadline = 0.0
    has_deadline = payload.get("has_explicit_deadline") or (payload.get("deadline") is not None)
    if has_deadline:
        deadline_val = payload.get("deadline_epoch") or payload.get("deadline")
        if deadline_val is not None:
            try:
                secs_left = max(float(deadline_val) - time.time(), 0.0) if isinstance(deadline_val, (int, float)) else 60.0
                c_deadline = weights.W4 * clamp(1.0 - (secs_left / 600.0))
            except Exception:
                pass

    intrinsic = clamp(c_monetary + c_scarcity + c_irreversibility + c_deadline, 0.0, 10.0)

    # State adjustment calculation
    c_queue = state.queue_depth_normalised * weights.W5
    c_anti_starve = time_waiting * weights.W6
    c_worker = state.worker_availability * weights.W7
    c_velocity = state.queue_velocity * weights.W9

    producer_id = payload.get("source") or payload.get("producer_id", "")
    is_within_quota = payload.get("is_within_quota", True)
    c_quota = weights.W8 if (producer_id and not state.producer_quotas.get(producer_id, is_within_quota)) else 0.0
    c_health = weights.W_MAX if payload.get("is_health_check", False) else 0.0

    raw_final = intrinsic + c_queue + c_anti_starve + c_worker + c_velocity + c_quota + c_health
    final = clamp(raw_final, 0.0, 10.0)
    action = determine_action(final, payload, state, thresholds)

    # Interdependent Event Check: Scarcity Race Condition Lock
    product_id = payload.get("product_id") or payload.get("item_id")
    if affects_scarcity and product_id and action == Action.EXECUTE:
        success, remaining_stock, reason = inventory_lock.try_reserve_stock(product_id)
        if not success:
            action = Action.BACKPRESSURE
            final = 0.0  # Deprioritize/Cancel

    band = get_display_band(final)

    return {
        "event_id": event.get("event_id", "unknown"),
        "type": event.get("type") or payload.get("type", "unknown"),
        "source": producer_id,
        "intrinsic_score": round(intrinsic, 3),
        "final_score": round(final, 3),
        "display_band": band.value,
        "action": action.value,
        "components": {
            "monetary": round(c_monetary, 3),
            "irreversibility": round(c_irreversibility, 3),
            "scarcity": round(c_scarcity, 3),
            "deadline": round(c_deadline, 3),
            "queue_pressure": round(c_queue, 3),
            "queue_velocity": round(c_velocity, 3),
            "anti_starvation": round(c_anti_starve, 3),
            "worker_adj": round(c_worker, 3),
            "quota_penalty": round(c_quota, 3),
            "health_boost": round(c_health, 3),
        },
    }
