"""
simulator/generator.py

Synthetic event generation.

Responsibilities:
  - Produce structurally valid events that match the pipeline's Event contract.
  - Vary event contents randomly within realistic bounds.
  - Select event_type according to configured probability weights.
  - Set timestamp at the moment of creation (not at send time).

Each event is a plain Python dict — serialised to JSON by the HTTP client.
No LLM is used; all values are generated programmatically.
"""

import random
import time
import uuid
from typing import Any

from simulator.config import EVENT_TYPE_WEIGHTS

# ---------------------------------------------------------------------------
# Reference data — realistic but synthetic
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
_LOG_LEVELS = ["INFO", "INFO", "INFO", "WARN", "ERROR"]  # weighted toward INFO

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
    return {
        "order_id": f"ord-{uuid.uuid4().hex[:8]}",
        "user_id": f"usr-{random.randint(1000, 99999)}",
        "product_id": f"prd-{random.randint(100, 9999)}",
        "quantity": random.randint(1, 10),
        "amount": round(random.uniform(99.0, 49999.0), 2),
        "currency": random.choice(_CURRENCIES),
        "status": random.choice(_ORDER_STATUSES),
    }


def _make_payment_payload() -> dict[str, Any]:
    return {
        "payment_id": f"pay-{uuid.uuid4().hex[:8]}",
        "order_id": f"ord-{uuid.uuid4().hex[:8]}",
        "user_id": f"usr-{random.randint(1000, 99999)}",
        "amount": round(random.uniform(99.0, 49999.0), 2),
        "currency": random.choice(_CURRENCIES),
        "method": random.choice(_PAYMENT_METHODS),
        "status": random.choice(_PAYMENT_STATUSES),
    }


def _make_inventory_payload() -> dict[str, Any]:
    return {
        "product_id": f"prd-{random.randint(100, 9999)}",
        "warehouse_id": f"wh-{random.randint(1, 20):02d}",
        "quantity": random.randint(0, 5000),
        "operation": random.choice(_INVENTORY_OPERATIONS),
    }


def _make_click_payload() -> dict[str, Any]:
    return {
        "user_id": f"usr-{random.randint(1000, 99999)}",
        "product_id": f"prd-{random.randint(100, 9999)}",
        "page": random.choice(_CLICK_PAGES),
        "action": random.choice(_CLICK_ACTIONS),
        "session_id": f"ses-{uuid.uuid4().hex[:12]}",
    }


def _make_log_payload() -> dict[str, Any]:
    level = random.choice(_LOG_LEVELS)
    template = random.choice(_LOG_MESSAGES[level])
    # Fill in any {} placeholder with a realistic latency/count value
    message = template.format(random.randint(5, 2000)) if "{}" in template else template
    return {
        "service": random.choice(_LOG_SERVICES),
        "level": level,
        "message": message,
        "instance_id": f"i-{random.randint(1, 8):02d}",
    }


# Map each event_type to its payload builder
_PAYLOAD_BUILDERS: dict[str, Any] = {
    "order":     _make_order_payload,
    "payment":   _make_payment_payload,
    "inventory": _make_inventory_payload,
    "click":     _make_click_payload,
    "log":       _make_log_payload,
}

# Pre-compute sorted lists for random.choices (stable order = reproducible tests)
_EVENT_TYPES: list[str] = list(EVENT_TYPE_WEIGHTS.keys())
_WEIGHTS: list[float] = [EVENT_TYPE_WEIGHTS[t] for t in _EVENT_TYPES]

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def pick_event_type() -> str:
    """
    Select a random event_type according to configured probability weights.

    Uses random.choices with the weights from config.EVENT_TYPE_WEIGHTS.
    """
    return random.choices(_EVENT_TYPES, weights=_WEIGHTS, k=1)[0]


def generate_event(event_type: str | None = None) -> dict[str, Any]:
    """
    Generate a single synthetic event.

    Args:
        event_type: Force a specific type (useful in tests).
                    If None, a type is chosen by probability weight.

    Returns:
        A dict conforming to the Event contract:
        {
            "event_id":   str (UUID4),
            "event_type": str,
            "timestamp":  float (Unix epoch, set at creation),
            "payload":    dict,
        }

    Notes:
        - timestamp is recorded at the moment this function is called —
          i.e. arrival time, not send time.
        - Payload contents vary per event_type; all values are synthetic.
    """
    chosen_type = event_type or pick_event_type()
    return {
        "event_id": str(uuid.uuid4()),
        "event_type": chosen_type,
        "timestamp": time.time(),        # creation / arrival time
        "payload": _PAYLOAD_BUILDERS[chosen_type](),
    }
