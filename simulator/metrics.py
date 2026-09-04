"""
simulator/metrics.py

Simulator-side metrics — tracks what the simulator itself is doing.

These are NOT pipeline processing metrics.  They answer:
  - How many events did we generate / send?
  - How many HTTP requests succeeded or failed?
  - What is our actual observed throughput vs. target?
  - What is the latency of each HTTP call?
  - How are events distributed across types?

All state is in a single SimulatorMetrics dataclass instance shared between
the producer loop and the status-display loop.  Only the asyncio event loop
touches it, so no locking is needed.
"""

import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any


@dataclass
class SimulatorMetrics:
    """
    Mutable counters updated by the producer loop.

    Attributes:
        generated       — total events created (timestamp recorded).
        sent            — total HTTP POST attempts made.
        successful      — HTTP 2xx responses.
        failed          — non-2xx or exception.
        status_codes    — tally of HTTP response status codes.
        latencies       — rolling list of the last N request durations (seconds).
        events_by_type  — count per event_type.
        _window_start   — monotonic start of the current 1-second rate window.
        _window_count   — events sent within the current window (for rate calc).
        actual_rate_per_sec — smoothed observed rate (exponential moving avg).
    """

    generated: int = 0
    sent: int = 0
    successful: int = 0
    failed: int = 0
    status_codes: dict[int, int] = field(default_factory=lambda: defaultdict(int))
    latencies: list[float] = field(default_factory=list)
    events_by_type: dict[str, int] = field(
        default_factory=lambda: defaultdict(int)
    )

    # Rate estimation (simple 1-second sliding window)
    _window_start: float = field(default_factory=time.monotonic)
    _window_count: int = 0
    actual_rate_per_sec: float = 0.0

    # Keep only the last N latencies to avoid unbounded growth
    _max_latency_samples: int = 500

    def record_generated(self, event_type: str) -> None:
        """Call immediately after generate_event()."""
        self.generated += 1
        self.events_by_type[event_type] += 1

    def record_sent(self) -> None:
        """Call just before the HTTP POST."""
        self.sent += 1
        self._window_count += 1
        now = time.monotonic()
        elapsed = now - self._window_start
        if elapsed >= 1.0:
            # Exponential moving average (α = 0.3) for smoother display
            new_rate = self._window_count / elapsed
            self.actual_rate_per_sec = (
                0.3 * new_rate + 0.7 * self.actual_rate_per_sec
                if self.actual_rate_per_sec > 0
                else new_rate
            )
            self._window_start = now
            self._window_count = 0

    def record_response(self, status_code: int, latency: float) -> None:
        """Call after receiving an HTTP response."""
        self.status_codes[status_code] += 1
        if 200 <= status_code < 300:
            self.successful += 1
        else:
            self.failed += 1
        self.latencies.append(latency)
        if len(self.latencies) > self._max_latency_samples:
            self.latencies = self.latencies[-self._max_latency_samples :]

    def record_failure(self) -> None:
        """Call when the HTTP call raises an exception (no response)."""
        self.failed += 1

    def avg_latency_ms(self) -> float:
        """Average HTTP round-trip latency over the last N samples (milliseconds)."""
        if not self.latencies:
            return 0.0
        return round(sum(self.latencies) / len(self.latencies) * 1000, 2)

    def snapshot(self) -> dict[str, Any]:
        """Return a plain dict suitable for display or serialisation."""
        return {
            "generated": self.generated,
            "sent": self.sent,
            "successful": self.successful,
            "failed": self.failed,
            "actual_rate_per_sec": round(self.actual_rate_per_sec, 2),
            "avg_latency_ms": self.avg_latency_ms(),
            "status_codes": dict(self.status_codes),
            "events_by_type": dict(self.events_by_type),
        }
