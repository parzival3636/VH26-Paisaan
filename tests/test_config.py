"""
tests/test_config.py

Unit tests for simulator.config.

Covers:
  - Presence and types of all config constants
  - EVENT_TYPE_WEIGHTS sum to approximately 1.0
  - Derived rate values
"""

from simulator import config


def test_normal_rate_positive():
    assert config.NORMAL_RATE_PER_MIN > 0
    assert config.NORMAL_RATE_PER_SEC > 0


def test_spike_rate_greater_than_normal():
    assert config.SPIKE_RATE_PER_MIN > config.NORMAL_RATE_PER_MIN
    assert config.SPIKE_RATE_PER_SEC > config.NORMAL_RATE_PER_SEC


def test_derived_rates_consistent():
    assert abs(config.NORMAL_RATE_PER_SEC - config.NORMAL_RATE_PER_MIN / 60) < 1e-9
    assert abs(config.SPIKE_RATE_PER_SEC - config.SPIKE_RATE_PER_MIN / 60) < 1e-9


def test_event_type_weights_present():
    required = {"order", "payment", "inventory", "click", "log"}
    assert required.issubset(set(config.EVENT_TYPE_WEIGHTS.keys()))


def test_event_type_weights_sum_to_one():
    total = sum(config.EVENT_TYPE_WEIGHTS.values())
    assert abs(total - 1.0) < 1e-9


def test_event_type_weights_positive():
    for name, w in config.EVENT_TYPE_WEIGHTS.items():
        assert w > 0, f"Weight for {name!r} must be positive"


def test_http_timeout_positive():
    assert config.HTTP_TIMEOUT > 0


def test_endpoint_is_string():
    assert isinstance(config.EVENT_ENDPOINT, str)
    assert config.EVENT_ENDPOINT.startswith("http")


def test_status_interval_positive():
    assert config.STATUS_INTERVAL > 0
