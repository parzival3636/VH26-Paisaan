"""
simulator/controller.py

Simulator state machine.

The SimulatorState dataclass holds the mutable state that is read by the
producer loop on every iteration.  Changing a field immediately takes effect
on the *next* inter-arrival calculation — no restart required.

Modes:
  normal  — 1 000 events/min  (≈ 16.67/sec)
  spike   — 20 000 events/min (≈ 333.33/sec)
  custom  — any rate set via set_rate()

Traffic model:
  poisson — inter-arrival times ~ Exponential(λ)   [default, realistic]
  fixed   — constant 1/λ delay                      [useful for debugging]
"""

from dataclasses import dataclass, field
from typing import Literal

from simulator.config import NORMAL_RATE_PER_SEC, SPIKE_RATE_PER_SEC

Mode = Literal["normal", "spike", "custom"]
TrafficModel = Literal["poisson", "fixed"]


@dataclass
class SimulatorState:
    """
    Shared state between the CLI / control layer and the producer loop.

    Fields:
        running         — producer loop continues while True.
        current_rate    — events per second (λ for Poisson inter-arrivals).
        mode            — human-readable label for the current rate regime.
        traffic_model   — poisson (default) or fixed for testing.
    """

    running: bool = False
    current_rate: float = field(default_factory=lambda: NORMAL_RATE_PER_SEC)
    mode: Mode = "normal"
    traffic_model: TrafficModel = "poisson"

    # -----------------------------------------------------------------------
    # Control methods
    # -----------------------------------------------------------------------

    def start(self) -> None:
        """Begin producing events."""
        self.running = True

    def stop(self) -> None:
        """Signal the producer loop to exit after the current iteration."""
        self.running = False

    def set_normal(self) -> None:
        """Switch to normal-traffic mode (1 000 events/min)."""
        self.current_rate = NORMAL_RATE_PER_SEC
        self.mode = "normal"

    def set_spike(self) -> None:
        """
        Activate flash-sale spike mode (20 000 events/min).

        This is a *step change* — the rate changes on the very next
        inter-arrival calculation.  There is no gradual ramp.
        """
        self.current_rate = SPIKE_RATE_PER_SEC
        self.mode = "spike"

    def set_rate(self, rate_per_min: float) -> None:
        """
        Set a custom arrival rate.

        Args:
            rate_per_min: Desired events per minute (positive float).

        Raises:
            ValueError: If rate_per_min is not positive.
        """
        if rate_per_min <= 0:
            raise ValueError(f"Rate must be positive; got {rate_per_min}")
        self.current_rate = rate_per_min / 60.0
        self.mode = "custom"

    # -----------------------------------------------------------------------
    # Read-only helpers
    # -----------------------------------------------------------------------

    @property
    def rate_per_min(self) -> float:
        """Current target rate expressed in events per minute."""
        return self.current_rate * 60.0

    def describe(self) -> str:
        """One-line human-readable description of current state."""
        status = "RUNNING" if self.running else "STOPPED"
        return (
            f"[{status}] mode={self.mode}  "
            f"target={self.rate_per_min:.0f} events/min  "
            f"({self.current_rate:.2f}/sec)  "
            f"model={self.traffic_model}"
        )
