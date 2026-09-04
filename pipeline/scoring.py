"""
pipeline/scoring.py

Dynamic Criticality Scoring Engine — the core differentiator.

This module is a set of PURE FUNCTIONS:
    event payload + system state → continuous score → routing action

No event type is inspected anywhere.  A payment scores high because its
payload happens to carry has_monetary_value=True, is_reversible=False —
the engine doesn't know or care it's called "payment."

Two-stage formula:
    1. Intrinsic Criticality  — computed from the event's own payload.
    2. Live State Adjustment  — folds in queue depth, worker availability,
       producer quota, and health-check status at the moment of evaluation.

Decision thresholds turn the continuous score into an action:
    EXECUTE → fast lane  |  BATCH → micro-batch  |  DEFER → cold queue  |  SHED

A hard-floor guarantee ensures events with monetary value or irreversible
effects can NEVER be shed, regardless of system pressure.

A display-only bucketing function maps scores to human-readable bands
(Critical / Standard / Best-effort) for dashboard reporting — it never
touches routing logic.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


# ---------------------------------------------------------------------------
# Scoring weights — all tunable, no magic
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ScoringWeights:
    """
    Tunable weight parameters for the scoring formula.

    W1–W4: intrinsic criticality components.
    W5–W8: live system state adjustment components.
    W_MAX: health-check / canary override weight.
    """
    W1: float = 1.0     # monetary value weight (scaled by log(amount+1))
    W2: float = 2.0     # physical scarcity weight
    W3: float = 3.0     # irreversibility weight
    W4: float = 1.5     # deadline urgency weight
    W5: float = 0.5     # queue depth pressure
    W6: float = 0.3     # time-already-waiting boost (anti-starvation)
    W7: float = 0.5     # worker availability dampener
    W8: float = 2.0     # quota violation penalty
    W_MAX: float = 9.5  # health-check / canary near-max weight


# ---------------------------------------------------------------------------
# Decision thresholds
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Thresholds:
    """Score boundaries for routing decisions."""
    EXECUTE: float = 6.0   # above → fast lane
    BATCH: float = 3.5     # above → micro-batch
    DEFER: float = 1.5     # above → cold queue; at or below → shed-eligible


# ---------------------------------------------------------------------------
# Display bands (Gap Fix #2 — never used for routing)
# ---------------------------------------------------------------------------

class DisplayBand(str, Enum):
    """Human-readable priority tiers for dashboard reporting only."""
    CRITICAL = "Critical"
    STANDARD = "Standard"
    BEST_EFFORT = "Best-effort"


def get_display_band(score: float) -> DisplayBand:
    """
    Map a continuous score to a display band for dashboard reporting.

    This function is NEVER used in routing decisions — it exists purely
    so the dashboard can show per-tier breakdowns as the problem statement
    requires.

    Bands:
        ≥ 7.0  → Critical
        4.0–6.9 → Standard
        < 4.0  → Best-effort
    """
    if score >= 7.0:
        return DisplayBand.CRITICAL
    elif score >= 4.0:
        return DisplayBand.STANDARD
    else:
        return DisplayBand.BEST_EFFORT


# ---------------------------------------------------------------------------
# Routing actions
# ---------------------------------------------------------------------------

class Action(str, Enum):
    """Routing outcome for a scored event."""
    EXECUTE = "execute"           # fast lane, immediate
    BATCH = "batch"               # micro-batch window
    DEFER = "defer"               # cold queue, periodic re-score
    SHED = "shed"                 # drop (logged, never silent)
    BACKPRESSURE = "backpressure" # fast lane full → reject upstream


# ---------------------------------------------------------------------------
# System state snapshot (read by the scoring engine)
# ---------------------------------------------------------------------------

@dataclass
class SystemState:
    """
    Live system metrics read at the moment of scoring.

    All values are normalised to [0.0, 1.0] unless noted.
    The pipeline engine updates this continuously; the scoring engine
    reads it as a snapshot — no mutation.
    """
    queue_depth_normalised: float = 0.0     # 0 = empty, 1 = at capacity
    worker_availability: float = 1.0        # 0 = all busy, 1 = all free
    fast_lane_full: bool = False            # all fast-lane workers busy
    producer_quotas: dict[str, bool] = field(
        default_factory=dict
    )  # producer_id → within_quota (True = ok)


# ---------------------------------------------------------------------------
# Component 1 — Intrinsic Criticality
# ---------------------------------------------------------------------------

def compute_intrinsic_criticality(
    payload: dict[str, Any],
    weights: ScoringWeights = ScoringWeights(),
) -> float:
    """
    Compute intrinsic criticality from the event's own payload.

    Formula:
        (hasMonetaryValue × W1 × log(amount + 1))
      + (affectsPhysicalScarcity × W2)
      + (isReversible ? 0 : W3)
      + (hasExplicitDeadline × W4 × urgencyFromDeadline)

    An event with no recognisable scoring attributes defaults to 0.0
    (fail-safe to lowest urgency — default-deny posture).
    """
    score = 0.0

    # Monetary value
    if payload.get("has_monetary_value", False):
        amount = payload.get("amount", 0)
        score += weights.W1 * math.log(amount + 1)

    # Physical scarcity
    if payload.get("affects_physical_scarcity", False):
        score += weights.W2

    # Irreversibility (irreversible → higher stakes)
    if not payload.get("is_reversible", True):
        score += weights.W3

    # Deadline urgency
    if payload.get("has_explicit_deadline", False):
        deadline = payload.get("deadline_epoch")
        if deadline is not None:
            seconds_left = max(deadline - time.time(), 0.0)
            # urgency rises as deadline approaches: 1/(seconds_left + 1)
            urgency = 1.0 / (seconds_left + 1.0)
            score += weights.W4 * urgency

    return score


# ---------------------------------------------------------------------------
# Component 2 — Live System State Adjustment
# ---------------------------------------------------------------------------

def compute_final_score(
    intrinsic: float,
    payload: dict[str, Any],
    state: SystemState,
    time_waiting: float = 0.0,
    weights: ScoringWeights = ScoringWeights(),
) -> float:
    """
    Adjust intrinsic criticality with live system state.

    Formula:
        intrinsicCriticality
      + (queueDepthNormalized × W5)
      + (timeAlreadyWaitingInQueue × W6)
      - (currentWorkerAvailability × W7)
      + (isProducerWithinQuota ? 0 : -W8)
      + (isHealthCheckOrCanaryEvent × W_MAX)

    The result is a continuous score used for threshold-based routing.
    """
    score = intrinsic

    # Queue pressure: higher depth → boost urgency (process faster)
    score += state.queue_depth_normalised * weights.W5

    # Anti-starvation: waiting events climb slowly
    score += time_waiting * weights.W6

    # Worker availability: more free workers → less urgency boost needed
    score -= state.worker_availability * weights.W7

    # Quota penalty: producer over quota → score penalised
    producer_id = payload.get("producer_id", "")
    if producer_id and not state.producer_quotas.get(producer_id, True):
        score -= weights.W8

    # Health-check / canary: near-maximum priority (Amazon-derived)
    if payload.get("is_health_check", False):
        score += weights.W_MAX

    return score


# ---------------------------------------------------------------------------
# Routing decision
# ---------------------------------------------------------------------------

def determine_action(
    score: float,
    payload: dict[str, Any],
    state: SystemState,
    thresholds: Thresholds = Thresholds(),
) -> Action:
    """
    Turn a continuous score into a routing action.

    Decision logic:
        1. If score > EXECUTE_THRESHOLD and fast lane is full:
           → BACKPRESSURE (Gap Fix #1 — never shed, never queue behind lower)
        2. If score > EXECUTE_THRESHOLD: → EXECUTE
        3. If score > BATCH_THRESHOLD:   → BATCH
        4. If score > DEFER_THRESHOLD:   → DEFER
        5. Otherwise, shed-eligible — but ONLY if the event is reversible
           AND has no monetary value.  If either condition fails, DEFER
           instead (hard floor guarantee).
    """
    if score > thresholds.EXECUTE:
        if state.fast_lane_full:
            return Action.BACKPRESSURE
        return Action.EXECUTE

    if score > thresholds.BATCH:
        return Action.BATCH

    if score > thresholds.DEFER:
        return Action.DEFER

    # Below DEFER_THRESHOLD → shed-eligible, but check hard floor
    is_reversible = payload.get("is_reversible", True)
    has_monetary = payload.get("has_monetary_value", False)

    if is_reversible and not has_monetary:
        return Action.SHED

    # Hard floor: monetary or irreversible events are NEVER shed
    return Action.DEFER


# ---------------------------------------------------------------------------
# Convenience: full scoring pipeline in one call
# ---------------------------------------------------------------------------

def score_event(
    event: dict[str, Any],
    state: SystemState,
    time_waiting: float = 0.0,
    weights: ScoringWeights = ScoringWeights(),
    thresholds: Thresholds = Thresholds(),
) -> dict[str, Any]:
    """
    Score an event end-to-end and return the full decision record.

    Returns:
        {
            "event_id": str,
            "intrinsic_score": float,
            "final_score": float,
            "display_band": str,
            "action": str,
        }
    """
    payload = event.get("payload", {})
    intrinsic = compute_intrinsic_criticality(payload, weights)
    final = compute_final_score(intrinsic, payload, state, time_waiting, weights)
    action = determine_action(final, payload, state, thresholds)
    band = get_display_band(final)

    return {
        "event_id": event.get("event_id", "unknown"),
        "intrinsic_score": round(intrinsic, 3),
        "final_score": round(final, 3),
        "display_band": band.value,
        "action": action.value,
    }
