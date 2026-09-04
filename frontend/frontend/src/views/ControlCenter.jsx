import { useState, useRef, useEffect } from 'react';
import { usePipeline, API_BASE } from '../context/PipelineContext';
import StatusBadge from '../components/shared/StatusBadge';
import { ThresholdLineChart } from '../components/charts/Charts';
import './ControlCenter.css';

const TRAFFIC_PRESETS = [
  { id: 'normal',      label: 'Normal Traffic',          sub: '1,000 req/min',    rate: 1000,   icon: 'wifi',    color: 'var(--iris)' },
  { id: 'moderate',    label: 'Moderate Load',           sub: '5,000 req/min',    rate: 5000,   icon: 'trending_up', color: 'var(--ochre)' },
  { id: 'flash',       label: 'Flash Sale Spike',        sub: '20,000 req/min',   rate: 20000,  icon: 'bolt',    color: 'var(--bordeaux-light)' },
  { id: 'blackfriday', label: 'Black Friday',            sub: '100,000 req/min',  rate: 100000, icon: 'whatshot', color: 'var(--bordeaux)' },
];

export default function ControlCenter() {
  const { state, dispatch } = usePipeline();
  const [toggling, setToggling] = useState(false);
  const [feedback, setFeedback] = useState(null);
  const [health, setHealth] = useState(null);
  const feedbackTimer = useRef(null);

  // Derive active preset from live backend simulator state
  const currentRate = state.simulator?.rate_per_min || 1000;
  const activePreset = TRAFFIC_PRESETS.find(p => Math.abs(p.rate - currentRate) < 100)?.id || 
    (currentRate >= 90000 ? 'blackfriday' : currentRate >= 15000 ? 'flash' : currentRate >= 4000 ? 'moderate' : 'normal');

  const showFeedback = (msg, type = 'info') => {
    clearTimeout(feedbackTimer.current);
    setFeedback({ msg, type });
    feedbackTimer.current = setTimeout(() => setFeedback(null), 3000);
  };

  // Fetch health data
  useEffect(() => {
    const fetchHealth = async () => {
      try {
        const res = await fetch(`${API_BASE}/health`);
        setHealth(await res.json());
      } catch {}
    };
    fetchHealth();
    const id = setInterval(fetchHealth, 5000);
    return () => clearInterval(id);
  }, []);

  const toggleBaseline = async () => {
    setToggling(true);
    try {
      const res = await fetch(`${API_BASE}/baseline/toggle`);
      const data = await res.json();
      dispatch({ type: 'SET_BASELINE', payload: data.baseline_mode });
      showFeedback(
        data.baseline_mode ? 'Switched to Naive FIFO — scoring OFF' : 'Switched to Adaptive — scoring ON',
        data.baseline_mode ? 'warn' : 'success'
      );
    } catch { showFeedback('Failed to toggle mode', 'error'); }
    finally { setToggling(false); }
  };

  const applyPreset = async (preset) => {
    try {
      await fetch(`${API_BASE}/simulator/rate`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ rate: preset.rate }),
      });
      showFeedback(`Traffic: ${preset.label} (${preset.sub})`, 'success');
    } catch { showFeedback('Failed to set rate', 'error'); }
  };

  const pid = state.pid || {};
  const scaler = state.scaler || {};
  const latest = state.thresholdHistory[state.thresholdHistory.length - 1];
  const durabilityMode = health?.durability_mode || state.durability_mode || 'unknown';

  const CHAIN = [
    { label: 'Gateway',       active: true },
    { label: 'Kafka',         active: health?.kafka_healthy },
    { label: 'Redis Buffer',  active: !health?.kafka_healthy && health?.redis_healthy },
    { label: 'Local WAL',     active: !health?.kafka_healthy && !health?.redis_healthy },
  ];

  return (
    <div className="cc-view">
      {/* Toast */}
      {feedback && (
        <div className={`cc-toast cc-toast-${feedback.type}`}>
          <span className="material-symbols-outlined" style={{ fontSize: 16 }}>
            {feedback.type === 'success' ? 'check_circle' : feedback.type === 'warn' ? 'warning' : 'info'}
          </span>
          {feedback.msg}
        </div>
      )}

      {/* Header */}
      <div className="page-header">
        <div>
          <h1 className="page-title">Control Center</h1>
          <p className="page-desc">Toggle pipeline intelligence, adjust traffic load, monitor system health</p>
        </div>
      </div>

      {/* Mode Toggle */}
      <div className="card cc-toggle-card">
        <div className="cc-toggle-header">
          <span className="material-symbols-outlined" style={{ fontSize: 20, color: 'var(--iris)' }}>auto_awesome</span>
          <div>
            <div className="cc-toggle-title">Pipeline Intelligence Mode</div>
            <div className="cc-toggle-sub">Toggle live to prove adaptive engine superiority</div>
          </div>
        </div>
        <div className="cc-toggle-row">
          <div className={`cc-mode-box ${!state.baseline_mode ? 'active' : ''}`}>
            <span className="material-symbols-outlined">psychology</span>
            <div>
              <div className="cc-mode-name">Adaptive Scoring</div>
              <div className="cc-mode-desc">PID-controlled urgency scoring + lane routing</div>
            </div>
          </div>
          <button className={`cc-toggle-btn ${state.baseline_mode ? 'on' : ''} ${toggling ? 'spin' : ''}`} onClick={toggleBaseline} disabled={toggling}>
            <span className="cc-toggle-knob">
              <span className="material-symbols-outlined" style={{ fontSize: 16 }}>{toggling ? 'sync' : 'swap_horiz'}</span>
            </span>
          </button>
          <div className={`cc-mode-box ${state.baseline_mode ? 'active fifo' : ''}`}>
            <span className="material-symbols-outlined">view_list</span>
            <div>
              <div className="cc-mode-name">Naive FIFO</div>
              <div className="cc-mode-desc">First-in-first-out · no prioritization</div>
            </div>
          </div>
        </div>
      </div>

      {/* Traffic Presets */}
      <div className="card">
        <div className="card-header">
          <span className="card-title">Traffic Load Presets</span>
          <span className="card-sub">Select a scenario — pipeline handles all automatically</span>
        </div>
        <div className="cc-presets">
          {TRAFFIC_PRESETS.map(p => (
            <button
              key={p.id}
              className={`cc-preset ${activePreset === p.id ? 'active' : ''}`}
              style={activePreset === p.id ? { borderColor: p.color, background: `color-mix(in srgb, ${p.color} 8%, transparent)` } : {}}
              onClick={() => applyPreset(p)}
            >
              <span className="material-symbols-outlined cc-preset-icon" style={activePreset === p.id ? { color: p.color } : {}}>{p.icon}</span>
              <div className="cc-preset-label">{p.label}</div>
              <div className="cc-preset-sub">{p.sub}</div>
            </button>
          ))}
        </div>
      </div>

      {/* System Health + Thresholds row */}
      <div className="cc-bottom-row">
        {/* System Health */}
        <div className="card">
          <div className="card-header">
            <span className="card-title">System Health</span>
            <StatusBadge status={durabilityMode} />
          </div>
          <div className="cc-health-cards">
            {[
              { label: 'Kafka', ok: health?.kafka_healthy, role: 'Primary broker' },
              { label: 'Redis', ok: health?.redis_healthy, role: 'Emergency buffer' },
              { label: 'WAL',   ok: health?.wal_healthy ?? true, role: 'Local fallback' },
            ].map(c => (
              <div key={c.label} className="cc-health-item">
                <span className="cc-health-name">{c.label}</span>
                <StatusBadge status={c.ok ? 'healthy' : 'down'} size="sm" />
                <span className="cc-health-role">{c.role}</span>
              </div>
            ))}
          </div>
          <div className="cc-chain">
            {CHAIN.map((node, i) => (
              <span key={node.label} className="cc-chain-node">
                <span className="cc-chain-dot" style={{ background: node.active ? 'var(--green)' : 'var(--border)' }} />
                <span style={{ opacity: node.active ? 1 : 0.4 }}>{node.label}</span>
                {i < CHAIN.length - 1 && <span className="cc-chain-arrow">→</span>}
              </span>
            ))}
          </div>

          {/* Worker Auto-Scaler */}
          <div className="cc-scaler-section">
            <div className="cc-scaler-header">
              <span className="card-title" style={{ fontSize: 12 }}>Worker Auto-Scaler</span>
              <span className="cc-scaler-badge">{scaler.active_workers || 2} / {scaler.max_workers || 10}</span>
            </div>
            <div className="cc-worker-dots">
              {Array.from({ length: scaler.max_workers || 10 }).map((_, i) => (
                <div key={i} className={`cc-worker-dot ${i < (scaler.active_workers || 2) ? 'active' : ''}`} />
              ))}
            </div>
          </div>
        </div>

        {/* PID Thresholds */}
        <div className="card">
          <div className="card-header">
            <span className="card-title">PID Threshold History</span>
            <span className="card-sub">Auto-tuned every 5s</span>
          </div>
          <div style={{ padding: '12px 8px 8px' }}>
            {state.thresholdHistory.length < 2 ? (
              <div className="empty-state">Collecting threshold data…</div>
            ) : (
              <ThresholdLineChart data={state.thresholdHistory} />
            )}
          </div>
          <div className="cc-thresh-vals">
            <div className="cc-thresh-item">
              <span>Execute</span>
              <b style={{ color: 'var(--iris)' }}>{(latest?.execute ?? pid.current_execute_threshold ?? 6.0).toFixed(3)}</b>
            </div>
            <div className="cc-thresh-item">
              <span>Batch</span>
              <b style={{ color: 'var(--cassis)' }}>{(latest?.batch ?? 3.0).toFixed(3)}</b>
            </div>
            <div className="cc-thresh-item">
              <span>Defer</span>
              <b style={{ color: 'var(--ochre)' }}>{(latest?.defer ?? 1.0).toFixed(3)}</b>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
