import './LaneBar.css';

const LANE_CONFIG = {
  fast:     { label: 'Fast Lane',     color: 'var(--iris)',    capacity: 64   },
  standard: { label: 'Standard Lane', color: 'var(--cassis)',  capacity: 1000 },
  cold:     { label: 'Cold Lane',     color: 'var(--ochre)',   capacity: 5000 },
};

export default function LaneBar({ lane = 'fast', depth = 0, inRate = 0, outRate = 0, lag = 0 }) {
  const cfg = LANE_CONFIG[lane] || LANE_CONFIG.fast;
  const pct = Math.min((depth / cfg.capacity) * 100, 100);
  const over = depth > cfg.capacity;

  return (
    <div className="lane-bar-row">
      <div className="lane-bar-meta">
        <span className="lane-bar-name">{cfg.label}</span>
        <span className={`lane-bar-count ${over ? 'over' : ''}`}>
          {depth.toLocaleString()} / {cfg.capacity.toLocaleString()}
        </span>
      </div>
      <div className="lane-bar-track">
        <div className="lane-bar-fill" style={{ width: `${pct}%`, background: over ? 'var(--bordeaux)' : cfg.color }} />
      </div>
      <div className="lane-bar-stats">
        <span>In: <b>{inRate}/s</b></span>
        <span>Out: <b>{outRate}/s</b></span>
        <span>Lag: <b>{lag}ms</b></span>
      </div>
    </div>
  );
}
