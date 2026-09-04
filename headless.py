"""
headless.py — Start the pipeline backend + simulator without terminal UI.

Usage:
    python headless.py              # Normal traffic (1,000 req/min)
    python headless.py --spike      # Flash sale (20,000 req/min)

The React frontend at http://localhost:5173 connects via WebSocket for live data.
"""
import os
import sys
import logging

# Mute noisy internal logging for a clean console
logging.getLogger("pipeline.controller").setLevel(logging.WARNING)
logging.getLogger("pipeline.wal").setLevel(logging.WARNING)
logging.getLogger("pipeline.kafka_client").setLevel(logging.ERROR)

# Tell pipeline/main.py to auto-start the in-process simulator on boot
os.environ["AUTO_START_SIMULATOR"] = "1"

import uvicorn

if __name__ == "__main__":
    if "--spike" in sys.argv:
        os.environ["SIM_NORMAL_RATE_PER_MIN"] = "20000"

    print("\n" + "=" * 55)
    print("  INTELLIGENT ADAPTIVE PIPELINE — HEADLESS MODE")
    print("=" * 55)
    print("  Backend API:   http://127.0.0.1:8000")
    print("  WebSocket:     ws://127.0.0.1:8000/dashboard/feed")
    print("  Frontend:      cd frontend/frontend && npm run dev")
    print("=" * 55 + "\n")

    uvicorn.run(
        "pipeline.main:app",
        host="127.0.0.1",
        port=8000,
        log_level="warning",
    )
