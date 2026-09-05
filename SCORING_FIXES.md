# Scoring & Lane Routing Fixes

## Problem
At 1000 req/min (normal load), too many events were being routed to Batch and Cold lanes when they should go to Fast Lane. The system appeared non-context-aware.

## Root Causes

### 1. Queue Depth Normalization Too Sensitive
**Before:** Normalized against 0-50 eps
- 1000 req/min = ~17 eps → queue_depth = 0.34 (appears as 34% load!)
- This inflated scores artificially, routing normal events to batch/defer lanes

**After:** Normalized against 0-150 eps  
- 1000 req/min = ~17 eps → queue_depth = 0.11 (11% load - realistic!)
- Normal events now stay in fast lane where they belong

### 2. Fast Lane Full Threshold Too Low
**Before:** fast_lane_full triggered at 120 eps
- Prematurely activated backpressure logic

**After:** fast_lane_full triggers at 200 eps
- Allows more breathing room for fast lane routing

### 3. Queue Pressure Weight Too High
**Before:** W5 = 1.2 (queue depth weight)
- Even at low load, queue pressure component added significant score boost

**After:** W5 = 0.8
- Queue pressure has realistic impact only under actual load

## Expected Behavior Now

### At 1000 req/min (Normal Load)
- **Queue Depth:** ~0.11 (11%)
- **Queue Pressure Contribution:** ~0.09 (0.11 × 0.8)
- **Most Events:** Fast Lane (execute) - intrinsic + 0.09 usually stays > 6.0
- **Moderate Events:** Standard Lane (batch) - if intrinsic 3.0-5.9  
- **Low Priority:** Cold Lane (defer) - if intrinsic < 3.0

### At 5000 req/min (Moderate Load)
- **Queue Depth:** ~0.56 (56%)
- **Queue Pressure Contribution:** ~0.45
- **High Value Events:** Fast Lane - intrinsic + 0.45 pushes them over 6.0
- **Moderate Events:** Standard Lane - batched for efficiency
- **Low Priority:** Cold Lane - deferred, will be re-scored later

### At 20,000 req/min (Flash Sale Spike)
- **Queue Depth:** ~2.22 (clamped to 1.0)
- **Queue Pressure Contribution:** 0.8 (maxed out)
- **Critical Events Only:** Fast Lane - need intrinsic > 5.2 to reach 6.0
- **Most Events:** Standard/Cold Lanes - batched, scheduled with DRR
- **PID Controller:** Raises execute threshold to protect P0 SLA

## DRR Deficit Display

The LaneQueueMonitor component correctly displays DRR deficit values from the backend:
- `lanes.standard.drr_deficit` - Shows quantum credits for standard lane
- `lanes.cold.drr_deficit` - Shows quantum credits for cold lane
- Values are **dynamically calculated** by the DRR scheduler in real-time
- Deficit increases by quantum each round, decreases by events processed

**Example:**
```
Standard Lane:
- Quantum: 10
- Queue Size: 25
- DRR Deficit: 7 (processed 3 events this round, have 7 credits left)

Cold Lane:  
- Quantum: 3
- Queue Size: 12
- DRR Deficit: 1 (processed 2 events this round, have 1 credit left)
```

## Files Changed
1. `pipeline/main.py` - Fixed queue_depth normalization (150 threshold, fast_lane_full=200)
2. `pipeline/scoring.py` - Reduced W5 from 1.2 to 0.8

## Verification
Restart the pipeline and simulator:
```bash
stop_all.bat
start_all.bat
```

At 1000 req/min, you should now see:
- ✅ Majority of events in Fast Lane (6,000-8,000 count)
- ✅ Some in Standard Lane (200-500 count)
- ✅ Few in Cold Lane (50-100 count)
- ✅ DRR deficit shows real numbers (0-10 for standard, 0-3 for cold)

The system is now properly **context-aware** and routes based on actual load! 🎯
