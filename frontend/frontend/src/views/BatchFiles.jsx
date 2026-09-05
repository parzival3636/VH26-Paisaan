import { useState, useEffect } from 'react';
import { API_BASE } from '../context/PipelineContext';
import './BatchFiles.css';

const LANE_COLORS = {
  fast: { color: '#8B1538', bg: '#FFF1F3', border: '#FECDD6', label: 'Fast Lane' },
  standard: { color: '#4C1D95', bg: '#F5F3FF', border: '#DDD6FE', label: 'Standard Lane' },
  cold: { color: '#B45309', bg: '#FFFBEB', border: '#FDE68A', label: 'Cold Lane' },
};

export default function BatchFiles() {
  const [batches, setBatches] = useState([]);
  const [selectedBatch, setSelectedBatch] = useState(null);
  const [loading, setLoading] = useState(false);
  const [filter, setFilter] = useState('all');

  const fetchBatches = async () => {
    try {
      const url = filter === 'all' 
        ? `${API_BASE}/batches`
        : `${API_BASE}/batches?lane=${filter}`;
      const res = await fetch(url);
      const data = await res.json();
      setBatches(data.batches || []);
    } catch (e) {
      console.error('Failed to fetch batches:', e);
    }
  };

  const fetchBatchDetail = async (batchId) => {
    setLoading(true);
    try {
      const res = await fetch(`${API_BASE}/batches/${batchId}`);
      const data = await res.json();
      setSelectedBatch(data);
    } catch (e) {
      console.error('Failed to fetch batch detail:', e);
    } finally {
      setLoading(false);
    }
  };

  const clearBatches = async () => {
    if (!confirm('Delete all batch files?')) return;
    try {
      await fetch(`${API_BASE}/batches`, { method: 'DELETE' });
      setBatches([]);
      setSelectedBatch(null);
    } catch (e) {
      console.error('Failed to clear batches:', e);
    }
  };

  useEffect(() => {
    fetchBatches();
    const interval = setInterval(fetchBatches, 2000); // Refresh every 2s
    return () => clearInterval(interval);
  }, [filter]);

  const formatTime = (ts) => {
    const d = new Date(ts * 1000);
    return d.toLocaleTimeString();
  };

  const formatSize = (bytes) => {
    if (bytes < 1024) return `${bytes}B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)}KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)}MB`;
  };

  return (
    <div className="batch-files-view">
      {/* Header */}
      <div className="page-header">
        <div>
          <h1 className="page-title">Batch Files</h1>
          <p className="page-desc">Inspect processed batches from Standard and Cold lanes (DRR scheduled)</p>
        </div>
        <div className="page-header-actions">
          <button className="btn-outline" onClick={fetchBatches}>
            <span className="material-symbols-outlined" style={{ fontSize: 16 }}>refresh</span>
            Refresh
          </button>
          <button className="btn-danger" onClick={clearBatches}>
            <span className="material-symbols-outlined" style={{ fontSize: 16 }}>delete</span>
            Clear All
          </button>
        </div>
      </div>

      {/* Filter Tabs */}
      <div className="filter-tabs">
        {['all', 'fast', 'standard', 'cold'].map(f => (
          <button
            key={f}
            className={`filter-tab ${filter === f ? 'active' : ''}`}
            onClick={() => setFilter(f)}
          >
            {f === 'all' ? 'All Lanes' : LANE_COLORS[f]?.label || f}
          </button>
        ))}
      </div>

      <div className="batch-files-content">
        {/* Batch List */}
        <div className="batch-list-panel card">
          <div className="card-header">
            <span className="card-title">Batch Files ({batches.length})</span>
          </div>
          {batches.length === 0 ? (
            <div className="empty-state">
              <span className="material-symbols-outlined" style={{ fontSize: 32, color: '#E3E6EB', marginBottom: 8 }}>
                folder_open
              </span>
              <p>No batch files yet</p>
              <p style={{ fontSize: 11, color: '#9CA3AF', marginTop: 4 }}>
                Batches are created when Standard or Cold lanes process events
              </p>
            </div>
          ) : (
            <div className="batch-list">
              {batches.map(batch => {
                const laneConfig = LANE_COLORS[batch.lane] || LANE_COLORS.standard;
                const isSelected = selectedBatch?.batch_id === batch.batch_id;
                return (
                  <div
                    key={batch.batch_id}
                    className={`batch-item ${isSelected ? 'selected' : ''}`}
                    onClick={() => fetchBatchDetail(batch.batch_id)}
                  >
                    <div className="batch-item-header">
                      <div
                        className="batch-lane-tag"
                        style={{
                          background: laneConfig.bg,
                          border: `1px solid ${laneConfig.border}`,
                          color: laneConfig.color,
                        }}
                      >
                        {laneConfig.label}
                      </div>
                      <div className="batch-time">{formatTime(batch.created)}</div>
                    </div>
                    <div className="batch-filename">{batch.batch_id}</div>
                    <div className="batch-meta">
                      <span>{formatSize(batch.size_bytes)}</span>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>

        {/* Batch Detail */}
        <div className="batch-detail-panel card">
          <div className="card-header">
            <span className="card-title">
              {selectedBatch ? 'Batch Details' : 'Select a batch to preview'}
            </span>
            {selectedBatch && (
              <span
                className="sbadge sbadge-sm"
                style={{
                  background: selectedBatch.status === 'completed' ? '#F0FDF4' : '#FEF3C7',
                  color: selectedBatch.status === 'completed' ? '#16A34A' : '#D97706',
                  border: `1px solid ${selectedBatch.status === 'completed' ? '#BBF7D0' : '#FDE68A'}`,
                }}
              >
                {selectedBatch.status}
              </span>
            )}
          </div>

          {loading ? (
            <div className="empty-state">
              <div className="spinner" />
              <p>Loading batch...</p>
            </div>
          ) : !selectedBatch ? (
            <div className="empty-state">
              <span className="material-symbols-outlined" style={{ fontSize: 40, color: '#E3E6EB' }}>
                description
              </span>
              <p style={{ marginTop: 8, color: '#9CA3AF' }}>Click a batch file to view details</p>
            </div>
          ) : (
            <div className="batch-detail-content">
              {/* Metadata */}
              <div className="batch-metadata">
                <div className="batch-meta-row">
                  <span className="batch-meta-label">Batch ID</span>
                  <span className="batch-meta-value">{selectedBatch.batch_id}</span>
                </div>
                <div className="batch-meta-row">
                  <span className="batch-meta-label">Lane</span>
                  <span className="batch-meta-value">{selectedBatch.lane}</span>
                </div>
                <div className="batch-meta-row">
                  <span className="batch-meta-label">Size</span>
                  <span className="batch-meta-value">{selectedBatch.size} events</span>
                </div>
                <div className="batch-meta-row">
                  <span className="batch-meta-label">Timestamp</span>
                  <span className="batch-meta-value">
                    {new Date(selectedBatch.timestamp * 1000).toLocaleString()}
                  </span>
                </div>
                {selectedBatch.latency_ms && (
                  <div className="batch-meta-row">
                    <span className="batch-meta-label">Latency</span>
                    <span className="batch-meta-value">{selectedBatch.latency_ms.toFixed(1)}ms</span>
                  </div>
                )}
              </div>

              {/* Events */}
              <div className="batch-events-section">
                <div className="batch-section-title">Events in Batch</div>
                <div className="batch-events-list">
                  {selectedBatch.events?.map((event, idx) => (
                    <div key={idx} className="batch-event-item">
                      <div className="batch-event-header">
                        <span className="batch-event-id">{event.event_id}</span>
                        <span className="batch-event-type">{event.type || event.event_type}</span>
                      </div>
                      <div className="batch-event-payload">
                        <pre>{JSON.stringify(event.payload || event, null, 2)}</pre>
                      </div>
                    </div>
                  ))}
                </div>
              </div>

              {/* Processing Result */}
              {selectedBatch.result && (
                <div className="batch-result-section">
                  <div className="batch-section-title">Processing Result</div>
                  <div className="batch-result-content">
                    <pre>{JSON.stringify(selectedBatch.result, null, 2)}</pre>
                  </div>
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
