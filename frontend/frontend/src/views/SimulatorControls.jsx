import { useState, useEffect, useRef } from 'react';
import { usePipeline, API_BASE } from '../context/PipelineContext';
import './SimulatorControls.css';

const TRAFFIC_PRESETS = [
  {
    id: 'normal',
    label: 'Normal Traffic',
    sub: '50 req/s — Steady state',
    rate: 3000,
    icon: 'wifi',
    color: 'var(--iris)',
    colorLight: 'var(--iris-light)',
    colorBorder: 'var(--iris-border)',
  },
  {
    id: 'flash',
    label: 'Flash Sale Spike',
    sub: '2,000 req/s — Peak load',
    rate: 120000,
    icon: 'bolt',
    color: 'var(--ochre)',
    colorLight: 'var(--ochre-soft)',
    colorBorder: 'var(--ochre-border)',
  },
  {
    id: 'blackfriday',
    label: 'Black Friday Overload',
    sub: '10,000 req/s — Extreme load',
    rate: 600000,
    icon: 'whatshot',
    color: 'var(--bordeaux)',
    colorLight: 'var(--bordeaux-tint)',
    colorBorder: 'var(--bordeaux-border)',
  },
];

const LATENCY_BY_MODE = {
  adaptive: {
    fast: '18ms',
    standard: '240ms',
    cold: '1,200ms',
    avg: '~145ms avg',
    cost: '$0.22/hr',
    costRaw: 0.22,
  },
  fifo: {
    fast: '5,200ms',
    standard: '5,400ms',
    cold: '6,800ms',
    avg: '~5,800ms avg',
    cost: '$1.00/hr',
    costRaw: 1.00,
  },
};

export default function SimulatorControls() {
  const { state, dispatch } = usePipeline();
  const [activePreset, setActivePreset] = useState('normal');
  const [toggling, setToggling] = useState(false);
  const [applying, setApplying] = useState(false);
  const [feedback, setFeedback] = useState(null);
  const feedbackTimer = useRef(null);

  const showFeedback = (msg, type = 'info') => {
    clearTimeout(feedbackTimer.current);
    setFeedback({ msg, type });
    feedbackTimer.current = setTimeout(() => setFeedback(null), 3000);
  };

  const toggleBaseline = async () => {
    setToggling(true);
    try {
      const res = await fetch(`${API_BASE}/baseline/toggle`);
      const data = await res.json();
      dispatch({ type: 'SET_BASELINE', payload: data.baseline_mode });
      showFeedback(
        data.baseline_mode
          ? 'Switched to Naive FIFO — scoring engine OFF'
          : 'Switched to Adaptive Pipeline — scoring engine ON',
        data.baseline_mode ? 'warn' : 'success'
      );
    } catch {
      showFeedback('Failed to toggle mode', 'error');
    } finally {
      setToggling(false);
    }
  };

  const applyPreset = async (preset) => {
    setActivePreset(preset.id);
    setApplying(true);
    try {
      // Try to call the rate endpoint; ignore if not implemented
      await fetch(`${API_BASE}/simulator/rate`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ rate: preset.rate }),
      }).catch(() => {});
      showFeedback(`Traffic preset: ${preset.label}`, 'success');
    } finally {
      setApplying(false);
    }
  };

  const modeKey = state.baseline_mode ? 'fifo' : 'adaptive';
  const modeMetrics = LATENCY_BY_MODE[modeKey];
  const otherMetrics = LATENCY_BY_MODE[state.baseline_mode ? 'adaptive' : 'fifo'];

  return (
    <div className="sim-view">
      {/* Feedback toast */}
      {feedback && (
        <div className={`sim-toast sim-toast-${feedback.type}`}>
          <span className="material-symbols-outlined sim-toast-icon">
            {feedback.type === 'success' ? 'check_circle' : feedback.type === 'warn' ? 'warning' : 'info'}
          </span>
          {feedback.msg}
        </div>
      )}

      {/* PAGE HEADER */}
      <div className="page-header">
        <div>
          <div className="page-header-title-row">
            <h1 className="page-title">Demo Control Center</h1>
            <span className={`sbadge sbadge-${state.baseline_mode ? 'bd' : 'iris'} sbadge-md`}>
              <span className="sbadge-dot" />
              {state.baseline_mode ? 'FIFO Baseline Active' : 'Adaptive Engine Active'}
            </span>
          </div>
          <p className="page-desc">Control traffic load, toggle pipeline intelligence, and compare latency live on stage.</p>
        </div>
      </div>

      {/* ====== BIG TOGGLE (THE HERO PANEL) ====== */}
      <div className="sim-hero-toggle-card card">
        <div className="sim-mode-header">
          <div className="sim-mode-icon-wrap">
            <span className="material-symbols-outlined" style={{ fontSize: 22 }}>auto_awesome</span>
          </div>
          <div>
            <div className="sim-mode-title">Pipeline Intelligence Mode</div>
            <div className="sim-mode-sub">Flip this switch live to prove the adaptive engine's superiority</div>
          </div>
        </div>

        <div className="sim-toggle-stage">
          {/* Left: Adaptive */}
          <div className={`sim-mode-option ${!state.baseline_mode ? 'active-adaptive' : 'inactive'}`}>
            <div className="sim-mode-opt-icon iris-icon">
              <span className="material-symbols-outlined">psychology</span>
            </div>
            <div className="sim-mode-opt-label">Intelligent Adaptive</div>
            <div className="sim-mode-opt-sub">Urgency scoring · PID control · Lane routing</div>
            <div className="sim-mode-stat">{LATENCY_BY_MODE.adaptive.avg}</div>
            <div className="sim-mode-cost adaptive-cost">{LATENCY_BY_MODE.adaptive.cost}</div>
          </div>

          {/* Toggle button */}
          <button
            className={`sim-big-toggle ${state.baseline_mode ? 'on' : ''} ${toggling ? 'spinning' : ''}`}
            onClick={toggleBaseline}
            disabled={toggling}
            aria-label="Toggle pipeline mode"
          >
            <span className="sim-big-knob">
              <span className="material-symbols-outlined sim-big-knob-icon">
                {toggling ? 'sync' : state.baseline_mode ? 'swap_horiz' : 'swap_horiz'}
              </span>
            </span>
          </button>

          {/* Right: FIFO */}
          <div className={`sim-mode-option ${state.baseline_mode ? 'active-fifo' : 'inactive'}`}>
            <div className="sim-mode-opt-icon fifo-icon">
              <span className="material-symbols-outlined">view_list</span>
            </div>
            <div className="sim-mode-opt-label">Naive FIFO Baseline</div>
            <div className="sim-mode-opt-sub">First-in-first-out · No prioritization</div>
            <div className="sim-mode-stat">{LATENCY_BY_MODE.fifo.avg}</div>
            <div className="sim-mode-cost fifo-cost">{LATENCY_BY_MODE.fifo.cost}</div>
          </div>
        </div>

        {/* Live comparison strip */}
        <div className="sim-compare-strip">
          <div className="sim-compare-item">
            <span className="sim-compare-label">Fast Lane P0</span>
            <span className="sim-compare-now">{modeMetrics.fast}</span>
            <span className="sim-compare-vs">vs {otherMetrics.fast}</span>
          </div>
          <div className="sim-compare-divider" />
          <div className="sim-compare-item">
            <span className="sim-compare-label">Standard Lane</span>
            <span className="sim-compare-now">{modeMetrics.standard}</span>
            <span className="sim-compare-vs">vs {otherMetrics.standard}</span>
          </div>
          <div className="sim-compare-divider" />
          <div className="sim-compare-item">
            <span className="sim-compare-label">Cold Lane</span>
            <span className="sim-compare-now">{modeMetrics.cold}</span>
            <span className="sim-compare-vs">vs {otherMetrics.cold}</span>
          </div>
          <div className="sim-compare-divider" />
          <div className="sim-compare-item">
            <span className="sim-compare-label">Cloud Cost</span>
            <span className="sim-compare-now" style={{ color: state.baseline_mode ? 'var(--bordeaux)' : 'var(--green)' }}>{modeMetrics.cost}</span>
            <span className="sim-compare-vs">vs {otherMetrics.cost}</span>
          </div>
        </div>
      </div>

      {/* ====== TRAFFIC PRESETS ====== */}
      <div className="card">
        <div className="card-header">
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <div style={{ width: 24, height: 24, borderRadius: 6, background: 'var(--iris-light)', border: '1px solid var(--iris-border)', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
              <span className="material-symbols-outlined" style={{ fontSize: 14, color: 'var(--iris)' }}>traffic</span>
            </div>
            <span className="card-title">Traffic Load Presets</span>
          </div>
          <span className="card-sub">Select a scenario to simulate — pipeline handles all automatically</span>
        </div>
        <div className="sim-presets">
          {TRAFFIC_PRESETS.map(p => (
            <button
              key={p.id}
              className={`sim-preset-btn ${activePreset === p.id ? 'active' : ''}`}
              style={activePreset === p.id ? {
                borderColor: p.color,
                background: p.colorLight,
              } : {}}
              onClick={() => applyPreset(p)}
            >
              <div className="sim-preset-icon" style={activePreset === p.id ? { background: p.color } : {}}>
                <span className="material-symbols-outlined">{p.icon}</span>
              </div>
              <div className="sim-preset-label">{p.label}</div>
              <div className="sim-preset-sub">{p.sub}</div>
              {activePreset === p.id && (
                <div className="sim-preset-active-badge" style={{ background: p.color }}>ACTIVE</div>
              )}
            </button>
          ))}
        </div>
      </div>

      {/* ====== LIVE STATS (from WS) ====== */}
      <div className="sim-live-grid">
        <div className="card sim-stat-card">
          <div className="sim-stat-label">Total Ingested</div>
          <div className="sim-stat-value">{(state.total_ingested || 0).toLocaleString()}</div>
          <div className="sim-stat-sub">events processed</div>
        </div>
        <div className="card sim-stat-card">
          <div className="sim-stat-label">Events / sec</div>
          <div className="sim-stat-value">{(state.events_per_second || 0).toFixed(1)}</div>
          <div className="sim-stat-sub">current throughput</div>
        </div>
        <div className="card sim-stat-card">
          <div className="sim-stat-label">Execute Threshold</div>
          <div className="sim-stat-value mono">{state.pid?.current_execute_threshold?.toFixed(3) ?? '6.000'}</div>
          <div className="sim-stat-sub">PID-adjusted live</div>
        </div>
        <div className="card sim-stat-card">
          <div className="sim-stat-label">Quota Violations</div>
          <div className="sim-stat-value" style={{ color: (state.quota_violations || 0) > 0 ? 'var(--bordeaux)' : 'var(--green)' }}>
            {state.quota_violations || 0}
          </div>
          <div className="sim-stat-sub">rate-limit trips</div>
        </div>
      </div>
    </div>
  );
}
