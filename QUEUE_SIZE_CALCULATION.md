# Queue Size Calculation Explained

## Overview

Each lane (Fast, Standard, Cold) has its queue size calculated using **Python's asyncio.Queue.qsize()** method, which returns the **current number of events waiting in the queue**.

---

## Queue Size Calculation by Lane

### 1. Fast Lane Queue Size

**Location:** `pipeline/lane_processor.py`

**Queue Declaration:**
```python
self.fast_queue: asyncio.Queue = asyncio.Queue(maxsize=100)
```

**How It's Calculated:**

#### A) During Event Routing (`route_event` method):
```python
if action == "execute":
    topic = TOPIC_FAST
    queue = self.fast_queue
    self.stats["fast"].queue_size += 1  # ❌ INCORRECT - Manual increment
    
    await queue.put(event)  # Add to queue
```

**Issue:** This manual increment is **inaccurate** because it doesn't account for events being removed by the processor.

#### B) During Processing (`_process_fast_lane` method):
```python
async def _process_fast_lane(self):
    while self._running:
        event = await self.fast_queue.get()  # Remove from queue
        
        # Process event...
        
        # Update queue size AFTER processing
        stats.queue_size = self.fast_queue.qsize()  # ✅ CORRECT
        self.fast_queue.task_done()
```

**Correct Calculation:** `self.fast_queue.qsize()` returns the **actual** number of events currently in the queue.

#### C) When Stats Are Queried (`get_stats` method):
```python
def get_stats(self) -> Dict[str, Any]:
    return {
        "fast": {
            "processed": self.stats["fast"].processed,
            "queue_size": self.fast_queue.qsize(),  # ✅ Real-time count
            "avg_latency_ms": round(self.stats["fast"].avg_latency_ms, 2),
        },
        # ...
    }
```

**This is the ACTUAL queue size** sent to the frontend - real-time count via `qsize()`.

---

### 2. Standard Lane Queue Size

**Queue Declaration:**
```python
self.standard_queue: asyncio.Queue = asyncio.Queue(maxsize=500)
```

**How It's Calculated:**

#### A) During Event Routing:
```python
elif action == "batch":
    topic = TOPIC_STANDARD
    queue = self.standard_queue
    self.stats["standard"].queue_size += 1  # ❌ Manual increment (inaccurate)
    
    await queue.put(event)
```

#### B) During Batch Processing:
```python
async def _process_batch(self, batch: List[Dict[str, Any]], lane: str, worker: BatchWorker):
    # Process batch...
    
    stats = self.stats[lane]
    stats.processed += len(batch)
    stats.batches += 1
    stats.queue_size = (
        self.standard_queue.qsize() if lane == "standard"  # ✅ Real-time count
        else self.cold_queue.qsize()
    )
```

#### C) When Stats Are Queried:
```python
"standard": {
    "processed": self.stats["standard"].processed,
    "batches": self.stats["standard"].batches,
    "queue_size": self.standard_queue.qsize(),  # ✅ Real-time count
    "avg_latency_ms": round(self.stats["standard"].avg_latency_ms, 2),
    "drr_deficit": self.drr.standard_deficit,
},
```

---

### 3. Cold Lane Queue Size

**Queue Declaration:**
```python
self.cold_queue: asyncio.Queue = asyncio.Queue(maxsize=1000)
```

**How It's Calculated:**

#### A) During Event Routing:
```python
else:  # defer
    topic = TOPIC_COLD
    queue = self.cold_queue
    self.stats["cold"].queue_size += 1  # ❌ Manual increment (inaccurate)
    
    await queue.put(event)
```

#### B) During Batch Processing:
```python
stats.queue_size = (
    self.standard_queue.qsize() if lane == "standard" 
    else self.cold_queue.qsize()  # ✅ Real-time count for cold lane
)
```

#### C) When Stats Are Queried:
```python
"cold": {
    "processed": self.stats["cold"].processed,
    "batches": self.stats["cold"].batches,
    "queue_size": self.cold_queue.qsize(),  # ✅ Real-time count
    "avg_latency_ms": round(self.stats["cold"].avg_latency_ms, 2),
    "drr_deficit": self.drr.cold_deficit,
},
```

---

## Python's `asyncio.Queue.qsize()` Method

### What It Does:
Returns the **approximate** number of items currently in the queue.

### How It Works:
```python
def qsize(self) -> int:
    """Number of items in the queue."""
    return len(self._queue)  # Returns length of internal deque
```

### Key Characteristics:
- **Real-time snapshot** of queue length
- **Thread-safe** and **coroutine-safe**
- **Accurate** at the moment it's called
- **No blocking** - instant return

---

## Data Flow Example

Let's trace 100 events going to Fast Lane:

### Step 1: Events Arrive
```python
# 100 events scored as "execute" (fast lane)
for event in events:
    await lane_processor.route_event(event, "execute")
    # self.fast_queue now has events added
```

**Queue State:** `fast_queue.qsize() = 100`

### Step 2: Fast Lane Processor Runs
```python
async def _process_fast_lane(self):
    while self._running:
        event = await self.fast_queue.get()  # Removes 1 event
        # Queue now has 99 events
        
        await self.fast_worker.process_batch([event])  # Process it
        
        stats.queue_size = self.fast_queue.qsize()  # Updates to 99
```

**Queue State:** `fast_queue.qsize() = 99` (after processing 1)

### Step 3: Frontend Requests Stats
```python
# Backend API endpoint: GET /lanes/stats
stats = lane_processor.get_stats()
# Returns: { "fast": { "queue_size": 42 } }  ← Current qsize()
```

**Queue State:** Real-time count - changes every time processor removes events

---

## Why Manual Increment is Inaccurate

### The Problem:
```python
# In route_event():
self.stats["fast"].queue_size += 1  # Increment

# But in _process_fast_lane():
# We never decrement! Only replace with qsize()
```

### The Issue:
- Manual increment ONLY tracks **additions**
- Doesn't track **removals** (processing)
- Gets out of sync quickly

### The Fix (Already Implemented):
The `get_stats()` method **always calls `qsize()`** directly, which overrides the inaccurate manual stat:

```python
"queue_size": self.fast_queue.qsize()  # Ignores self.stats["fast"].queue_size
```

So the **frontend always sees the correct, real-time queue size**! ✅

---

## Queue Size Capacity Limits

Each queue has a maximum capacity:

| Lane     | Max Capacity | Purpose                                    |
|----------|-------------|--------------------------------------------|
| Fast     | 100         | Small - events process immediately         |
| Standard | 500         | Medium - batch processing with DRR         |
| Cold     | 1000        | Large - can hold more deferred events      |

### What Happens When Full?

```python
await queue.put(event)  # This line will RAISE asyncio.QueueFull

# Handled in route_event():
except asyncio.QueueFull:
    logger.warning(f"Queue full for {action} lane - backpressure activated")
    return False
```

When a queue is full:
1. `route_event` returns `False`
2. Event is marked for **backpressure**
3. Can be retried later or handled by overflow logic

---

## Summary

### Fast Lane Queue Size:
- **Calculation:** `self.fast_queue.qsize()`
- **Updated:** After each event is processed
- **Reported:** Real-time via `get_stats()` → WebSocket → Frontend

### Standard Lane Queue Size:
- **Calculation:** `self.standard_queue.qsize()`
- **Updated:** After each batch is processed
- **Reported:** Real-time via `get_stats()` → WebSocket → Frontend

### Cold Lane Queue Size:
- **Calculation:** `self.cold_queue.qsize()`
- **Updated:** After each batch is processed
- **Reported:** Real-time via `get_stats()` → WebSocket → Frontend

### Key Insight:
The **manual increment in `route_event()`** is NOT used for reporting! The `get_stats()` method always calls `qsize()` directly, ensuring **accurate real-time queue sizes** are sent to the frontend. 🎯
