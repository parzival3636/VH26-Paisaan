"""
tests/test_pipeline.py

Integration tests for the FastAPI pipeline receiver.

Uses httpx.AsyncClient with ASGITransport — no live server required.
Tests:
  - Valid event accepted (200 + "accepted" status)
  - Invalid event_type rejected (422)
  - Missing fields rejected (422)
  - /health returns ok
  - /stats returns expected shape
  - Correct event_id echoed in response
"""

import time
import uuid

import pytest
import pytest_asyncio
import httpx
from httpx import AsyncClient, ASGITransport

from pipeline.main import app


@pytest.fixture
def valid_event() -> dict:
    return {
        "event_id": str(uuid.uuid4()),
        "event_type": "payment",
        "timestamp": time.time(),
        "payload": {
            "payment_id": "pay-abc123",
            "order_id": "ord-xyz456",
            "amount": 499.0,
            "currency": "INR",
            "method": "upi",
            "status": "success",
        },
    }


@pytest.fixture
def async_client():
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


# ---------------------------------------------------------------------------
# /events endpoint
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_valid_event_accepted(async_client, valid_event):
    async with async_client as client:
        response = await client.post("/events", json=valid_event)
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "accepted"
    assert body["event_id"] == valid_event["event_id"]


@pytest.mark.asyncio
@pytest.mark.parametrize("etype", ["order", "payment", "inventory", "click", "log"])
async def test_all_event_types_accepted(async_client, etype):
    event = {
        "event_id": str(uuid.uuid4()),
        "event_type": etype,
        "timestamp": time.time(),
        "payload": {"key": "value"},
    }
    async with async_client as client:
        response = await client.post("/events", json=event)
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_invalid_event_type_rejected(async_client):
    event = {
        "event_id": str(uuid.uuid4()),
        "event_type": "unknown_type",
        "timestamp": time.time(),
        "payload": {},
    }
    async with async_client as client:
        response = await client.post("/events", json=event)
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_missing_event_id_rejected(async_client):
    event = {
        "event_type": "click",
        "timestamp": time.time(),
        "payload": {},
    }
    async with async_client as client:
        response = await client.post("/events", json=event)
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_missing_payload_rejected(async_client):
    event = {
        "event_id": str(uuid.uuid4()),
        "event_type": "order",
        "timestamp": time.time(),
    }
    async with async_client as client:
        response = await client.post("/events", json=event)
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_empty_payload_accepted(async_client):
    """Payload is typed as dict — an empty dict is technically valid."""
    event = {
        "event_id": str(uuid.uuid4()),
        "event_type": "log",
        "timestamp": time.time(),
        "payload": {},
    }
    async with async_client as client:
        response = await client.post("/events", json=event)
    assert response.status_code == 200


# ---------------------------------------------------------------------------
# /health
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_health_returns_ok(async_client):
    async with async_client as client:
        response = await client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


# ---------------------------------------------------------------------------
# /stats
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stats_returns_expected_shape(async_client):
    async with async_client as client:
        response = await client.get("/stats")
    assert response.status_code == 200
    data = response.json()
    assert "total_received" in data
    assert "by_type" in data
    assert "uptime_seconds" in data
    assert "events_per_second" in data
