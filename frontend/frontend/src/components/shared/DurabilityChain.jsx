import { useRef, useState, useEffect } from 'react';
import { usePipeline } from '../../context/PipelineContext';

const CHAIN_NODES = [
  { key: 'gateway',  label: 'Ingestion Gateway', kind: 'gateway' },
  { key: 'kafka',    label: 'Kafka',             kind: 'broker' },
  { key: 'redis',    label: 'Redis Buffer',       kind: 'buffer' },
  { key: 'wal',      label: 'Local WAL',         kind: 'wal' },
];

export default function DurabilityChain({ health }) {
  const svgRef = useRef(null);
  const [activePath, setActivePath] = useState(['gateway', 'kafka']);
  const [animating, setAnimating] = useState(false);
  const [rerouteKey, setRerouteKey] = useState(0);
  const prevHealthyRef = useRef(null);

  const kafkaOk   = health?.kafka_healthy ?? true;
  const redisOk  = health?.redis_healthy ?? true;

  const currentPath = kafkaOk
    ? ['gateway', 'kafka']
    : (redisOk ? ['gateway', 'redis'] : ['gateway', 'redis', 'wal']);

  // Detect health transitions to trigger reroute animation
  useEffect(() => {
    const prev = prevHealthyRef.current;
    const changed = prev && (
      (prev.kafka !== kafkaOk) || (prev.redis !== redisOk)
    );
    prevHealthyRef.current = { kafka: kafkaOk, redis: redisOk };

    if (changed) {
      setRerouteKey(k => k + 1);
      setAnimating(true);
      setActivePath(currentPath);
      const t = setTimeout(() => setAnimating(false), 1200);
      return () => clearTimeout(t);
    } else {
      setActivePath(currentPath);
    }
  }, [kafkaOk, redisOk, currentPath]);

  // Build path segments that should be drawn as flowing links
  const activeLinks = [];
  for (let i = 0; i < currentPath.length - 1; i++) {
    activeLinks.push([currentPath[i], currentPath[i + 1]]);
  }
  // Reroute link (dashed, animated) when kafka down -> redis up
  const showReroute = (!kafkaOk && redisOk) || (!kafkaOk && !redisOk);

  const nodePositions = {
    gateway: { x: 60,  y: 130 },
    kafka:   { x: 230, y: 130 },
    redis:   { x: 230, y: 250 },
    wal:     { x: 60,  y: 250 },
  };

  const nodeColor = (n) => {
    if (n.key === 'gateway') return '#8B1538';
    if (n.key === 'kafka')   return kafkaOk ? '#22C55E' : '#EF4444';
    if (n.key === 'redis')   return (!kafkaOk && redisOk) ? '#A91D42' : (redisOk ? '#22C55E' : '#EF4444');
    if (n.key === 'wal')     return (!kafkaOk && !redisOk) ? '#F5A623' : '#71717A';
    return '#71717A';
  };

  const nodeOutline = (n) => {
    if (n.key === 'gateway') return '#8B1538';
    if (n.key === 'kafka')   return kafkaOk ? '#16A34A' : '#B91C1C';
    if (n.key === 'redis')   return (!kafkaOk && redisOk) ? '#8B1538' : (redisOk ? '#16A34A' : '#B91C1C');
    if (n.key === 'wal')     return (!kafkaOk && !redisOk) ? '#B45309' : '#D4D4D8';
    return '#D4D4D8';
  };

  return (
    <div style={{ padding: '0 16px 14px' }}>
      <svg
        ref={svgRef}
        width="100%"
        viewBox="0 0 320 300"
        style={{ display: 'block', maxWidth: 320, margin: '0 auto', overflow: 'visible' }}
      >
        {/* Drop shadow under nodes */}
        <defs>
          <filter id="chain-shadow" x="-20%" y="-20%" width="140%" height="140%">
            <feDropShadow dx="0" dy="1.5" stdDeviation="2" flood-color="#71717A" flood-opacity="0.25"/>
          </filter>
          <marker id="arrow-head" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto">
            <path d="M0,0 L10,5 L0,10 Z" fill="#9CA3AF"/>
          </marker>
        </defs>

        {/* Background flow path hint (ghost) */}
        <path
          d="M 60,130 L 230,130 L 230,250 L 60,250"
          fill="none"
          stroke="#E3E6EB"
          strokeWidth="1.5"
          strokeDasharray="4 4"
          opacity="0.5"
        />

        {/* Primary active flow link (Kafka path) */}
        <path
          key={`main-${rerouteKey}`}
          d="M 60,130 L 230,130"
          fill="none"
          stroke={kafkaOk ? '#8B1538' : '#EF4444'}
          strokeWidth="2.5"
          markerEnd="url(#arrow-head)"
          opacity={kafkaOk ? 1 : 0.25}
        />

        {/* Fallback link (Redis) — animated dashed when rerouting */}
        {(showReroute) && (
          <path
            key={`fallback-${rerouteKey}`}
            d="M 230,130 L 230,250"
            fill="none"
            stroke={redisOk ? '#A91D42' : '#EF4444'}
            strokeWidth="2.5"
            strokeDasharray={animating ? '2 18' : '6 4'}
            strokeDashoffset={animating ? 0 : 0}
            markerEnd="url(#arrow-head)"
            opacity={animating ? 1 : 0.85}
            style={{
              animation: animating ? 'rerouteDash 0.9s linear infinite' : 'none',
              transition: 'stroke 0.25s, opacity 0.25s',
            }}
          />
        )}

        {/* WAL fallback link when both down */}
        {(!kafkaOk && !redisOk) && (
          <path
            d="M 230,250 L 60,250"
            fill="none"
            stroke="#F5A623"
            strokeWidth="2.5"
            strokeDasharray="6 4"
            markerEnd="url(#arrow-head)"
            opacity="0.9"
          />
        )}

        {/* Nodes */}
        {CHAIN_NODES.map(n => {
          const pos = nodePositions[n.key];
          const isOnPath = activePath.includes(n.key);
          const pulse = (n.key === 'gateway') || (n.key === 'kafka' && kafkaOk) || (n.key === 'redis' && !kafkaOk && redisOk);
          return (
            <g key={n.key} filter="url(#chain-shadow)">
              {/* Pulse ring when data flowing through */}
              {pulse && (
                <circle
                  cx={pos.x} cy={pos.y} r="22"
                  fill="none"
                  stroke={nodeColor(n)}
                  strokeWidth="1.2"
                  opacity="0.35"
                  style={{
                    animation: 'nodePulse 2.2s ease-in-out infinite',
                    transformOrigin: `${pos.x}px ${pos.y}px`,
                  }}
                />
              )}
              {/* Outer ring */}
              <circle
                cx={pos.x} cy={pos.y} r="18"
                fill={nodeColor(n)}
                fillOpacity="0.12"
                stroke={nodeOutline(n)}
                strokeWidth="1.5"
                style={{ transition: 'fill 0.25s, stroke 0.25s' }}
              />
              {/* Inner dot */}
              <circle
                cx={pos.x} cy={pos.y} r="7"
                fill={nodeColor(n)}
                opacity="0.9"
                style={{ transition: 'fill 0.25s' }}
              />
              {/* Label */}
              <text
                x={pos.x} y={pos.y + 34}
                textAnchor="middle"
                fill="#374151"
                fontSize="10.5"
                fontWeight="600"
                fontFamily="ui-monospace, 'JetBrains Mono', monospace"
                letterSpacing="0.04em"
                style={{ transition: 'fill 0.25s' }}
              >
                {n.label}
              </text>
              {/* Status micro text */}
              <text
                x={pos.x} y={pos.y + 46}
                textAnchor="middle"
                fill={nodeColor(n) === '#22C55E' ? '#16A34A' : (nodeColor(n) === '#EF4444' ? '#B91C1C' : '#9CA3AF')}
                fontSize="8.5"
                fontFamily="ui-monospace, 'JetBrains Mono', monospace"
                letterSpacing="0.06em"
                textTransform="uppercase"
                style={{ transition: 'fill 0.25s' }}
              >
                {n.key === 'kafka' ? (kafkaOk ? 'PRIMARY' : 'DOWN') : ''}
                {n.key === 'redis' ? (redisOk ? (kafkaOk ? 'STANDBY' : 'ACTIVE') : 'DOWN') : ''}
                {n.key === 'wal' ? (!kafkaOk && !redisOk ? 'FALLBACK' : 'SLEEP') : ''}
              </text>
            </g>
          );
        })}

        {/* Reroute annotation */}
        {showReroute && (
          <g>
            <text
              x="245" y="195"
              fill="#8B1538"
              fontSize="8.5"
              fontFamily="ui-monospace, 'JetBrains Mono', monospace"
              fontWeight="700"
              letterSpacing="0.08em"
              textTransform="uppercase"
              transform="rotate(90 245 195)"
              style={{ animation: animating ? 'fadeInUp 0.3s ease forwards' : 'none' }}
            >
              FALLBACK ENGAGED
            </text>
          </g>
        )}
      </svg>

      <style>{`
        @keyframes nodePulse {
          0%, 100% { opacity: 0.2; transform: scale(1); }
          50%       { opacity: 0.5; transform: scale(1.12); }
        }
        @keyframes rerouteDash {
          to { stroke-dashoffset: -20; }
        }
        @keyframes fadeInUp {
          from { opacity: 0; transform: translateY(2px); }
          to   { opacity: 1; transform: translateY(0); }
        }
      `}</style>
    </div>
  );
}
