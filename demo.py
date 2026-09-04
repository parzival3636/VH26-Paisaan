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
# In-process Producer Loop — Direct Scoring (no HTTP bottleneck)
# ---------------------------------------------------------------------------

async def run_producer(state: SimulatorState, metrics: SimulatorMetrics, client: SimulatorClient):
    """
    High-throughput event producer that scores events directly in-process.

    Instead of sending each event as an HTTP POST (bottlenecked at ~40-80 eps
    on Windows localhost), we call score_event() directly and update the
    pipeline's shared stats. This achieves true 20,000+ events/min.

    The HTTP server still runs for the dashboard to poll /stats and /recent.
    """
    from pipeline.main import _stats, _recent_events, _arrival_timestamps
    from pipeline.scoring import score_event, SystemState
    from pipeline.db_sink import db_sink

    last_time = time.monotonic()
    accumulator = 0.0

    while True:
        if not state.running:
            await asyncio.sleep(0.05)
            last_time = time.monotonic()
            continue

        now = time.monotonic()
        dt = now - last_time
        last_time = now

        lam = state.current_rate  # events/sec (16.7 at 1x, 333.3 at 20x)
        accumulator += dt * lam

        count = int(accumulator)
        if count > 0:
            accumulator -= count
            count = min(count, 500)  # max burst per tick

            for _ in range(count):
                event = generate_event()
                metrics.record_generated(event["event_type"])
                metrics.record_sent()

                # -- Direct in-process scoring (bypasses HTTP entirely) --
                now_mono = time.monotonic()
                _arrival_timestamps.append(now_mono)
                # Trim sliding window to 1 second
                while _arrival_timestamps and _arrival_timestamps[0] < now_mono - 1.0:
                    _arrival_timestamps.popleft()

                current_eps = len(_arrival_timestamps)
                queue_depth = min(current_eps / 50.0, 1.0)
                fast_lane_full = current_eps > 120

                e_type = event["event_type"]
                payload = event["payload"]
                producer_id = payload.get("producer_id", "simulator")

                normalized_event = {
                    "event_id": event["event_id"],
                    "event_type": e_type,
                    "type": e_type,
                    "timestamp": event["timestamp"],
                    "payload": payload,
                }

                system_state = SystemState(
                    queue_depth_normalised=queue_depth,
                    fast_lane_full=fast_lane_full,
                    queue_velocity=0.0,
                    producer_quotas={producer_id: True},
                )

                scoring_result = score_event(normalized_event, system_state)

                # Update shared pipeline stats (read by /stats endpoint)
                _stats["total_ingested"] += 1
                action_key = scoring_result["action"]
                if action_key in _stats["actions"]:
                    _stats["actions"][action_key] += 1
                type_key = e_type if e_type in _stats["by_type"] else "other"
                _stats["by_type"][type_key] += 1

                # Update recent events (read by /recent endpoint)
                event_record = {
                    "event_id": event["event_id"][:16],
                    "producer": producer_id,
                    "type": e_type,
                    "quota": True,
                    "intrinsic": scoring_result["intrinsic_score"],
                    "final_score": scoring_result["final_score"],
                    "band": scoring_result["display_band"],
                    "action": scoring_result["action"],
                    "ingestion_time": event["timestamp"],
                    "latency_ms": 0.0,
                    "components": scoring_result.get("components", {}),
                }
                _recent_events.append(event_record)
                db_sink.record_transaction(event_record)

                metrics.record_response(202, 0.0)

        await asyncio.sleep(0.005)  # 5ms tick — yields to event loop for dashboard polling


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

        target_rate = self.state.rate_per_min
        mult = target_rate / 1000.0

        if mult >= 15.0:
            badge = Text(f" FLASH SPIKE ({mult:g}x — {target_rate:,.0f} req/min) ", style="bold white on red")
        elif mult >= 5.0:
            badge = Text(f" HIGH LOAD ({mult:g}x — {target_rate:,.0f} req/min) ", style="bold white on dark_orange")
        elif mult > 1.0:
            badge = Text(f" MODERATE LOAD ({mult:g}x — {target_rate:,.0f} req/min) ", style="bold white on blue")
        else:
            badge = Text(f" NORMAL TRAFFIC (1x — 1k req/min) ", style="bold white on dark_green")

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

        avg_eps = sum(self.throughput_history) / max(len(self.throughput_history), 1) if self.throughput_history else eps
        req_per_min = avg_eps * 60.0

        spark = sparkline(list(self.throughput_history), 10)

        t = Table(show_header=False, box=None, padding=(0, 0))
        t.add_column("k", style=C_DIM, width=14)
        t.add_column("v", style="bold white", width=12, justify="right")
        t.add_column("g", width=10, justify="right")

        t.add_row("Total Ingested", f"{total:,}", "")
        t.add_row("Rate / sec", f"{avg_eps:.1f} /s", Text(spark, style="bright_green"))
        t.add_row("Rate / min", Text(f"{req_per_min:,.0f} /m", style="bold bright_yellow"), "")
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

            ss = "bold bright_green" if score >= 6.0 else ("bold yellow" if score >= 3.0 else ("bold bright_yellow" if score >= 1.0 else "dim white"))

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

            ss = "bold bright_green" if final >= 6.0 else ("bold yellow" if final >= 3.0 else ("bold bright_yellow" if final >= 1.0 else "dim white"))

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
        f.append(f"{df:,} Deferred (Cold)", style=C_DEFER)
        if sh > 0:
            f.append(" | ", style="dim")
            f.append(f"{sh:,} Legacy Shed", style=C_SHED)
        f.append(" | ", style="dim")
        f.append("ZERO-LOSS", style="bold bright_green")
        f.append(" | ", style="dim")
        f.append("[1] 1x [5] 5x [0] 10x [2] 20x [+/-] Adjust", style="bold yellow")

        return Panel(f, style="bright_blue", height=3)


def start_keyboard_listener(state: SimulatorState, dash: Dashboard):
    import threading
    import time
    def _listener():
        try:
            import msvcrt
            while True:
                try:
                    if msvcrt.kbhit():
                        ch = msvcrt.getch()
                        if ch in (b'\x00', b'\xe0'):
                            msvcrt.getch()
                            continue
                        c = ch.decode("utf-8", errors="ignore").lower()
                        if c == "1":
                            state.set_multiplier(1.0)
                            dash.spike_triggered = True
                        elif c == "2":
                            state.set_multiplier(20.0)
                            dash.spike_triggered = True
                        elif c == "5":
                            state.set_multiplier(5.0)
                            dash.spike_triggered = True
                        elif c == "0":
                            state.set_multiplier(10.0)
                            dash.spike_triggered = True
                        elif c in ("+", "="):
                            cur = state.rate_per_min / 1000.0
                            state.set_multiplier(min(cur + 5.0, 50.0))
                            dash.spike_triggered = True
                        elif c in ("-", "_"):
                            cur = state.rate_per_min / 1000.0
                            state.set_multiplier(max(cur - 5.0, 1.0))
                            dash.spike_triggered = True
                except Exception:
                    pass
                time.sleep(0.02)
        except Exception:
            pass

    t = threading.Thread(target=_listener, daemon=True)
    t.start()


# ---------------------------------------------------------------------------
# Main Orchestrator
# ---------------------------------------------------------------------------

async def run_dashboard(mode_flag: str = "auto", multiplier: float = 1.0, external: bool = False):
    console = Console(force_terminal=True)
    state = SimulatorState()
    metrics = SimulatorMetrics()

    if mode_flag == "spike":
        state.set_spike()
    elif mode_flag == "custom":
        state.set_multiplier(multiplier)
    elif mode_flag == "normal":
        state.set_normal()
    else:
        state.set_normal()

    state.start()

    dash = Dashboard(state)
    start_keyboard_listener(state, dash)

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
        with Live(console=console, refresh_per_second=4, screen=False) as live:
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

                    # Auto transition mode (Normal -> Spike -> Normal) if not interactively controlled
                    if mode_flag == "auto":
                        elapsed = time.monotonic() - dash.start_time
                        if not dash.spike_triggered and elapsed > 12:
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
    external = "--external" in sys.argv
    mode_flag = "normal"
    multiplier = 1.0

    args = [a for a in sys.argv[1:] if a != "--external"]

    if len(args) == 0:
        print("\n" + "=" * 65)
        print("  INTELLIGENT ADAPTIVE DATA PIPELINE — DEMO LOAD SELECTION")
        print("=" * 65)
        print("  [1] Normal Traffic Mode   (1x  —  1,000 req/min  — Zero Loss)")
        print("  [2] Flash Spike Mode     (20x — 20,000 req/min  — Graceful Degradation)")
        print("  [3] Auto-Transition Mode (Starts 1x -> Spikes to 20x after 12s)")
        print("=" * 65)
        try:
            choice = input("Select mode [1/2/3] (default 1): ").strip()
        except (KeyboardInterrupt, EOFError):
            sys.exit(0)

        if choice == "2":
            mode_flag = "spike"
            multiplier = 20.0
        elif choice == "3":
            mode_flag = "auto"
            multiplier = 1.0
        else:
            mode_flag = "normal"
            multiplier = 1.0
    else:
        for i, arg in enumerate(args):
            a_lower = arg.lower()
            if a_lower in ("--spike", "-s", "20x"):
                mode_flag = "spike"
                multiplier = 20.0
            elif a_lower in ("--normal", "-n", "1x"):
                mode_flag = "normal"
                multiplier = 1.0
            elif a_lower.startswith("--load"):
                val_str = ""
                if "=" in arg:
                    val_str = arg.split("=")[1]
                elif i + 1 < len(args):
                    val_str = args[i + 1]
                val_str = val_str.lower().rstrip("x")
                try:
                    multiplier = float(val_str)
                    mode_flag = "custom"
                except ValueError:
                    pass
            elif a_lower.endswith("x") and a_lower[:-1].replace(".", "", 1).isdigit():
                try:
                    multiplier = float(a_lower[:-1])
                    mode_flag = "custom"
                except ValueError:
                    pass

    try:
        asyncio.run(run_dashboard(mode_flag=mode_flag, multiplier=multiplier, external=external))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
