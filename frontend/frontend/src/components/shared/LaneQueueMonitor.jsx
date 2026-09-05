import { usePipeline } from '../../context/PipelineContext';

export default function LaneQueueMonitor() {
  const { state } = usePipeline();
  const lanes = state.lanes || {};

  const fastStats = lanes.fast || { processed: 0, queue_size: 0, avg_latency_ms: 0 };
  const standardStats = lanes.standard || { processed: 0, queue_size: 0, avg_latency_ms: 0, batches: 0, drr_deficit: 0 };
  const coldStats = lanes.cold || { processed: 0, queue_size: 0, avg_latency_ms: 0, batches: 0, drr_deficit: 0 };

  const laneConfigs = [
    {
      id: 'fast',
      label: 'Fast Lane',
      sub: 'Immediate execution',
      color: '#8B1538',
      bg: '#FFF1F3',
      border: '#FECDD6',
      stats: fastStats,
      icon: 'bolt',
    },
    {
      id: 'standard',
      label: 'Standard Lane',
      sub: 'Micro-batch (DRR)',
      color: '#4C1D95',
      bg: '#F5F3FF',
      border: '#DDD6FE',
      stats: standardStats,
      icon: 'inventory_2',
    },
    {
      id: 'cold',
      label: 'Cold Lane',
      sub: 'Deferred (DRR)',
      color: '#B45309',
      bg: '#FFFBEB',
      border: '#FDE68A',
      stats: coldStats,
      icon: 'ac_unit',
    },
  ];

  return (
    <div className="card" style={{ padding: '16px 18px 18px' }}>
      <div style={{ marginBottom: 14 }}>
        <div style={{ fontWeight: 700, fontSize: 14, color: '#18181B', letterSpacing: '-0.01em' }}>
          Lane Queue Monitor
        </div>
        <div style={{ fontSize: 11.5, color: '#71717A', marginTop: 2, fontFamily: 'JetBrains Mono, monospace' }}>
          Real-time processing with Deficit Round Robin scheduling
        </div>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 10 }}>
        {laneConfigs.map((lane) => {
          const queuePct = Math.min((lane.stats.queue_size / 50) * 100, 100);
          const isActive = lane.stats.queue_size > 0;

          return (
            <div
              key={lane.id}
              style={{
                display: 'flex',
                flexDirection: 'column',
                padding: '12px',
                border: `1px solid ${lane.border}`,
                borderRadius: '6px',
                background: isActive ? lane.bg : '#FFFFFF',
                position: 'relative',
                overflow: 'hidden',
              }}
            >
              {/* Queue depth indicator */}
              {queuePct > 0 && (
                <div
                  style={{
                    position: 'absolute',
                    left: 0,
                    bottom: 0,
                    height: 3,
                    width: `${queuePct}%`,
                    background: lane.color,
                    opacity: 0.4,
                    transition: 'width 0.3s',
                  }}
                />
              )}

              {/* Header */}
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10 }}>
                <span className="material-symbols-outlined" style={{ fontSize: 16, color: lane.color }}>
                  {lane.icon}
                </span>
                <div style={{ flex: 1 }}>
                  <div style={{ fontSize: 12, fontWeight: 700, color: lane.color, lineHeight: 1.2 }}>
                    {lane.label}
                  </div>
                  <div style={{ fontSize: 9.5, color: '#71717A', fontFamily: 'JetBrains Mono, monospace' }}>
                    {lane.sub}
                  </div>
                </div>
              </div>

              {/* Metrics */}
              <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline' }}>
                  <span style={{ fontSize: 10, color: '#71717A', textTransform: 'uppercase', fontFamily: 'JetBrains Mono, monospace', letterSpacing: '0.05em' }}>
                    Queue
                  </span>
                  <span style={{ fontSize: 13, fontWeight: 700, fontFamily: 'JetBrains Mono, monospace', color: lane.stats.queue_size > 0 ? lane.color : '#9CA3AF' }}>
                    {lane.stats.queue_size}
                  </span>
                </div>

                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline' }}>
                  <span style={{ fontSize: 10, color: '#71717A', textTransform: 'uppercase', fontFamily: 'JetBrains Mono, monospace', letterSpacing: '0.05em' }}>
                    Processed
                  </span>
                  <span style={{ fontSize: 12, fontWeight: 600, fontFamily: 'JetBrains Mono, monospace', color: '#374151' }}>
                    {lane.stats.processed.toLocaleString()}
                  </span>
                </div>

                {lane.stats.batches !== undefined && (
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline' }}>
                    <span style={{ fontSize: 10, color: '#71717A', textTransform: 'uppercase', fontFamily: 'JetBrains Mono, monospace', letterSpacing: '0.05em' }}>
                      Batches
                    </span>
                    <span style={{ fontSize: 12, fontWeight: 600, fontFamily: 'JetBrains Mono, monospace', color: '#374151' }}>
                      {lane.stats.batches}
                    </span>
                  </div>
                )}

                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline' }}>
                  <span style={{ fontSize: 10, color: '#71717A', textTransform: 'uppercase', fontFamily: 'JetBrains Mono, monospace', letterSpacing: '0.05em' }}>
                    Latency
                  </span>
                  <span style={{ fontSize: 11.5, fontWeight: 600, fontFamily: 'JetBrains Mono, monospace', color: '#374151' }}>
                    {lane.stats.avg_latency_ms.toFixed(1)}ms
                  </span>
                </div>

                {lane.stats.drr_deficit !== undefined && (
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', paddingTop: 4, borderTop: '1px solid #EEF0F4' }}>
                    <span style={{ fontSize: 9.5, color: '#9CA3AF', textTransform: 'uppercase', fontFamily: 'JetBrains Mono, monospace', letterSpacing: '0.05em' }}>
                      DRR Deficit
                    </span>
                    <span style={{ fontSize: 11, fontWeight: 600, fontFamily: 'JetBrains Mono, monospace', color: lane.stats.drr_deficit > 0 ? '#16A34A' : '#9CA3AF' }}>
                      {lane.stats.drr_deficit}
                    </span>
                  </div>
                )}
              </div>
            </div>
          );
        })}
      </div>

      <div style={{ marginTop: 12, paddingTop: 10, borderTop: '1px solid #EEF0F4', fontSize: 10, color: '#71717A', fontFamily: 'JetBrains Mono, monospace' }}>
        <strong>DRR Scheduling:</strong> Standard quantum = 10 | Cold quantum = 3 | Fast lane bypasses DRR
      </div>
    </div>
  );
}
