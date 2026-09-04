import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell, ReferenceLine } from 'recharts';
import { usePipeline } from '../../context/PipelineContext';
import './ROIPanel.css';

const ROI_DATA_ADAPTIVE = [
  { name: 'Adaptive', cost: 0.22, label: '$0.22/hr' },
  { name: 'Naive FIFO', cost: 1.00, label: '$1.00/hr' },
];

function CostTooltip({ active, payload }) {
  if (!active || !payload?.length) return null;
  return (
    <div style={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 6, padding: '8px 12px', fontSize: 12 }}>
      <div style={{ fontWeight: 700 }}>{payload[0].payload.name}</div>
      <div style={{ color: payload[0].payload.name === 'Adaptive' ? 'var(--green)' : 'var(--bordeaux)', fontFamily: 'var(--font-mono)', fontSize: 14, fontWeight: 800 }}>
        {payload[0].payload.label}
      </div>
    </div>
  );
}

export default function ROIPanel() {
  const { state } = usePipeline();
  const isAdaptive = !state.baseline_mode;
  const pid = state.pid || {};

  // Worker count derived from scaler state (approximated from queue depth)
  const eps = state.events_per_second || 0;
  const workerCount = Math.max(2, Math.min(10, Math.ceil(eps / 3)));
  const workerPct = (workerCount / 10) * 100;

  const savings = Math.round((1 - 0.22) * 100);

  return (
    <div className="roi-panel card">
      <div className="card-header">
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <div className="roi-header-icon">
            <span className="material-symbols-outlined">trending_up</span>
          </div>
          <div>
            <div className="card-title">Executive ROI Dashboard</div>
            <div className="card-sub">Cloud cost savings vs naive infrastructure</div>
          </div>
        </div>
        {isAdaptive && (
          <div className="roi-savings-badge">
            <span className="material-symbols-outlined" style={{ fontSize: 14 }}>savings</span>
            {savings}% Cloud Cost Savings
          </div>
        )}
      </div>

      <div className="roi-body">
        {/* Cost bar chart */}
        <div className="roi-chart-section">
          <div className="roi-section-label">Cloud Infrastructure Cost / Hour</div>
          <ResponsiveContainer width="100%" height={110}>
            <BarChart data={ROI_DATA_ADAPTIVE} layout="vertical" margin={{ top: 4, right: 24, bottom: 0, left: 8 }}>
              <XAxis type="number" domain={[0, 1.2]} tick={{ fontSize: 10, fill: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }} tickFormatter={v => `$${v}`} />
              <YAxis type="category" dataKey="name" tick={{ fontSize: 11, fill: 'var(--text-secondary)' }} width={72} />
              <Tooltip content={<CostTooltip />} />
              <ReferenceLine x={0.22} stroke="var(--iris)" strokeDasharray="3 3" />
              <Bar dataKey="cost" radius={[0, 4, 4, 0]} barSize={22}>
                <Cell key="adaptive" fill={isAdaptive ? '#4F46E5' : '#C7D2FE'} />
                <Cell key="fifo" fill={!isAdaptive ? '#881337' : '#FECDD3'} />
              </Bar>
            </BarChart>
          </ResponsiveContainer>
          <div className="roi-cost-labels">
            <span className="roi-cost-active">
              {isAdaptive ? '✦ Active: ' : ''}
              <strong style={{ color: 'var(--iris)' }}>$0.22/hr</strong> Adaptive
            </span>
            <span className="roi-cost-baseline">
              {!isAdaptive ? '✦ Active: ' : ''}
              <strong style={{ color: 'var(--bordeaux)' }}>$1.00/hr</strong> FIFO
            </span>
          </div>
        </div>

        <div className="roi-divider" />

        {/* Worker auto-scaler */}
        <div className="roi-scaler-section">
          <div className="roi-section-label">
            Worker Auto-Scaler
            <span className="roi-scaler-badge">{workerCount} / 10 Active</span>
          </div>
          <div className="roi-worker-dots">
            {Array.from({ length: 10 }).map((_, i) => (
              <div
                key={i}
                className={`roi-worker-dot ${i < workerCount ? 'active' : ''}`}
                style={i < workerCount ? { animationDelay: `${i * 0.07}s` } : {}}
              />
            ))}
          </div>
          <div className="roi-worker-bar-track">
            <div
              className="roi-worker-bar-fill"
              style={{ width: `${workerPct}%` }}
            />
          </div>
          <div className="roi-scaler-meta">
            <span>Min: 2</span>
            <span style={{ fontFamily: 'var(--font-mono)', color: 'var(--iris)', fontWeight: 700 }}>
              {workerCount} online
            </span>
            <span>Max: 10</span>
          </div>
        </div>

        <div className="roi-divider" />

        {/* PID stats */}
        <div className="roi-pid-section">
          <div className="roi-section-label">PID Controller Live</div>
          <div className="roi-pid-grid">
            <div className="roi-pid-item">
              <span>Execute Threshold</span>
              <b style={{ color: 'var(--iris)' }}>{pid.current_execute_threshold?.toFixed(3) ?? '6.000'}</b>
            </div>
            <div className="roi-pid-item">
              <span>P0 Latency</span>
              <b>{pid.p0_latency?.toFixed(1) ?? '—'}ms</b>
            </div>
            <div className="roi-pid-item">
              <span>PID Error</span>
              <b style={{ color: (pid.error || 0) > 0 ? 'var(--bordeaux)' : 'var(--green)' }}>
                {pid.error?.toFixed(3) ?? '—'}
              </b>
            </div>
            <div className="roi-pid-item">
              <span>Mode</span>
              <b style={{ color: isAdaptive ? 'var(--iris)' : 'var(--ochre)' }}>
                {isAdaptive ? 'Adaptive' : 'FIFO'}
              </b>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
