"""
tests/test_metrics.py

Unit tests for simulator.metrics.SimulatorMetrics.

Covers:
  - record_generated / by_type counting
  - record_response (success vs failure classification by status code)
  - record_failure (network exception)
  - avg_latency_ms computation
  - latency ring buffer (max samples)
  - rate estimation (basic sanity)
  - snapshot() shape
"""

import pytest

from simulator.metrics import SimulatorMetrics


def test_initial_state():
    m = SimulatorMetrics()
    assert m.generated == 0
    assert m.sent == 0
    assert m.successful == 0
    assert m.failed == 0
    assert m.avg_latency_ms() == 0.0


def test_record_generated_increments():
    m = SimulatorMetrics()
    m.record_generated("order")
    m.record_generated("click")
    m.record_generated("click")
    assert m.generated == 3
    assert m.events_by_type["order"] == 1
    assert m.events_by_type["click"] == 2


def test_record_sent_increments():
    m = SimulatorMetrics()
    m.record_sent()
    m.record_sent()
    assert m.sent == 2


def test_record_response_2xx_counts_as_success():
    m = SimulatorMetrics()
    m.record_response(200, 0.01)
    m.record_response(201, 0.02)
    assert m.successful == 2
    assert m.failed == 0


def test_record_response_4xx_counts_as_failure():
    m = SimulatorMetrics()
    m.record_response(422, 0.01)
    assert m.successful == 0
    assert m.failed == 1
    assert m.status_codes[422] == 1


def test_record_response_5xx_counts_as_failure():
    m = SimulatorMetrics()
    m.record_response(503, 0.01)
    assert m.failed == 1


def test_record_failure_increments_failed():
    m = SimulatorMetrics()
    m.record_failure()
    m.record_failure()
    assert m.failed == 2
    assert m.successful == 0


def test_avg_latency_ms():
    m = SimulatorMetrics()
    m.record_response(200, 0.010)  # 10 ms
    m.record_response(200, 0.020)  # 20 ms
    m.record_response(200, 0.030)  # 30 ms
    assert abs(m.avg_latency_ms() - 20.0) < 0.01


def test_latency_ring_buffer():
    """Latencies list should not exceed _max_latency_samples."""
    m = SimulatorMetrics()
    max_samples = m._max_latency_samples
    for _ in range(max_samples + 100):
        m.record_response(200, 0.001)
    assert len(m.latencies) <= max_samples


def test_snapshot_has_required_keys():
    m = SimulatorMetrics()
    snap = m.snapshot()
    for key in ("generated", "sent", "successful", "failed",
                "actual_rate_per_sec", "avg_latency_ms",
                "status_codes", "events_by_type"):
        assert key in snap


def test_snapshot_values_consistent():
    m = SimulatorMetrics()
    m.record_generated("payment")
    m.record_sent()
    m.record_response(200, 0.005)
    snap = m.snapshot()
    assert snap["generated"] == 1
    assert snap["sent"] == 1
    assert snap["successful"] == 1
    assert snap["failed"] == 0
