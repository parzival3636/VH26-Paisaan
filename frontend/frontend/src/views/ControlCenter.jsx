import { useState, useRef, useEffect, useMemo } from 'react';
import { usePipeline, API_BASE } from '../context/PipelineContext';
import StatusBadge from '../components/shared/StatusBadge';
import DurabilityChain from '../components/shared/DurabilityChain';
import ChaosControlPanel from './ChaosControlPanel';
import BaselineSplitView from './BaselineSplitView';
import ThresholdGraph from './ThresholdGraph';
import './ControlCenter.css';

const TRAFFIC_PRESETS = [
  { id: 'normal',      label: 'Normal Traffic',          sub: '1,000 req/min',    rate: 1000,   icon: 'wifi',    color: '#8B1538' },
  { id: 'moderate',    label: 'Moderate Load',           sub: '5,000 req/min',    rate: 5000,   icon: 'trending_up', color: '#B45309' },
  { id: 'flash',       label: 'Flash Sale Spike',        sub: '20,000 req/min',   rate: 20000,  icon: 'bolt',    color: '#881337' },
  { id: 'blackfriday', label: 'Black Friday',            sub: '100,000 req/min',  rate: 100000, icon: 'whatshot', color: '#881337' },
];

export default function ControlCenter() {
  const { state, dispatch } = usePipeline();
  const [toggling, setToggling] = useState(false);
  const [feedback, setFeedback] = useState(null);
  const [health, setHealth] = useState(null);
  const feedbackTimer = useRef(null);

  const showFeedback = (msg, variant = 'info') => {
    clearTimeout(feedbackTimer.current);
    setFeedback({ msg, variant });
    feedbackTimer.current = setTimeout(() => setFeedback(null), 3200);
  };

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
  const durabilityMode = health?.durability_mode || state.durability_mode || 'unknown';

  const CHAIN = [
    { label: 'Gateway',      active: true },
    { label: 'Kafka',        active: health?.kafka_healthy },
    { label: 'Redis Buffer', active: !health?.kafka_healthy && health?.redis_healthy },
    { label: 'Local WAL',    active: !health?.kafka_healthy && !health?.redis_healthy },
  ];

  const activePreset = TRAFFIC_PRESETS.find(p => Math.abs(p.rate - (state.simulator?.rate_per_min || 1000)) < 100)?.id
    || (state.simulator?.rate_per_min >= 90000 ? 'blackfriday'
        : state.simulator?.rate_per_min >= 15000 ? 'flash'
        : state.simulator?.rate_per_min >= 4000 ? 'moderate'
        : 'normal');

  return (
    <div className="cc-view">
      {/* Toast */}
      {feedback && (
        <div className={`cc-toast cc-toast-${feedback.variant === 'warn' ? 'warn' : feedback.variant === 'error' ? 'error' : 'success'}`}>
          <span className="material-symbols-outlined" style={{ fontSize: 16 }}>
            {feedback.variant === 'success' ? 'check_circle' : feedback.variant === 'warn' ? 'warning' : feedback.variant === 'error' ? 'error' : 'info'}
          </span>
          {feedback.msg}
        </div>
      )}

      {/* Header */}
      <div className="page-header">
        <div>
          <h1 className="page-title">Control Center</h1>
          <p className="page-desc">Toggle pipeline intelligence, adjust traffic load, and watch the durability chain respond live</p>
        </div>
      </div>

      {/* Mode Toggle */}
      <div className="card cc-toggle-card">
        <div className="cc-toggle-header">
          <span className="material-symbols-outlined" style={{ fontSize: 20, color: '#8B1538' }}>auto_awesome</span>
          <div>
            <div className="cc-toggle-title">Pipeline Intelligence Mode</div>
            <div className="cc-toggle-sub">Flip live to prove adaptive engine superiority — split view appears in FIFO mode</div>
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

      {/* Chaos Control Panel */}
      <ChaosControlPanel />

      {/* Bottom row: durability chain + PID thresholds */}
      <div className="cc-bottom-row">
        {/* Durability Chain Visualizer */}
        <div className="card" style={{ padding: '16px' }}>
          <div className="card-header">
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <span className="material-symbols-outlined" style={{ fontSize: 15, color: '#8B1538' }}>pipeline</span>
              <div>
                <span className="card-title">Durability Chain Visualizer</span>
                <span className="card-sub" style={{ marginLeft: 8 }}>Kafka → Redis Buffer → Local WAL · live</span>
              </div>
            </div>
            <StatusBadge status={durabilityMode} />
          </div>
          <div style={{ padding: '6px 16px 14px' }}>
            <DurabilityChain health={health} />
          </div>
          <div className="cc-chain">
            {CHAIN.map((node, i) => (
              <span key={node.label} className="cc-chain-node">
                <span className="cc-chain-dot" style={{ background: node.active ? '#22C55E' : '#E3E6EB' }} />
                <span style={{ opacity: node.active ? 1 : 0.45 }}>{node.label}</span>
                {i < CHAIN.length - 1 && <span className="cc-chain-arrow">→</span>}
              </span>
            ))}
          </div>
          <div style={{ padding: '0 16px 12px', fontSize: 10.5, color: '#71717A', fontFamily: 'JetBrains Mono, monospace' }}>
            If a layer fails, flow reroutes to the next. Reconciler replays to Kafka on recovery.
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

        {/* PID Thresholds — annotated graph */}
        <div className="card">
          <div className="card-header">
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <span className="material-symbols-outlined" style={{ fontSize: 15, color: '#8B1538' }}>science</span>
              <div>
                <span className="card-title">PID Threshold History</span>
                <span className="card-sub" style={{ marginLeft: 8 }}>Execute / Batch / Defer · PID-adjusted</span>
              </div>
            </div>
          </div>
          <div style={{ padding: '12px 8px 8px' }}>
            <ThresholdGraph
              thresholdHistory={state.thresholdHistory}
              annotations={state.thresholdAnnotations}
            />
          </div>
          <div className="cc-thresh-vals">
            <div className="cc-thresh-item">
              <span>Execute</span>
              <b style={{ color: '#8B1538' }}>{(state.thresholdHistory[state.thresholdHistory.length - 1]?.execute ?? pid.current_execute_threshold ?? 6.0).toFixed(3)}</b>
            </div>
            <div className="cc-thresh-item">
              <span>Batch</span>
              <b style={{ color: '#4C1D95' }}>{(state.thresholdHistory[state.thresholdHistory.length - 1]?.batch ?? 3.0).toFixed(3)}</b>
            </div>
            <div className="cc-thresh-item">
              <span>Defer</span>
              <b style={{ color: '#B45309' }}>{(state.thresholdHistory[state.thresholdHistory.length - 1]?.defer ?? 1.0).toFixed(3)}</b>
            </div>
          </div>
        </div>
      </div>

      {/* Baseline vs Adaptive split view — only when FIFO toggle is ON */}
      {state.baseline_mode && (
        <div style={{ marginTop: 4 }}>
          <BaselineSplitView />
        </div>
      )}
    </div>
  );
}
