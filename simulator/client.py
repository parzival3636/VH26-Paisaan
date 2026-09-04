"""
simulator/client.py

Async HTTP client for the Request Simulator.

Design principles:
  - One shared httpx.AsyncClient per simulator run (connection pooling /
    keep-alive). Never create a new client per request.
  - All network errors are caught and surfaced as a (False, status_code)
    tuple so the producer loop can record the failure and continue.
  - Configurable timeout; no infinite retries that would distort arrival rate.
"""

import logging
import time
from typing import Any

import httpx

from simulator.config import EVENT_ENDPOINT, HTTP_MAX_CONNECTIONS, HTTP_TIMEOUT

logger = logging.getLogger("simulator.client")


class SimulatorClient:
    """
    Thin async wrapper around httpx.AsyncClient.

    Lifecycle:
        client = SimulatorClient()
        await client.start()          # opens the connection pool
        ...
        ok, code = await client.send_event(event)
        ...
        await client.stop()           # drains and closes the pool

    Or use as an async context manager:
        async with SimulatorClient() as client:
            ok, code = await client.send_event(event)
    """

    def __init__(
        self,
        endpoint: str = EVENT_ENDPOINT,
        timeout: float = HTTP_TIMEOUT,
        max_connections: int = HTTP_MAX_CONNECTIONS,
    ) -> None:
        self._endpoint = endpoint
        self._timeout = timeout
        self._max_connections = max_connections
        self._http: httpx.AsyncClient | None = None

    # -----------------------------------------------------------------------
    # Lifecycle
    # -----------------------------------------------------------------------

    async def start(self) -> None:
        """Open the connection pool."""
        limits = httpx.Limits(
            max_connections=self._max_connections,
            max_keepalive_connections=self._max_connections,
        )
        self._http = httpx.AsyncClient(
            timeout=self._timeout,
            limits=limits,
        )
        logger.debug("HTTP client started (pool size=%d)", self._max_connections)

    async def stop(self) -> None:
        """Drain and close the connection pool."""
        if self._http is not None:
            await self._http.aclose()
            self._http = None
            logger.debug("HTTP client stopped")

    async def __aenter__(self) -> "SimulatorClient":
        await self.start()
        return self

    async def __aexit__(self, *_: Any) -> None:
        await self.stop()

    # -----------------------------------------------------------------------
    # Sending
    # -----------------------------------------------------------------------

    async def send_event(self, event: dict[str, Any]) -> tuple[bool, int, float]:
        """
        POST a single event to the ingestion endpoint.

        Args:
            event: The event dict produced by generator.generate_event().

        Returns:
            (success, status_code, latency_seconds)
              success     — True if HTTP 2xx, False otherwise.
              status_code — The HTTP status code (0 on network exception).
              latency     — Round-trip time in seconds.

        Notes:
            - Never raises; all exceptions are caught and logged.
            - Does NOT retry.  Retrying would delay the Poisson schedule.
        """
        if self._http is None:
            raise RuntimeError("SimulatorClient not started — call start() first")

        t0 = time.monotonic()
        try:
            producer_id = event.get("payload", {}).get("producer_id", "simulator")
            headers = {"X-Source": producer_id}
            response = await self._http.post(self._endpoint, json=event, headers=headers)
            latency = time.monotonic() - t0
            success = 200 <= response.status_code < 300
            if not success:
                logger.warning(
                    "HTTP %d for event_id=%s", response.status_code, event["event_id"]
                )
            return success, response.status_code, latency

        except httpx.ConnectError:
            latency = time.monotonic() - t0
            logger.warning(
                "Connection refused — is the pipeline receiver running at %s?",
                self._endpoint,
            )
            return False, 0, latency

        except httpx.TimeoutException:
            latency = time.monotonic() - t0
            logger.warning("HTTP timeout for event_id=%s", event["event_id"])
            return False, 0, latency

        except Exception as exc:  # noqa: BLE001
            latency = time.monotonic() - t0
            logger.error("Unexpected HTTP error: %s", exc)
            return False, 0, latency
