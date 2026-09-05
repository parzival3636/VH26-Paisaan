import { useState, useRef } from 'react';
import { API_BASE } from '../context/PipelineContext';

const BUTTONS = [
  {
    id: 'kill-kafka',
    label: 'Kill Kafka',
    sub: 'Take down the primary broker',
    icon: 'shock',
    color: '#EF4444',
    bg: '#FEE2E2',
    border: '#FCA5A5',
    variant: 'danger',
  },
  {
    id: 'kill-redis',
    label: 'Kill Redis',
    sub: 'Drop the emergency buffer',
    icon: 'block',
    color: '#EF4444',
    bg: '#FEE2E2',
    border: '#FCA5A5',
    variant: 'danger',
  },
  {
    id: 'kill-both',
    label: 'Kill Both',
    sub: 'Fallback chain fully engaged',
    icon: 'error',
    color: '#EF4444',
    bg: '#FEE2E2',
    border: '#FCA5A5',
    variant: 'danger',
  },
  {
    id: 'restore-all',
    label: 'Restore All',
    sub: 'Bring Kafka + Redis back up',
    icon: 'local_fire_department',
    color: '#22C55E',
    bg: '#F0FDF4',
    border: '#BBF7D0',
    variant: 'success',
  },
  {
    id: 'inject-payment',
    label: 'Inject ₹5,00,000 payment',
    sub: 'High-value P0 event',
    icon: 'payments',
    color: '#F5A623',
    bg: '#FCD9A1',
    border: '#F5C882',
    variant: 'amber',
  },
  {
    id: 'flood-fast-lane',
    label: 'Flood fast lane',
    sub: 'Overwhelm execute threshold',
    icon: 'trending_up',
    color: '#8B1538',
    bg: '#FFF1F3',
    border: '#FECDD6',
    variant: 'iris',
  },
];

const CHAOS_ENDPOINTS = {
  'kill-kafka':    { method: 'POST', path: '/chaos/kill-kafka' },
  'kill-redis':    { method: 'POST', path: '/chaos/kill-redis' },
  'kill-both':     { method: 'POST', path: '/chaos/kill-both' },
  'restore-all':   { method: 'POST', path: '/chaos/restore' },
  'inject-payment':{ method: 'POST', path: '/chaos/inject-payment' },
  'flood-fast-lane':{ method: 'POST', path: '/chaos/flood-fast' },
};

export default function ChaosControlPanel() {
  const [activeId, setActiveId] = useState(null);
  const [cooldown, setCooldown] = useState(null);
  const [feedback, setFeedback] = useState(null);
  const timerRef = useRef(null);

  const showFeedback = (msg, variant = 'info') => {
    if (timerRef.current) clearTimeout(timerRef.current);
    setFeedback({ msg, variant });
    timerRef.current = setTimeout(() => setFeedback(null), 3200);
  };

  const fire = async (id) => {
    if (cooldown) return;
    setActiveId(id);
    setCooldown(1400);

    const cfg = CHAOS_ENDPOINTS[id];
    try {
      const res = await fetch(`${API_BASE}${cfg.path}`, { method: cfg.method });
      if (!res.ok) throw new Error('endpoint unavailable');
      showFeedback(`Chaos injected: ${BUTTONS.find(b => b.id === id).label}`, cfg.variant);
    } catch {
      // Endpoint may not exist yet — simulate for demo feel
      showFeedback(`Chaos injected (demo): ${BUTTONS.find(b => b.id === id).label}`, cfg.variant);
    }

    setTimeout(() => {
      setActiveId(null);
      setCooldown(null);
    }, 1400);
  };

  return (
    <div className="card" style={{ padding: '18px 20px 20px' }}>
      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', marginBottom: 14 }}>
        <div>
          <div style={{ fontWeight: 700, fontSize: 14, color: '#18181B', letterSpacing: '-0.01em' }}>
            Chaos Control Panel
          </div>
          <div style={{ fontSize: 11.5, color: '#71717A', marginTop: 2, fontFamily: 'JetBrains Mono, monospace' }}>
            Live demo — trigger failure conditions and watch the system respond
          </div>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 2 }}>
          <span className="material-symbols-outlined" style={{ fontSize: 16, color: activeId ? '#EF4444' : '#71717A' }}>
            {activeId ? 'error' : 'settings'}
          </span>
        </div>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 10 }}>
        {BUTTONS.map(b => {
          const isActive = activeId === b.id;
          const isCooldown = !!cooldown && activeId === b.id;
          return (
            <button
              key={b.id}
              disabled={isCooldown}
              onClick={() => fire(b.id)}
              style={{
                display: 'flex',
                flexDirection: 'column',
                alignItems: 'flex-start',
                gap: 4,
                padding: '12px 12px 10px',
                border: `1px solid ${isCooldown ? '#E3E6EB' : b.border}`,
                borderRadius: '6px',
                background: isCooldown ? '#F5F6F8' : (isActive ? b.bg : '#FFFFFF'),
                color: isCooldown ? '#9CA3AF' : (isActive ? b.color : '#18181B'),
                fontWeight: 700,
                fontSize: 12.5,
                fontFamily: "'JetBrains Mono', monospace",
                letterSpacing: '-0.01em',
                boxShadow: isCooldown ? 'none' : '0 1px 2px 0 rgba(24,24,27,0.04)',
                transition: 'background 0.12s, color 0.12s, border-color 0.12s, transform 0.08s',
                transform: isActive ? 'translateY(-1px)' : 'none',
                position: 'relative',
              }}
            >
              {isActive && (
                <span
                  style={{
                    position: 'absolute',
                    inset: 0,
                    borderRadius: 6,
                    background: b.color,
                    opacity: 0.08,
                    pointerEvents: 'none',
                  }}
                />
              )}
              <span className="material-symbols-outlined" style={{ fontSize: isActive ? 16 : 14, color: isActive ? b.color : '#71717A' }}>
                {b.icon}
              </span>
              <span style={{ color: isActive ? b.color : '#18181B', lineHeight: 1.2, fontWeight: 700 }}>
                {b.label}
              </span>
              <span style={{ fontSize: 10, color: isActive ? b.color : '#71717A', fontFamily: "'JetBrains Mono', monospace" }}>
                {b.sub}
              </span>
            </button>
          );
        })}
      </div>

      {feedback && (
        <div style={{ marginTop: 12, padding: '8px 12px', borderRadius: 5, fontFamily: "'JetBrains Mono', monospace", fontSize: 11.5, fontWeight: 600, display: 'flex', alignItems: 'center', gap: 6 }}>
          <span className="material-symbols-outlined" style={{ fontSize: 14, color: feedback.variant === 'danger' ? '#EF4444' : feedback.variant === 'success' ? '#22C55E' : feedback.variant === 'amber' ? '#F5A623' : '#8B1538' }}>
            {feedback.variant === 'danger' ? 'error' : feedback.variant === 'success' ? 'check_circle' : feedback.variant === 'amber' ? 'warning' : 'info'}
          </span>
          {feedback.msg}
        </div>
      )}
    </div>
  );
}
