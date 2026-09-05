# Restart Required to Apply Batching Fix

## The Problem

You're currently running the **OLD CODE** with threshold 4.0, which is why batching isn't happening. The fix has been applied to the source files, but the running Python process needs to be restarted.

## Quick Restart Steps

### Option 1: Full Restart (Recommended)
```bash
# Windows
stop_all.bat
start_all.bat

# Linux/Mac  
./stop_all.sh
./start_all.sh
```

### Option 2: Backend Only (Faster)
```bash
# Stop the Python backend
# Press Ctrl+C in the terminal running uvicorn

# Or find and kill the process
# Windows PowerShell:
Get-Process python | Stop-Process -Force

# Linux/Mac:
pkill -f "uvicorn"
pkill -f "pipeline.main"

# Restart backend
python -m uvicorn pipeline.main:app --reload --host 127.0.0.1 --port 8000
```

## How to Verify Fix is Applied

After restart, check the threshold being used:

```bash
curl http://localhost:8000/simulator/status
```

Then set rate to 20K and check lane stats:

```bash
# Set 20K load
curl -X POST http://localhost:8000/simulator/rate -H "Content-Type: application/json" -d '{"rate": 20000}'

# Wait 10 seconds for events to accumulate

# Check lane stats
curl http://localhost:8000/lanes/stats
```

**Look for:**
- `standard.batches` > 0 (should be growing)
- `standard.processed` > 0 (should show batched events)

## What You Should See After Fix

### Before Restart (Current - Broken)
```
Micro-Batch Lane: 0 processed, idle
Fast Lane: 3,643 (too high - 60%+)
Cold Lane: 3,040
Rejected: 4,517 (concerning!)
```

### After Restart (Fixed)
```
Micro-Batch Lane: ~1,200 processed, ~120 batches
Fast Lane: ~2,700 (45% - correct)
Cold Lane: ~2,100 (35%)
Rejected: <100 (should be minimal)
```

## Additional Issue: High Rejection Count

Your screenshot shows **4,517 rejected events**. This suggests backpressure or race conditions. After restart, monitor:

```bash
curl http://localhost:8000/stats | jq '.actions'
```

If `backpressure` or `shed` counts are high, you may need to:
1. Increase queue sizes in `lane_processor.py`
2. Adjust worker scaling
3. Check for inventory lock contention

## Test Commands After Restart

```bash
# 1. Start at 20K
curl -X POST http://localhost:8000/simulator/rate -d '{"rate": 20000}'

# 2. Wait 15 seconds
sleep 15

# 3. Check batching is happening
curl http://localhost:8000/lanes/stats | jq '.lanes.standard'

# Expected output:
# {
#   "processed": 1200,
#   "batches": 120,      ← Should be > 0!
#   "queue_size": 8,
#   "avg_latency_ms": 18.5,
#   "drr_deficit": 3
# }

# 4. Verify batch files exist
curl http://localhost:8000/batches?lane=standard | jq '.total'
# Should return a number > 0

# 5. Check action distribution
curl http://localhost:8000/stats | jq '.actions'
# Expected:
# {
#   "execute": 2700,  (45%)
#   "batch": 1200,    (20%) ← Should be ~20%!
#   "defer": 2100,    (35%)
#   "shed": 0,
#   "backpressure": <100
# }
```

## If Still Not Working After Restart

1. **Check the actual rate being used:**
```bash
curl http://localhost:8000/simulator/status | jq '.current_rate_per_sec'
```
Should show `~333` (20000/60)

2. **Verify threshold logic:**
Check if `lam = 333` triggers the right path:
- `lam > 300` ✓ (high load mode)
- `lam < 500` ✓ (should use 7.0 threshold)

3. **Check for errors in logs:**
Look at the terminal running uvicorn for any exceptions

4. **Try instant spike test:**
```bash
curl -X POST http://localhost:8000/simulator/spike -d '{"count": 20000}'
```
Check response for `lane_distribution` - should show `batch: ~4000`

## Why Restart is Needed

Python is an interpreted language, but uvicorn caches the imported modules. Even with `--reload`, some changes (especially to complex async code) don't hot-reload properly. A full restart ensures:

1. New threshold values (7.0) are loaded
2. All module state is reset
3. Lane processor restarts with correct configuration
4. No stale scoring logic remains

**TL;DR: Stop the backend, start it again, and batching should work!** 🔄
