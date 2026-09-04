"""
tests/test_ingest.py

Tests for Sub-component 1: Ingestion Gateway (POST /ingest).

Validates:
  - Step 1: Schema validation & Pydantic error response (422) on bad payloads.
  - Step 2: X-Source header producer quota tracking and penalty term assignment.
  - Step 3: Ingestion timestamp stamping.
  - Step 4: Scoring Engine handoff and 202 Accepted output structure.
  - Compatibility with both flat microservice payloads and nested simulator events.
"""

import pytest
from fastapi.testclient import TestClient
from pipeline.main import app

client = TestClient(app)


def test_schema_validation_failure():
    """Step 1: Test invalid payload produces 422 Unprocessable Entity."""
    # Missing required event_id
    bad_payload = {
        "type": "payment",
        "amount": 200.0,
    }
    response = client.post("/ingest", json=bad_payload)
    assert response.status_code == 422


def test_ingest_exact_spec_payload():
    """Test ingestion with exact payload structure from specification prompt."""
    payload = {
        "event_id": "evt_8f3a2b91",
        "type": "payment",
        "amount": 200.00,
        "reversible": False,
        "deadline": None,
        "order_id": "ord_5521",
    }
    headers = {"X-Source": "checkout-service"}

    response = client.post("/ingest", json=payload, headers=headers)
    assert response.status_code == 202

    data = response.json()
    assert data["status"] == "accepted"
    assert data["event_id"] == "evt_8f3a2b91"
    assert data["producer_id"] == "checkout-service"
    assert data["is_within_quota"] is True
    assert "ingestion_time" in data

    decision = data["decision"]
    assert decision["event_id"] == "evt_8f3a2b91"
    assert decision["action"] == "execute"  # High priority payment executes immediately
    assert decision["display_band"] == "Critical"
    assert decision["final_score"] > 6.0


def test_ingest_simulator_nested_event():
    """Test ingestion with simulator event format (nested payload)."""
    event = {
        "event_id": "evt_sim_123",
        "event_type": "click",
        "timestamp": 1725444000.0,
        "payload": {
            "page": "home",
            "action": "view",
            "has_monetary_value": False,
            "is_reversible": True,
            "producer_id": "frontend",
        },
    }
    headers = {"X-Source": "frontend"}

    response = client.post("/ingest", json=event, headers=headers)
    assert response.status_code == 202

    data = response.json()
    assert data["event_id"] == "evt_sim_123"
    assert data["producer_id"] == "frontend"
    assert "decision" in data
    # Low score click event should be batch/defer/shed eligible
    assert data["decision"]["action"] in ("batch", "defer", "shed")


def test_producer_quota_violation_penalty():
    """Step 2: Test producer exceeding quota gets score penalized."""
    import time
    from pipeline import redis_client

    # Directly saturate the in-memory quota dict to simulate over-quota
    window_seconds = redis_client.DEFAULT_QUOTA_WINDOW
    current_window = int(time.time() // window_seconds)
    redis_client._in_memory_quotas["burst-test-producer"] = (
        current_window,
        redis_client.DEFAULT_QUOTA_LIMIT + 10,
    )
    # Force in-memory fallback (bypass Redis for test isolation)
    original_disabled = redis_client._redis_disabled
    redis_client._redis_disabled = True

    try:
        headers = {"X-Source": "burst-test-producer"}
        payload = {
            "event_id": "evt_burst_1",
            "type": "log",
            "message": "test log",
        }

        response = client.post("/ingest", json=payload, headers=headers)
        assert response.status_code == 202

        data = response.json()
        assert data["producer_id"] == "burst-test-producer"
        assert data["is_within_quota"] is False
    finally:
        redis_client._redis_disabled = original_disabled

