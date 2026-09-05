# Backpressure & Shedding Implementation Analysis

## TL;DR: **No Real Queues - It's Simulated/Conceptual** 🎭

The project **does not actually implement separate queues/buffers** for backpressure or deferred events. Instead:

- Events are **scored and labeled** with actions (`execute`, `batch`, `defer`, `backpressure`, `shed`)
- These labels are **tracked in statistics** and shown in the UI
- There's **no actual queue management** - events flow directly through and are stored in durability layers (Kafka/Redis/WAL)

---

## What Actually Happens

### 1. Scoring & Classification (Real)
**File**: `pipeline/scoring.py`

```python
def determine_action(score, payload, state, thresholds):
    if score >= 6.0:  # EXECUTE threshold
        if state.fast_lane_full:
            # High-value events still go through
            if has_monetary or is_irreversible:
                return Action.EXECUTE
            # Others get labeled as backpressure
            return Action.BACKPRESSURE  # ⚠️ Just a label!
        return Action.EXECUTE
    
    elif score >= 3.0:  # BATCH threshold
        return Action.BATCH
    
    else:  # Low priority
        return Action.DEFER  # ⚠️ Just a label!
```

**Key Point**: These are **classification labels**, not queue assignments.

---

### 2. No Queue Management (Missing)
**File**: `pipeline/main.py`

When an event comes in:
```python
# Score the event
scoring_result = score_event(normalized_event, system_state, thresholds)

# Increment statistics counter
action_key = scoring_result["action"]
_stats["actions"][action_key] += 1  # ⚠️ Just counting!

# Store in durability layer (Kafka/Redis/WAL)
durability_info = await durably_accept(normalized_event)

# That's it - no queue push!
```

**What's Missing**:
```python
# This DOES NOT exist:
if action_key == "defer":
    cold_lane_queue.push(event)
elif action_key == "backpressure":
    backpressure_queue.push(event)
    # OR reject/drop event
```

---

### 3. "Queues" Are Just Stats Tracking
**File**: `pipeline/main.py`

```python
_stats: dict[str, Any] = {
    "actions": {
        "execute": 0,      # Counter
        "batch": 0,        # Counter  
        "defer": 0,        # Counter ⚠️ No actual queue
        "shed": 0,         # Counter (never incremented)
        "backpressure": 0  # Counter ⚠️ No actual queue
    }
}
```

These are **just counters for UI visualization**, not actual event queues.

---

## When Backpressure/Shed Actions Are Triggered

### Backpressure (2 Scenarios)

**Scenario 1: Fast Lane Full + Lower Priority**
```python
# pipeline/scoring.py lines 159-161
if score >= thresholds.EXECUTE:
    if state.fast_lane_full:  # EPS > 120
        if has_monetary or is_irreversible:
            return Action.EXECUTE  # Force through anyway
        return Action.BACKPRESSURE  # Label as backpressure
```

**Scenario 2: Inventory Race Condition**
```python
# pipeline/scoring.py lines 235-238
if affects_scarcity and product_id and action == Action.EXECUTE:
    success, remaining_stock, reason = inventory_lock.try_reserve_stock(product_id)
    if not success:
        action = Action.BACKPRESSURE  # Can't reserve stock
        final = -1.0  # Deprioritize
```

**What Actually Happens**:
- Event is **still accepted** (returns 202)
- Event is **still stored** in Kafka/Redis/WAL
- It's just **labeled** as "backpressure" in stats
- **No retry queue, no delay, no rejection**

---

### Shed (Never Used)

```python
# pipeline/scoring.py line 55
SHED = "shed"  # Retained for legacy visualization tags
```

**Comment says it all**: This is a **legacy label** that's never actually assigned. The counter exists but stays at 0.

```python
# pipeline/scoring.py lines 167-170
# Rule 3: Low / Negative Urgency -> Cold Lane / Defer (NO SHEDDING POLICY)
# Events are never dropped; under sustained overload, low-priority events 
# sit in cold queue.
return Action.DEFER
```

**Explicit Policy**: **"Events are never dropped"** - So there's no real shedding.

---

## What IS Actually Implemented

### ✅ Real Features:

1. **Scoring System** - Events get scores based on:
   - Monetary value (log scale)
   - Scarcity (inventory)
   - Irreversibility
   - Deadline urgency
   - Queue depth
   - Producer quotas

2. **Three Durability Layers** (Real Queues!)
   ```
   Kafka (primary) → Redis (fallback) → Local WAL (last resort)
   ```
   These ARE actual persistent queues/buffers.

3. **PID Controller** - Adjusts thresholds based on P0 latency
   ```python
   # pipeline/controller.py
   pid_controller.update(p0_latency)
   # Dynamically adjusts EXECUTE/BATCH/DEFER thresholds
   ```

4. **Inventory Lock** - Prevents overselling
   ```python
   # pipeline/inventory_lock.py
   success = inventory_lock.try_reserve_stock(product_id)
   # Actual Redis-backed atomic lock
   ```

5. **Idempotency Register** - Prevents duplicate processing
   ```python
   # pipeline/idempotency.py
   if idempotency_register.is_already_completed(eid):
       skip_event()
   ```

6. **Worker Scaler** - Adjusts worker count based on queue depth
   ```python
   # pipeline/worker_scaler.py
   scaler_status = worker_scaler.evaluate_scaling(queue_depth)
   # But workers don't actually consume from queues!
   ```

---

## What's Missing (Not Implemented)

### ❌ Missing Features:

1. **No Separate Lane Queues**
   ```python
   # These don't exist:
   fast_lane_queue = Queue()
   standard_lane_queue = Queue()  
   cold_lane_queue = Queue()
   backpressure_queue = Queue()
   ```

2. **No Queue Consumers**
   ```python
   # This pattern doesn't exist:
   async def fast_lane_worker():
       while True:
           event = await fast_lane_queue.get()
           process(event)
   ```

3. **No Actual Backpressure Mechanism**
   - No 503 Service Unavailable responses
   - No rate limiting on ingestion
   - No client-side retry hints
   - Events labeled "backpressure" are still accepted

4. **No Actual Shedding**
   - Events are never rejected
   - No 429 Too Many Requests
   - The "shed" counter never increments

5. **No Priority Processing**
   - Workers don't exist or don't prioritize execute > batch > defer
   - All events stored equally in Kafka/Redis/WAL

---

## Architecture: Actual vs. Conceptual

### What the UI Shows (Conceptual):
```
┌─────────────┐
│  Ingestion  │
└──────┬──────┘
       │ score event
       ↓
┌─────────────────────────────┐
│  Routing Decision           │
│  - Execute → Fast Lane      │ ⚠️ Conceptual lanes
│  - Batch → Standard Lane    │ ⚠️ Not real queues  
│  - Defer → Cold Lane        │ ⚠️ Just labels
│  - Backpressure → ???       │ ⚠️ No special handling
└─────────────────────────────┘
```

### What Actually Happens (Real):
```
┌─────────────┐
│  Ingestion  │
└──────┬──────┘
       │ score event, get label
       ↓
┌─────────────────────────────┐
│  Increment Counter          │
│  _stats["actions"][label]++ │
└──────┬──────────────────────┘
       │ store regardless of label
       ↓
┌─────────────────────────────┐
│  Durability Layer (REAL)    │
│  Kafka → Redis → WAL        │
│  (All events stored here)   │
└─────────────────────────────┘
```

---

## How to Make It Real

If you wanted **actual queue-based backpressure**, here's what you'd add:

### Option 1: In-Memory Queues (Simple)
```python
import asyncio

# Create actual queues
fast_lane_queue = asyncio.Queue(maxsize=100)
standard_lane_queue = asyncio.Queue(maxsize=500)
cold_lane_queue = asyncio.Queue(maxsize=1000)

# In /ingest endpoint:
if action == "execute":
    try:
        fast_lane_queue.put_nowait(event)
    except asyncio.QueueFull:
        # Real backpressure!
        return {"status": "backpressure", "retry_after": 1.0}, 503
elif action == "batch":
    await standard_lane_queue.put(event)
elif action == "defer":
    await cold_lane_queue.put(event)

# Create consumer workers:
async def fast_lane_worker():
    while True:
        event = await fast_lane_queue.get()
        await process_event(event)
        fast_lane_queue.task_done()
```

### Option 2: Redis-Based Queues (Scalable)
```python
# Use Redis lists as queues
await redis_client.lpush("queue:fast", json.dumps(event))
await redis_client.lpush("queue:standard", json.dumps(event))
await redis_client.lpush("queue:cold", json.dumps(event))

# Separate worker processes consume:
while True:
    event_json = await redis_client.brpop("queue:fast", timeout=1)
    if event_json:
        process(json.loads(event_json))
```

### Option 3: True Backpressure (HTTP 503)
```python
# In /ingest:
if queue_depth > 0.9:  # 90% full
    response.status_code = 503
    return {
        "status": "backpressure_shed",
        "message": "System overloaded",
        "retry_after": calculate_backoff(queue_depth)
    }
```

---

## Summary Table

| Feature | Implemented? | Type |
|---------|-------------|------|
| Event Scoring | ✅ Yes | Real logic |
| Action Labels (execute/batch/defer) | ✅ Yes | Labels only |
| Statistics Tracking | ✅ Yes | Counters |
| Durability Layers (Kafka/Redis/WAL) | ✅ Yes | Real queues |
| **Separate Lane Queues** | ❌ No | Missing |
| **Backpressure Queue** | ❌ No | Missing |
| **Queue Consumers/Workers** | ❌ No | Missing |
| **Actual Event Dropping/Shedding** | ❌ No | Never happens |
| **503 Backpressure Responses** | ❌ No | Always 202 |
| PID Threshold Tuning | ✅ Yes | Real logic |
| Inventory Lock | ✅ Yes | Redis-backed |
| Idempotency | ✅ Yes | Redis-backed |

---

## For the Demo/Judge

**What to say**:
- ✅ "We have an intelligent scoring system that classifies events into lanes"
- ✅ "High-value events get execute priority, low-value get deferred"
- ✅ "We track backpressure conditions when fast lane is saturated"
- ✅ "We have a three-tier durability fallback (Kafka → Redis → WAL)"

**What NOT to say**:
- ❌ "We maintain separate queues for each lane" (not true)
- ❌ "Backpressured events are retried from a buffer" (not true)
- ❌ "We shed/drop low-priority events under load" (not true)

**Better framing**:
> "We classify events by urgency and track their routing decisions. In a production system, these classifications would map to separate processing queues, but for this demo, we're focused on the **intelligent scoring** and **durability guarantees** rather than the queueing infrastructure."

---

## Bottom Line

**The backpressure and shedding are conceptual labels used for tracking and visualization - not actual queue management features.** The real innovations here are:
1. Sophisticated multi-factor scoring algorithm
2. Dynamic PID threshold adjustment  
3. Three-layer durability fallback chain
4. Inventory-aware coordination

The "lanes" are more about **classification taxonomy** than **infrastructure separation**.
