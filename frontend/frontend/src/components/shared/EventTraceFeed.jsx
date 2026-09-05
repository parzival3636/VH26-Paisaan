import { useState, useEffect, useRef } from 'react';
import { usePipeline } from '../../context/PipelineContext';
import StatusBadge from './StatusBadge';

const LANE_COLOR = {
  execute:      '#8B1538',
  batch:        '#4C1D95',
  defer:        '#B45309',
  shed:         '#881337',
  backpressure: '#881337',
};
const ACTION_LABEL = {
  execute:      'Fast Lane',
  batch:        'Standard',
  defer:        'Cold Lane',
  shed:         'Rejected',
  backpressure: 'Backpressure',
};
const TYPE_SHORT = {
  order:     'ORD',
  payment:   'PAY',
  inventory: 'INV',
  click:     'CLK',
  log:       'LOG',
  other:     'OTH',
};

export default function EventTraceFeed() {
  const { state } = usePipeline();
  const listRef = useRef(null);
  const [expandedId, setExpandedId] = useState(null);
  const lastCountRef = useRef(0);

  const events = state.recent_events || [];

  // Auto-scroll when new events arrive and user is near bottom
  useEffect(() => {
    if (!listRef.current) return;
    const el = listRef.current;
    const prevCount = lastCountRef.current;
    const newCount = events.length - prevCount;
    lastCountRef.current = events.length;
    if (newCount <= 0) return;
    const nearBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 420;
    if (nearBottom) {
      el.scrollTop = el.scrollHeight;
    }
  }, [events.length]);

  const latest = events[events.length - 1];
  const bandColor = (ev) => LANE_COLOR[ev.action] || '#71717A';
  const ev = expandedId ? events.find(e => e.event_id === expandedId) : null;
  const components = ev ? (ev.components || {}) : {};
  const compKeys = Object.keys(components).sort();

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12, padding: '0 4px' }}>
      {/* Feed header */}
      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 12 }}>
        <div>
          <div style={{ fontWeight: 700, fontSize: 14, color: '#18181B', letterSpacing: '-0.01em' }}>
            Live Event Trace Feed
          </div>
          <div style={{ fontSize: 11.5, color: '#71717A', marginTop: 2, fontFamily: 'JetBrains Mono, monospace' }}>
            {events.length.toLocaleString()} events scored · {latest ? `last ${latest.event_id}` : 'awaiting stream'}
          </div>
        </div>
        <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
          <span className="material-symbols-outlined" style={{ fontSize: 15, color: '#8B1538' }}>live_sync</span>
          <span style={{ fontFamily: 'JetBrains Mono, monospace', fontSize: 11, color: '#8B1538', fontWeight: 600 }}>
            LIVE
          </span>
          {state.baseline_mode && (
            <span className="sbadge sbadge-ochre sbadge-sm">
              <span className="sbadge-dot" />FIFO
            </span>
          )}
        </div>
      </div>

      {/* Trace list */}
      <div
        ref={listRef}
        style={{
          background: '#FFFFFF',
          border: '1px solid #E3E6EB',
          borderRadius: '8px',
          boxShadow: '0 1px 3px 0 rgba(24,24,27,0.04), 0 1px 2px -1px rgba(24,24,27,0.03)',
          overflow: 'hidden',
          maxHeight: 380,
          display: 'flex',
          flexDirection: 'column',
        }}
      >
        {events.length === 0 ? (
          <div style={{ padding: 28, textAlign: 'center', color: '#71717A', fontSize: 12.5 }}>
            <span className="material-symbols-outlined" style={{ fontSize: 28, color: '#E3E6EB', display: 'block', marginBottom: 8 }}>
              monitor_play
            </span>
            Waiting for traffic — trigger a load preset to begin
          </div>
        ) : (
          <ul style={{ listStyle: 'none', margin: 0, padding: 0, overflowY: 'auto', flex: 1 }}>
            {events.slice(-50).map(ev => {
              const color = bandColor(ev);
              const isExpanded = expandedId === ev.event_id;
              return (
                <li
                  key={ev.event_id}
                  style={{
                    borderBottom: '1px solid #EEF0F4',
                    cursor: 'pointer',
                    transition: 'background 0.1s',
                  }}
                  onMouseEnter={e => e.currentTarget.style.background = '#F8FAFC'}
                  onMouseLeave={e => e.currentTarget.style.background = 'transparent'}
                  onClick={() => setExpandedId(isExpanded ? null : ev.event_id)}
                >
                  <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '9px 14px' }}>
                    {/* Score badge */}
                    <div
                      style={{
                        width: 46,
                        height: 28,
                        borderRadius: 5,
                        background: `${color}1A`,
                        border: `1px solid ${color}4D`,
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                        flexShrink: 0,
                      }}
                    >
                      <span style={{ fontFamily: 'JetBrains Mono, monospace', fontSize: 12.5, fontWeight: 700, color, letterSpacing: '-0.02em' }}>
                        {ev.final_score != null ? ev.final_score.toFixed(2) : '—'}
                      </span>
                    </div>

                    {/* ID + type */}
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8, flex: 1, minWidth: 0 }}>
                      <span style={{ fontFamily: 'JetBrains Mono, monospace', fontSize: 11, color: '#374151', fontWeight: 600, letterSpacing: '0.02em' }}>
                        {ev.event_id}
                      </span>
                      <span
                        style={{
                          display: 'inline-flex',
                          padding: '1px 5px',
                          borderRadius: 3,
                          fontSize: 9.5,
                          fontWeight: 700,
                          fontFamily: 'JetBrains Mono, monospace',
                          color: '#8B1538',
                          background: '#FFF1F3',
                          letterSpacing: '0.04em',
                        }}
                      >
                        {TYPE_SHORT[ev.type] || 'OTH'}
                      </span>
                    </div>

                    {/* Lane pill */}
                    <StatusBadge
                      status={ev.action === 'execute' ? 'active' : ev.action === 'batch' ? 'standby' : 'degraded'}
                      label={ACTION_LABEL[ev.action] || ev.action}
                      size="sm"
                    />

                    {/* Expand chevron */}
                    <span className="material-symbols-outlined" style={{ fontSize: 14, color: '#9CA3AF', flexShrink: 0 }}>
                      {isExpanded ? 'expand_less' : 'expand_more'}
                    </span>
                  </div>

                  {/* Expanded score X-ray */}
                  {isExpanded && (
                    <div style={{ padding: '0 14px 12px 70px', borderLeft: '2px solid #E3E6EB', marginLeft: 14, paddingLeft: 14 }}>
                      <div style={{ fontSize: 10, fontWeight: 700, color: '#71717A', textTransform: 'uppercase', letterSpacing: '0.08em', fontFamily: 'JetBrains Mono, monospace', marginBottom: 8 }}>
                        SCORE X-RAY · {ev.event_id}
                      </div>
                      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '6px 12px' }}>
                        <div style={{ fontSize: 10.5, color: '#71717A', textTransform: 'uppercase', letterSpacing: '0.05em', fontFamily: 'JetBrains Mono, monospace' }}>Intrinsic</div>
                        <div style={{ fontSize: 10.5, color: '#71717A', textTransform: 'uppercase', letterSpacing: '0.05em', fontFamily: 'JetBrains Mono, monospace' }}>Final Score</div>
                        <div style={{ fontSize: 10.5, color: '#71717A', textTransform: 'uppercase', letterSpacing: '0.05em', fontFamily: 'JetBrains Mono, monospace' }}>Ingest Latency</div>

                        <div style={{ fontFamily: 'JetBrains Mono, monospace', fontSize: 12.5, fontWeight: 700, color: '#8B1538' }}>
                          {(ev.intrinsic ?? '—') && Number(ev.intrinsic).toFixed(2)}
                        </div>
                        <div style={{ fontFamily: 'JetBrains Mono, monospace', fontSize: 12.5, fontWeight: 700, color: '#18181B' }}>
                          {ev.final_score != null ? ev.final_score.toFixed(2) : '—'}
                        </div>
                        <div style={{ fontFamily: 'JetBrains Mono, monospace', fontSize: 12.5, color: '#374151' }}>
                          {ev.latency_ms != null ? `${ev.latency_ms.toFixed(1)}ms` : '—'}
                        </div>
                      </div>

                      {compKeys.length > 0 && (
                        <div style={{ marginTop: 10, paddingTop: 10, borderTop: '1px solid #EEF0F4' }}>
                          <div style={{ fontSize: 10, fontWeight: 700, color: '#71717A', textTransform: 'uppercase', letterSpacing: '0.08em', fontFamily: 'JetBrains Mono, monospace', marginBottom: 6 }}>
                            Component Breakdown
                          </div>
                          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '4px 12px' }}>
                            {compKeys.map(k => (
                              <div key={k} style={{ display: 'flex', gap: 6, alignItems: 'baseline' }}>
                                <span style={{ fontSize: 9.5, color: '#9CA3AF', fontFamily: 'JetBrains Mono, monospace', textTransform: 'uppercase', letterSpacing: '0.05em', flexShrink: 0 }}>
                                  {k.slice(0, 4)}
                                </span>
                                <span style={{ fontFamily: 'JetBrains Mono, monospace', fontSize: 10.5, fontWeight: 600, color: Number(components[k]) >= 0 ? '#16A34A' : '#B91C1C' }}>
                                  {Number(components[k]).toFixed(3)}
                                </span>
                              </div>
                            ))}
                          </div>
                        </div>
                      )}

                      {ev.payload ? (
                        <div style={{ marginTop: 10, paddingTop: 8, borderTop: '1px solid #EEF0F4' }}>
                          <div style={{ fontSize: 10, fontWeight: 700, color: '#71717A', textTransform: 'uppercase', letterSpacing: '0.08em', fontFamily: 'JetBrains Mono, monospace', marginBottom: 4 }}>
                            Payload
                          </div>
                          <div style={{ background: '#F8FAFC', border: '1px solid #E3E6EB', borderRadius: 5, padding: '6px 8px', fontFamily: 'JetBrains Mono, monospace', fontSize: 10, color: '#374151', overflow: 'auto', maxHeight: 80 }}>
                            {JSON.stringify(ev.payload, null, 0)}
                          </div>
                        </div>
                      ) : null}
                    </div>
                  )}
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </div>
  );
}
