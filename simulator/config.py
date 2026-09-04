"""
simulator/config.py

Central configuration for the Request Simulator.

All "magic numbers" live here.  Values can be overridden via environment
variables so the simulator is easy to tune without touching source code.

Environment variables (all optional):
  SIM_NORMAL_RATE_PER_MIN   default 1000
  SIM_SPIKE_RATE_PER_MIN    default 20000
  SIM_EVENT_ENDPOINT        default http://127.0.0.1:8000/events
  SIM_HTTP_TIMEOUT          default 5.0
  SIM_STATUS_INTERVAL       default 5.0
"""

import os

# ---------------------------------------------------------------------------
# Arrival rates (events / minute)
# ---------------------------------------------------------------------------

NORMAL_RATE_PER_MIN: float = float(os.environ.get("SIM_NORMAL_RATE_PER_MIN", 1000))
SPIKE_RATE_PER_MIN: float = float(os.environ.get("SIM_SPIKE_RATE_PER_MIN", 20000))

# Derived: events / second (used by the Poisson generator)
NORMAL_RATE_PER_SEC: float = NORMAL_RATE_PER_MIN / 60.0   # ≈ 16.67
SPIKE_RATE_PER_SEC: float = SPIKE_RATE_PER_MIN / 60.0     # ≈ 333.33

# ---------------------------------------------------------------------------
# HTTP transport
# ---------------------------------------------------------------------------

EVENT_ENDPOINT: str = os.environ.get(
    "SIM_EVENT_ENDPOINT", "http://127.0.0.1:8000/ingest"
)

HTTP_TIMEOUT: float = float(os.environ.get("SIM_HTTP_TIMEOUT", 5.0))

# Number of keep-alive connections in the httpx connection pool.
# Increase if you observe connection-limit errors at high rates.
HTTP_MAX_CONNECTIONS: int = int(os.environ.get("SIM_HTTP_MAX_CONNECTIONS", 100))

# ---------------------------------------------------------------------------
# Event-type distribution
# Weights are relative — they are normalised by random.choices automatically.
# Click events dominate (50 %) because user browsing is the most common action.
# ---------------------------------------------------------------------------

EVENT_TYPE_WEIGHTS: dict[str, float] = {
    "order":     float(os.environ.get("SIM_W_ORDER",     0.10)),
    "payment":   float(os.environ.get("SIM_W_PAYMENT",   0.10)),
    "inventory": float(os.environ.get("SIM_W_INVENTORY", 0.10)),
    "click":     float(os.environ.get("SIM_W_CLICK",     0.50)),
    "log":       float(os.environ.get("SIM_W_LOG",       0.20)),
}

# ---------------------------------------------------------------------------
# Observability
# ---------------------------------------------------------------------------

# How often (in seconds) the simulator prints a status summary to the terminal.
# At 333 events/sec, per-event logging would flood the console; we summarise
# instead.
STATUS_INTERVAL: float = float(os.environ.get("SIM_STATUS_INTERVAL", 5.0))
