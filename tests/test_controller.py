"""
tests/test_controller.py

Unit tests for simulator.controller.SimulatorState.

Covers:
  - Default state
  - start / stop
  - set_normal / set_spike (rates and mode labels)
  - set_rate (custom, negative guard)
  - rate_per_min property
  - describe() output
  - traffic_model assignment
"""

import pytest

from simulator.config import NORMAL_RATE_PER_SEC, SPIKE_RATE_PER_SEC
from simulator.controller import SimulatorState


def test_default_state():
    state = SimulatorState()
    assert state.running is False
    assert state.mode == "normal"
    assert state.traffic_model == "poisson"
    assert abs(state.current_rate - NORMAL_RATE_PER_SEC) < 1e-6


def test_start_sets_running():
    state = SimulatorState()
    state.start()
    assert state.running is True


def test_stop_clears_running():
    state = SimulatorState()
    state.start()
    state.stop()
    assert state.running is False


def test_set_spike():
    state = SimulatorState()
    state.set_spike()
    assert state.mode == "spike"
    assert abs(state.current_rate - SPIKE_RATE_PER_SEC) < 1e-6


def test_set_normal_after_spike():
    state = SimulatorState()
    state.set_spike()
    state.set_normal()
    assert state.mode == "normal"
    assert abs(state.current_rate - NORMAL_RATE_PER_SEC) < 1e-6


def test_set_rate_custom():
    state = SimulatorState()
    state.set_rate(5000)
    assert state.mode == "custom"
    assert abs(state.current_rate - 5000 / 60.0) < 1e-6


def test_set_rate_negative_raises():
    state = SimulatorState()
    with pytest.raises(ValueError, match="positive"):
        state.set_rate(-100)


def test_set_rate_zero_raises():
    state = SimulatorState()
    with pytest.raises(ValueError):
        state.set_rate(0)


def test_rate_per_min_normal():
    state = SimulatorState()
    assert abs(state.rate_per_min - 1000.0) < 0.01


def test_rate_per_min_spike():
    state = SimulatorState()
    state.set_spike()
    assert abs(state.rate_per_min - 20000.0) < 0.1


def test_describe_contains_mode():
    state = SimulatorState()
    desc = state.describe()
    assert "normal" in desc.lower()
    assert "STOPPED" in desc


def test_describe_running():
    state = SimulatorState()
    state.start()
    assert "RUNNING" in state.describe()


def test_traffic_model_switch():
    state = SimulatorState()
    assert state.traffic_model == "poisson"
    state.traffic_model = "fixed"
    assert state.traffic_model == "fixed"
