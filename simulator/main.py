"""
simulator/main.py

Entry point for the Request Simulator.

Runs two concurrent asyncio tasks:
  1. producer_loop  — generates events and sends them via HTTP.
  2. status_loop    — prints a periodic terminal summary.

And one synchronous task (run in a thread executor):
  3. cli_loop       — reads stdin commands and updates SimulatorState.

CLI commands:
  start             Start producing events
  stop              Stop producing events
  spike             Switch to flash-sale rate (20 000 events/min)
  normal            Switch to normal rate (1 000 events/min)
  rate <N>          Set a custom rate of N events/min
  model poisson     Use Poisson (expovariate) inter-arrival times [default]
  model fixed       Use fixed 1/λ inter-arrival times
  status            Print current metrics snapshot
  help              Show command list
  quit / exit       Stop and exit

Usage:
  python -m simulator.main

Or run both services:
  # Terminal 1 — start the FastAPI receiver
  uvicorn pipeline.main:app --reload

  # Terminal 2 — start the simulator
  python -m simulator.main
"""

import asyncio
import logging
import random
import sys
import time
from typing import Any

from simulator.client import SimulatorClient
from simulator.config import STATUS_INTERVAL
from simulator.controller import SimulatorState
from simulator.generator import generate_event
from simulator.metrics import SimulatorMetrics

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [SIMULATOR] %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("simulator")

# ---------------------------------------------------------------------------
# Producer loop (core)
# ---------------------------------------------------------------------------


async def producer_loop(
    state: SimulatorState,
    metrics: SimulatorMetrics,
    client: SimulatorClient,
) -> None:
    """
    The main event-generation and HTTP-sending loop.

    Behaviour:
      - Runs while state.running is True.
      - Samples an inter-arrival time each iteration from the configured model.
      - Records the event timestamp at creation (not at send time).
      - Sends the event; records success/failure; continues regardless.
      - The loop is a single coroutine — no mass task.gather() is used.
        Concurrency comes from asyncio yielding control at each await.

    Poisson model (default):
      delay = random.expovariate(λ)   where λ = state.current_rate (events/sec)
      This produces stochastic arrivals with mean 1/λ seconds between events.

    Fixed model (debug):
      delay = 1 / λ
      Perfectly uniform; useful to verify counts and rate calculations.
    """
    logger.info("Producer loop started")

    while True:
        # Check if we should stop *before* sleeping
        if not state.running:
            await asyncio.sleep(0.05)  # yield briefly to avoid busy-wait
            continue

        lam = state.current_rate  # events/sec — read every iteration

        # --- Arrival scheduling ---
        if state.traffic_model == "poisson":
            # Inter-arrival time ~ Exponential(λ)
            # random.expovariate(λ) returns 1/λ on average
            delay = random.expovariate(lam)
        else:
            # Fixed mode: perfectly uniform
            delay = 1.0 / lam

        await asyncio.sleep(delay)

        # --- Event creation (timestamp recorded here = arrival time) ---
        event = generate_event()
        metrics.record_generated(event["event_type"])

        # --- HTTP POST ---
        metrics.record_sent()
        success, status_code, latency = await client.send_event(event)

        if success:
            metrics.record_response(status_code, latency)
        else:
            if status_code != 0:
                metrics.record_response(status_code, latency)
            else:
                metrics.record_failure()


# ---------------------------------------------------------------------------
# Status display loop
# ---------------------------------------------------------------------------


async def status_loop(
    state: SimulatorState,
    metrics: SimulatorMetrics,
    interval: float = STATUS_INTERVAL,
) -> None:
    """
    Print a rate-limited terminal status block every `interval` seconds.

    At 333 events/sec we cannot log per-event without flooding stdout.
    This coroutine summarises activity on a configurable cadence.
    """
    while True:
        await asyncio.sleep(interval)
        _print_status(state, metrics)


def _print_status(state: SimulatorState, metrics: SimulatorMetrics) -> None:
    snap = metrics.snapshot()
    by_type = snap["events_by_type"]
    mode_label = snap.get("mode", state.mode).upper() if hasattr(snap, "get") else state.mode.upper()

    lines = [
        "=" * 54,
        " REQUEST SIMULATOR",
        "=" * 54,
        f" Mode:             {state.mode.upper():>10}",
        f" Target rate:   {state.rate_per_min:>10.0f} events/min",
        f" Actual rate:   {snap['actual_rate_per_sec']:>10.2f} events/sec",
        f" Avg latency:   {snap['avg_latency_ms']:>10.2f} ms",
        "-" * 54,
        f" Generated:     {snap['generated']:>10,}",
        f" Sent:          {snap['sent']:>10,}",
        f" Successful:    {snap['successful']:>10,}",
        f" Failed:        {snap['failed']:>10,}",
        "-" * 54,
        " Events by type:",
        *[
            f"   {etype:<12} {by_type.get(etype, 0):>8,}"
            for etype in ["order", "payment", "inventory", "click", "log"]
        ],
        "=" * 54,
    ]
    print("\n".join(lines), flush=True)


# ---------------------------------------------------------------------------
# CLI loop (runs in a thread so it doesn't block the event loop)
# ---------------------------------------------------------------------------


def _print_help() -> None:
    print(
        "\nCommands:\n"
        "  start              Start producing events\n"
        "  stop               Pause producing events\n"
        "  spike              Switch to flash-sale rate (20 000/min)\n"
        "  normal             Switch to normal rate (1 000/min)\n"
        "  rate <N>           Set custom rate of N events/min\n"
        "  model poisson      Poisson (expovariate) arrivals [default]\n"
        "  model fixed        Fixed uniform inter-arrival\n"
        "  status             Print current metrics\n"
        "  help               Show this message\n"
        "  quit / exit        Stop simulator and exit\n",
        flush=True,
    )


def cli_loop(
    state: SimulatorState,
    metrics: SimulatorMetrics,
    stop_event: asyncio.Event,
    loop: asyncio.AbstractEventLoop,
) -> None:
    """
    Blocking stdin reader; runs in a thread executor.

    Reads lines from stdin and updates SimulatorState accordingly.
    Signals the asyncio event loop to shut down via stop_event.
    """
    _print_help()
    print("> ", end="", flush=True)

    for raw_line in sys.stdin:
        line = raw_line.strip().lower()
        parts = line.split()
        cmd = parts[0] if parts else ""

        try:
            if cmd == "start":
                state.start()
                logger.info("Started — mode=%s  rate=%.0f/min", state.mode, state.rate_per_min)

            elif cmd == "stop":
                state.stop()
                logger.info("Paused")

            elif cmd == "spike":
                state.set_spike()
                logger.info("SPIKE activated — target=%.0f events/min", state.rate_per_min)

            elif cmd == "normal":
                state.set_normal()
                logger.info("NORMAL mode — target=%.0f events/min", state.rate_per_min)

            elif cmd == "rate":
                if len(parts) < 2:
                    print("Usage: rate <events_per_minute>", flush=True)
                else:
                    state.set_rate(float(parts[1]))
                    logger.info("Custom rate set: %.0f events/min", state.rate_per_min)

            elif cmd == "model":
                if len(parts) < 2 or parts[1] not in ("poisson", "fixed"):
                    print("Usage: model poisson|fixed", flush=True)
                else:
                    state.traffic_model = parts[1]  # type: ignore[assignment]
                    logger.info("Traffic model: %s", state.traffic_model)

            elif cmd == "status":
                _print_status(state, metrics)

            elif cmd == "help":
                _print_help()

            elif cmd in ("quit", "exit"):
                logger.info("Shutting down…")
                state.stop()
                loop.call_soon_threadsafe(stop_event.set)
                break

            elif cmd == "":
                pass  # blank line — ignore

            else:
                print(f"Unknown command: {cmd!r}  (type 'help')", flush=True)

        except ValueError as exc:
            print(f"Error: {exc}", flush=True)

        print("> ", end="", flush=True)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


async def main() -> None:
    import os
    state = SimulatorState()
    if os.environ.get("SIM_AUTO_START", "").lower() in ("1", "true", "yes"):
        state.start()
        logger.info("Auto-started simulator loop via SIM_AUTO_START")
    metrics = SimulatorMetrics()
    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()

    print(
        "\n" + "=" * 54 + "\n"
        " INTELLIGENT PIPELINE — REQUEST SIMULATOR\n" +
        "=" * 54 + "\n"
        " Type 'help' for commands.  Start with: start\n" +
        "=" * 54 + "\n",
        flush=True,
    )

    async with SimulatorClient() as client:
        # Launch background tasks
        producer_task = asyncio.create_task(
            producer_loop(state, metrics, client),
            name="producer",
        )
        status_task = asyncio.create_task(
            status_loop(state, metrics),
            name="status",
        )

        # CLI runs in a thread (blocks on stdin; must not block the event loop)
        await loop.run_in_executor(
            None,
            cli_loop,
            state,
            metrics,
            stop_event,
            loop,
        )

        # Wait for the shutdown signal from the CLI thread
        await stop_event.wait()

        # Cancel background tasks cleanly
        producer_task.cancel()
        status_task.cancel()
        await asyncio.gather(producer_task, status_task, return_exceptions=True)

    # Final summary
    _print_status(state, metrics)
    logger.info("Simulator stopped cleanly")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n[SIMULATOR] Interrupted by user", flush=True)
