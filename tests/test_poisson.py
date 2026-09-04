"""
tests/test_poisson.py

Verifies Poisson inter-arrival time generation.

Covers:
  - expovariate produces positive values
  - Mean of many samples converges toward 1/λ (Law of Large Numbers)
  - High rate (spike) yields shorter mean inter-arrival than normal rate
  - Values are not perfectly uniform (i.e., the model is stochastic)
"""

import random
import statistics

import pytest


def _sample_interarrivals(lam: float, n: int) -> list[float]:
    """Draw n inter-arrival times from Exponential(λ)."""
    return [random.expovariate(lam) for _ in range(n)]


def test_interarrival_values_are_positive():
    samples = _sample_interarrivals(lam=1000 / 60, n=1000)
    assert all(s > 0 for s in samples)


def test_mean_converges_to_one_over_lambda():
    """
    E[X] for Exponential(λ) = 1/λ.

    With 10 000 samples the mean should be within 5% of the theoretical value.
    """
    lam = 1000 / 60  # normal rate: ~16.67/sec
    expected_mean = 1.0 / lam  # ~0.060 seconds

    samples = _sample_interarrivals(lam=lam, n=10_000)
    observed_mean = statistics.mean(samples)

    assert abs(observed_mean - expected_mean) / expected_mean < 0.05, (
        f"Expected mean ≈ {expected_mean:.4f}, got {observed_mean:.4f}"
    )


def test_spike_interarrivals_shorter_than_normal():
    """
    At spike rate (333/sec) inter-arrivals should be much shorter than
    at normal rate (16.67/sec).
    """
    normal_mean = statistics.mean(_sample_interarrivals(1000 / 60, n=5000))
    spike_mean = statistics.mean(_sample_interarrivals(20000 / 60, n=5000))
    assert spike_mean < normal_mean / 10  # spike is ~20x faster


def test_interarrivals_have_variance():
    """
    Poisson arrivals are stochastic — the standard deviation should be
    non-trivial (equal to the mean for Exponential distribution).
    """
    lam = 1000 / 60
    samples = _sample_interarrivals(lam=lam, n=5000)
    expected_std = 1.0 / lam
    observed_std = statistics.stdev(samples)
    # std should be within 10% of 1/λ
    assert abs(observed_std - expected_std) / expected_std < 0.10
