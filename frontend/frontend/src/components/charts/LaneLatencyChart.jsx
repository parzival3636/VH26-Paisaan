import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid } from 'recharts';

const fmt = ts => {
  const d = new Date(ts * 1000);
  return `${d.getMinutes().toString().padStart(2,'0')}:${d.getSeconds().toString().padStart(2,'0')}`;
};

const TOOLTIP_STYLE = {
  background: '#FFFFFF',
  border: '1px solid #E3E6EB',
  borderRadius: 6,
  padding: '8px 10px',
  fontSize: 11,
  fontFamily: "'JetBrains Mono', monospace",
  boxShadow: '0 1px 3px 0 rgba(24,24,27,0.08)',
};

const CustomTooltip = ({ active, payload, label }) => {
  if (!active || !payload?.length) return null;
  return (
    <div style={TOOLTIP_STYLE}>
      {label && <div style={{ color: '#71717A', marginBottom: 4, fontSize: 9.5, textTransform: 'uppercase', letterSpacing: '0.05em' }}>{fmt(label)}</div>}
      {payload.map(p => (
        <div key={p.dataKey} style={{ color: p.color, fontWeight: 700 }}>
          {p.name}: {typeof p.value === 'number' ? p.value.toFixed(0) + 'ms' : p.value}
        </div>
      ))}
    </div>
  );
};

export function LaneLatencyChart({ data = [] }) {
  const mapped = data.map(d => ({
    t: d.t,
    fast:     d.fast     != null ? d.fast     : null,
    standard: d.standard != null ? d.standard : null,
    cold:     d.cold     != null ? d.cold     : null,
  }));

  return (
    <ResponsiveContainer width="100%" height={170}>
      <LineChart data={mapped} margin={{ top: 6, right: 4, left: -18, bottom: 0 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#EEF0F4" vertical={false} />
        <XAxis dataKey="t" tickFormatter={fmt} tick={{ fontSize: 9.5, fill: '#9CA3AF' }} minTickGap={24} />
        <YAxis
          tick={{ fontSize: 9.5, fill: '#9CA3AF', fontFamily: "'JetBrains Mono', monospace" }}
          domain={[0, 'auto']}
          tickFormatter={v => v + 'ms'}
        />
        <Tooltip content={<CustomTooltip />} />
        <Line
          type="monotone"
          dataKey="fast"
          name="Fast Lane"
          stroke="#8B1538"
          strokeWidth={2}
          dot={false}
          isAnimationActive={false}
          connectNulls
        />
        <Line
          type="monotone"
          dataKey="standard"
          name="Standard"
          stroke="#4C1D95"
          strokeWidth={2}
          dot={false}
          isAnimationActive={false}
          connectNulls
        />
        <Line
          type="monotone"
          dataKey="cold"
          name="Cold Lane"
          stroke="#B45309"
          strokeWidth={2}
          dot={false}
          isAnimationActive={false}
          connectNulls
        />
      </LineChart>
    </ResponsiveContainer>
  );
}

export function BuildLaneLatencyData(history, lanes) {
  // history: [{t, fast, standard, cold?}]-shaped; we only keep last 60
  return history
    ? history.slice(-60).map(h => ({
        t: h.t,
        fast: h.fast     ?? null,
        standard: h.standard ?? null,
        cold: h.cold ?? null,
      }))
    : [];
}
