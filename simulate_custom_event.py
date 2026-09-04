"""
simulate_custom_event.py — Interactive Custom Event Simulator & Explainability Tool

Allows judges/presenters to input custom event attributes or select presets,
and instantly compare how the Intelligent Adaptive Pipeline handles the exact
same event under Normal (1x) vs. Flash Spike (20x) traffic.

Usage:
    python simulate_custom_event.py
"""

import sys
import time
import math
from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.prompt import Prompt, Confirm

from pipeline.scoring import (
    score_event,
    compute_intrinsic_criticality,
    compute_final_score,
    determine_action,
    get_display_band,
    SystemState,
    ScoringWeights,
    Thresholds,
    Action,
)

console = Console()

# ---------------------------------------------------------------------------
# Presets
# ---------------------------------------------------------------------------

PRESETS = {
    "1": {
        "title": "Payment Event ($5,000 INR, Irreversible)",
        "type": "payment",
        "producer_id": "payment-service",
        "has_monetary_value": True,
        "amount": 5000.0,
        "is_reversible": False,
        "affects_physical_scarcity": False,
        "has_explicit_deadline": True,
        "deadline_epoch": time.time() + 2.0,
        "is_health_check": False,
        "is_within_quota": True,
    },
    "2": {
        "title": "Order Event ($1,200 INR, Irreversible)",
        "type": "order",
        "producer_id": "order-service",
        "has_monetary_value": True,
        "amount": 1200.0,
        "is_reversible": False,
        "affects_physical_scarcity": False,
        "has_explicit_deadline": False,
        "is_health_check": False,
        "is_within_quota": True,
    },
    "3": {
        "title": "Flash Sale Stock Reservation (Scarcity + Deadline 1s)",
        "type": "inventory",
        "producer_id": "inventory-service",
        "has_monetary_value": False,
        "amount": 0.0,
        "is_reversible": True,
        "affects_physical_scarcity": True,
        "has_explicit_deadline": True,
        "deadline_epoch": time.time() + 1.0,
        "is_health_check": False,
        "is_within_quota": True,
    },
    "4": {
        "title": "Cart Add Click ($250 INR intent)",
        "type": "click",
        "producer_id": "frontend",
        "has_monetary_value": True,
        "amount": 250.0,
        "is_reversible": True,
        "affects_physical_scarcity": False,
        "has_explicit_deadline": True,
        "deadline_epoch": time.time() + 3.0,
        "is_health_check": False,
        "is_within_quota": True,
    },
    "5": {
        "title": "Standard Browsing Click ($0 INR)",
        "type": "click",
        "producer_id": "frontend",
        "has_monetary_value": False,
        "amount": 0.0,
        "is_reversible": True,
        "affects_physical_scarcity": False,
        "has_explicit_deadline": False,
        "is_health_check": False,
        "is_within_quota": True,
    },
    "6": {
        "title": "Routine Info/Debug Log ($0 INR)",
        "type": "log",
        "producer_id": "auth-service",
        "has_monetary_value": False,
        "amount": 0.0,
        "is_reversible": True,
        "affects_physical_scarcity": False,
        "has_explicit_deadline": False,
        "is_health_check": False,
        "is_within_quota": True,
    },
    "7": {
        "title": "Health Check Canary Log",
        "type": "log",
        "producer_id": "gateway",
        "has_monetary_value": False,
        "amount": 0.0,
        "is_reversible": True,
        "affects_physical_scarcity": False,
        "has_explicit_deadline": False,
        "is_health_check": True,
        "is_within_quota": True,
    },
}


def build_custom_event_interactively() -> dict[str, Any]:
    console.print("\n[bold bright_yellow]-- CONFIGURE CUSTOM EVENT HEADERS & PAYLOAD --[/bold bright_yellow]\n")

    e_type = Prompt.ask("Event Type", choices=["order", "payment", "inventory", "click", "log"], default="payment")
    producer_id = Prompt.ask("Producer Service ID", default=f"{e_type}-service")

    has_monetary = Confirm.ask("Does this event have monetary value ($$$)?", default=True)
    amount = 0.0
    if has_monetary:
        amount_str = Prompt.ask("Monetary amount (in INR/USD)", default="1500.0")
        try:
            amount = float(amount_str)
        except ValueError:
            amount = 1500.0

    is_reversible = Confirm.ask("Is this event reversible (can be retried/undone safely)?", default=False)
    affects_scarcity = Confirm.ask("Does it affect physical stock / limited inventory?", default=False)
    has_deadline = Confirm.ask("Does it have an urgent time deadline?", default=False)

    deadline_epoch = None
    if has_deadline:
        secs_str = Prompt.ask("Seconds remaining before deadline expires", default="2.0")
        try:
            secs = float(secs_str)
        except ValueError:
            secs = 2.0
        deadline_epoch = time.time() + secs

    is_health = Confirm.ask("Is this a critical system health check?", default=False)
    within_quota = Confirm.ask("Is the producer within rate-limit quota?", default=True)

    return {
        "title": f"Custom {e_type.upper()} Event",
        "type": e_type,
        "producer_id": producer_id,
        "has_monetary_value": has_monetary,
        "amount": amount,
        "is_reversible": is_reversible,
        "affects_physical_scarcity": affects_scarcity,
        "has_explicit_deadline": has_deadline,
        "deadline_epoch": deadline_epoch,
        "is_health_check": is_health,
        "is_within_quota": within_quota,
    }


def evaluate_and_display(data: dict[str, Any]):
    e_type = data["type"]
    producer_id = data["producer_id"]
    is_within_quota = data.get("is_within_quota", True)

    payload = {
        "producer_id": producer_id,
        "has_monetary_value": data["has_monetary_value"],
        "amount": data["amount"],
        "is_reversible": data["is_reversible"],
        "affects_physical_scarcity": data["affects_physical_scarcity"],
        "has_explicit_deadline": data["has_explicit_deadline"],
        "deadline_epoch": data.get("deadline_epoch"),
        "is_health_check": data["is_health_check"],
        "is_within_quota": is_within_quota,
    }

    event = {
        "event_id": f"custom-{int(time.time())}",
        "event_type": e_type,
        "timestamp": time.time(),
        "payload": payload,
    }

    # Evaluate under Normal (1x) System State
    normal_state = SystemState(
        queue_depth_normalised=0.16,
        fast_lane_full=False,
        producer_quotas={producer_id: is_within_quota},
    )
    normal_result = score_event(event, normal_state)

    # Evaluate under 20x Flash Spike System State
    spike_state = SystemState(
        queue_depth_normalised=1.0,
        fast_lane_full=True,
        producer_quotas={producer_id: is_within_quota},
    )
    spike_result = score_event(event, spike_state)

    # Render Header Summary
    console.print()
    console.print(Panel.fit(
        f"[bold white]EVENT:[/] [bold bright_cyan]{data['title']}[/bold bright_cyan]\n"
        f"[dim]Producer:[/] {producer_id}  |  [dim]Type:[/] {e_type.upper()}  |  [dim]Quota OK:[/] {is_within_quota}",
        title="[bold bright_yellow]1. EVENT INPUT SUMMARY[/bold bright_yellow]",
        border_style="yellow"
    ))

    # Score Components Breakdown Table
    w = ScoringWeights()
    comp_table = Table(title="Score Contribution Breakdown", show_header=True, header_style="bold bright_white on dark_blue", box=None)
    comp_table.add_column("Attribute / Header", style="bold white", width=26)
    comp_table.add_column("Value", style="cyan", width=22)
    comp_table.add_column("Formula / Weight", style="dim white", width=25)
    comp_table.add_column("Points Added", style="bold bright_green", justify="right", width=14)

    # Monetary
    if data["has_monetary_value"]:
        amt = data["amount"]
        m_pts = w.W1 * math.log(amt + 1.0)
        comp_table.add_row("Monetary Value ($$$)", f"INR {amt:,.2f}", f"W1 (3.0) * ln({amt:,.0f} + 1)", f"+{m_pts:.2f}")
    else:
        comp_table.add_row("Monetary Value ($$$)", "None ($0.00)", "No monetary score", "  0.00")

    # Irreversibility
    if not data["is_reversible"]:
        comp_table.add_row("Irreversible Operation", "True (Non-undoable)", f"W3 ({w.W3})", f"+{w.W3:.2f}")
    else:
        comp_table.add_row("Irreversible Operation", "False (Reversible)", "No boost", "  0.00")

    # Scarcity
    if data["affects_physical_scarcity"]:
        stock = data.get("stock_remaining", 10)
        sc_factor = max(0.0, min(1.0, 1.0 - (float(stock) / 100.0)))
        sc_pts = w.W2 * sc_factor
        comp_table.add_row("Physical Scarcity", f"True (Stock: {stock})", f"W2 ({w.W2}) * (1 - stock/100)", f"+{sc_pts:.2f}")
    else:
        comp_table.add_row("Physical Scarcity", "False", "No boost", "  0.00")

    # Deadline Urgency
    if data["has_explicit_deadline"]:
        epoch = data.get("deadline_epoch") or (time.time() + 2.0)
        left = max(epoch - time.time(), 0.0)
        urgency = max(0.0, min(1.0, 1.0 - (left / 600.0)))
        d_pts = w.W4 * urgency
        comp_table.add_row("Deadline Urgency (SLA)", f"{left:.1f}s remaining", f"W4 ({w.W4}) * clamp(1 - secs/600)", f"+{d_pts:.2f}")
    else:
        comp_table.add_row("Deadline Urgency", "None", "No deadline boost", "  0.00")

    # Health Check
    if data["is_health_check"]:
        comp_table.add_row("Health Check Canary", "True", f"W_MAX ({w.W_MAX}) Canary Override", f"+{w.W_MAX:.2f}")

    # Quota Penalty
    if not is_within_quota:
        comp_table.add_row("Quota Violation", "Exceeded", f"W8 ({w.W8}) Penalty", f"{w.W8:.2f}")

    # Worker Adjustment
    comp_table.add_row("Worker Cost Adj.", "Standard Worker", f"W7 ({w.W7}) Cost Adj.", f"{w.W7:.2f}")

    console.print(Panel(comp_table, border_style="cyan"))

    # Comparison Table: Normal (1x) vs Flash Spike (20x)
    cmp_table = Table(show_header=True, header_style="bold white on dark_green", box=None, expand=True)
    cmp_table.add_column("Metric / Decision", width=22)
    cmp_table.add_column("NORMAL TRAFFIC (1x — 1k req/min)", width=32, justify="center")
    cmp_table.add_column("FLASH SPIKE (20x — 20k req/min)", width=32, justify="center")

    n_act = normal_result["action"].upper()
    s_act = spike_result["action"].upper()

    act_styles = {
        "EXECUTE": "bold white on green",
        "BATCH": "bold black on yellow",
        "DEFER": "bold white on orange3",
        "SHED": "bold white on red",
        "BACKPRESSURE": "bold white on magenta",
    }

    cmp_table.add_row(
        "Queue Pressure",
        "16% (Normal)",
        "100% (Saturated Overload)"
    )
    cmp_table.add_row(
        "Fast Lane Saturation",
        "False (Open)",
        "True (Full)"
    )
    cmp_table.add_row(
        "Final Criticality Score",
        f"{normal_result['final_score']:.2f}",
        f"{spike_result['final_score']:.2f}"
    )
    cmp_table.add_row(
        "Priority Band",
        normal_result['display_band'],
        spike_result['display_band']
    )
    cmp_table.add_row(
        "ROUTING ACTION TAKEN",
        Text(f" [{n_act}] ", style=act_styles.get(n_act, "white")),
        Text(f" [{s_act}] ", style=act_styles.get(s_act, "white")),
    )

    console.print(Panel(cmp_table, title="[bold bright_green]2. SIDE-BY-SIDE ROUTING DECISION COMPARISON[/bold bright_green]", border_style="bright_green"))

    # Judge Rationale Explanation
    explanation = ""
    if s_act == "EXECUTE":
        explanation = (
            f"[bold bright_green]PROTECTED & FAST-LANED:[/bold bright_green] This event carries critical "
            f"monetary or non-reversible value (Final Score = {spike_result['final_score']:.2f}). "
            f"Even under 20,000 req/min flash spike, the adaptive pipeline guarantees this event bypasses "
            f"all queues and executes immediately in the fast lane!"
        )
    elif s_act == "DEFER":
        explanation = (
            f"[bold yellow]DEFERRED TO COLD QUEUE (NO SHEDDING POLICY):[/bold yellow] Under normal traffic (1x), "
            f"this event was [{n_act}]. Under 20x flash overload, low-urgency events sit in the cold queue with "
            f"[bold bright_green]100% Data Durability[/bold bright_green] until system load relaxes."
        )
    elif s_act == "BATCH":
        explanation = (
            f"[bold bright_yellow]SAFE BATCHED PROCESSING:[/bold bright_yellow] Score = {spike_result['final_score']:.2f}. "
            f"Event is grouped into a micro-batch for asynchronous bulk worker execution."
        )
    else:
        explanation = f"Routed to [{s_act}] based on real-time adaptive scoring rules."

    console.print(Panel(Text.from_markup(explanation), title="[bold white]3. ADAPTIVE PIPELINE RATIONALE FOR JUDGES[/bold white]", border_style="cyan"))


def main():
    while True:
        console.clear()
        console.print("\n" + "=" * 70)
        console.print("[bold bright_cyan]  INTELLIGENT ADAPTIVE PIPELINE — CUSTOM EVENT TESTER & EXPLAINER[/bold bright_cyan]")
        console.print("=" * 70)
        console.print("Select an event scenario to test against 1x Normal vs 20x Flash Spike:\n")

        for key, p in PRESETS.items():
            console.print(f"  [bold bright_yellow][{key}][/bold bright_yellow] {p['title']}")
        console.print("  [bold bright_green][8][/bold bright_green] Custom Event (Interactively enter your own headers)")
        console.print("  [bold red][Q][/bold red] Quit\n")

        choice = Prompt.ask("Choose scenario [1-8 or Q]", default="1").strip().upper()

        if choice == "Q":
            console.print("[bold bright_green]Exiting custom event tester. Goodbye![/bold bright_green]")
            break

        if choice in PRESETS:
            evaluate_and_display(PRESETS[choice])
        elif choice == "8":
            custom_data = build_custom_event_interactively()
            evaluate_and_display(custom_data)
        else:
            console.print("[red]Invalid choice. Try again.[/red]")

        console.print("\n" + "-" * 70)
        Prompt.ask("Press [Enter] to test another event scenario...")


if __name__ == "__main__":
    main()
