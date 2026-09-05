# Batching Fix for 20K Request Load

## Problem Identified

At 20,000 requests/minute (20K load), **batching was not happening** because most events were being routed to either the Fast Lane (execute) or Cold Lane (defer), skipping the Standard Lane (batch) entirely.

## Root Cause

The execute threshold was set too low at **4.0**, which created a very narrow scoring band for the Standard Lane:

```
OLD THRESHOLDS (at 18-30K req/min):
- score >= 4.0  → Fast Lane (execute)
- 3.0 <= score < 4.0  → Standard Lane (batch)  ⚠️ ONLY 1.0 POINT RANGE!
- score < 3.0  → Cold Lane (defer)
```

### Typical Event Scores:
- **Orders**: amount 199-49,999 → score 7-14 (Fast Lane)
- **Payments**: similar + deadline → score 8-15 (Fast Lane)
- **Inventory** (45%): scarcity + deadline → score 4.5-5.5 (Fast Lane instead of Batch!)
- **Click** (25%): amount 49-499 → score 3.6-4.8 (Fast Lane instead of Batch!)
- **Logs**: mostly → score 0-2.2 (Cold Lane)

Result: **Events either scored too high (>4.0) or too low (<3.0), completely bypassing the Standard Lane.**

## Solution

Raised the execute threshold from **4.0 to 7.0** at moderate-high loads (18-30K req/min) to create a wider batching band:

```
NEW THRESHOLDS (at 18-30K req/min):
- score >= 7.0  → Fast Lane (execute) - only very high-value transactions
- 3.0 <= score < 7.0  → Standard Lane (batch)  ✅ 4.0 POINT RANGE!
- score < 3.0  → Cold Lane (defer)
```

### Expected Lane Distribution After Fix:
- **Orders** (score 7-14): Fast Lane ✓
- **Payments** (score 8-15): Fast Lane ✓
- **Inventory 45%** (score 4.5-5.5): **Standard Lane (BATCHING!)** ✓
- **Click add_to_cart** (score 3.6-4.8): **Standard Lane (BATCHING!)** ✓
- **Click browse** (score 1.8-2.8): Cold Lane ✓
- **Logs** (score 0-2.2): Cold Lane ✓

## Changes Made

### File: `pipeline/main.py`

**Location 1: High-load batch generation (line ~200)**
```python
if lam < 500:  # Moderate threshold for 18-30K req/min
    execute_threshold = 7.0  # Changed from 4.0
    # score >= 7.0: Fast Lane (only very high value payments/orders)
    # 3.0 <= score < 7.0: Standard Lane (BATCHING - most events land here)
    # score < 3.0: Cold Lane
```

**Location 2: Normal load event generation (line ~310)**
```python
elif lam < 500:  # Moderate-high load (< 30K req/min)
    execute_threshold = 7.0  # Changed from PID controller to fixed 7.0
```

## Expected Results

With 20,000 requests/minute:
1. **~40-50% of events** should now route to Standard Lane for **micro-batching**
2. **Batch files** in `batch_files/` directory should show `standard_*.json` files
3. **Lane stats** should show:
   - Standard Lane: `batches > 0` and growing
   - Standard Lane: `processed` events accumulating in batches of 10
4. **Queue sizes**: Standard queue should show non-zero depth

## Testing

Run the simulator at 20K load and verify:
```bash
# Check lane stats
curl http://localhost:8000/lanes/stats

# List batch files
curl http://localhost:8000/batches

# Monitor Standard Lane batching
# Should see files like: standard_1788579402081_10.json
ls -la batch_files/ | grep standard
```

## Why 7.0?

The threshold of 7.0 was chosen because:
1. High-value orders/payments (amounts > ₹1000) score ~7-14 → Still get Fast Lane
2. Medium-value inventory/clicks score 3.6-5.5 → Now get Standard Lane batching
3. Low-value logs/browse score 0-3.0 → Cold Lane
4. Creates a balanced distribution across all three lanes

## Impact

This fix ensures that at high loads (18-30K req/min):
- **Batching activates** as intended by the DRR (Deficit Round Robin) scheduler
- **Throughput improves** by processing events in micro-batches of 10
- **Resource utilization** is more efficient (fewer context switches)
- **The Standard Lane is no longer empty** at moderate-high loads
