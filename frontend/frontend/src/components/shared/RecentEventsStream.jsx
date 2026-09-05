import { useState, useEffect, useRef } from 'react';
import { usePipeline } from '../../context/PipelineContext';
import StatusBadge from './StatusBadge';
import './RecentEventsStream.css';

const TYPE_COLORS = {
  order: 'var(--iris)',
  payment: 'var(--green)',
  inventory: 'var(--ochre)',
  click: 'var(--cassis)',
  log: 'var(--text-muted)',
  other: 'var(--text-muted)',
};

const ACTION_LABEL = {
  execute: { label: 'Fast Lane', color: 'var(--iris)' },
  batch:   { label: 'Standard',  color: 'var(--cassis)' },
  defer:   { label: 'Cold Lane', color: 'var(--ochre)' },
  shed:    { label: 'Rejected',  color: 'var(--bordeaux)' },
  backpressure: { label: 'Backpressure', color: 'var(--bordeaux)' },
};

const BATCH_WINDOW_SECONDS = 20;

export default function RecentEventsStream({ onSelectEvent }) {
  const { state } = usePipeline();
  
  // State for visible rows rendered in DOM
  const [visibleEvents, setVisibleEvents] = useState([]);
  const [newBatchIds, setNewBatchIds] = useState(new Set());
  const [countdown, setCountdown] = useState(BATCH_WINDOW_SECONDS);
  const [unreadCount, setUnreadCount] = useState(0);
  const [userScrolledUp, setUserScrolledUp] = useState(false);

  // Refs for tracking across renders & timers
  const pendingBufferRef = useRef([]);
  const seenEventIdsRef = useRef(new Set());
  const scrollContainerRef = useRef(null);
  const userScrolledUpRef = useRef(false);

  // 1. Ingest new events into memory buffer (no immediate UI update)
  useEffect(() => {
    const rawEvents = state.recent_events || [];
    if (rawEvents.length === 0) return;

    // On initial load, populate first 20 events immediately
    if (seenEventIdsRef.current.size === 0) {
      const initial = rawEvents.slice(-20);
      initial.forEach(ev => seenEventIdsRef.current.add(ev.event_id));
      setVisibleEvents(initial);
      return;
    }

    // Ingest unseen events into pending buffer
    let addedCount = 0;
    rawEvents.forEach(ev => {
      if (ev?.event_id && !seenEventIdsRef.current.has(ev.event_id)) {
        seenEventIdsRef.current.add(ev.event_id);
        pendingBufferRef.current.push(ev);
        addedCount++;
      }
    });
  }, [state.recent_events]);

  // 2. 20-Second Batch Timer & Countdown
  useEffect(() => {
    const timer = setInterval(() => {
      setCountdown((prev) => {
        if (prev <= 1) {
          // Flush pending buffer to DOM
          flushBufferToDOM();
          return BATCH_WINDOW_SECONDS;
        }
        return prev - 1;
      });
    }, 1000);

    return () => clearInterval(timer);
  }, []);

  // Flush buffer to visible DOM in a single atomic update
  const flushBufferToDOM = () => {
    const toFlush = [...pendingBufferRef.current];
    if (toFlush.length === 0) return;

    // Clear memory buffer
    pendingBufferRef.current = [];

    // Track newly appended event IDs for CSS highlight animation
    const batchIds = new Set(toFlush.map(ev => ev.event_id));
    setNewBatchIds(batchIds);

    // Clear highlight animation after 1.2s
    setTimeout(() => {
      setNewBatchIds(new Set());
    }, 1200);

    // Atomic append to bottom of visible list
    setVisibleEvents((prev) => [...prev, ...toFlush]);

    // Handle scroll position logic
    if (userScrolledUpRef.current) {
      setUnreadCount((prev) => prev + toFlush.length);
    } else {
      setTimeout(scrollToBottom, 50);
    }
  };

  // Scroll listener to detect if user has scrolled up
  const handleScroll = () => {
    if (!scrollContainerRef.current) return;
    const el = scrollContainerRef.current;
    const isAtBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 60;
    
    userScrolledUpRef.current = !isAtBottom;
    setUserScrolledUp(!isAtBottom);

    if (isAtBottom) {
      setUnreadCount(0);
    }
  };

  const scrollToBottom = () => {
    if (scrollContainerRef.current) {
      const el = scrollContainerRef.current;
      el.scrollTo({ top: el.scrollHeight, behavior: 'smooth' });
      setUnreadCount(0);
      setUserScrolledUp(false);
      userScrolledUpRef.current = false;
    }
  };

  const pendingCount = pendingBufferRef.current.length;

  return (
    <div className="recent-events-card card">
      {/* Card Header */}
      <div className="card-header res-header">
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <div className="res-icon-box">
            <span className="material-symbols-outlined" style={{ fontSize: 14, color: 'var(--iris)' }}>
              table_rows
            </span>
          </div>
          <div>
            <span className="card-title">Recent Events Stream</span>
            <span className="card-sub" style={{ marginLeft: 8 }}>
              Pipeline: Live Real-Time (&lt;1ms) · UI List: 20s Batch Buffer
            </span>
          </div>
        </div>

        {/* Batch Status Badge & Timer */}
        <div className="res-timer-badge">
          <span className="res-pulse-dot" />
          <span className="res-timer-text">
            UI Flush in <strong>{countdown}s</strong>
          </span>
          {pendingCount > 0 && (
            <span className="res-pending-pill">
              {pendingCount} buffered
            </span>
          )}
        </div>
      </div>

      {/* Table Container */}
      {visibleEvents.length === 0 ? (
        <div className="empty-state">
          <span className="material-symbols-outlined" style={{ fontSize: 32, color: 'var(--border)', display: 'block', marginBottom: 8 }}>
            inbox
          </span>
          Awaiting traffic stream — trigger a load preset to begin
        </div>
      ) : (
        <div className="res-table-wrapper">
          <div
            className="res-scroll-container"
            ref={scrollContainerRef}
            onScroll={handleScroll}
          >
            <table className="events-table res-table">
              <thead>
                <tr>
                  <th>Event ID</th>
                  <th>Type</th>
                  <th>Score</th>
                  <th>Band</th>
                  <th>Lane</th>
                  <th>Latency</th>
                </tr>
              </thead>
              <tbody>
                {visibleEvents.map((ev, index) => {
                  const lane = ACTION_LABEL[ev.action] || { label: ev.action, color: 'var(--text-muted)' };
                  const isNewBatch = newBatchIds.has(ev.event_id);
                  const isEvenRow = index % 2 === 0;

                  return (
                    <tr
                      key={ev.event_id}
                      className={`events-row res-row ${isEvenRow ? 'row-even' : 'row-odd'} ${isNewBatch ? 'row-new-batch' : ''}`}
                      onClick={() => onSelectEvent && onSelectEvent(ev)}
                    >
                      <td className="event-id truncate">{ev.event_id}</td>
                      <td>
                        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                          <span
                            style={{
                              width: 6,
                              height: 6,
                              borderRadius: '50%',
                              background: TYPE_COLORS[ev.type] || 'var(--text-muted)',
                              flexShrink: 0,
                            }}
                          />
                          <span style={{ fontWeight: 500 }}>{ev.type}</span>
                        </div>
                      </td>
                      <td className="score-cell">{ev.final_score?.toFixed(2) ?? '—'}</td>
                      <td>
                        <span className="band-pill">{ev.band || '—'}</span>
                      </td>
                      <td>
                        <StatusBadge
                          status={ev.action === 'execute' ? 'active' : ev.action === 'batch' ? 'standby' : 'degraded'}
                          label={lane.label}
                          size="sm"
                        />
                      </td>
                      <td className="latency-cell">{ev.latency_ms ?? '—'}ms</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>

          {/* Floating Pill when User Scrolled Up */}
          {userScrolledUp && unreadCount > 0 && (
            <button className="res-unread-pill" onClick={scrollToBottom}>
              <span className="material-symbols-outlined" style={{ fontSize: 14 }}>
                arrow_downward
              </span>
              {unreadCount} new events appended ↓
            </button>
          )}

          {/* Architecture Note Footer */}
          <div className="res-footer-note">
            <span className="material-symbols-outlined" style={{ fontSize: 13, color: '#059669' }}>bolt</span>
            <span>
              <strong>Pipeline Execution:</strong> Ingestion, urgency scoring (0–10), and DRR lane routing process continuously in real-time. Only this visual DOM table buffers updates (20s) to prevent UI flicker.
            </span>
          </div>
        </div>
      )}
    </div>
  );
}
