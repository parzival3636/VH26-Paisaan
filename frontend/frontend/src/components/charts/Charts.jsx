import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid, ReferenceLine } from 'recharts';

const fmt = (ts) => {
  const d = new Date(ts * 1000);
  return `${d.getMinutes().toString().padStart(2,'0')}:${d.getSeconds().toString().padStart(2,'0')}`;
};

const CustomTooltip = ({ active, payload, label }) => {
  if (!active || !payload?.length) return null;
  return (
    <div style={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 6, padding: '8px 12px', fontSize: 12, fontFamily: 'var(--font-mono)' }}>
      {label && <div style={{ color: 'var(--text-muted)', marginBottom: 4, fontSize: 10 }}>{fmt(label)}</div>}
      {payload.map(p => (
        <div key={p.dataKey} style={{ color: p.color, fontWeight: 700 }}>
          {p.name}: {typeof p.value === 'number' ? p.value.toFixed(2) : p.value}
        </div>
      ))}
    </div>
  );
};

export function ThroughputChart({ data = [] }) {
  return (
    <ResponsiveContainer width="100%" height={180}>
      <LineChart data={data} margin={{ top: 4, right: 4, left: -20, bottom: 0 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#E3E6EB" />
        <XAxis dataKey="t" tickFormatter={fmt} tick={{ fontSize: 10, fill: '#71717A' }} minTickGap={20} />
        <YAxis tick={{ fontSize: 10, fill: '#71717A' }} />
        <Tooltip content={<CustomTooltip />} />
        <Line type="monotone" dataKey="eps" name="Events/s" stroke="#8B1538" dot={false} strokeWidth={2} isAnimationActive={false} />
      </LineChart>
    </ResponsiveContainer>
  );
}

export function ActionsChart({ data = [] }) {
  return (
    <ResponsiveContainer width="100%" height={180}>
      <LineChart data={data} margin={{ top: 4, right: 4, left: -20, bottom: 0 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#E3E6EB" />
        <XAxis dataKey="t" tickFormatter={fmt} tick={{ fontSize: 10, fill: '#71717A' }} minTickGap={20} />
        <YAxis tick={{ fontSize: 10, fill: '#71717A' }} />
        <Tooltip content={<CustomTooltip />} />
        <Line type="monotone" dataKey="execute" name="Execute (Fast)"   stroke="#8B1538" dot={false} strokeWidth={2} isAnimationActive={false} />
        <Line type="monotone" dataKey="batch"   name="Batch (Standard)" stroke="#4C1D95" dot={false} strokeWidth={2} isAnimationActive={false} />
        <Line type="monotone" dataKey="defer"   name="Defer (Cold)"     stroke="#B45309" dot={false} strokeWidth={2} isAnimationActive={false} />
      </LineChart>
    </ResponsiveContainer>
  );
}

export function ThresholdLineChart({ data = [], annotations = [] }) {
  // annotations: [{ t, label, reason, color }]
  const markStyle = {
    position: 'absolute',
    transform: 'translateX(-50%)',
    fontSize: 9.5,
    fontFamily: "'JetBrains Mono', monospace",
    fontWeight: 700,
    letterSpacing: '0.04em',
    textTransform: 'uppercase',
    padding: '2px 6px',
    borderRadius: 3,
    border: '1px solid',
    whiteSpace: 'nowrap',
  };

  return (
    <ResponsiveContainer width="100%" height={220}>
      <LineChart data={data} margin={{ top: 4, right: 4, left: -20, bottom: 0 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#E3E6EB" />
        <XAxis dataKey="t" tickFormatter={fmt} tick={{ fontSize: 10, fill: '#71717A' }} minTickGap={20} />
        <YAxis tick={{ fontSize: 10, fill: '#71717A' }} domain={[0, 12]} />
        <Tooltip content={<CustomTooltip />} />
        <Line type="monotone" dataKey="execute" name="Execute" stroke="#8B1538" dot={false} strokeWidth={2} isAnimationActive={false} />
        <Line type="monotone" dataKey="batch"   name="Batch"   stroke="#4C1D95" dot={false} strokeWidth={2} isAnimationActive={false} />
        <Line type="monotone" dataKey="defer"   name="Defer"   stroke="#B45309" dot={false} strokeWidth={2} isAnimationActive={false} />
        {annotations.map((a, i) => (
          <ReferenceLine key={i} x={a.t} label={{ value: '', position: 'top', fill: a.color, fontSize: 10, fontWeight: 700 }} stroke={a.color} strokeDasharray="3 3" />
        ))}
      </LineChart>
    </ResponsiveContainer>
  );
}
