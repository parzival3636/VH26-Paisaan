import { useMemo } from 'react';
import { ThresholdLineChart } from '../components/charts/Charts';
import './ThresholdGraph.css';

const ANNOTATION_REASONS = [
  { key: 'latency-drift', label: 'P0 latency drift detected', detail: 'Tightening EXECUTE_THRESHOLD' },
  { key: 'spike-surge',    label: 'Traffic spike surge',       detail: 'Lowering defer floor to protect fast lane' },
  { key: 'recovery',       label: 'System recovered',          detail: 'Relaxing thresholds back toward baseline' },
];

export default function ThresholdGraph({ thresholdHistory = [], annotations = [] }) {
  const pid = {};
  const latest = thresholdHistory[thresholdHistory.length - 1];

  // Build annotation markers with reasons for callouts
  const markers = useMemo(() => {
    return annotations.map((a, i) => {
      const reason = ANNOTATION_REASONS[i % ANNOTATION_REASONS.length];
      return {
        ...a,
        reasonLabel: reason.label,
        reasonDetail: reason.detail,
      };
    });
  }, [annotations]);

  return (
    <div className="threshold-view">
      <div className="threshold-body">
        <div className="card threshold-main">
          <div className="card-header">
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <span className="material-symbols-outlined" style={{ fontSize: 15, color: '#8B1538' }}>science</span>
              <div>
                <span className="card-title">Threshold History</span>
                <span className="card-sub" style={{ marginLeft: 8 }}>Execute / Batch / Defer · PID-adjusted</span>
              </div>
            </div>
            <span style={{ fontFamily: 'JetBrains Mono, monospace', fontSize: 10, color: '#71717A' }}>
              {thresholdHistory.length < 2 ? 'collecting…' : 'live'}
            </span>
          </div>
          <div style={{ padding: '12px 6px 6px', position: 'relative' }}>
            {thresholdHistory.length < 2 ? (
              <div className="empty-state">
                <span className="material-symbols-outlined" style={{ fontSize: 24, color: '#E3E6EB', display: 'block', marginBottom: 6 }}>science</span>
                Collecting threshold data…
              </div>
            ) : (
              <ThresholdLineChart data={thresholdHistory} annotations={markers} />
            )}
          </div>
          <div className="threshold-legend">
            <span className="leg-item" style={{ color: '#8B1538' }}>● Execute</span>
            <span className="leg-item" style={{ color: '#4C1D95' }}>● Batch</span>
            <span className="leg-item" style={{ color: '#B45309' }}>● Defer</span>
            <span style={{ color: '#9CA3AF', marginLeft: 6, fontSize: 10.5, fontFamily: 'JetBrains Mono, monospace' }}>
              {markers.length > 0 ? `${markers.length} adjustment${markers.length > 1 ? 's' : ''} recorded` : 'no adjustments yet'}
            </span>
          </div>
        </div>

        <div className="threshold-side">
          <div className="card">
            <div className="card-header"><span className="card-title">Current Values</span></div>
            <div className="threshold-vals">
              <div className="tval-row">
                <span className="tval-label">Execute</span>
                <span className="tval-num" style={{ color: '#8B1538' }}>{(latest?.execute ?? 6.0).toFixed(3)}</span>
              </div>
              <div className="tval-row">
                <span className="tval-label">Batch</span>
                <span className="tval-num" style={{ color: '#4C1D95' }}>{(latest?.batch ?? 3.0).toFixed(3)}</span>
              </div>
              <div className="tval-row">
                <span className="tval-label">Defer</span>
                <span className="tval-num" style={{ color: '#B45309' }}>{(latest?.defer ?? 1.0).toFixed(3)}</span>
              </div>
            </div>
          </div>

          <div className="card">
            <div className="card-header"><span className="card-title">Live Annotations</span></div>
            {markers.length === 0 ? (
              <div style={{ padding: '12px 16px', fontSize: 11.5, color: '#9CA3AF', fontFamily: 'JetBrains Mono, monospace' }}>
                No threshold shifts yet — the PID controller will annotate each adjustment here.
              </div>
            ) : (
              <div style={{ padding: '0 12px 12px' }}>
                {markers.slice(-4).reverse().map((m, i) => (
                  <div
                    key={i}
                    className="threshold-annotation"
                    onMouseEnter={e => { e.currentTarget.style.background = '#FAFBFC'; }}
                    onMouseLeave={e => { e.currentTarget.style.background = '#FFFFFF'; }}
                  >
                    <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 2 }}>
                      <span style={{ width: 6, height: 6, borderRadius: '50%', background: m.color, flexShrink: 0 }} />
                      <span style={{ fontFamily: 'JetBrains Mono, monospace', fontSize: 10, fontWeight: 700, color: m.color, textTransform: 'uppercase', letterSpacing: '0.05em' }}>
                        {m.reasonLabel}
                      </span>
                      <span style={{ marginLeft: 'auto', fontFamily: 'JetBrains Mono, monospace', fontSize: 9.5, color: '#9CA3AF' }}>
                        {m.t ? new Date(m.t * 1000).toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit', second: '2-digit' }) : '—'}
                      </span>
                    </div>
                    <div style={{ fontSize: 10.5, color: '#71717A', fontFamily: 'JetBrains Mono, monospace', marginLeft: 10 }}>
                      {m.reasonDetail}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
