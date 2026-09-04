"""
demo.py — Intelligent Adaptive Pipeline: Live Terminal Dashboard

Demonstrates the end-to-end adaptive pipeline with full score explainability:
    Request Simulator -> Ingestion Gateway -> Scoring Engine -> Dynamic Routing

Usage:
    python demo.py            # All-in-one mode (clean terminal UI)
    python demo.py --spike    # Start in 20,000 req/min flash-sale spike mode
    python demo.py --external # Attach to an externally running pipeline server
"""

import asyncio
import logging
import os
import sys
import time
from collections import deque
from datetime import datetime

import httpx
import uvicorn
from rich.align import Align
from rich.columns import Columns
from rich.console import Console
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

# Mute noisy background loggers
for log_name in (
    "pipeline", "pipeline.redis", "uvicorn", "uvicorn.access",
    "uvicorn.error", "httpx", "simulator", "simulator.client"
):
    logging.getLogger(log_name).setLevel(logging.ERROR)

from pipeline.main import app as fastapi_app
from simulator.client import SimulatorClient
from simulator.controller import SimulatorState
from simulator.generator import generate_event
from simulator.metrics import SimulatorMetrics

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

PIPELINE_BASE = "http://127.0.0.1:8000"
POLL_INTERVAL = 0.25
MAX_STREAM_ROWS = 6
MAX_BREAKDOWN_ROWS = 8

# Styles
C_EXECUTE = "bold bright_green"
C_BATCH = "bold yellow"
C_DEFER = "bold bright_yellow"
C_SHED = "bold red"
C_BACKPRESSURE = "bold magenta"
C_QUOTA_OK = "green"
C_QUOTA_OVER = "bold red"
C_HEADER = "bold cyan"
C_DIM = "dim white"
C_POS = "bright_green"
C_NEG = "bright_red"
C_ZERO = "dim"

ACTION_STYLES = {
    "execute": C_EXECUTE, "batch": C_BATCH, "defer": C_DEFER,
    "shed": C_SHED, "backpressure": C_BACKPRESSURE,
}
ACTION_TAGS = {
    "execute": "[EXEC]", "batch": "[BATCH]", "defer": "[DEFER]",
    "shed": "[SHED]", "backpressure": "[BACK]",
}
BAND_STYLES = {
    "Critical": "bold bright_red", "Standard": "bold bright_yellow",
    "Best-effort": "dim white",
}
TYPE_TAGS = {"order": "ORD", "payment": "PAY", "inventory": "INV", "click": "CLK", "log": "LOG"}
TYPE_STYLES = {
    "order": "bright_yellow", "payment": "bright_green", "inventory": "bright_blue",
    "click": "dim white", "log": "dim cyan",
}

SPARK = " _.:oO@#"


def sparkline(values: list[float], width: int = 14) -> str:
    if not values:
        return "_" * width
    recent = values[-width:]
    mn, mx = min(recent), max(recent)
    rng = mx - mn if mx != mn else 1.0
    return "".join(
        SPARK[min(int((v - mn) / rng * (len(SPARK) - 1)), len(SPARK) - 1)]
        for v in recent
    )


def _fmt_component(val: float) -> Text:
    """Format a score component with color: green if positive, red if negative, dim if zero."""
    if val > 0.001:
        return Text(f"+{val:.2f}", style=C_POS)
    elif val < -0.001:
        return Text(f"{val:.2f}", style=C_NEG)
    else:
        return Text("  -- ", style=C_ZERO)


# ---------------------------------------------------------------------------
# In-process Producer Loop
# ---------------------------------------------------------------------------

async def _send_and_record(client: SimulatorClient, metrics: SimulatorMetrics, event: dict):
    try:
        success, status_code, latency = await client.send_event(event)
        if success:
            metrics.record_response(status_code, latency)
        else:
            metrics.record_failure()
    except Exception:
        pass


async def run_producer(state: SimulatorState, metrics: SimulatorMetrics, client: SimulatorClient):
    import random
    while True:
        if not state.running:
            await asyncio.sleep(0.05)
            continue
        lam = state.current_rate
        delay = random.expovariate(lam) if state.traffic_model == "poisson" else 1.0 / lam
        await asyncio.sleep(delay)
        event = generate_event()
        metrics.record_generated(event["event_type"])
        metrics.record_sent()
        asyncio.create_task(_send_and_record(client, metrics, event))


# ---------------------------------------------------------------------------
# Dashboard Builder
# ---------------------------------------------------------------------------

class Dashboard:

    def __init__(self, state: SimulatorState):
        self.state = state
        self.throughput_history: deque[float] = deque(maxlen=60)
        self.last_total = 0
        self.last_time = time.monotonic()
        self.start_time = time.monotonic()
        self.spike_triggered = False
        self.spike_time: float | None = None

    def build(self, stats: dict, recent: list[dict]) -> Layout:
        layout = Layout()
        layout.split_column(
            Layout(name="header", size=3),
            Layout(name="top_body"),
            Layout(name="breakdown", size=13),
            Layout(name="footer", size=3),
        )

        layout["header"].update(self._header(stats))
        layout["footer"].update(self._footer(stats))

        layout["top_body"].split_row(
            Layout(name="left", ratio=2),
            Layout(name="right", ratio=3),
        )

        layout["left"].split_column(
            Layout(name="throughput", size=8),
            Layout(name="actions", size=10),
            Layout(name="types"),
        )

        layout["throughput"].update(self._throughput(stats))
        layout["actions"].update(self._actions(stats))
        layout["types"].update(self._types(stats))
        layout["right"].update(self._event_stream(recent))
        layout["breakdown"].update(self._score_breakdown(recent))

        return layout

    # -- header --
    def _header(self, stats: dict) -> Panel:
        now = datetime.now().strftime("%H:%M:%S")
        left = Text()
        left.append(">> ", style="bold bright_green")
        left.append("INTELLIGENT ADAPTIVE PIPELINE", style="bold white")
        left.append(" | ", style="dim")
        left.append("LIVE METRICS", style="bold bright_cyan")
        left.append(f" | {now}", style="dim white")

        if self.state.mode == "spike":
            badge = Text(" FLASH SPIKE (20k req/min) ", style="bold white on red")
        else:
            badge = Text(" NORMAL TRAFFIC (1k req/min) ", style="bold white on dark_green")

        row = Columns([left, Align.right(badge)], expand=True)
        return Panel(row, style="bright_blue", height=3)

    # -- throughput --
    def _throughput(self, stats: dict) -> Panel:
        total = stats.get("total_ingested", 0)
        eps = stats.get("events_per_second", 0)
        uptime = stats.get("uptime_seconds", 0)
        quota_v = stats.get("quota_violations", 0)

        now = time.monotonic()
        dt = now - self.last_time
        if dt > 0.1:
            instant = (total - self.last_total) / dt
            self.throughput_history.append(instant)
            self.last_total = total
            self.last_time = now

        spark = sparkline(list(self.throughput_history), 12)

        t = Table(show_header=False, box=None, padding=(0, 0))
        t.add_column("k", style=C_DIM, width=14)
        t.add_column("v", style="bold white", width=8, justify="right")
        t.add_column("g", width=14, justify="right")

        t.add_row("Total Ingested", f"{total:,}", "")
        t.add_row("Throughput/s", f"{eps:.1f}", Text(spark, style="bright_green"))
        t.add_row("Uptime", f"{uptime:.0f}s", "")
        qstyle = C_QUOTA_OVER if quota_v > 0 else C_QUOTA_OK
        t.add_row("Quota Penalties", Text(f"{quota_v:,}", style=qstyle), "")

        return Panel(t, title="[bold bright_cyan]THROUGHPUT[/]", border_style="cyan")

    # -- routing actions --
    def _actions(self, stats: dict) -> Panel:
        actions = stats.get("actions", {})
        total = max(sum(actions.values()), 1)

        t = Table(show_header=True, header_style=C_HEADER, box=None, padding=(0, 0))
        t.add_column("Action", width=10)
        t.add_column("Count", justify="right", width=7)
        t.add_column("Share", width=18)

        for a in ["execute", "batch", "defer", "shed", "backpressure"]:
            c = actions.get(a, 0)
            pct = c / total * 100
            s = ACTION_STYLES.get(a, "white")
            bw = min(int(pct / 8), 12)
            bar = "#" * bw + "." * (12 - bw)
            t.add_row(
                Text(ACTION_TAGS[a], style=s),
                Text(f"{c:,}", style="bold white"),
                Text(f"{bar} {pct:.0f}%", style=s),
            )

        return Panel(t, title="[bold bright_cyan]ROUTING[/]", border_style="cyan")

    # -- event types --
    def _types(self, stats: dict) -> Panel:
        by_type = stats.get("by_type", {})
        total = max(sum(by_type.values()), 1)

        t = Table(show_header=True, header_style=C_HEADER, box=None, padding=(0, 0))
        t.add_column("Type", width=10)
        t.add_column("Count", justify="right", width=7)
        t.add_column("Distribution", width=18)

        for et in ["payment", "order", "inventory", "click", "log"]:
            c = by_type.get(et, 0)
            pct = c / total * 100
            s = TYPE_STYLES.get(et, "white")
            bw = min(int(pct / 8), 12)
            bar = "#" * bw + "." * (12 - bw)
            t.add_row(
                Text(f"[{TYPE_TAGS[et]}]", style=s),
                Text(f"{c:,}", style="bold white"),
                Text(f"{bar} {pct:.0f}%", style=s),
            )

        return Panel(t, title="[bold bright_cyan]EVENT TYPES[/]", border_style="cyan")

    # -- live event stream (compact, top-right) --
    def _event_stream(self, recent: list[dict]) -> Panel:
        t = Table(
            show_header=True,
            header_style="bold bright_white on dark_blue",
            box=None, padding=(0, 1), expand=True,
        )
        t.add_column("EVENT_ID", width=14, style=C_DIM)
        t.add_column("TYPE", width=6)
        t.add_column("PRODUCER", width=16)
        t.add_column("SCORE", width=6, justify="right")
        t.add_column("BAND", width=10)
        t.add_column("ACTION", width=10)
        t.add_column("LAT", width=6, justify="right")

        rows = recent[-MAX_STREAM_ROWS:] if recent else []
        for e in rows:
            eid = e.get("event_id", "?")[:12]
            etype = e.get("type", "?")
            prod = e.get("producer", "?")[:15]
            score = e.get("final_score", 0.0)
            band = e.get("band", "?")
            action = e.get("action", "?")
            lat = e.get("latency_ms", 0.0)

            ss = "bold bright_green" if score >= 6.0 else ("bold yellow" if score >= 3.5 else ("bold bright_yellow" if score >= 1.5 else "dim white"))

            t.add_row(
                Text(eid, style=C_DIM),
                Text(TYPE_TAGS.get(etype, etype[:3].upper()), style=TYPE_STYLES.get(etype, "white")),
                Text(prod, style="dim cyan"),
                Text(f"{score:.1f}", style=ss),
                Text(band[:8], style=BAND_STYLES.get(band, "white")),
                Text(ACTION_TAGS.get(action, action), style=ACTION_STYLES.get(action, "white")),
                Text(f"{lat:.0f}ms", style="dim white"),
            )

        return Panel(
            t,
            title="[bold bright_cyan]LIVE EVENT STREAM[/]",
            border_style="bright_green",
        )

    # -- SCORE BREAKDOWN panel (bottom, full-width) --
    def _score_breakdown(self, recent: list[dict]) -> Panel:
        t = Table(
            show_header=True,
            header_style="bold bright_white on dark_blue",
            box=None, padding=(0, 1), expand=True,
        )
        t.add_column("EVENT_ID", width=14, style=C_DIM)
        t.add_column("TYPE", width=5)
        t.add_column("PRODUCER", width=14)
        t.add_column("$$$", width=6, justify="right")       # monetary
        t.add_column("IRREV", width=6, justify="right")     # irreversibility
        t.add_column("SCARCE", width=6, justify="right")    # scarcity
        t.add_column("DEADLN", width=6, justify="right")    # deadline
        t.add_column("QUOTA", width=6, justify="right")     # quota penalty
        t.add_column("WORKR", width=6, justify="right")     # worker adj
        t.add_column("HLTH", width=6, justify="right")      # health boost
        t.add_column("= FINAL", width=7, justify="right")   # final score
        t.add_column("ACTION", width=10)                     # routing decision

        # Pick the last 8 events that have component data
        candidates = [e for e in recent if e.get("components")] if recent else []
        rows = candidates[-MAX_BREAKDOWN_ROWS:]

        for e in rows:
            eid = e.get("event_id", "?")[:12]
            etype = e.get("type", "?")
            prod = e.get("producer", "?")[:13]
            comp = e.get("components", {})
            final = e.get("final_score", 0.0)
            action = e.get("action", "?")

            ss = "bold bright_green" if final >= 6.0 else ("bold yellow" if final >= 3.5 else ("bold bright_yellow" if final >= 1.5 else "dim white"))

            t.add_row(
                Text(eid, style=C_DIM),
                Text(TYPE_TAGS.get(etype, etype[:3].upper()), style=TYPE_STYLES.get(etype, "white")),
                Text(prod, style="dim cyan"),
                _fmt_component(comp.get("monetary", 0)),
                _fmt_component(comp.get("irreversibility", 0)),
                _fmt_component(comp.get("scarcity", 0)),
                _fmt_component(comp.get("deadline", 0)),
                _fmt_component(comp.get("quota_penalty", 0)),
                _fmt_component(comp.get("worker_adj", 0)),
                _fmt_component(comp.get("health_boost", 0)),
                Text(f"{final:.2f}", style=ss),
                Text(ACTION_TAGS.get(action, action), style=ACTION_STYLES.get(action, "white")),
            )

        return Panel(
            t,
            title="[bold bright_cyan]SCORE BREAKDOWN -- Why Each Event Was Routed to Its Lane[/]",
            border_style="bright_yellow",
            subtitle="[dim]$$$ = monetary | IRREV = irreversibility | SCARCE = physical scarcity | DEADLN = deadline urgency | QUOTA = over-quota penalty | WORKR = worker avail adj | HLTH = health-check boost[/dim]",
        )

    # -- footer --
    def _footer(self, stats: dict) -> Panel:
        actions = stats.get("actions", {})
        ex = actions.get("execute", 0)
        ba = actions.get("batch", 0)
        df = actions.get("defer", 0)
        sh = actions.get("shed", 0)

        f = Text()
        f.append("ADAPTIVE LANES: ", style="bold white")
        f.append(f"{ex:,} Fast-laned", style=C_EXECUTE)
        f.append(" | ", style="dim")
        f.append(f"{ba:,} Batched", style=C_BATCH)
        f.append(" | ", style="dim")
        f.append(f"{df:,} Deferred", style=C_DEFER)
        f.append(" | ", style="dim")
        f.append(f"{sh:,} Shed", style=C_SHED)
        f.append(" | Zero loss on monetary events", style="bold bright_green")

        return Panel(f, style="bright_blue", height=3)


# ---------------------------------------------------------------------------
# Main Orchestrator
# ---------------------------------------------------------------------------

async def run_dashboard(spike_mode: bool = False, external: bool = False):
    console = Console(force_terminal=True)
    state = SimulatorState()
    metrics = SimulatorMetrics()

    if spike_mode:
        state.set_spike()
    else:
        state.set_normal()
    state.start()

    dash = Dashboard(state)

    if not external:
        console.print("\n[bold bright_cyan]>> Starting Ingestion Gateway (127.0.0.1:8000)...[/bold bright_cyan]")
        config = uvicorn.Config(
            app=fastapi_app,
            host="127.0.0.1",
            port=8000,
            log_level="critical",
            access_log=False,
            loop="asyncio",
        )
        server = uvicorn.Server(config)
        server_task = asyncio.create_task(server.serve())

        async with httpx.AsyncClient() as client:
            for _ in range(25):
                try:
                    r = await client.get(f"{PIPELINE_BASE}/health")
                    if r.status_code == 200:
                        console.print("[bold bright_green]   [OK] Gateway Server READY[/bold bright_green]")
                        break
                except Exception:
                    pass
                await asyncio.sleep(0.1)
    else:
        console.print("\n[bold bright_cyan]>> Connecting to existing Gateway...[/bold bright_cyan]")

    sim_client = SimulatorClient()
    await sim_client.start()
    producer_task = asyncio.create_task(run_producer(state, metrics, sim_client))
    console.print("[bold bright_green]   [OK] Request Generator STARTED[/bold bright_green]\n")
    await asyncio.sleep(0.3)

    try:
        with Live(console=console, refresh_per_second=4, screen=True) as live:
            async with httpx.AsyncClient() as api_client:
                while True:
                    try:
                        sr = await api_client.get(f"{PIPELINE_BASE}/stats", timeout=2.0)
                        rr = await api_client.get(f"{PIPELINE_BASE}/recent", timeout=2.0)
                        stats = sr.json() if sr.status_code == 200 else {}
                        recent = rr.json() if rr.status_code == 200 else []
                    except Exception:
                        stats, recent = {}, []

                    live.update(dash.build(stats, recent))

                    elapsed = time.monotonic() - dash.start_time
                    if not spike_mode and not dash.spike_triggered and elapsed > 10:
                        dash.spike_triggered = True
                        dash.spike_time = time.monotonic()
                        state.set_spike()

                    if dash.spike_triggered and dash.spike_time:
                        if time.monotonic() - dash.spike_time > 15:
                            state.set_normal()
                            dash.spike_time = None

                    await asyncio.sleep(POLL_INTERVAL)

    except KeyboardInterrupt:
        pass
    finally:
        producer_task.cancel()
        await sim_client.stop()
        if not external and 'server' in locals():
            server.should_exit = True
            server_task.cancel()

        console.print(Panel(
            Text.from_markup(
                "[bold bright_green][OK] Pipeline demo stopped cleanly.[/bold bright_green]"
            ),
            title="[bold]INTELLIGENT ADAPTIVE PIPELINE",
            border_style="bright_green",
        ))


def main():
    spike = "--spike" in sys.argv
    external = "--external" in sys.argv
    try:
        asyncio.run(run_dashboard(spike_mode=spike, external=external))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
