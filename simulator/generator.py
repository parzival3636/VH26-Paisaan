"""
simulator/generator.py

Synthetic event generation with realistic scoring attributes.

Responsibilities:
  - Produce structurally valid events matching the pipeline contract.
  - Generate attributes (monetary value, irreversibility, physical scarcity, deadlines, health checks)
    that span the full criticality spectrum (0.0 to 15.0+).
  - Ensure all 4 adaptive routing actions (EXECUTE, BATCH, DEFER, SHED) are actively exercised.
"""

import random
import time
import uuid
from typing import Any

from simulator.config import EVENT_TYPE_WEIGHTS

# ---------------------------------------------------------------------------
# Reference data
# ---------------------------------------------------------------------------

_CURRENCIES = ["INR", "USD", "EUR", "GBP", "AED"]
_PAYMENT_METHODS = ["upi", "card", "netbanking", "wallet"]
_PAYMENT_STATUSES = ["success", "pending", "failed"]
_ORDER_STATUSES = ["created", "confirmed", "processing", "shipped", "cancelled"]
_INVENTORY_OPERATIONS = ["stock_update", "reservation", "release"]
_CLICK_PAGES = ["home", "product", "cart", "checkout", "search", "category", "wishlist"]
_CLICK_ACTIONS = ["view", "click", "search", "add_to_cart"]
_LOG_SERVICES = [
    "order-service",
    "payment-service",
    "inventory-service",
    "gateway",
    "auth-service",
    "search-service",
]
_LOG_LEVELS = ["INFO", "INFO", "WARN", "ERROR"]

_LOG_MESSAGES: dict[str, list[str]] = {
    "INFO": [
        "Request processed successfully",
        "Cache hit for product listing",
        "Database query completed in {}ms",
        "Health check passed",
        "Session refreshed",
    ],
    "WARN": [
        "Response time exceeding threshold: {}ms",
        "Cache miss — falling back to database",
        "Retrying failed request (attempt {}/3)",
        "High memory usage detected",
    ],
    "ERROR": [
        "Unhandled exception in request handler",
        "Database connection timeout after {}ms",
        "External API call failed with status 503",
        "Payment gateway unreachable",
    ],
}

# ---------------------------------------------------------------------------
# Per-type payload generators
# ---------------------------------------------------------------------------


def _make_order_payload() -> dict[str, Any]:
    amount = round(random.uniform(199.0, 49999.0), 2)
    return {
        "order_id": f"ord-{uuid.uuid4().hex[:8]}",
        "user_id": f"usr-{random.randint(1000, 99999)}",
        "product_id": f"prd-{random.randint(100, 9999)}",
        "quantity": random.randint(1, 10),
        "amount": amount,
        "currency": random.choice(_CURRENCIES),
        "status": random.choice(_ORDER_STATUSES),
        # --- Intrinsic scoring attributes: High Criticality (Score ~ 7-14 -> EXECUTE) ---
        "has_monetary_value": True,
        "is_reversible": False,
        "affects_physical_scarcity": False,
        "has_explicit_deadline": False,
        "deadline_epoch": None,
        "is_health_check": False,
        "producer_id": "order-service",
    }


def _make_payment_payload() -> dict[str, Any]:
    amount = round(random.uniform(299.0, 49999.0), 2)
    return {
        "payment_id": f"pay-{uuid.uuid4().hex[:8]}",
        "order_id": f"ord-{uuid.uuid4().hex[:8]}",
        "user_id": f"usr-{random.randint(1000, 99999)}",
        "amount": amount,
        "currency": random.choice(_CURRENCIES),
        "method": random.choice(_PAYMENT_METHODS),
        "status": random.choice(_PAYMENT_STATUSES),
        # --- Intrinsic scoring attributes: High Criticality (Score ~ 8-15 -> EXECUTE) ---
        "has_monetary_value": True,
        "is_reversible": False,
        "affects_physical_scarcity": False,
        "has_explicit_deadline": True,
        "deadline_epoch": time.time() + random.uniform(1.0, 5.0),
        "is_health_check": False,
        "producer_id": "payment-service",
    }


def _make_inventory_payload() -> dict[str, Any]:
    quantity = random.randint(0, 5000)
    variant = random.random()

    if variant < 0.45:
        # Urgent stock reservation / flash sale lock -> Score ~ 4.5 to 5.5 (BATCH)
        affects_scarcity = True
        has_deadline = True
        deadline_epoch = time.time() + random.uniform(0.5, 2.0)
    elif variant < 0.80:
        # Medium stock update -> Score ~ 2.0 to 3.0 (DEFER)
        affects_scarcity = True
        has_deadline = False
        deadline_epoch = None
    else:
        # Routine warehouse audit -> Score ~ 0.0 (SHED)
        affects_scarcity = False
        has_deadline = False
        deadline_epoch = None

    return {
        "product_id": f"prd-{random.randint(100, 9999)}",
        "warehouse_id": f"wh-{random.randint(1, 20):02d}",
        "quantity": quantity,
        "operation": random.choice(_INVENTORY_OPERATIONS),
        # --- Intrinsic scoring attributes ---
        "has_monetary_value": False,
        "is_reversible": True,
        "affects_physical_scarcity": affects_scarcity,
        "has_explicit_deadline": has_deadline,
        "deadline_epoch": deadline_epoch,
        "is_health_check": False,
        "producer_id": "inventory-service",
    }


def _make_click_payload() -> dict[str, Any]:
    action = random.choice(_CLICK_ACTIONS)
    variant = random.random()

    if action == "add_to_cart" or variant < 0.25:
        # Intent to buy / cart action -> Score ~ 3.6 to 4.8 (BATCH)
        has_monetary = True
        amount = round(random.uniform(49.0, 499.0), 2)
        has_deadline = True
        deadline_epoch = time.time() + random.uniform(1.0, 3.0)
    elif variant < 0.55:
        # Checkout view / item click -> Score ~ 1.8 to 2.8 (DEFER)
        has_monetary = True
        amount = round(random.uniform(10.0, 99.0), 2)
        has_deadline = False
        deadline_epoch = None
    else:
        # Browsing click -> Score ~ 0.0 (SHED)
        has_monetary = False
        amount = 0.0
        has_deadline = False
        deadline_epoch = None

    return {
        "user_id": f"usr-{random.randint(1000, 99999)}",
        "product_id": f"prd-{random.randint(100, 9999)}",
        "page": random.choice(_CLICK_PAGES),
        "action": action,
        "session_id": f"ses-{uuid.uuid4().hex[:12]}",
        "amount": amount,
        # --- Intrinsic scoring attributes ---
        "has_monetary_value": has_monetary,
        "is_reversible": True,
        "affects_physical_scarcity": False,
        "has_explicit_deadline": has_deadline,
        "deadline_epoch": deadline_epoch,
        "is_health_check": False,
        "producer_id": "frontend",
    }


def _make_log_payload() -> dict[str, Any]:
    level = random.choice(_LOG_LEVELS)
    template = random.choice(_LOG_MESSAGES[level])
    message = template.format(random.randint(5, 2000)) if "{}" in template else template
    service = random.choice(_LOG_SERVICES)

    is_health = "Health check" in message
    if is_health:
        # Health check canary log -> Score > 9.5 (EXECUTE)
        has_deadline = False
        deadline_epoch = None
    elif level in ("WARN", "ERROR"):
        # Alert / Error log -> Score ~ 2.2 to 4.2 (DEFER / BATCH)
        has_deadline = True
        deadline_epoch = time.time() + random.uniform(0.5, 2.0)
    else:
        # Info debug log -> Score ~ 0.0 (SHED)
        has_deadline = False
        deadline_epoch = None

    return {
        "service": service,
        "level": level,
        "message": message,
        "instance_id": f"i-{random.randint(1, 8):02d}",
        # --- Intrinsic scoring attributes ---
        "has_monetary_value": False,
        "is_reversible": True,
        "affects_physical_scarcity": False,
        "has_explicit_deadline": has_deadline,
        "deadline_epoch": deadline_epoch,
        "is_health_check": is_health,
        "producer_id": service,
    }


# Map each event_type to its payload builder
_PAYLOAD_BUILDERS: dict[str, Any] = {
    "order":     _make_order_payload,
    "payment":   _make_payment_payload,
    "inventory": _make_inventory_payload,
    "click":     _make_click_payload,
    "log":       _make_log_payload,
}

_EVENT_TYPES: list[str] = list(EVENT_TYPE_WEIGHTS.keys())
_WEIGHTS: list[float] = [EVENT_TYPE_WEIGHTS[t] for t in _EVENT_TYPES]

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def pick_event_type() -> str:
    return random.choices(_EVENT_TYPES, weights=_WEIGHTS, k=1)[0]


def generate_event(event_type: str | None = None) -> dict[str, Any]:
    chosen_type = event_type or pick_event_type()
    return {
        "event_id": str(uuid.uuid4()),
        "event_type": chosen_type,
        "timestamp": time.time(),
        "payload": _PAYLOAD_BUILDERS[chosen_type](),
    }
