import { useEffect, useRef, useState } from 'react';
import { usePipeline } from '../../context/PipelineContext';
import './LaneVisualizer.css';

const LANE_CONFIG = {
  execute: {
    key: 'execute',
    label: 'Fast Lane',
    sublabel: 'EXECUTE · <20ms',
    icon: 'bolt',
    color: '#4F46E5',
    bg: 'var(--iris-light)',
    border: 'var(--iris-border)',
    iconBg: 'var(--iris)',
  },
  batch: {
    key: 'batch',
    label: 'Micro-Batch Lane',
    sublabel: 'BATCH · ~500ms windows',
    icon: 'inventory_2',
    color: '#4C1D95',
    bg: 'var(--cassis-subtle)',
    border: 'var(--cassis-border)',
    iconBg: 'var(--cassis)',
  },
  defer: {
    key: 'defer',
    label: 'Cold Storage Lane',
    sublabel: 'DEFER · low priority',
    icon: 'schedule',
    color: '#B45309',
    bg: 'var(--ochre-soft)',
    border: 'var(--ochre-border)',
    iconBg: 'var(--ochre)',
  },
  shed: {
    key: 'shed',
    label: 'Backpressure / Dedup',
    sublabel: 'REJECTED · race prevention',
    icon: 'block',
    color: '#881337',
    bg: 'var(--bordeaux-tint)',
    border: 'var(--bordeaux-border)',
    iconBg: 'var(--bordeaux)',
  },
};

const TYPE_LABELS = {
  order: 'ORD', payment: 'PAY', inventory: 'INV', click: 'CLK', log: 'LOG', other: 'OTH',
};

let _globalId = 0;

export default function LaneVisualizer() {
  const { state } = usePipeline();
  const [laneQueues, setLaneQueues] = useState({ execute: [], batch: [], defer: [], shed: [] });
  const lastEventIdRef = useRef(null);
  const prevEventsRef = useRef([]);

  // Detect new events from WS state and add animated pills
  useEffect(() => {
    const incoming = state.recent_events;
    if (!incoming?.length) return;

    // Find events that weren't in the previous snapshot
    const prevIds = new Set(prevEventsRef.current.map(e => e.event_id));
    const newEvents = incoming.filter(e => !prevIds.has(e.event_id));
    prevEventsRef.current = incoming;

    if (!newEvents.length) return;

    setLaneQueues(prev => {
      const next = { ...prev };
      newEvents.forEach(ev => {
        const lane = (ev.action === 'shed' || ev.action === 'backpressure')
          ? 'shed'
          : (ev.action || 'defer');
        if (!next[lane]) return;

        const pill = {
          id: ++_globalId,
          type: ev.type || 'other',
          score: ev.final_score,
          eventId: ev.event_id,
        };

        // Cap lane queue at 8 visible pills
        next[lane] = [pill, ...next[lane]].slice(0, 8);
      });
      return next;
    });
  }, [state.recent_events]);

  // Auto-expire pills after 4 seconds
  useEffect(() => {
    const id = setInterval(() => {
      setLaneQueues(prev => {
        const next = {};
        let changed = false;
        Object.keys(prev).forEach(lane => {
          if (prev[lane].length > 0) {
            next[lane] = prev[lane].slice(0, Math.max(0, prev[lane].length - 1));
            changed = true;
          } else {
            next[lane] = prev[lane];
          }
        });
        return changed ? next : prev;
      });
    }, 800);
    return () => clearInterval(id);
  }, []);

  const counts = state.actions || {};
  const backpressureCount = (counts.shed || 0) + (counts.backpressure || 0);

  return (
    <div className="card lv-card">
      <div className="card-header">
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <div className="lv-header-icon">
            <span className="material-symbols-outlined">account_tree</span>
          </div>
          <div>
            <div className="card-title">Live 4-Lane Event Router</div>
            <div className="card-sub">Real-time event stream routed by urgency score</div>
          </div>
        </div>
        <div className="lv-legend">
          <span className="lv-legend-item iris">● Execute</span>
          <span className="lv-legend-item cassis">● Batch</span>
          <span className="lv-legend-item ochre">● Defer</span>
          <span className="lv-legend-item bd">● Rejected</span>
        </div>
      </div>

      <div className="lv-lanes">
        {Object.values(LANE_CONFIG).map(cfg => {
          const rawCount = cfg.key === 'shed'
            ? backpressureCount
            : (counts[cfg.key] || 0);
          const pills = laneQueues[cfg.key] || [];

          return (
            <div
              key={cfg.key}
              className="lv-lane"
              style={{ background: cfg.bg, borderColor: cfg.border }}
            >
              {/* Lane header */}
              <div className="lv-lane-head">
                <div className="lv-lane-icon" style={{ background: cfg.iconBg }}>
                  <span className="material-symbols-outlined">{cfg.icon}</span>
                </div>
                <div>
                  <div className="lv-lane-name">{cfg.label}</div>
                  <div className="lv-lane-sub">{cfg.sublabel}</div>
                </div>
                <div className="lv-lane-count" style={{ color: cfg.color }}>
                  {rawCount.toLocaleString()}
                </div>
              </div>

              {/* Pill stream */}
              <div className="lv-pill-stream">
                {pills.map(pill => (
                  <div
                    key={pill.id}
                    className="lv-pill"
                    style={{ background: cfg.color, opacity: 1 }}
                  >
                    <span className="lv-pill-type">{TYPE_LABELS[pill.type] || 'OTH'}</span>
                    {pill.score != null && (
                      <span className="lv-pill-score">{Number(pill.score).toFixed(1)}</span>
                    )}
                  </div>
                ))}
                {pills.length === 0 && (
                  <div className="lv-empty-pills">
                    <span className="material-symbols-outlined" style={{ fontSize: 16, color: cfg.color, opacity: 0.3 }}>
                      {rawCount > 0 ? 'check_circle' : 'hourglass_empty'}
                    </span>
                    <span style={{ fontSize: 11, color: cfg.color, opacity: 0.5 }}>
                      {rawCount > 0 ? `${rawCount.toLocaleString()} total` : 'idle'}
                    </span>
                  </div>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
