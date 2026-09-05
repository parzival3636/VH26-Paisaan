# How to Verify Batching is Working

## Quick Test

### 1. Start the pipeline
```bash
# Windows
start_all.bat

# Linux/Mac
./start_all.sh
```

### 2. Set simulator to 20K requests/minute
Open the dashboard: http://localhost:3000

Navigate to **Control Center** and set rate to **20000 req/min**

### 3. Check Lane Stats
```bash
curl http://localhost:8000/lanes/stats
```

**Expected Output (after fix):**
```json
{
  "lanes": {
    "fast": {
      "processed": 450,
      "queue_size": 5,
      "avg_latency_ms": 12.3
    },
    "standard": {
      "processed": 200,
      "batches": 20,  ← SHOULD BE > 0 and growing!
      "queue_size": 8,
      "avg_latency_ms": 18.5,
      "drr_deficit": 3
    },
    "cold": {
      "processed": 350,
      "batches": 70,
      "queue_size": 15,
      "avg_latency_ms": 45.2,
      "drr_deficit": 1
    }
  },
  "scheduler": "Deficit Round Robin (DRR)",
  "description": "Fast lane: immediate | Standard/Cold: DRR with quantum 10:3"
}
```

**Key Indicator:** `standard.batches` should be **greater than 0** and **increasing**.

### 4. Check Batch Files
```bash
# Windows PowerShell
Get-ChildItem batch_files | Where-Object { $_.Name -like "standard_*" }

# Linux/Mac/Git Bash
ls -la batch_files/ | grep standard
```

**Expected Output:**
```
standard_1788579402081_10.json
standard_1788579402397_9.json
standard_1788579402589_10.json
standard_1788579403769_10.json
```

Files should be named `standard_TIMESTAMP_SIZE.json` where SIZE is the batch size (typically 10).

### 5. Inspect a Batch File
```bash
curl http://localhost:8000/batches | jq '.batches[] | select(.lane == "standard") | .batch_id' | head -1
```

Copy the batch_id and fetch it:
```bash
curl http://localhost:8000/batches/standard_1788579402081_10 | jq
```

**Expected Contents:**
```json
{
  "batch_id": "standard_1788579402081_10",
  "lane": "standard",
  "timestamp": 1788579402.081,
  "size": 10,
  "status": "completed",
  "latency_ms": 18.4,
  "events": [
    {
      "event_id": "abc-123...",
      "event_type": "inventory",
      "payload": {
        "affects_physical_scarcity": true,
        "has_explicit_deadline": true,
        ...
      }
    },
    ... 9 more events
  ],
  "result": {
    "processed": 10,
    "success": true
  }
}
```

## Detailed Verification Steps

### Step 1: Monitor Live Metrics
```bash
watch -n 1 'curl -s http://localhost:8000/lanes/stats | jq'
```

Monitor for 30 seconds. You should see:
- `standard.batches` **incrementing**
- `standard.processed` **growing in jumps of ~10**

### Step 2: Check Event Distribution
```bash
curl http://localhost:8000/stats | jq '.actions'
```

**Expected Output:**
```json
{
  "execute": 450,   ← Fast Lane (45%)
  "batch": 200,     ← Standard Lane (20%) ✓ Should be ~15-25%
  "defer": 350,     ← Cold Lane (35%)
  "shed": 0,
  "backpressure": 0
}
```

### Step 3: Verify Batch Distribution
```bash
curl http://localhost:8000/batches?limit=100 | jq '.batches | group_by(.lane) | map({lane: .[0].lane, count: length})'
```

**Expected Output:**
```json
[
  {"lane": "cold", "count": 70},
  {"lane": "standard", "count": 20},  ← Should have entries!
  {"lane": "fast", "count": 0}        ← Fast lane doesn't batch (size=1)
]
```

### Step 4: Test Instant Spike
```bash
curl -X POST http://localhost:8000/simulator/spike -H "Content-Type: application/json" -d '{"count": 20000}'
```

**Expected Response:**
```json
{
  "status": "spike_complete",
  "count": 20000,
  "elapsed_seconds": 2.134,
  "events_per_second": 9375,
  "lane_distribution": {
    "execute": 9000,     ← 45%
    "batch": 4000,       ← 20% ✓ Going to Standard Lane!
    "defer": 7000,       ← 35%
    "backpressure": 0
  },
  "queue_sizes": {
    "fast": 12,
    "standard": 45,      ← Should show queued events
    "cold": 120
  }
}
```

## What "Working" Looks Like

✅ **Standard Lane is active**
- `batches > 0` in lane stats
- Batch files with `standard_*.json` naming exist
- `processed` count grows in steps of ~10

✅ **Proper distribution**
- ~45% execute (Fast Lane)
- ~20% batch (Standard Lane)  ← KEY METRIC
- ~35% defer (Cold Lane)

✅ **Batching behavior**
- Standard queue accumulates events
- Events are processed in micro-batches of 10
- Latency is slightly higher than Fast Lane but much lower than Cold Lane

## What "Broken" Looks Like

❌ **No batching**
- `standard.batches = 0` (stuck at zero)
- No `standard_*.json` files in batch_files/
- `batch` action count is 0 or < 5%

❌ **Wrong distribution**
- > 60% going to Fast Lane (execute)
- < 5% going to Standard Lane (batch)
- Standard Lane being skipped

❌ **Threshold too low**
- Everything scores above threshold
- Only Fast and Cold lanes are used
- No micro-batching optimization

## Before vs After Fix

### BEFORE (threshold = 4.0)
```bash
$ curl -s http://localhost:8000/stats | jq '.actions'
{
  "execute": 580,   ← 58% (too high!)
  "batch": 20,      ← 2% (way too low!)
  "defer": 400
}

$ curl -s http://localhost:8000/lanes/stats | jq '.lanes.standard.batches'
2  ← Almost nothing!
```

### AFTER (threshold = 7.0)
```bash
$ curl -s http://localhost:8000/stats | jq '.actions'
{
  "execute": 450,   ← 45% (correct)
  "batch": 200,     ← 20% (much better!)
  "defer": 350
}

$ curl -s http://localhost:8000/lanes/stats | jq '.lanes.standard.batches'
20  ← Growing steadily!
```

## Troubleshooting

### If Standard Lane is still empty:

1. **Check the threshold being used:**
```bash
curl http://localhost:8000/stats | jq '.pid_status.current_threshold'
```
Should be **7.0** (not 4.0 or 6.0)

2. **Verify load is high enough:**
```bash
curl http://localhost:8000/metrics/live | jq '.requests_per_minute'
```
Should be **>= 18000** to trigger the 7.0 threshold

3. **Check if baseline mode is enabled:**
```bash
curl http://localhost:8000/stats | jq '.baseline_mode'
```
Should be **false** (baseline mode disables intelligent scoring)

4. **Restart the pipeline:**
```bash
# Stop
./stop_all.sh

# Start
./start_all.sh
```

## Success Criteria

✅ Standard Lane shows `batches > 0` and growing
✅ ~20% of events route to "batch" action
✅ Batch files with `standard_*` prefix exist
✅ Queue sizes show Standard Lane is active
✅ DRR scheduler is processing Standard Lane batches

This confirms that micro-batching is **actually happening** at 20K load! 🎉
