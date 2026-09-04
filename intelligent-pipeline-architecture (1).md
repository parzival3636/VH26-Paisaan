# Intelligent Adaptive Data Pipeline — Full Technical Specification

**Domain:** Application Building Pipelines / Processing
**Problem Statement:** Intelligent Data Pipeline for Optimized Data Processing
**Challenge Line:** *Build a pipeline that doesn't handle more data by using more resources — it handles the right data, at the right time, using the resources it already has, and never silently loses the events that actually matter.*

---

## 1. Executive Summary

This system ingests a mixed e-commerce event stream (orders, payments, inventory updates, clicks, logs) and makes a real-time decision for every single event: **execute now, batch, defer, or shed** — without ever silently losing a critical event.

The core innovation: instead of a static lookup table (`event.type → fixed priority`), urgency is **computed dynamically** per event from (a) what the event itself is worth/at-stake (intrinsic criticality) and (b) what the system is currently experiencing (live load state). This means two events of the same "type" can be treated differently if their actual stakes differ, and the system's behavior shifts continuously as load changes — no hardcoded "if spike then batch-mode" branch anywhere.

The design combines two lineages of industry practice:
- **Amazon's publicly documented layered admission-control philosophy** (cheap filters first, expensive decisions delegated to local real-time state, health-check-equivalent priority, staleness-aware queue management)
- **A novel, explicit, continuous scoring engine** that fills the gap Amazon's public docs describe conceptually but never specify — making the "local server-side decision" concrete, tunable, and demonstrable.

---

## 2. Functional Requirements

| ID | Requirement | Satisfied By |
|---|---|---|
| FR1 | Ingest ≥3 distinct event types (orders, payments, inventory, clicks, logs) at an adjustable rate, from 1,000/min to 20,000/min, triggerable live | Load Simulator (Section 6.1) |
| FR2 | Classify and route orders/payments with priority over logs/clicks | Dynamic Criticality Scoring (Section 4) |
| FR3 | Process individually under normal load; shift to micro-batching for lower-priority types under spike load | Continuous scoring against load-sensitive thresholds (Section 4.3) |
| FR4 | Apply backpressure and a documented, visible shedding policy when queues exceed thresholds | Layered Admission Control + Shed Policy (Section 5) |
| FR5 | Live observability dashboard: queue size per tier, throughput, per-tier latency, deferred/batched/shed counts | Dashboard spec (Section 8) |
| FR6 | Critical events must never be silently dropped | Hard floor in scoring function + backpressure branch (Section 4.4, Section 5.3) |
| FR7 | Demonstrate both baseline (1,000/min) and spike (20,000/min) conditions live, on the same running pipeline | Toggleable rate control in simulator |
| FR8 | Benchmark adaptive pipeline against a naive fixed-strategy baseline under identical spike conditions | Baseline Mode (Section 9) |

### Stretch Functional Requirements

| ID | Requirement | Satisfied By |
|---|---|---|
| SFR1 | Fault tolerance with idempotent retry | Section 10.1 |
| SFR2 | Dynamic worker scaling based on real queue depth | Section 10.2 |
| SFR3 | Duplicate event detection | Section 10.3 |
| SFR4 | Formalized scored decision function, not fixed if/else | **This entire document — Section 4 is this requirement, fully implemented as core, not stretch** |
| SFR5 | Cost/energy estimation per strategy | Section 10.4 |

---

## 3. Non-Functional Requirements

| Category | Requirement |
|---|---|
| **Latency** | P0-equivalent (high-score) events: end-to-end latency must remain stable (target <100ms) regardless of system load. Reported per display-tier, never as a single aggregate. |
| **Throughput** | System must sustain 20,000 events/min ingestion without crashing, OOMing, or unbounded queue growth. |
| **Data Integrity** | Zero silent data loss for any event scoring above the shed floor. Every shed event must be logged with event ID, computed score, and reason. |
| **Observability** | All routing decisions (execute/batch/defer/shed) must be visible in real time on the dashboard, with the computed score shown per event class, not just the outcome. |
| **Bounded Memory** | All queues are hard-bounded. Memory overhead is O(number of queues), not O(number of events) — queue count stays fixed (roughly 4–6 structures) regardless of load. |
| **Honesty/Transparency** | Any mocked component (DB, payment gateway) must be explicitly declared as simulated, not disguised as real infrastructure. |
| **Demonstrability** | Every core behavior (priority differentiation, batching shift, shedding, backpressure) must be triggerable and visible live during a 5-minute demo — not only shown as pre-recorded numbers. |

---

## 4. The Dynamic Scoring Engine (Core Differentiator)

### 4.1 Why not a static table

A static `event.type → priority` lookup cannot answer: *why should two payment events — one for ₹200, one for ₹2,00,000 — receive identical treatment?* It also cannot handle an unknown event type gracefully without a hardcoded fallback rule, and it cannot adapt priority as system conditions change without a separate layer of if/else logic bolted on top.

Instead, priority is **computed fresh, per event**, from two components.

### 4.2 Component 1 — Intrinsic Criticality (from the event's own payload)

```
intrinsicCriticality =
      (hasMonetaryValue × W1 × log(amount + 1))
    + (affectsPhysicalScarcity × W2)
    + (isReversible ? 0 : W3)
    + (hasExplicitDeadline × W4 × urgencyFromDeadline)
```

- `hasMonetaryValue`: 1 if the event carries a real monetary amount (payments, refunds), 0 otherwise
- `amount`: the actual value at stake; log-scaled so a ₹2,00,000 payment scores meaningfully higher than a ₹200 one, without letting one huge outlier dominate the whole formula
- `affectsPhysicalScarcity`: 1 if the event touches a finite, physically limited resource (e.g., last unit of stock in a dark-store-style scenario)
- `isReversible`: whether undoing this event's effect is trivial (a click) or costly/impossible (a completed payment)
- `hasExplicitDeadline` / `urgencyFromDeadline`: for events tied to an SLA (e.g., delivery windows), urgency rises as the deadline approaches — computed live, not fixed at ingestion

No event type is special-cased in code. A "payment" event scores high because its payload happens to set `hasMonetaryValue=1` and `isReversible=false` — the system doesn't know or care that it's called "payment."

### 4.3 Component 2 — Live System State Adjustment

```
finalUrgencyScore =
      intrinsicCriticality
    + (queueDepthNormalized × W5)
    + (timeAlreadyWaitingInQueue × W6)
    - (currentWorkerAvailability × W7)
    + (isProducerWithinQuota ? 0 : -W8)
    + (isHealthCheckOrCanaryEvent × W_MAX)
```

- `queueDepthNormalized` / `currentWorkerAvailability`: reflect real-time pressure — under normal 1,000/min load these terms are near-zero, so almost every event scores above the execute threshold naturally. Under the 20x spike, these terms swing hard, pulling lower-intrinsic-score events down into batch/defer/shed territory. **This is why the system doesn't need separate "normal mode" and "spike mode" code paths — the behavior change emerges from one continuous formula reacting to live state.**
- `timeAlreadyWaitingInQueue`: an event that's been waiting gets a small boost each re-evaluation cycle, preventing starvation
- `isProducerWithinQuota`: Amazon-derived fairness signal — a producer bursting past its fair-use quota gets its events' scores penalized, independent of event type
- `isHealthCheckOrCanaryEvent`: reserved near-maximum weight, mirroring Amazon's documented insight that infrastructure self-checks must be protected above almost everything else, since losing them cascades into losing capacity

### 4.4 Decision Thresholds and the Hard Floor

| Score condition | Outcome |
|---|---|
| `finalUrgencyScore > EXECUTE_THRESHOLD` | Execute immediately, dedicated fast lane |
| `> BATCH_THRESHOLD` | Micro-batch (window size itself scales with current load — busier system → larger batch window, computed live, not fixed) |
| `> DEFER_THRESHOLD` | Push to cold queue; **re-scored periodically** (every 2–5s) so a deferred event can climb back to execute if load eases, or sink toward shed if it worsens |
| `≤ DEFER_THRESHOLD` | Eligible for shed — **but only if** `isReversible == true` AND `hasMonetaryValue == false` |

**The hard floor is a mathematical guarantee, not a special case:** because `hasMonetaryValue=1` and `isReversible=false` are baked into the intrinsic formula for any payment-like event, it is structurally near-impossible for such an event's score to fall to the shed-eligible region even under maximum system pressure. Critical-event protection *emerges* from the math rather than being hardcoded as `if type == "payment": never_shed()`.

### 4.5 Fallback for Unrecognized Events

An event with no recognizable payload fields defaults to `intrinsicCriticality = 0` (fail-safe to lowest urgency) and is additionally logged to an "unclassified events" audit trail visible on the dashboard — never silently absorbed as trustworthy, never silently dropped without a record. This mirrors a default-deny security posture (deny/deprioritize by default, elevate only on evidence).

---

## 5. Layered Admission Control (Amazon-Derived)

Every event passes through cheap, dumb filters before reaching the expensive scoring engine — so junk/abusive/over-quota traffic never pays the cost of full evaluation.

### 5.1 Layer 0 — Edge Admission Control
Schema validation, malformed-request rejection, global connection ceiling. ~0.1–0.2ms. Doesn't inspect event meaning at all.

### 5.2 Layer 1 — Quota / Fairness Check
Is the producing service within its allocated fair-usage budget for this time window? Protects against one misbehaving/bursty producer starving everyone else — independent of event criticality. Feeds the `isProducerWithinQuota` term in Section 4.3.

### 5.3 Layer 2 — Backpressure Branch for Saturated Fast Lane (Gap Fix #1)

Even a high-scoring event needs an explicit fallback if the fast execution lane is *itself* fully saturated (all dedicated workers busy — a rare, extreme edge case):

```
if finalScore > EXECUTE_THRESHOLD AND fastLaneWorkersAllBusy:
    → apply backpressure at Layer 0/1 (reject or slow NEW incoming
      events at the gateway, e.g., HTTP 503 + Retry-After)
    → NEVER silently queue this event behind lower-score work
    → NEVER shed this event
```

The fast lane's worker pool is sized with deliberate headroom so this branch should essentially never trigger during the demo — but it exists as the documented, code-present safety valve that satisfies the PS's explicit requirement: *"critical events are never dropped and get applied backpressure upstream instead."* This is shown on the architecture diagram as its own explicit path, not left implicit.

### 5.4 Layer 3 — Scoring Engine
As detailed in Section 4.

### 5.5 Layer 4 — Execution Lanes
- **Fast lane:** dedicated worker pool, isolated from batching/deferral machinery entirely
- **Standard lane:** Deficit Round Robin (DRR) scheduled queues for batch/defer-eligible events — DRR chosen over simple weighted round robin because it accounts for variable per-event processing cost, not just event count, preventing starvation more precisely (same principle used by Linux traffic control / `fq_codel`)
- **Cold/deferred queue:** periodically re-scored, slow-cadence drain
- **Shed log:** append-only, visible on dashboard — every shed event recorded with ID, computed score, and reason

---

## 6. Component Breakdown

### 6.1 Load Simulator
- Async event generator, ≥3 distinct types with realistic payloads (including `amount`, `reversible`, `deadline`, `scarcity` fields feeding the scoring formula)
- Arrival modeled as a **Poisson process** for baseline load (λ = 1,000/min), transitioning to a **step function** for the spike (λ = 20,000/min) — arriving suddenly, not gradually, per the PS's explicit constraint
- Rate is live-adjustable (dashboard slider or CLI trigger) so the spike can be triggered during the live demo, not pre-recorded

### 6.2 Ingestion Gateway
Layers 0–1 from Section 5. Stamps `ingestion_time` on every event for later latency computation.

### 6.3 Scoring Engine
Layer 3 from Section 5. Stateless, pure function of event payload + live system metrics pulled from the queue/worker state store.

### 6.4 Queue & Broker Layer
Recommended: **Redis** — sorted sets for the fast lane (score-ordered), Redis Streams for durability on standard/cold lanes. Chosen because it's inspectable, fast, persistent, and a broker judges recognize as real infrastructure rather than an in-memory Python list.

### 6.5 Worker Pool
Dedicated pool for fast lane; separate pool for standard/DRR lanes. Each "execution" performs real, calibrated CPU work (e.g., hashing or small matrix operations sized to hit a target latency with jitter) rather than a blocking `sleep()` — this ensures energy/cost metrics measure real CPU cycles, not fabricated numbers.

### 6.6 Sink
Mock persistence store — explicitly declared as simulated per the PS's honesty requirement.

### 6.7 Dashboard
WebSocket-fed live view. See Section 8.

---

## 7. Reconciling Continuous Scoring With "Priority Tiers" (Gap Fix #2)

The PS explicitly requires dashboard reporting **"queue size per priority tier"** and **"latency per priority tier, not aggregate."** Since routing uses a continuous score rather than fixed tiers, a **display-bucketing layer** is added purely for visualization — it does not affect any routing decision:

| Score range | Display Band |
|---|---|
| ≥ 7.0 | Critical |
| 4.0 – 6.9 | Standard |
| < 4.0 | Best-effort |

The routing engine always uses the raw continuous score against `EXECUTE/BATCH/DEFER` thresholds; the bucketing exists only so the dashboard can present tiered breakdowns as required. State this explicitly to judges: *the engine never uses fixed tiers internally — only the display layer does.*

---

## 8. Dashboard Specification

Live, WebSocket-pushed, updating in real time:

- Queue depth, per display band (Critical / Standard / Best-effort)
- Throughput (events/sec), overall and per band
- End-to-end latency, per display band — **never a single aggregate number**, since an average can look healthy while payments are quietly timing out
- Running counts: batched / deferred / shed, per band
- Shed log: scrollable list of `{event_id, computed_score, reason, timestamp}` — proves shedding is visible, not silent
- Toggle: Adaptive Mode vs. Naive Baseline Mode (Section 9), for live side-by-side comparison
- Live-adjustable load slider (1,000/min ↔ 20,000/min) to trigger the spike during demo

---

## 9. Baseline Comparison Mode

A feature-flag toggle (`adaptive_mode: true/false`) on the **same pipeline codebase**, not a separate build:

- **Baseline (off):** single FIFO queue, single worker pool, no scoring, no batching, no shedding — every event processed identically in arrival order
- **Adaptive (on):** full system as described above

Both modes run against the identical simulated spike trace, and the dashboard shows side-by-side: per-band latency, throughput, and shed/dropped counts. Expect the baseline to show payment latency degrading badly (or the process falling over / unbounded queue growth) under the 20x spike, while adaptive mode keeps high-score events flat.

---

## 10. Stretch Goals (Attempt Only After Core Is Solid)

### 10.1 Fault Tolerance with Idempotent Retry
Kill a worker mid-processing; retry only the failed event, not the whole batch, with no duplicate side effects (e.g., a payment marked completed twice). Implement via an idempotency key (`event_id`) checked against a "processed" set before applying effects.

### 10.2 Dynamic Worker Scaling
Spin up/down worker processes based on real queue depth rather than a fixed pool size — directly demonstrable by watching worker count rise on the dashboard as the spike hits.

### 10.3 Duplicate Event Detection
If the same `event_id` arrives twice (simulating an upstream retry), detect via a short-lived dedup cache and skip reprocessing.

### 10.4 Cost/Energy Estimation
Estimate energy per event as CPU-seconds × TDP-based wattage proxy (standard estimation method used in real FinOps/GreenOps tooling — no special hardware counters needed). Compute total estimated cost for adaptive mode vs. naive-always-scale-up baseline under identical spike load, and show adaptive costing less. This directly satisfies the PS's stretch goal #5.

---

## 11. Worked Example — ₹200 Payment, Full Trace

**Payload arrives:**
```json
{
  "event_id": "evt_8f3a2b91",
  "type": "payment",
  "order_id": "ord_5521",
  "amount": 200.00,
  "reversible": false,
  "deadline": null
}
```

**Layer 0/1:** Well-formed, `checkout-service` within quota → passes in ~0.2ms.

**Layer 3 (Scoring):**
```
intrinsicCriticality = (1 × W1 × log(201)) + 0 + (1 × W3) + 0 ≈ 7.4
```
Under mid-spike conditions (queueDepthNormalized=0.9, low worker availability):
```
finalUrgencyScore = 7.4 + (0.9 × W5) + (0 × W6) − (0.1 × W7) + 0 ≈ 8.9
```
8.9 clears `EXECUTE_THRESHOLD` (e.g., 6.0) comfortably — **even under extreme system pressure**, because the intrinsic stakes (real money, irreversible) dominate the formula.

**Layer 4:** Routed to fast lane → dedicated worker picks it up in microseconds → simulated processing (~60ms ± jitter, real CPU cycles) → `completion_time` marked → `latency = 64ms`.

**Sink:** `{event_id, status: "completed", latency_ms: 64, amount: 200, display_band: "Critical"}`

**Dashboard:** Critical-band latency graph ticks up with 64ms; throughput counter increments.

**Simultaneously, a click event** (`amount: null, reversible: true`) scores near 0 intrinsically; under the same spike pressure its score falls below `BATCH_THRESHOLD`, enters a micro-batch window, gets re-scored every few seconds, and if the spike sustains, eventually crosses below the shed floor — logged explicitly: `{event_id: evt_click_441, score: 1.2, reason: "below defer threshold, reversible, no monetary value", timestamp: ...}`.

**The proof this demonstrates live:** the payment never touches a batch, never waits behind a click event, and never gets shed — not because of a hardcoded `if type == "payment"` rule, but because its own payload mathematically guarantees a high score under any load condition the demo can produce.

---

## 12. Recommended Stack

| Layer | Technology | Why |
|---|---|---|
| Middle layer | Python (FastAPI + asyncio) | Fast to build, async-native, easy to instrument |
| Broker | Redis (sorted sets + Streams) | Real, inspectable, persistent, industry-recognized |
| Dashboard transport | WebSocket | True live push, not polling |
| Dashboard UI | React + lightweight charting | Fast to iterate, judges expect a polished live view |
| Load simulator | Python async loop, Poisson + step-function arrival | Matches real queueing-theory traffic modeling |

---

## 13. Build Priority Order (for execution planning)

1. Event schema + Load Simulator (Poisson baseline + step spike, live-adjustable rate)
2. Ingestion Gateway (Layer 0/1, minimal)
3. Scoring Engine (Section 4) — this is the core differentiator, get it right before anything else
4. Queue layer: fast lane + DRR standard lane + cold/defer queue
5. Worker pool with realistic simulated execution cost
6. Dashboard: per-band latency/throughput/queue depth, shed log
7. Baseline toggle mode for comparison
8. Backpressure branch (Section 5.3) explicitly coded and demonstrable
9. Stretch goals (Section 10), only once 1–8 are solid end to end
