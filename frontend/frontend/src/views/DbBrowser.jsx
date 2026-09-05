import { useState, useEffect } from 'react';
import { API_BASE } from '../context/PipelineContext';
import './DbBrowser.css';

const ACTION_COLORS = {
  execute: { bg: '#FFF1F3', color: '#8B1538', border: '#FECDD6', label: 'EXECUTE (Fast)' },
  batch: { bg: '#F5F3FF', color: '#4C1D95', border: '#DDD6FE', label: 'BATCH (Micro)' },
  defer: { bg: '#FFFBEB', color: '#B45309', border: '#FDE68A', label: 'DEFER (Cold)' },
};

export default function DbBrowser() {
  const [meta, setMeta] = useState(null);
  const [records, setRecords] = useState([]);
  const [totalRecords, setTotalRecords] = useState(0);
  const [loading, setLoading] = useState(false);
  const [selectedRecord, setSelectedRecord] = useState(null);

  // Filters & Pagination
  const [search, setSearch] = useState('');
  const [eventType, setEventType] = useState('all');
  const [priorityBand, setPriorityBand] = useState('all');
  const [laneAction, setLaneAction] = useState('all');
  const [limit, setLimit] = useState(25);
  const [page, setPage] = useState(0);
  const [autoRefresh, setAutoRefresh] = useState(false);

  const fetchMeta = async () => {
    try {
      const res = await fetch(`${API_BASE}/api/db/browser/meta`);
      const data = await res.json();
      setMeta(data);
    } catch (err) {
      console.error('Failed to fetch DB meta:', err);
    }
  };

  const fetchRecords = async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams({
        limit: limit.toString(),
        offset: (page * limit).toString(),
        event_type: eventType,
        priority_band: priorityBand,
        lane_action: laneAction,
      });
      if (search.trim()) {
        params.append('search', search.trim());
      }

      const res = await fetch(`${API_BASE}/api/db/browser/records?${params.toString()}`);
      const data = await res.json();
      setRecords(data.rows || []);
      setTotalRecords(data.total_records || 0);
    } catch (err) {
      console.error('Failed to fetch DB records:', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchMeta();
  }, []);

  useEffect(() => {
    fetchRecords();
  }, [page, limit, eventType, priorityBand, laneAction]);

  useEffect(() => {
    if (!autoRefresh) return;
    const interval = setInterval(() => {
      fetchMeta();
      fetchRecords();
    }, 2500);
    return () => clearInterval(interval);
  }, [autoRefresh, page, limit, eventType, priorityBand, laneAction, search]);

  const handleSearchSubmit = (e) => {
    e.preventDefault();
    setPage(0);
    fetchRecords();
  };

  const totalPages = Math.ceil(totalRecords / limit) || 1;

  const getScoreBadgeColor = (score) => {
    if (score >= 6.0) return { bg: '#FEE2E2', color: '#991B1B', label: 'High' };
    if (score >= 3.0) return { bg: '#FEF3C7', color: '#92400E', label: 'Mid' };
    return { bg: '#F3F4F6', color: '#374151', label: 'Low' };
  };

  return (
    <div className="db-browser-view">
      {/* Header */}
      <div className="page-header">
        <div>
          <h1 className="page-title">SQLite Database Browser</h1>
          <p className="page-desc">
            Inspect persistent order history and transaction logs stored in SQLite disk database
          </p>
        </div>
        <div className="page-header-actions">
          <button
            className={`btn-outline ${autoRefresh ? 'active' : ''}`}
            onClick={() => setAutoRefresh(!autoRefresh)}
          >
            <span className="material-symbols-outlined" style={{ fontSize: 16 }}>
              {autoRefresh ? 'sync' : 'sync_disabled'}
            </span>
            {autoRefresh ? 'Live Auto-Sync ON' : 'Auto-Sync OFF'}
          </button>
          <button className="btn-primary" onClick={() => { fetchMeta(); fetchRecords(); }}>
            <span className="material-symbols-outlined" style={{ fontSize: 16 }}>refresh</span>
            Refresh DB
          </button>
        </div>
      </div>

      {/* DB Metadata Cards */}
      {meta && (
        <div className="db-meta-grid">
          <div className="db-meta-card card">
            <div className="db-meta-label">
              <span className="material-symbols-outlined">database</span>
              Database File
            </div>
            <div className="db-meta-val">{meta.filename}</div>
            <div className="db-meta-sub">{meta.db_path}</div>
          </div>

          <div className="db-meta-card card">
            <div className="db-meta-label">
              <span className="material-symbols-outlined">hard_drive</span>
              Disk File Size
            </div>
            <div className="db-meta-val">{meta.size_mb} MB</div>
            <div className="db-meta-sub">{meta.size_bytes.toLocaleString()} bytes</div>
          </div>

          <div className="db-meta-card card">
            <div className="db-meta-label">
              <span className="material-symbols-outlined">receipt_long</span>
              Total Records
            </div>
            <div className="db-meta-val">{totalRecords.toLocaleString()}</div>
            <div className="db-meta-sub">Table: order_history</div>
          </div>

          <div className="db-meta-card card">
            <div className="db-meta-label">
              <span className="material-symbols-outlined">settings_suggest</span>
              SQLite Engine
            </div>
            <div className="db-meta-val">v{meta.sqlite_version}</div>
            <div className="db-meta-sub">Journal: {meta.journal_mode.toUpperCase()}</div>
          </div>
        </div>
      )}

      {/* Toolbar & Filters */}
      <div className="db-toolbar card">
        <form onSubmit={handleSearchSubmit} className="db-search-form">
          <div className="search-input-wrapper">
            <span className="material-symbols-outlined search-icon">search</span>
            <input
              type="text"
              placeholder="Search Event ID or Producer ID..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="db-search-input"
            />
            {search && (
              <button
                type="button"
                className="clear-search-btn"
                onClick={() => { setSearch(''); setPage(0); fetchRecords(); }}
              >
                <span className="material-symbols-outlined">close</span>
              </button>
            )}
          </div>
          <button type="submit" className="btn-outline">Search</button>
        </form>

        <div className="db-filter-group">
          {/* Event Type */}
          <select
            className="db-select"
            value={eventType}
            onChange={(e) => { setEventType(e.target.value); setPage(0); }}
          >
            <option value="all">All Event Types</option>
            <option value="order">Orders</option>
            <option value="payment">Payments</option>
            <option value="inventory">Inventory</option>
            <option value="click">Clicks</option>
            <option value="log">Logs</option>
          </select>

          {/* Priority Band */}
          <select
            className="db-select"
            value={priorityBand}
            onChange={(e) => { setPriorityBand(e.target.value); setPage(0); }}
          >
            <option value="all">All Priority Bands</option>
            <option value="Critical">Critical</option>
            <option value="Standard">Standard</option>
            <option value="Best-effort">Best-effort</option>
          </select>

          {/* Lane Action */}
          <select
            className="db-select"
            value={laneAction}
            onChange={(e) => { setLaneAction(e.target.value); setPage(0); }}
          >
            <option value="all">All Lane Actions</option>
            <option value="execute">EXECUTE (Fast)</option>
            <option value="batch">BATCH (Micro)</option>
            <option value="defer">DEFER (Cold)</option>
          </select>

          {/* Limit */}
          <select
            className="db-select limit-select"
            value={limit}
            onChange={(e) => { setLimit(Number(e.target.value)); setPage(0); }}
          >
            <option value={10}>10 / page</option>
            <option value={25}>25 / page</option>
            <option value={50}>50 / page</option>
            <option value={100}>100 / page</option>
          </select>
        </div>
      </div>

      {/* Main Table & Detail Split */}
      <div className="db-main-content">
        <div className="db-table-panel card">
          <div className="card-header">
            <span className="card-title">
              SQLite Table Rows ({totalRecords.toLocaleString()} Total)
            </span>
            <div className="pagination-controls">
              <button
                className="btn-pagination"
                disabled={page === 0 || loading}
                onClick={() => setPage(page - 1)}
              >
                <span className="material-symbols-outlined">chevron_left</span>
              </button>
              <span className="page-indicator">
                Page {page + 1} of {totalPages}
              </span>
              <button
                className="btn-pagination"
                disabled={page + 1 >= totalPages || loading}
                onClick={() => setPage(page + 1)}
              >
                <span className="material-symbols-outlined">chevron_right</span>
              </button>
            </div>
          </div>

          {loading ? (
            <div className="empty-state">
              <div className="spinner" />
              <p>Querying SQLite Database...</p>
            </div>
          ) : records.length === 0 ? (
            <div className="empty-state">
              <span className="material-symbols-outlined" style={{ fontSize: 40, color: '#E3E6EB' }}>
                table_rows
              </span>
              <p style={{ marginTop: 8, color: '#9CA3AF' }}>No database records match your filter query</p>
            </div>
          ) : (
            <div className="table-responsive">
              <table className="db-table">
                <thead>
                  <tr>
                    <th>Row #</th>
                    <th>Event ID</th>
                    <th>Producer</th>
                    <th>Type</th>
                    <th>Score (0-10)</th>
                    <th>Action</th>
                    <th>Band</th>
                    <th>Durability</th>
                    <th>Created At</th>
                  </tr>
                </thead>
                <tbody>
                  {records.map((r) => {
                    const isSelected = selectedRecord?.id === r.id;
                    const actionConfig = ACTION_COLORS[r.lane_action] || ACTION_COLORS.execute;
                    const scoreStyle = getScoreBadgeColor(r.score);

                    return (
                      <tr
                        key={r.id}
                        className={isSelected ? 'selected-row' : ''}
                        onClick={() => setSelectedRecord(r)}
                      >
                        <td className="col-id">#{r.id}</td>
                        <td className="col-event-id" title={r.event_id}>
                          {r.event_id.slice(0, 16)}...
                        </td>
                        <td>
                          <span className="producer-tag">{r.producer_id}</span>
                        </td>
                        <td>
                          <span className="type-badge">{r.event_type}</span>
                        </td>
                        <td>
                          <span
                            className="score-pill"
                            style={{ background: scoreStyle.bg, color: scoreStyle.color }}
                          >
                            {r.score.toFixed(2)}
                          </span>
                        </td>
                        <td>
                          <span
                            className="action-badge"
                            style={{
                              background: actionConfig.bg,
                              color: actionConfig.color,
                              border: `1px solid ${actionConfig.border}`,
                            }}
                          >
                            {r.lane_action.toUpperCase()}
                          </span>
                        </td>
                        <td>
                          <span className="band-badge">{r.priority_band}</span>
                        </td>
                        <td>
                          <span className="durability-badge">{r.durability_mode || 'kafka'}</span>
                        </td>
                        <td className="col-time">
                          {new Date(r.created_at).toLocaleTimeString()}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </div>

        {/* Record Inspector Drawer */}
        {selectedRecord && (
          <div className="db-detail-panel card">
            <div className="card-header">
              <span className="card-title">Record #{selectedRecord.id} Inspector</span>
              <button
                className="close-drawer-btn"
                onClick={() => setSelectedRecord(null)}
              >
                <span className="material-symbols-outlined">close</span>
              </button>
            </div>

            <div className="drawer-content">
              <div className="drawer-section">
                <div className="drawer-label">Full Event ID</div>
                <div className="drawer-val code-text">{selectedRecord.event_id}</div>
              </div>

              <div className="drawer-grid">
                <div>
                  <div className="drawer-label">Producer ID</div>
                  <div className="drawer-val">{selectedRecord.producer_id}</div>
                </div>
                <div>
                  <div className="drawer-label">Event Type</div>
                  <div className="drawer-val">{selectedRecord.event_type}</div>
                </div>
                <div>
                  <div className="drawer-label">Monetary Amount</div>
                  <div className="drawer-val">${selectedRecord.monetary_amount.toFixed(2)}</div>
                </div>
                <div>
                  <div className="drawer-label">Priority Score</div>
                  <div className="drawer-val font-bold" style={{ color: '#8B1538' }}>
                    {selectedRecord.score.toFixed(2)} / 10.0
                  </div>
                </div>
                <div>
                  <div className="drawer-label">Action Lane</div>
                  <div className="drawer-val">{selectedRecord.lane_action}</div>
                </div>
                <div>
                  <div className="drawer-label">Priority Band</div>
                  <div className="drawer-val">{selectedRecord.priority_band}</div>
                </div>
              </div>

              <div className="drawer-section" style={{ marginTop: 16 }}>
                <div className="drawer-label">Stored JSON Payload (SQLite)</div>
                <div className="json-container">
                  <pre>{JSON.stringify(selectedRecord.payload_json, null, 2)}</pre>
                </div>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
