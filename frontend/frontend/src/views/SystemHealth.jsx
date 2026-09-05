import { useState, useEffect } from 'react';
import { API_BASE } from '../context/PipelineContext';
import { usePipeline } from '../context/PipelineContext';
import StatusBadge from '../components/shared/StatusBadge';
import './SystemHealth.css';

export default function SystemHealth() {
  const { state } = usePipeline();
  const [health, setHealth] = useState(null);
  const [loading, setLoading] = useState(true);

  const fetchHealth = async () => {
    try {
      const res = await fetch(`${API_BASE}/health`);
      const data = await res.json();
      setHealth(data);
    } catch {}
    finally { setLoading(false); }
  };

  useEffect(() => {
    fetchHealth();
    const id = setInterval(fetchHealth, 5000);
    return () => clearInterval(id);
  }, []);

  const durabilityMode = health?.durability_mode || state.durability_mode || 'unknown';

  const components = [
    {
      key: 'kafka',
      label: 'Kafka',
      status: 'healthy',
      stat: 'raw-events / fast-lane / standard-lane / cold-lane',
      statLabel: 'Topics',
    },
    {
      key: 'redis',
      label: 'Redis',
      status: health?.redis_healthy ? 'healthy' : 'down',
      stat: 'Fast-lane speed layer + emergency buffer',
      statLabel: 'Role',
    },
    {
      key: 'wal',
      label: 'WAL File',
      status: health?.wal_healthy ? 'healthy' : 'unknown',
      stat: 'local_wal.jsonl',
      statLabel: 'File',
    },
    {
      key: 'reconciler',
      label: 'Reconciler',
      status: 'healthy',
      stat: 'Replays emergency_buffer + WAL → Kafka on recovery',
      statLabel: 'Role',
    },
  ];

  const CHAIN = [
    { label: 'Ingestion Gateway', key: 'gateway', active: true },
    { label: 'Kafka raw-events',  key: 'kafka',   active: health?.kafka_healthy },
    { label: 'Redis Buffer',      key: 'redis',    active: !health?.kafka_healthy && health?.redis_healthy },
    { label: 'Local WAL',         key: 'wal',      active: !health?.kafka_healthy && !health?.redis_healthy },
  ];

  return (
    <div className="health-view">
      <div className="health-components">
        {components.map(c => (
          <div key={c.key} className="card health-card">
            <div className="health-card-top">
              <span className="health-card-name">{c.label}</span>
              {loading ? <div className="skeleton" style={{ height: 20, width: 70 }} /> : <StatusBadge status={c.status} />}
            </div>
            <div className="health-card-stat-label">{c.statLabel}</div>
            <div className="health-card-stat">{c.stat}</div>
          </div>
        ))}
      </div>

      <div className="card">
        <div className="card-header">
          <span className="card-title">Active Durability Path</span>
          <StatusBadge status={durabilityMode} />
        </div>
        <div className="chain-flow">
          {CHAIN.map((node, i) => (
            <div key={node.key} className="chain-node-wrap">
              <div className={`chain-node ${node.active ? 'active' : ''}`}>
                <span className="chain-dot" style={{ background: node.active ? 'var(--green)' : 'var(--border)' }} />
                {node.label}
              </div>
              {i < CHAIN.length - 1 && (
                <div className={`chain-arrow ${node.active ? 'active' : ''}`}>→</div>
              )}
            </div>
          ))}
        </div>
        <div className="chain-legend">
          The system writes events through this chain in order. If a layer fails, it falls back to the next. Reconciler replays to Kafka on recovery.
        </div>
      </div>

      <div className="card">
        <div className="card-header">
          <span className="card-title">Pipeline Stats</span>
        </div>
        <div className="stats-grid">
          <div className="stat-item"><span>Total Ingested</span><b>{state.total_ingested.toLocaleString()}</b></div>
          <div className="stat-item"><span>Quota Violations</span><b>{state.quota_violations || '—'}</b></div>
          <div className="stat-item"><span>PID Execute Threshold</span><b>{state.pid?.current_execute_threshold?.toFixed(3) || '6.000'}</b></div>
          <div className="stat-item"><span>Baseline Mode</span><b>{state.baseline_mode ? 'ON (FIFO)' : 'OFF (Adaptive)'}</b></div>
          <div className="stat-item"><span>Uptime</span><b>{Math.round(state.uptime)}s</b></div>
          <div className="stat-item"><span>Events/sec</span><b>{state.events_per_second?.toFixed(2)}</b></div>
        </div>
      </div>
    </div>
  );
}
