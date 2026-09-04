import { useState } from 'react';
import { usePipeline, API_BASE } from '../context/PipelineContext';
import ScoreDrawer from './ScoreDrawer';
import StatusBadge from '../components/shared/StatusBadge';
import './EventExplorer.css';

const EVENT_TYPES = ['all', 'order', 'payment', 'inventory', 'click', 'log'];
const LANES = ['all', 'execute', 'batch', 'defer'];

export default function EventExplorer() {
  const { state } = usePipeline();
  const [typeFilter, setTypeFilter] = useState('all');
  const [laneFilter, setLaneFilter] = useState('all');
  const [selected, setSelected] = useState(null);

  const events = [...state.recent_events].reverse().filter(ev => {
    if (typeFilter !== 'all' && ev.type !== typeFilter) return false;
    if (laneFilter !== 'all' && ev.action !== laneFilter) return false;
    return true;
  });

  return (
    <div className="explorer">
      <div className="explorer-filters card">
        <div className="filter-group">
          <label>Event Type</label>
          <select value={typeFilter} onChange={e => setTypeFilter(e.target.value)}>
            {EVENT_TYPES.map(t => <option key={t} value={t}>{t === 'all' ? 'All Types' : t}</option>)}
          </select>
        </div>
        <div className="filter-group">
          <label>Lane</label>
          <select value={laneFilter} onChange={e => setLaneFilter(e.target.value)}>
            {LANES.map(l => <option key={l} value={l}>{l === 'all' ? 'All Lanes' : l}</option>)}
          </select>
        </div>
        <span className="filter-count">{events.length} events</span>
      </div>

      <div className="card">
        {events.length === 0 ? (
          <div className="empty-state">No events match the current filters</div>
        ) : (
          <table className="events-table">
            <thead>
              <tr><th>Event ID</th><th>Type</th><th>Score</th><th>Action</th><th>Durability</th><th>Latency</th></tr>
            </thead>
            <tbody>
              {events.map(ev => (
                <tr key={ev.event_id} className={`events-row ${selected?.event_id === ev.event_id ? 'selected' : ''}`} onClick={() => setSelected(ev)}>
                  <td className="event-id truncate">{ev.full_event_id || ev.event_id}</td>
                  <td><span style={{ fontWeight: 600, textTransform: 'capitalize', fontSize: 12 }}>{ev.type}</span></td>
                  <td style={{ fontWeight: 600, fontVariantNumeric: 'tabular-nums' }}>{ev.final_score?.toFixed(2) ?? '—'}</td>
                  <td><StatusBadge status={ev.action === 'execute' ? 'healthy' : ev.action === 'defer' ? 'degraded' : 'ok'} label={ev.action} size="sm" /></td>
                  <td><StatusBadge status={ev.durability || 'unknown'} size="sm" /></td>
                  <td style={{ fontVariantNumeric: 'tabular-nums', fontSize: 12 }}>{ev.latency_ms ?? '—'}ms</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {selected && <ScoreDrawer event={selected} onClose={() => setSelected(null)} />}
    </div>
  );
}
