import { createContext, useContext, useReducer, useEffect, useRef } from 'react';

const API_BASE = import.meta.env.VITE_API_URL || 'http://localhost:8000';
const WS_URL = API_BASE.replace(/^http/, 'ws') + '/dashboard/feed';

const initialState = {
  connected: false,
  lastUpdated: null,
  stale: false,
  total_ingested: 0,
  events_per_second: 0,
  requests_per_minute: 0,
  quota_violations: 0,
  uptime: 0,
  actions: { execute: 0, batch: 0, defer: 0, shed: 0, backpressure: 0 },
  by_type: { order: 0, payment: 0, inventory: 0, click: 0, log: 0, other: 0 },
  recent_events: [],
  durability_mode: 'unknown',
  pid: { current_execute_threshold: 6.0, batch_threshold: 3.0, defer_threshold: 1.0, p0_latency: 0 },
  baseline_mode: false,
  simulator: { running: false, mode: 'normal', rate_per_min: 1000 },
  scaler: { active_workers: 2, min_workers: 2, max_workers: 10 },
  chartData: {
    throughput: [],
    actions: [],
  },
  thresholdHistory: [],
};

function reducer(state, action) {
  switch (action.type) {
    case 'WS_CONNECTED':
      return { ...state, connected: true, stale: false };
    case 'WS_DISCONNECTED':
      return { ...state, connected: false };
    case 'WS_DATA': {
      const d = action.payload;
      const now = Date.now();
      const currentSec = Math.floor(now / 1000);

      // 1-second interval sampling for clean chart steps
      const lastThroughput = state.chartData.throughput[state.chartData.throughput.length - 1];
      const shouldPushChart = !lastThroughput || lastThroughput.t !== currentSec;

      const throughput = shouldPushChart
        ? [...state.chartData.throughput, { t: currentSec, eps: d.events_per_second || 0 }].slice(-60)
        : state.chartData.throughput;

      const actions = shouldPushChart
        ? [...state.chartData.actions, {
            t: currentSec,
            execute: d.actions?.execute || 0,
            batch: d.actions?.batch || 0,
            defer: d.actions?.defer || 0,
          }].slice(-60)
        : state.chartData.actions;

      const thresholdHistory = shouldPushChart
        ? [...state.thresholdHistory, {
            t: currentSec,
            execute: d.pid?.current_execute_threshold || 6.0,
            batch: d.pid?.batch_threshold || 3.0,
            defer: d.pid?.defer_threshold || 1.0,
          }].slice(-180)
        : state.thresholdHistory;

      return {
        ...state,
        lastUpdated: now,
        stale: false,
        total_ingested: d.total_ingested ?? state.total_ingested,
        events_per_second: d.events_per_second ?? state.events_per_second,
        requests_per_minute: d.requests_per_minute ?? state.requests_per_minute,
        quota_violations: d.quota_violations ?? state.quota_violations,
        uptime: d.uptime ?? state.uptime,
        actions: d.actions ?? state.actions,
        by_type: d.by_type ?? state.by_type,
        recent_events: d.recent_events ?? state.recent_events,
        durability_mode: d.durability_mode ?? state.durability_mode,
        pid: d.pid ?? state.pid,
        baseline_mode: d.baseline_mode ?? state.baseline_mode,
        simulator: d.simulator ?? state.simulator,
        scaler: d.scaler ?? state.scaler,
        chartData: { throughput, actions },
        thresholdHistory,
      };
    }
    case 'SET_STALE':
      return { ...state, stale: true };
    case 'SET_BASELINE':
      return { ...state, baseline_mode: action.payload };
    default:
      return state;
  }
}

const PipelineContext = createContext(null);

export function PipelineProvider({ children }) {
  const [state, dispatch] = useReducer(reducer, initialState);
  const wsRef = useRef(null);
  const staleTimerRef = useRef(null);
  const reconnectRef = useRef(null);
  const mountedRef = useRef(true);

  const connect = () => {
    if (wsRef.current) wsRef.current.close();
    const ws = new WebSocket(WS_URL);
    wsRef.current = ws;

    ws.onopen = () => {
      if (!mountedRef.current) return;
      dispatch({ type: 'WS_CONNECTED' });
      clearTimeout(reconnectRef.current);
    };

    ws.onmessage = (e) => {
      if (!mountedRef.current) return;
      try {
        const data = JSON.parse(e.data);
        dispatch({ type: 'WS_DATA', payload: data });
        clearTimeout(staleTimerRef.current);
        staleTimerRef.current = setTimeout(() => dispatch({ type: 'SET_STALE' }), 5000);
      } catch {}
    };

    ws.onclose = () => {
      if (!mountedRef.current) return;
      dispatch({ type: 'WS_DISCONNECTED' });
      reconnectRef.current = setTimeout(connect, 3000);
    };

    ws.onerror = () => ws.close();
  };

  useEffect(() => {
    mountedRef.current = true;
    connect();
    return () => {
      mountedRef.current = false;
      clearTimeout(staleTimerRef.current);
      clearTimeout(reconnectRef.current);
      wsRef.current?.close();
    };
  }, []);

  return (
    <PipelineContext.Provider value={{ state, dispatch, API_BASE }}>
      {children}
    </PipelineContext.Provider>
  );
}

export const usePipeline = () => useContext(PipelineContext);
export { API_BASE };
