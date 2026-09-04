# Intelligent Data Pipeline — Request Simulator

> **Hackathon Component: Event Producer / Request Simulator**
> 
> Generates realistic synthetic e-commerce events at a configurable Poisson arrival rate and sends them via HTTP to a FastAPI ingestion endpoint.

---

## Overview

This component simulates e-commerce traffic for an intelligent data pipeline.  It models two traffic regimes:

| Mode   | Rate             | Events/sec |
|--------|------------------|------------|
| Normal | 1 000 events/min | ≈ 16.67    |
| Spike  | 20 000 events/min | ≈ 333.33  |

The spike models a **flash-sale**: a sudden step-change in traffic (not a ramp).

---

## Architecture

```
simulator/
├── config.py       ← Constants + environment variable overrides
├── generator.py    ← Synthetic event generation (5 types)
├── client.py       ← httpx async HTTP client (connection pooling)
├── controller.py   ← SimulatorState: running / rate / mode
├── metrics.py      ← Counters, latency, rate estimation
└── main.py         ← Entry point: producer loop + CLI + status display

pipeline/
└── main.py         ← Minimal FastAPI receiver (test sink)
```

The simulator is **a separate process** that communicates with the pipeline over HTTP.  It does not import pipeline code.

---

## Quick Start

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Start the FastAPI receiver (Terminal 1)

```bash
cd intelligent-pipeline
uvicorn pipeline.main:app --reload
```

Check it's running: http://127.0.0.1:8000/docs

### 3. Start the simulator (Terminal 2)

```bash
cd intelligent-pipeline
python -m simulator.main
```

### 4. Control the simulator via CLI

```
> start            ← Begin producing events at 1 000/min
> status           ← Print current metrics
> spike            ← Jump to 20 000/min (flash-sale)
> normal           ← Return to 1 000/min
> rate 5000        ← Set a custom rate (events/min)
> model poisson    ← Poisson arrivals (default, realistic)
> model fixed      ← Fixed uniform inter-arrival (debug)
> stop             ← Pause production
> quit             ← Exit
```

### 5. Monitor live stats (automatic every 5 seconds)

```
======================================================
 REQUEST SIMULATOR
======================================================
 Mode:                    NORMAL
 Target rate:           1000 events/min
 Actual rate:          16.42 events/sec
 Avg latency:           2.31 ms
------------------------------------------------------
 Generated:             1,250
 Sent:                  1,247
 Successful:            1,245
 Failed:                    2
------------------------------------------------------
 Events by type:
   order           123
   payment         118
   inventory       121
   click           624
   log             264
======================================================
```

---

## Event Contract

Every event posted to `POST /events`:

```json
{
  "event_id": "0f6f4a48-...",
  "event_type": "payment",
  "timestamp": 1756960000.123,
  "payload": {
    "payment_id": "pay-abc123",
    "order_id":   "ord-xyz456",
    "amount":     499.0,
    "currency":   "INR",
    "method":     "upi",
    "status":     "success"
  }
}
```

### Event Types

| Type        | Distribution | Key Payload Fields |
|-------------|-------------|--------------------|
| `order`     | 10%         | order_id, user_id, product_id, quantity, amount, currency, status |
| `payment`   | 10%         | payment_id, order_id, user_id, amount, currency, method, status |
| `inventory` | 10%         | product_id, warehouse_id, quantity, operation |
| `click`     | 50%         | user_id, product_id, page, action, session_id |
| `log`       | 20%         | service, level, message, instance_id |

---

## Traffic Model

The primary model is a **Poisson arrival process**:

```python
delay = random.expovariate(lambda_rate)   # lambda = events/sec
await asyncio.sleep(delay)
```

This produces statistically realistic stochastic arrivals.  Short windows may differ from the target rate; longer windows converge toward it (Law of Large Numbers).

A **fixed mode** (`model fixed`) is available for debugging — it spaces events exactly `1/λ` seconds apart.

---

## Configuration

All values can be overridden via environment variables:

| Env Variable              | Default                       | Description                        |
|---------------------------|-------------------------------|------------------------------------|
| `SIM_NORMAL_RATE_PER_MIN` | `1000`                        | Normal traffic rate (events/min)   |
| `SIM_SPIKE_RATE_PER_MIN`  | `20000`                       | Spike rate (events/min)            |
| `SIM_EVENT_ENDPOINT`      | `http://127.0.0.1:8000/events`| Target FastAPI endpoint            |
| `SIM_HTTP_TIMEOUT`        | `5.0`                         | HTTP request timeout (seconds)     |
| `SIM_HTTP_MAX_CONNECTIONS`| `20`                          | httpx connection pool size         |
| `SIM_STATUS_INTERVAL`     | `5.0`                         | Status display cadence (seconds)   |
| `SIM_W_ORDER`             | `0.10`                        | Weight for `order` events          |
| `SIM_W_PAYMENT`           | `0.10`                        | Weight for `payment` events        |
| `SIM_W_INVENTORY`         | `0.10`                        | Weight for `inventory` events      |
| `SIM_W_CLICK`             | `0.50`                        | Weight for `click` events          |
| `SIM_W_LOG`               | `0.20`                        | Weight for `log` events            |

---

## Running Tests

```bash
cd intelligent-pipeline
pytest -v
```

Test coverage:
- `test_generator.py`   — event structure, UUID, timestamps, payloads, distribution
- `test_controller.py`  — state transitions, rate switching, validation
- `test_metrics.py`     — counters, latency, rate estimation, ring buffer
- `test_config.py`      — config presence, types, weight sum
- `test_poisson.py`     — LLN convergence, spike vs normal inter-arrival
- `test_pipeline.py`    — FastAPI validation (all accepted/rejected cases)
- `test_client.py`      — HTTP success/failure/error handling (mock transport)

---

## FastAPI Endpoints

| Endpoint    | Method | Description                           |
|-------------|--------|---------------------------------------|
| `/events`   | POST   | Accept a validated event              |
| `/stats`    | GET    | Per-process ingestion counters        |
| `/health`   | GET    | Liveness check                        |
| `/docs`     | GET    | Swagger UI (auto-generated)           |

---

## Design Principles

1. **Arrival rate ≠ iteration count** — 20 000 events/min = ~333 events arriving per second over time, not 20 000 concurrent requests.
2. **Single async producer** — one coroutine with `asyncio.sleep`; no mass `asyncio.gather`.
3. **Connection reuse** — one `httpx.AsyncClient` for the entire run.
4. **Rate changes are immediate** — the producer reads `state.current_rate` every iteration; no restart needed.
5. **Failure resilience** — all HTTP errors are caught and counted; the loop never stops due to a bad response.
6. **No flooding stdout** — periodic summaries instead of per-event logging at high rates.

---

## Future Extensions (not implemented here)

- Priority classification (P0/P1/P2) in the pipeline
- Redis / Kafka integration
- Adaptive processing engine
- Dashboard
- Worker pools and backpressure

---

## License

MIT
