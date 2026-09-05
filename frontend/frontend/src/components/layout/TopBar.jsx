import { useLocation } from 'react-router-dom';
import { useState, useEffect } from 'react';
import { usePipeline } from '../../context/PipelineContext';
import './TopBar.css';

const VIEW_LABELS = {
  '/':         ['Telemetry', 'live-pipeline-01', 'Dashboard'],
  '/controls': ['Telemetry', 'live-pipeline-01', 'Control Center'],
  '/batches':  ['Telemetry', 'live-pipeline-01', 'Batch Files'],
};

function Clock() {
  const [time, setTime] = useState('');
  useEffect(() => {
    const tick = () => {
      const now = new Date();
      setTime(now.toLocaleTimeString('en-GB') + ' UTC');
    };
    tick();
    const id = setInterval(tick, 1000);
    return () => clearInterval(id);
  }, []);
  return <span>{time}</span>;
}

export default function TopBar() {
  const { pathname } = useLocation();
  const { state } = usePipeline();
  const labels = VIEW_LABELS[pathname] || VIEW_LABELS['/'];
  const [section, pipeline, view] = labels;

  const wsStatus = state.connected
    ? (state.stale ? 'stale' : 'live')
    : 'disconnected';

  return (
    <header className="topbar">
      {/* Breadcrumb */}
      <div className="topbar-breadcrumb">
        <span className="topbar-bc-section">{section}</span>
        <span className="topbar-bc-sep">/</span>
        <div className="topbar-bc-pipeline">
          <span className={`topbar-pulse-dot ${wsStatus === 'live' ? 'live' : ''}`} />
          <span>{pipeline}</span>
        </div>
        <span className="topbar-bc-sep">/</span>
        <span className="topbar-bc-view">{view}</span>
      </div>

      {/* Right side */}
      <div className="topbar-right">
        {state.baseline_mode && (
          <div className="topbar-badge ochre">Baseline FIFO Active</div>
        )}

        {/* WS status pill */}
        <div className={`topbar-ws-pill ws-${wsStatus}`}>
          <span className="topbar-ws-dot" />
          <span>{wsStatus === 'live' ? 'Live WebSocket' : wsStatus === 'stale' ? 'Stale Data' : 'Disconnected'}</span>
        </div>

        {/* Clock */}
        <div className="topbar-clock">
          <span className="material-symbols-outlined" style={{ fontSize: 14 }}>schedule</span>
          <Clock />
        </div>
      </div>
    </header>
  );
}
