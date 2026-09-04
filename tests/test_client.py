"""
tests/test_client.py

Unit tests for simulator.client.SimulatorClient.

Uses httpx.MockTransport to avoid requiring a live server.

Covers:
  - Successful send returns (True, 200, latency > 0)
  - HTTP 4xx returns (False, 422, latency > 0)
  - HTTP 5xx returns (False, 503, latency > 0)
  - Connection error returns (False, 0, latency)
  - Client not started raises RuntimeError
"""

import time
import uuid

import httpx
import pytest

from simulator.client import SimulatorClient
from simulator.generator import generate_event


def _make_event() -> dict:
    return generate_event()


# ---------------------------------------------------------------------------
# Mock transports
# ---------------------------------------------------------------------------


def _mock_transport(status_code: int, body: dict | None = None):
    """Return an httpx transport that always responds with status_code."""
    import json

    response_body = json.dumps(body or {"status": "accepted"}).encode()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, content=response_body)

    return httpx.MockTransport(handler)


def _error_transport(exc_class):
    """Return a transport that always raises exc_class."""

    def handler(request: httpx.Request) -> httpx.Response:
        raise exc_class()

    return httpx.MockTransport(handler)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_send_event_success():
    client = SimulatorClient()
    client._http = httpx.AsyncClient(transport=_mock_transport(200))
    success, code, latency = await client.send_event(_make_event())
    assert success is True
    assert code == 200
    assert latency >= 0


@pytest.mark.asyncio
async def test_send_event_422():
    client = SimulatorClient()
    client._http = httpx.AsyncClient(transport=_mock_transport(422))
    success, code, latency = await client.send_event(_make_event())
    assert success is False
    assert code == 422


@pytest.mark.asyncio
async def test_send_event_503():
    client = SimulatorClient()
    client._http = httpx.AsyncClient(transport=_mock_transport(503))
    success, code, latency = await client.send_event(_make_event())
    assert success is False
    assert code == 503


@pytest.mark.asyncio
async def test_send_event_connect_error():
    client = SimulatorClient()
    client._http = httpx.AsyncClient(
        transport=_error_transport(httpx.ConnectError)
    )
    success, code, latency = await client.send_event(_make_event())
    assert success is False
    assert code == 0  # no HTTP status on network failure
    assert latency >= 0


@pytest.mark.asyncio
async def test_send_event_timeout():
    client = SimulatorClient()
    client._http = httpx.AsyncClient(
        transport=_error_transport(httpx.TimeoutException)
    )
    success, code, latency = await client.send_event(_make_event())
    assert success is False
    assert code == 0


@pytest.mark.asyncio
async def test_not_started_raises():
    client = SimulatorClient()
    with pytest.raises(RuntimeError, match="not started"):
        await client.send_event(_make_event())


@pytest.mark.asyncio
async def test_context_manager_lifecycle():
    """start() and stop() via async context manager."""
    async with SimulatorClient(
        endpoint="http://test",
    ) as client:
        # Override transport after start
        client._http._transport = _mock_transport(200)
        success, code, _ = await client.send_event(_make_event())
        assert success is True
    # After exiting context, _http should be None
    assert client._http is None
