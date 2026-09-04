"""
tests/test_generator.py

Unit tests for simulator.generator.

Covers:
  - generate_event() output structure
  - All five event types and their required payload keys
  - UUID4 uniqueness
  - Timestamp semantics (creation time, not send time)
  - pick_event_type() distribution (chi-square sanity)
  - Forced event_type argument
"""

import time
import uuid
from collections import Counter

import pytest

from simulator.generator import generate_event, pick_event_type
from simulator.config import EVENT_TYPE_WEIGHTS

VALID_TYPES = {"order", "payment", "inventory", "click", "log"}


# ---------------------------------------------------------------------------
# Structure tests
# ---------------------------------------------------------------------------


def test_generate_event_has_required_fields():
    event = generate_event()
    assert "event_id" in event
    assert "event_type" in event
    assert "timestamp" in event
    assert "payload" in event


def test_event_type_is_valid():
    for _ in range(50):
        event = generate_event()
        assert event["event_type"] in VALID_TYPES


def test_event_id_is_valid_uuid4():
    event = generate_event()
    parsed = uuid.UUID(event["event_id"], version=4)
    assert str(parsed) == event["event_id"]


def test_event_ids_are_unique():
    ids = {generate_event()["event_id"] for _ in range(200)}
    assert len(ids) == 200  # no collisions in 200 samples


def test_timestamp_is_close_to_now():
    before = time.time()
    event = generate_event()
    after = time.time()
    assert before <= event["timestamp"] <= after


def test_payload_is_dict():
    for _ in range(10):
        event = generate_event()
        assert isinstance(event["payload"], dict)
        assert len(event["payload"]) > 0


# ---------------------------------------------------------------------------
# Per-type payload tests
# ---------------------------------------------------------------------------


def test_order_payload_fields():
    event = generate_event(event_type="order")
    p = event["payload"]
    for key in ("order_id", "user_id", "product_id", "quantity", "amount", "currency", "status"):
        assert key in p, f"Missing key in order payload: {key}"
    assert isinstance(p["quantity"], int) and p["quantity"] >= 1
    assert isinstance(p["amount"], float) and p["amount"] > 0


def test_payment_payload_fields():
    event = generate_event(event_type="payment")
    p = event["payload"]
    for key in ("payment_id", "order_id", "user_id", "amount", "currency", "method", "status"):
        assert key in p
    assert p["method"] in ("upi", "card", "netbanking", "wallet")
    assert p["status"] in ("success", "pending", "failed")


def test_inventory_payload_fields():
    event = generate_event(event_type="inventory")
    p = event["payload"]
    for key in ("product_id", "warehouse_id", "quantity", "operation"):
        assert key in p
    assert p["operation"] in ("stock_update", "reservation", "release")
    assert isinstance(p["quantity"], int) and p["quantity"] >= 0


def test_click_payload_fields():
    event = generate_event(event_type="click")
    p = event["payload"]
    for key in ("user_id", "product_id", "page", "action", "session_id"):
        assert key in p
    assert p["action"] in ("view", "click", "search", "add_to_cart")


def test_log_payload_fields():
    event = generate_event(event_type="log")
    p = event["payload"]
    for key in ("service", "level", "message", "instance_id"):
        assert key in p
    assert p["level"] in ("INFO", "WARN", "ERROR")


# ---------------------------------------------------------------------------
# Forced event_type argument
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("etype", list(VALID_TYPES))
def test_forced_event_type(etype: str):
    event = generate_event(event_type=etype)
    assert event["event_type"] == etype


# ---------------------------------------------------------------------------
# Distribution test (pick_event_type)
# ---------------------------------------------------------------------------


def test_pick_event_type_distribution():
    """
    Generate 10 000 picks and verify the observed frequency of each type
    is within ±5 percentage points of the configured weight.
    """
    n = 10_000
    counts = Counter(pick_event_type() for _ in range(n))
    total = sum(counts.values())

    for etype, expected_weight in EVENT_TYPE_WEIGHTS.items():
        observed = counts[etype] / total
        tolerance = 0.05  # ±5 pp
        assert abs(observed - expected_weight) < tolerance, (
            f"{etype}: expected ~{expected_weight:.2%}, got {observed:.2%}"
        )


def test_pick_event_type_returns_valid_type():
    for _ in range(100):
        assert pick_event_type() in VALID_TYPES
