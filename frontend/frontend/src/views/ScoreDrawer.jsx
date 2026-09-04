import { X } from 'lucide-react';
import './ScoreDrawer.css';

const WEIGHTS = [
  { key: 'monetary',        label: 'Monetary Value ($$$)',   color: 'var(--iris)' },
  { key: 'scarcity',        label: 'Scarcity Factor',       color: 'var(--cassis)' },
  { key: 'irreversibility', label: 'Irreversibility',       color: 'var(--bordeaux)' },
  { key: 'deadline',        label: 'Deadline Urgency',      color: 'var(--ochre)' },
  { key: 'queue_pressure',  label: 'Queue Depth',           color: 'var(--iris-soft)' },
  { key: 'queue_velocity',  label: 'Queue Velocity',        color: 'var(--ochre-warm)' },
  { key: 'worker_adj',      label: 'Worker Availability',   color: 'var(--text-muted)' },
  { key: 'quota_penalty',   label: 'Quota Penalty',         color: 'var(--bordeaux)' },
  { key: 'health_boost',    label: 'Health Check Boost',    color: 'var(--green)' },
];

const THRESHOLDS = [
  { label: 'Defer 1.0',   value: 1.0, color: 'var(--ochre)' },
  { label: 'Batch 3.0',   value: 3.0, color: 'var(--cassis)' },
  { label: 'Execute 6.0', value: 6.0, color: 'var(--iris)' },
];

export default function ScoreDrawer({ event, onClose }) {
  if (!event) return null;
  const components = event.components || {};
  const vals = WEIGHTS.map(w => Math.abs(components[w.key] ?? 0));
  const maxVal = Math.max(...vals, 0.01);
  const score = event.final_score ?? 0;

  return (
    <div className="drawer-overlay" onClick={onClose}>
      <div className="drawer" onClick={e => e.stopPropagation()}>
        <div className="drawer-header">
          <div>
            <div className="drawer-title">Score X-Ray</div>
            <div className="drawer-sub">{event.full_event_id || event.event_id}</div>
          </div>
          <button className="drawer-close" onClick={onClose}><X size={16} /></button>
        </div>

        <div className="drawer-body">
          {/* 1. Event Payload & Raw Variables (at Top) */}
          <div className="drawer-section-title" style={{ marginTop: 0 }}>Event Payload & Raw Variables</div>
          <div style={{
            background: 'var(--surface-muted)',
            border: '1px solid var(--border)',
            borderRadius: 8,
            padding: 10,
            fontFamily: 'monospace',
            fontSize: 11,
            color: 'var(--text)',
            whiteSpace: 'pre-wrap',
            wordBreak: 'break-all',
            marginBottom: 16
          }}>
            {JSON.stringify(event.payload || {
              event_id: event.event_id,
              type: event.type,
              producer: event.producer,
              components: event.components
            }, null, 2)}
          </div>

          {/* 2. Score hero */}
          <div className="score-hero">
            <span className="score-big">{score.toFixed(2)}</span>
            <span className="score-label">Final Score</span>
          </div>

          {/* 3. Threshold ruler */}
          <div className="threshold-ruler">
            {THRESHOLDS.map(t => (
              <div key={t.label} className="ruler-mark" style={{ left: `${Math.min((t.value / 12) * 100, 100)}%`, borderColor: t.color }}>
                <span style={{ color: t.color, fontSize: 9 }}>{t.label}</span>
              </div>
            ))}
            <div className="ruler-score-marker" style={{ left: `${Math.min((score / 12) * 100, 100)}%` }} />
          </div>

          {/* 4. Weight bars */}
          <div className="drawer-section-title">Weight Contributions</div>
          {WEIGHTS.map((w) => {
            const val = components[w.key] ?? 0;
            return (
              <div key={w.key} className="weight-row">
                <span className="weight-label">{w.label}</span>
                <div className="weight-bar-track">
                  <div className="weight-bar-fill" style={{ width: `${(Math.abs(val) / maxVal) * 100}%`, background: w.color }} />
                </div>
                <span className="weight-val" style={{ color: val < 0 ? 'var(--bordeaux)' : 'inherit' }}>
                  {val > 0 ? '+' : ''}{Number(val).toFixed(3)}
                </span>
              </div>
            );
          })}

          {/* 5. Routing Decision Meta */}
          <div className="drawer-section-title">Routing Decision</div>
          <div className="meta-grid">
            <div className="meta-item"><span>Type</span><b>{event.type}</b></div>
            <div className="meta-item"><span>Action</span><b>{event.action}</b></div>
            <div className="meta-item"><span>Band</span><b>{event.band || 'Standard'}</b></div>
            <div className="meta-item"><span>Latency</span><b>{event.latency_ms ?? 0}ms</b></div>
            <div className="meta-item"><span>Intrinsic</span><b>{event.intrinsic?.toFixed(2) ?? '—'}</b></div>
            <div className="meta-item"><span>Quota OK</span><b>{event.quota ? 'Yes' : 'No'}</b></div>
          </div>
        </div>
      </div>
    </div>
  );
}
