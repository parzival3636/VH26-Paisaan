import './MetricCard.css';

export default function MetricCard({
  icon = 'analytics',
  iconStyle = 'iris',
  name,
  sub,
  statusLabel,
  statusStyle = 'iris',
  metrics = [],   // [{ label, value, unit }]
  bottom,
  bottomRight,
  bottomIcon,
  bottomIconColor,
  loading = false,
}) {
  if (loading) {
    return (
      <div className="metric-card">
        <div className="skeleton" style={{ height: 28, width: '60%', marginBottom: 16 }} />
        <div className="skeleton" style={{ height: 40, marginBottom: 10 }} />
        <div className="skeleton" style={{ height: 14, width: '80%' }} />
      </div>
    );
  }

  return (
    <div className="metric-card">
      {/* Top row: icon + name/sub + status badge */}
      <div className="metric-card-top">
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <div className={`metric-card-icon icon-${iconStyle}`}>
            <span className="material-symbols-outlined">{icon}</span>
          </div>
          <div>
            <div className="metric-card-name">{name}</div>
            {sub && <div className="metric-card-sub">{sub}</div>}
          </div>
        </div>
        {statusLabel && (
          <div className={`metric-card-status ms-${statusStyle}`}>
            <span className="sd" />
            {statusLabel}
          </div>
        )}
      </div>

      {/* Big metric digits */}
      {metrics.length > 0 && (
        <div className="metric-digits">
          {metrics.map((m, i) => (
            <div key={i}>
              <div className="metric-digit-label">{m.label}</div>
              <div className="metric-digit-value">
                {m.value ?? '—'}
                {m.unit && <span className="metric-digit-unit">{m.unit}</span>}
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Bottom micro row */}
      {(bottom || bottomRight) && (
        <div className="metric-bottom">
          <span className="metric-bottom-icon">
            {bottomIcon && (
              <span className="material-symbols-outlined" style={{ color: bottomIconColor }}>{bottomIcon}</span>
            )}
            {bottom}
          </span>
          <span>{bottomRight}</span>
        </div>
      )}
    </div>
  );
}
