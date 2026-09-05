# 🚀 Pipeline Demo - Quick Start Guide

## Fixed Critical Bug
✅ **FIXED**: Undefined `chartData` variable in PipelineContext that was causing the frontend to crash after 1 second.

## Quick Start (Automated)

### Windows:
```batch
start_all.bat
```

### Linux/Mac:
```bash
./start_all.sh
```

Then open: **http://localhost:5174**

---

## Architecture Overview
```
Frontend (React) ← WebSocket → Backend (FastAPI) ← Kafka/Redis → Pipeline Workers
```

## Manual Start (3 Terminal Setup)

### Terminal 1: Infrastructure
```bash
# Start Kafka, Zookeeper, Redis
docker-compose up
```

### Terminal 2: Backend Pipeline
```bash
# Start the pipeline backend (FastAPI + WebSocket)
python pipeline/main.py
```

### Terminal 3: Frontend
```bash
cd frontend/frontend
npm run dev
```

Then open: **http://localhost:5174**

---

## All Implemented Features ✨

### 1. Live Event Trace Feed
- Real-time scrolling event list on Dashboard
- Each row shows: event_id (monospace), type pill, score (color-coded by lane), destination lane badge
- Expandable Score X-Ray with:
  - Intrinsic/Final/Latency metrics
  - Component breakdown (monetary, irreversibility, scarcity, deadline, etc.)
  - Full payload display
- Auto-scrolls when near bottom

### 2. Durability Chain Visualizer (Control Center)
- SVG visualization: Gateway → Kafka → Redis → WAL
- Live pulse on active nodes
- Color-coded health: green (healthy) / red (down) / amber (degraded)
- Dashed fallback path animates when Kafka fails
- Shows "FALLBACK ENGAGED" callout during rerouting

### 3. Chaos Control Panel
- **Kill Kafka** button
- **Kill Redis** button
- **Kill Both** button
- **Restore All** button
- **Inject ₹5,00,000 payment** button
- **Flood Fast Lane** button
- Calls pipeline chaos endpoints (falls back to demo feedback if backend unavailable)

### 4. Per-Lane Latency Breakdown Chart
- Dashboard charts row shows throughput + lane latency
- Separate lines for Fast/Standard/Cold lanes
- Reads from `laneLatency` in context
- Real-time updates

### 5. Baseline vs Adaptive Split View
- Only visible when FIFO toggle is ON
- Side-by-side comparison cards showing:
  - Per-lane latency for baseline vs adaptive
  - Lane counts for both modes
  - Proves adaptive superiority during spikes

### 6. Annotated PID Threshold Graph
- Tracks threshold shifts in real-time
- Renders recent shift callouts with reason text
- Annotations appear when thresholds move more than:
  - ±0.02 for execute/batch
  - ±0.01 for defer
- Shows PID auto-tuning reasoning

### 7. Enhanced Empty States
All empty states now have friendly messages:
- "Waiting for traffic — trigger a load preset to begin"
- Applied to: idle lane cards, empty trace feed, empty breakdown, empty recent-events table

### 8. Typography & Design System
- **Numbers**: JetBrains Mono (monospace) with `tabular-nums`
- **Labels/Prose**: Plus Jakarta Sans
- **Color Palette** (light mode only):
  - Violet/Indigo #4F46E5 — adaptive/execute lane/active
  - Amber #F5A623 — defer/degraded
  - Red #EF4444 — down/rejected/failure
  - Green #22C55E — healthy/executed
- Canvas: #F5F6F8
- Cards: #FFFFFF with 1px #E3E6EB borders

---

## Traffic Load Presets (Control Center)
1. **Normal Traffic** — 1,000 req/min
2. **Moderate Load** — 5,000 req/min
3. **Flash Sale Spike** — 20,000 req/min
4. **Black Friday** — 100,000 req/min

---

## Testing the Demo Flow

### Suggested Judge Demo Script:
1. **Start in Adaptive mode** → Show live event feed populating
2. **Apply "Flash Sale Spike"** → Watch latency breakdown show Fast lane stays flat while Standard/Cold rise
3. **Open Score X-Ray** on a payment event → Show component breakdown explaining WHY it went to Fast lane
4. **Kill Kafka** → Watch durability chain animate fallback to Redis
5. **Toggle to FIFO Baseline** → Baseline split view appears comparing performance
6. **Restore All** → Watch chain return to healthy state
7. **Inject ₹5,00,000 payment** → Show it routes to Fast lane with high score
8. **Check PID Threshold Graph** → Show annotations explaining auto-tuning

---

## Backend Endpoints
The frontend expects these endpoints (check if `pipeline/main.py` implements them):

- `GET /health` — System health (Kafka/Redis status)
- `WS /dashboard/feed` — Real-time metrics WebSocket
- `POST /baseline/toggle` — Switch FIFO ↔ Adaptive
- `POST /simulator/rate` — Set traffic rate
- `POST /chaos/kill-kafka` — Chaos testing
- `POST /chaos/kill-redis` — Chaos testing
- `POST /chaos/restore` — Restore services
- `POST /chaos/inject-payment` — Inject high-value event
- `POST /chaos/flood-fast` — Flood fast lane

---

## Next Enhancements (Optional)

1. **Live ping indicator** in DurabilityChain showing packet flow even before chaos
2. **Drive per-lane latency** from simulator so Fast stays flat during spikes (real proof point)
3. **Score X-Ray payload truncation** to prevent expanded rows from blowing out height
4. **No-code demo script** for Chaos Panel (auto-sequence buttons with timing)
5. **"Last threshold shift" caption** under PID graph in plain English
6. **Better scroll position persistence** during rapid feed updates
7. **Dark mode support** (currently light-only)

---

## Troubleshooting

### Frontend shows blank screen after 1 sec
✅ **FIXED** — Was caused by undefined `chartData` in reducer

### WebSocket not connecting
- Check backend is running on port 8000
- Check console for CORS errors
- Verify `VITE_API_URL` in `.env` (defaults to `http://localhost:8000`)

### Chaos buttons don't work
- Backend chaos endpoints may not be implemented yet
- Frontend shows demo-style feedback as fallback
- Check browser console for 404s

### Docker services won't start
```bash
# Stop any existing containers
docker-compose down

# Remove volumes if needed
docker-compose down -v

# Rebuild and start
docker-compose up --build
```

---

## Build for Production
```bash
cd frontend/frontend
npm run build
# Output: dist/ folder ready to serve
```

---

Good luck with the demo! 🎉
