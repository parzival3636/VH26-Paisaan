"""
tests/test_scoring.py

Unit tests for pipeline.scoring — the dynamic criticality engine.

Covers:
  - Intrinsic criticality computation for all event types
  - ₹200 vs ₹2,00,000 payment differentiation (the motivating question)
  - Live system state adjustment (queue pressure, worker availability)
  - Hard floor guarantee: monetary/irreversible events NEVER shed
  - Backpressure branch: high-score + fast lane full → BACKPRESSURE
  - Display bucketing: correct band assignment, never used for routing
  - Full end-to-end score_event() pipeline
  - Health check near-max priority (Amazon-derived)
  - Producer quota penalty
  - Anti-starvation: deferred events climb with wait time
  - Unrecognised events default to 0 intrinsic (fail-safe)
"""

import math
import time

import pytest

from pipeline.scoring import (
    Action,
    DisplayBand,
    ScoringWeights,
    SystemState,
    Thresholds,
    compute_final_score,
    compute_intrinsic_criticality,
    determine_action,
    get_display_band,
    score_event,
)


# ---------------------------------------------------------------------------
# Helpers — canonical payloads
# ---------------------------------------------------------------------------

def _payment_payload(amount: float = 200.0) -> dict:
    return {
        "has_monetary_value": True,
        "amount": amount,
        "is_reversible": False,
        "affects_physical_scarcity": False,
        "has_explicit_deadline": False,
        "deadline_epoch": None,
        "is_health_check": False,
        "producer_id": "payment-service",
    }


def _click_payload() -> dict:
    return {
        "has_monetary_value": False,
        "is_reversible": True,
        "affects_physical_scarcity": False,
        "has_explicit_deadline": False,
        "deadline_epoch": None,
        "is_health_check": False,
        "producer_id": "frontend",
    }


def _health_check_payload() -> dict:
    return {
        "has_monetary_value": False,
        "is_reversible": True,
        "affects_physical_scarcity": False,
        "has_explicit_deadline": False,
        "deadline_epoch": None,
        "is_health_check": True,
        "producer_id": "gateway",
    }


def _inventory_scarce_payload() -> dict:
    return {
        "has_monetary_value": False,
        "is_reversible": True,
        "affects_physical_scarcity": True,
        "has_explicit_deadline": False,
        "deadline_epoch": None,
        "is_health_check": False,
        "producer_id": "inventory-service",
    }


CALM = SystemState()  # all queues empty, all workers free
STRESSED = SystemState(
    queue_depth_normalised=0.9,
    worker_availability=0.1,
    fast_lane_full=False,
)
SATURATED = SystemState(
    queue_depth_normalised=1.0,
    worker_availability=0.0,
    fast_lane_full=True,
)
W = ScoringWeights()
T = Thresholds()


# ---------------------------------------------------------------------------
# 1. Intrinsic Criticality
# ---------------------------------------------------------------------------

class TestIntrinsicCriticality:

    def test_payment_200_has_positive_intrinsic(self):
        score = compute_intrinsic_criticality(_payment_payload(200))
        # W1 * log(201) + W3 = 1.0 * log(201) + 3.0 ≈ 8.3
        assert score > 7.0

    def test_payment_200000_scores_higher_than_200(self):
        """The motivating question: ₹2,00,000 must score higher than ₹200."""
        low = compute_intrinsic_criticality(_payment_payload(200))
        high = compute_intrinsic_criticality(_payment_payload(200_000))
        assert high > low
        # log(200001) ≈ 12.2 vs log(201) ≈ 5.3 → meaningful gap
        assert (high - low) > 1.0

    def test_click_scores_near_zero(self):
        score = compute_intrinsic_criticality(_click_payload())
        assert score == 0.0

    def test_health_check_intrinsic_is_zero(self):
        """Health check boost is a system-state adjustment, not intrinsic."""
        score = compute_intrinsic_criticality(_health_check_payload())
        assert score == 0.0

    def test_inventory_scarcity_adds_W2(self):
        score = compute_intrinsic_criticality(_inventory_scarce_payload())
        assert score == pytest.approx(W.W2)

    def test_empty_payload_defaults_to_zero(self):
        """Unrecognised event → fail-safe to lowest urgency."""
        score = compute_intrinsic_criticality({})
        assert score == 0.0


# ---------------------------------------------------------------------------
# 2. Live System State Adjustment
# ---------------------------------------------------------------------------

class TestFinalScore:

    def test_calm_system_barely_changes_intrinsic(self):
        intrinsic = compute_intrinsic_criticality(_payment_payload(200))
        final = compute_final_score(intrinsic, _payment_payload(200), CALM)
        # Under calm: queue=0, avail=1.0 → adjustment = W7*1.0 = -1.0
        # Final = intrinsic + W7*worker_availability = intrinsic + (-1.0)*1.0
        expected = intrinsic + W.W7 * CALM.worker_availability
        assert abs(final - expected) < 0.01

    def test_stressed_system_boosts_score(self):
        intrinsic = compute_intrinsic_criticality(_payment_payload(200))
        final_calm = compute_final_score(intrinsic, _payment_payload(200), CALM)
        final_stress = compute_final_score(intrinsic, _payment_payload(200), STRESSED)
        # Stress adds queue_depth*W5 and reduces worker_avail*W7
        assert final_stress > final_calm

    def test_health_check_gets_near_max_boost(self):
        intrinsic = compute_intrinsic_criticality(_health_check_payload())
        final = compute_final_score(intrinsic, _health_check_payload(), CALM)
        # Should be near W_MAX - W7 ≈ 9.0
        assert final > 8.0

    def test_quota_violation_penalises_score(self):
        payload = _click_payload()
        state_normal = SystemState(producer_quotas={"frontend": True})
        state_over = SystemState(producer_quotas={"frontend": False})
        intrinsic = compute_intrinsic_criticality(payload)
        score_ok = compute_final_score(intrinsic, payload, state_normal)
        score_bad = compute_final_score(intrinsic, payload, state_over)
        assert score_bad < score_ok
        assert (score_ok - score_bad) == pytest.approx(-W.W8)

    def test_wait_time_boosts_deferred_events(self):
        """Anti-starvation: a deferred event climbs with wait time."""
        payload = _click_payload()
        intrinsic = compute_intrinsic_criticality(payload)
        score_0s = compute_final_score(intrinsic, payload, CALM, time_waiting=0.0)
        score_10s = compute_final_score(intrinsic, payload, CALM, time_waiting=10.0)
        assert score_10s > score_0s
        assert (score_10s - score_0s) == pytest.approx(10.0 * W.W6)


# ---------------------------------------------------------------------------
# 3. Routing Decisions
# ---------------------------------------------------------------------------

class TestDetermineAction:

    def test_high_score_executes(self):
        action = determine_action(8.0, _payment_payload(), CALM)
        assert action == Action.EXECUTE

    def test_high_score_plus_full_fast_lane_monetary_irreversible_still_executes(self):
        """Monetary + irreversible events override backpressure and always execute."""
        action = determine_action(8.0, _payment_payload(), SATURATED)
        assert action == Action.EXECUTE

    def test_high_score_full_fast_lane_reversible_spills_to_batch(self):
        """Reversible, non-monetary events gracefully degrade to batch lane when fast lane is full."""
        action = determine_action(8.0, _click_payload(), SATURATED)
        assert action == Action.BATCH

    def test_medium_score_batches(self):
        action = determine_action(4.5, _click_payload(), CALM)
        assert action == Action.BATCH

    def test_low_score_defers(self):
        action = determine_action(2.0, _click_payload(), CALM)
        assert action == Action.DEFER

    def test_very_low_reversible_no_money_defers(self):
        """No-shedding policy: low-priority events DEFER instead of SHED."""
        action = determine_action(0.5, _click_payload(), CALM)
        assert action == Action.DEFER

    def test_payment_never_shed_even_at_lowest_score(self):
        """Hard floor: monetary + irreversible → DEFER, never SHED."""
        action = determine_action(-5.0, _payment_payload(), CALM)
        assert action == Action.DEFER  # NOT SHED

    def test_irreversible_event_never_shed(self):
        """Even a non-monetary but irreversible event won't be shed."""
        payload = {"is_reversible": False, "has_monetary_value": False}
        action = determine_action(0.1, payload, CALM)
        assert action == Action.DEFER

    def test_monetary_reversible_event_never_shed(self):
        payload = {"is_reversible": True, "has_monetary_value": True, "amount": 50.0}
        action = determine_action(0.1, payload, CALM)
        assert action == Action.DEFER


# ---------------------------------------------------------------------------
# 4. Display Bucketing (Gap Fix #2)
# ---------------------------------------------------------------------------

class TestDisplayBand:

    def test_critical_band(self):
        assert get_display_band(7.0) == DisplayBand.CRITICAL
        assert get_display_band(10.0) == DisplayBand.CRITICAL

    def test_standard_band(self):
        assert get_display_band(4.0) == DisplayBand.STANDARD
        assert get_display_band(5.9) == DisplayBand.STANDARD

    def test_best_effort_band(self):
        assert get_display_band(2.9) == DisplayBand.BEST_EFFORT
        assert get_display_band(0.0) == DisplayBand.BEST_EFFORT
        assert get_display_band(-1.0) == DisplayBand.BEST_EFFORT


# ---------------------------------------------------------------------------
# 5. End-to-End score_event()
# ---------------------------------------------------------------------------

class TestScoreEvent:

    def test_payment_200_under_spike_full_trace(self):
        """
        The worked example from the architecture doc:
        ₹200 payment under mid-spike → score ≈8.9, band=Critical, action=execute
        """
        event = {
            "event_id": "evt_8f3a2b91",
            "event_type": "payment",
            "timestamp": time.time(),
            "payload": _payment_payload(200),
        }
        result = score_event(event, STRESSED)
        assert result["event_id"] == "evt_8f3a2b91"
        assert result["intrinsic_score"] > 7.0
        assert result["final_score"] > T.EXECUTE
        assert result["display_band"] == "Critical"
        assert result["action"] == "execute"

    def test_click_under_spike_gets_low_score(self):
        event = {
            "event_id": "evt_click_441",
            "event_type": "click",
            "timestamp": time.time(),
            "payload": _click_payload(),
        }
        result = score_event(event, STRESSED)
        assert result["intrinsic_score"] == 0.0
        assert result["final_score"] < T.EXECUTE
        assert result["display_band"] == "Best-effort"

    def test_health_check_scores_critical(self):
        event = {
            "event_id": "evt_health_01",
            "event_type": "log",
            "timestamp": time.time(),
            "payload": _health_check_payload(),
        }
        result = score_event(event, CALM)
        assert result["display_band"] == "Critical"
        assert result["action"] == "execute"

    def test_unknown_event_defaults_safe(self):
        event = {
            "event_id": "evt_mystery",
            "event_type": "unknown",
            "timestamp": time.time(),
            "payload": {},
        }
        result = score_event(event, CALM)
        assert result["intrinsic_score"] == 0.0
        assert result["action"] in ("defer", "batch")
