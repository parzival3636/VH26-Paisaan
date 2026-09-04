from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


@dataclass(frozen=True)
class ScoringWeights:
    W1: float = 1.0
    W2: float = 2.0
    W3: float = 3.0
    W4: float = 1.5
    W5: float = 0.5
    W6: float = 0.3
    W7: float = 0.5
    W8: float = 2.0
    W_MAX: float = 9.5


@dataclass(frozen=True)
class Thresholds:
    EXECUTE: float = 6.0
    BATCH: float = 3.5
    DEFER: float = 1.5


class DisplayBand(str, Enum):
    CRITICAL = "Critical"
    STANDARD = "Standard"
    BEST_EFFORT = "Best-effort"


def get_display_band(score: float) -> DisplayBand:
    if score >= 7.0:
        return DisplayBand.CRITICAL
    elif score >= 4.0:
        return DisplayBand.STANDARD
    else:
        return DisplayBand.BEST_EFFORT


class Action(str, Enum):
    EXECUTE = "execute"
    BATCH = "batch"
    DEFER = "defer"
    SHED = "shed"
    BACKPRESSURE = "backpressure"


@dataclass
class SystemState:
    queue_depth_normalised: float = 0.0
    worker_availability: float = 1.0
    fast_lane_full: bool = False
    producer_quotas: dict[str, bool] = field(default_factory=dict)


def compute_intrinsic_criticality(
    payload: dict[str, Any],
    weights: ScoringWeights = ScoringWeights(),
) -> float:
    score = 0.0

    if payload.get("has_monetary_value", False):
        amount = payload.get("amount", 0)
        score += weights.W1 * math.log(amount + 1)

    if payload.get("affects_physical_scarcity", False):
        score += weights.W2

    if not payload.get("is_reversible", True):
        score += weights.W3

    if payload.get("has_explicit_deadline", False):
        deadline = payload.get("deadline_epoch")
        if deadline is not None:
            seconds_left = max(deadline - time.time(), 0.0)
            urgency = 1.0 / (seconds_left + 1.0)
            score += weights.W4 * urgency

    return score


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
    score -= state.worker_availability * weights.W7

    producer_id = payload.get("producer_id", "")
    if producer_id and not state.producer_quotas.get(producer_id, True):
        score -= weights.W8

    if payload.get("is_health_check", False):
        score += weights.W_MAX

    return score


def determine_action(
    score: float,
    payload: dict[str, Any],
    state: SystemState,
    thresholds: Thresholds = Thresholds(),
) -> Action:
    if score > thresholds.EXECUTE:
        if state.fast_lane_full:
            return Action.BACKPRESSURE
        return Action.EXECUTE

    if score > thresholds.BATCH:
        return Action.BATCH

    if score > thresholds.DEFER:
        return Action.DEFER

    is_reversible = payload.get("is_reversible", True)
    has_monetary = payload.get("has_monetary_value", False)

    if is_reversible and not has_monetary:
        return Action.SHED

    return Action.DEFER


def score_event(
    event: dict[str, Any],
    state: SystemState,
    time_waiting: float = 0.0,
    weights: ScoringWeights = ScoringWeights(),
    thresholds: Thresholds = Thresholds(),
) -> dict[str, Any]:
    payload = event.get("payload", {})

    c_monetary = 0.0
    if payload.get("has_monetary_value", False):
        amount = payload.get("amount", 0)
        c_monetary = weights.W1 * math.log(amount + 1)

    c_scarcity = weights.W2 if payload.get("affects_physical_scarcity", False) else 0.0
    c_irreversibility = weights.W3 if not payload.get("is_reversible", True) else 0.0

    c_deadline = 0.0
    if payload.get("has_explicit_deadline", False):
        deadline = payload.get("deadline_epoch")
        if deadline is not None:
            seconds_left = max(deadline - time.time(), 0.0)
            c_deadline = weights.W4 * (1.0 / (seconds_left + 1.0))

    intrinsic = c_monetary + c_scarcity + c_irreversibility + c_deadline

    c_queue = state.queue_depth_normalised * weights.W5
    c_anti_starve = time_waiting * weights.W6
    c_worker = -(state.worker_availability * weights.W7)

    c_quota = 0.0
    producer_id = payload.get("producer_id", "")
    if producer_id and not state.producer_quotas.get(producer_id, True):
        c_quota = -weights.W8

    c_health = weights.W_MAX if payload.get("is_health_check", False) else 0.0

    final = intrinsic + c_queue + c_anti_starve + c_worker + c_quota + c_health
    action = determine_action(final, payload, state, thresholds)
    band = get_display_band(final)

    return {
        "event_id": event.get("event_id", "unknown"),
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
            "anti_starvation": round(c_anti_starve, 3),
            "worker_adj": round(c_worker, 3),
            "quota_penalty": round(c_quota, 3),
            "health_boost": round(c_health, 3),
        },
    }
