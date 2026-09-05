import { useState, useEffect, useRef } from 'react';
import { usePipeline, API_BASE } from '../context/PipelineContext';
import StatusBadge from '../components/shared/StatusBadge';
import LaneVisualizer from '../components/shared/LaneVisualizer';
import LaneQueueMonitor from '../components/shared/LaneQueueMonitor';
import EventTraceFeed from '../components/shared/EventTraceFeed';
import RecentEventsStream from '../components/shared/RecentEventsStream';
import { ThroughputChart, ActionsChart } from '../components/charts/Charts';
import { LaneLatencyChart } from '../components/charts/LaneLatencyChart';
import ScoreDrawer from './ScoreDrawer';
import './Dashboard.css';

const TRAFFIC_PRESETS = [
  { id: 'normal',      label: 'Normal Traffic',          sub: '1,000 req/min',    rate: 1000,   icon: 'wifi',         color: '#8B1538' },
  { id: 'moderate',    label: 'Moderate Load',           sub: '5,000 req/min',    rate: 5000,   icon: 'trending_up',  color: '#B45309' },
  { id: 'flash',       label: 'Flash Sale Spike',        sub: '20,000 req/min',   rate: 20000,  icon: 'bolt',         color: '#881337' },
  { id: 'blackfriday', label: 'Black Friday',            sub: '100,000 req/min',  rate: 100000, icon: 'whatshot',     color: '#881337' },
];

const TYPE_COLORS = {
  order: 'var(--iris)', payment: 'var(--green)', inventory: 'var(--ochre)',
  click: 'var(--cassis)', log: 'var(--text-muted)', other: 'var(--text-muted)',
};

const ACTION_LABEL = {
  execute: { label: 'Fast Lane', color: 'var(--iris)' },
  batch:   { label: 'Standard',  color: 'var(--cassis)' },
  defer:   { label: 'Cold Lane', color: 'var(--ochre)' },
  shed:    { label: 'Rejected',  color: 'var(--bordeaux)' },
  backpressure: { label: 'Backpressure', color: 'var(--bordeaux)' },
};

const COMPONENT_COLS = [
  { key: 'monetary',        label: '$$$',    title: 'Monetary Value' },
  { key: 'irreversibility', label: 'IRREV',  title: 'Irreversibility' },
  { key: 'scarcity',        label: 'SCARCE', title: 'Scarcity' },
  { key: 'deadline',        label: 'DEADLN', title: 'Deadline Urgency' },
  { key: 'quota_penalty',   label: 'QUOTA',  title: 'Over-Quota Penalty' },
  { key: 'worker_adj',      label: 'WORKR',  title: 'Worker Availability' },
  { key: 'health_boost',    label: 'HLTH',   title: 'Health Boost' },
];

function fmtComponent(val) {
  if (val > 0.001) return <span className="comp-pos">+{val.toFixed(2)}</span>;
  if (val < -0.001) return <span className="comp-neg">{val.toFixed(2)}</span>;
  return <span className="comp-zero">—</span>;
}

export default function Dashboard() {
  const { state } = usePipeline();
  const [selected, setSelected] = useState(null);
  const [feedback, setFeedback] = useState(null);
  const feedbackTimer = useRef(null);
  const loading = !state.lastUpdated;

  const showFeedback = (msg, variant = 'info') => {
    clearTimeout(feedbackTimer.current);
    setFeedback({ msg, variant });
    feedbackTimer.current = setTimeout(() => setFeedback(null), 3200);
  };

  const applyPreset = async (preset) => {
    try {
      await fetch(`${API_BASE}/simulator/rate`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ rate: preset.rate }),
      });
      showFeedback(`Traffic: ${preset.label} (${preset.sub})`, 'success');
    } catch { 
      showFeedback('Failed to set rate', 'error'); 
    }
  };

  const eps = state.events_per_second || 0;
  const rpm = state.requests_per_minute || 0;
  const actions = state.actions || {};
  const totalActions = Math.max(Object.values(actions).reduce((a, b) => a + b, 0), 1);

  // Events with score components for breakdown
  const breakdownEvents = [...(state.recent_events || [])].filter(e => e.components && Object.keys(e.components).length > 0).slice(-8);

  const activePreset = TRAFFIC_PRESETS.find(p => Math.abs(p.rate - (state.simulator?.rate_per_min || 1000)) < 100)?.id
    || (state.simulator?.rate_per_min >= 90000 ? 'blackfriday'
        : state.simulator?.rate_per_min >= 15000 ? 'flash'
        : state.simulator?.rate_per_min >= 4000 ? 'moderate'
        : 'normal');

  return (
    <div className="dashboard">
      {/* Toast Feedback */}
      {feedback && (
        <div className={`cc-toast cc-toast-${feedback.variant === 'warn' ? 'warn' : feedback.variant === 'error' ? 'error' : 'success'}`}>
          <span className="material-symbols-outlined" style={{ fontSize: 16 }}>
            {feedback.variant === 'success' ? 'check_circle' : feedback.variant === 'warn' ? 'warning' : feedback.variant === 'error' ? 'error' : 'info'}
          </span>
          {feedback.msg}
        </div>
      )}

      {/* Page header */}
      <div className="page-header">
        <div>
          <h1 className="page-title">Live Pipeline Dashboard</h1>
          <p className="page-desc">Real-time event scoring, lane routing, and durability — zero loss guarantee</p>
        </div>
        <div className="page-header-actions">
          <span className={`sbadge sbadge-${state.baseline_mode ? 'ochre' : 'iris'} sbadge-md`}>
            <span className="sbadge-dot" />
            {state.baseline_mode ? 'FIFO Baseline' : 'Adaptive Scoring'}
          </span>
          {state.simulator?.running && (
            <span className="sbadge sbadge-iris sbadge-sm">
              <span className="sbadge-dot" />
              {state.simulator.mode} · {(state.simulator.rate_per_min || 0).toLocaleString()}/min
            </span>
          )}
        </div>
      </div>

      {/* KPI Strip — 4 compact metric cards */}
      <div className="kpi-strip">
        {loading ? (
          [...Array(4)].map((_, i) => <div key={i} className="kpi-card"><div className="skeleton" style={{ height: 40, width: '60%' }} /></div>)
        ) : (<>
          <div className="kpi-card">
            <div className="kpi-value">{(state.total_ingested || 0).toLocaleString()}</div>
            <div className="kpi-label">Total Ingested</div>
          </div>
          <div className="kpi-card">
            <div className="kpi-value">{eps.toFixed(1)} <span className="kpi-unit">ev/s</span></div>
            <div className="kpi-label">Throughput</div>
          </div>
          <div className="kpi-card">
            <div className="kpi-value">{rpm.toLocaleString()} <span className="kpi-unit">/min</span></div>
            <div className="kpi-label">Requests</div>
          </div>
          <div className="kpi-card">
            <div className="kpi-value">{Math.round(state.uptime || 0)}<span className="kpi-unit">s</span></div>
            <div className="kpi-label">Uptime</div>
          </div>
        </>)}
      </div>

      {/* Traffic Load Presets */}
      <div className="card">
        <div className="card-header">
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <div style={{ width: 24, height: 24, borderRadius: 6, background: '#FFF1F3', border: '1px solid #FECDD6', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
              <span className="material-symbols-outlined" style={{ fontSize: 14, color: '#8B1538' }}>traffic</span>
            </div>
            <div>
              <span className="card-title">Traffic Load Presets</span>
              <span className="card-sub" style={{ marginLeft: 8 }}>Select a scenario — pipeline handles all automatically</span>
            </div>
          </div>
        </div>
        <div className="cc-presets">
          {TRAFFIC_PRESETS.map(p => (
            <button
              key={p.id}
              className={`cc-preset ${activePreset === p.id ? 'active' : ''}`}
              style={activePreset === p.id ? { borderColor: p.color, background: p.color + '0D' } : {}}
              onClick={() => applyPreset(p)}
            >
              <span className="material-symbols-outlined cc-preset-icon" style={activePreset === p.id ? { color: p.color } : {}}>{p.icon}</span>
              <div className="cc-preset-label">{p.label}</div>
              <div className="cc-preset-sub">{p.sub}</div>
            </button>
          ))}
        </div>
      </div>

      {/* Live Event Trace Feed — the real-time scoring proof */}
      <EventTraceFeed />

      {/* Lane Queue Monitor — DRR scheduling visualization */}
      <LaneQueueMonitor />

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 320px', gap: 14 }}>
        <div>
          {/* Lane Visualizer */}
          <LaneVisualizer />
        </div>
      </div>

      {/* Charts row — throughput + per-lane latency */}
      <div className="dash-charts-row">
        <div className="card">
          <div className="card-header">
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <span className="card-title">Throughput</span>
              <span className="card-sub" style={{ marginLeft: 8 }}>Events/sec · rolling</span>
            </div>
          </div>
          <div style={{ padding: '12px 8px 8px' }}>
            <ThroughputChart data={state.chartData?.throughput ?? []} />
          </div>
        </div>
        <div className="card">
          <div className="card-header">
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <span className="card-title">Per-Lane Latency Breakdown</span>
              <span className="card-sub" style={{ marginLeft: 8 }}>Fast / Standard / Cold · ms</span>
            </div>
          </div>
          <div style={{ padding: '12px 8px 8px' }}>
            <LaneLatencyChart data={state.chartData?.laneLatency ?? []} />
          </div>
        </div>
      </div>

      {/* Routing summary bar */}
      <div className="routing-bar card">
        <div className="routing-bar-inner">
          {['execute', 'batch', 'defer', 'shed', 'backpressure'].map(a => {
            const count = actions[a] || 0;
            const pct = ((count / totalActions) * 100).toFixed(0);
            const cfg = ACTION_LABEL[a] || { label: a, color: 'var(--text-muted)' };
            return (
              <div key={a} className="routing-item">
                <span className="routing-dot" style={{ background: cfg.color }} />
                <span className="routing-label">{cfg.label}</span>
                <span className="routing-count">{count.toLocaleString()}</span>
                <span className="routing-pct">{pct}%</span>
              </div>
            );
          })}
        </div>
      </div>

      {/* Score Breakdown Table — the "WHY" panel (matches demo.py) */}
      <div className="card">
        <div className="card-header">
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <div style={{ width: 24, height: 24, borderRadius: 6, background: 'var(--ochre-soft)', border: '1px solid var(--ochre-border)', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
              <span className="material-symbols-outlined" style={{ fontSize: 14, color: 'var(--ochre)' }}>science</span>
            </div>
            <div>
              <span className="card-title">Score Breakdown</span>
              <span className="card-sub" style={{ marginLeft: 8 }}>Why each event was routed to its lane</span>
            </div>
          </div>
        </div>
        {breakdownEvents.length === 0 ? (
          <div className="empty-state">
            <span className="material-symbols-outlined" style={{ fontSize: 26, color: 'var(--border)', display: 'block', marginBottom: 6 }}>science</span>
            Waiting for events with scoring data — scoring components appear as events are scored
          </div>
        ) : (
          <div style={{ overflowX: 'auto' }}>
            <table className="events-table breakdown-table">
              <thead>
                <tr>
                  <th>Event ID</th>
                  <th>Type</th>
                  {COMPONENT_COLS.map(c => <th key={c.key} title={c.title} className="comp-th">{c.label}</th>)}
                  <th className="comp-th">= FINAL</th>
                  <th>Lane</th>
                </tr>
              </thead>
              <tbody>
                {breakdownEvents.map(ev => {
                  const comp = ev.components || {};
                  const lane = ACTION_LABEL[ev.action] || { label: ev.action, color: 'var(--text-muted)' };
                  return (
                    <tr key={ev.event_id} className="events-row" onClick={() => setSelected(ev)}>
                      <td className="event-id truncate">{ev.event_id}</td>
                      <td>
                        <span className="type-pill" style={{ '--pill-color': TYPE_COLORS[ev.type] || 'var(--text-muted)' }}>
                          {(ev.type || '?').toUpperCase().slice(0, 3)}
                        </span>
                      </td>
                      {COMPONENT_COLS.map(c => (
                        <td key={c.key} className="comp-cell">{fmtComponent(comp[c.key] ?? 0)}</td>
                      ))}
                      <td className="comp-cell final-cell">{ev.final_score?.toFixed(2) ?? '—'}</td>
                      <td>
                        <StatusBadge
                          status={ev.action === 'execute' ? 'active' : ev.action === 'batch' ? 'standby' : 'degraded'}
                          label={lane.label}
                          size="sm"
                        />
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
        <div className="breakdown-legend">
          $$$ = monetary · IRREV = irreversibility · SCARCE = physical scarcity · DEADLN = deadline urgency · QUOTA = over-quota penalty · WORKR = worker avail · HLTH = health boost
        </div>
      </div>

      {/* Recent Events Stream (20s Batched, Append-Only) */}
      <RecentEventsStream onSelectEvent={setSelected} />

      {selected && <ScoreDrawer event={selected} onClose={() => setSelected(null)} />}
    </div>
  );
}
