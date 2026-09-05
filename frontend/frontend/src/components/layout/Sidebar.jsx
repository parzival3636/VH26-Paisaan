import { NavLink } from 'react-router-dom';
import { usePipeline } from '../../context/PipelineContext';
import './Sidebar.css';

const navItems = [
  { to: '/',          icon: 'space_dashboard', label: 'Dashboard' },
  { to: '/controls',  icon: 'tune',            label: 'Control Center' },
  { to: '/batches',   icon: 'inventory_2',     label: 'Batch Files' },
  { to: '/benchmark', icon: 'speed',           label: 'Benchmark' },
  { to: '/db-browser', icon: 'database',        label: 'SQLite DB' },
];

export default function Sidebar() {
  const { state } = usePipeline();

  const statusColor = state.connected
    ? (state.stale ? 'var(--ochre)' : 'var(--green)')
    : 'var(--bordeaux)';
  const statusLabel = state.connected
    ? (state.stale ? 'Data Stale' : 'Live Connected')
    : 'Disconnected';

  const handleNavClick = (to) => {
    console.log('Navigation clicked:', to);
  };

  return (
    <aside className="sidebar">
      {/* Brand */}
      <div className="sidebar-brand">
        <div className="sidebar-brand-icon">
          <span className="material-symbols-outlined">shield_with_heart</span>
        </div>
        <div>
          <div className="sidebar-product">Pipeline Ops</div>
          <div className="sidebar-version">Telemetry Core</div>
        </div>
      </div>

      <div className="sidebar-scroll">
        <div className="sidebar-section">
          <div className="sidebar-section-label">Navigation</div>
          <nav className="sidebar-nav">
            {navItems.map(({ to, icon, label }) => (
              <NavLink
                key={to}
                to={to}
                end={to === '/'}
                className={({ isActive }) => `sidebar-item ${isActive ? 'active' : ''}`}
                style={{ cursor: 'pointer', pointerEvents: 'auto' }}
                onClick={() => handleNavClick(to)}
              >
                <span className="material-symbols-outlined sidebar-icon">{icon}</span>
                <span>{label}</span>
              </NavLink>
            ))}
          </nav>
        </div>
      </div>

      {/* Footer */}
      <div className="sidebar-footer">
        <div className="sidebar-footer-row">
          <span>Mode: {state.baseline_mode ? 'FIFO' : 'Adaptive'}</span>
          <span className="sidebar-n3">{state.connected ? 'WS OK' : 'WS OFF'}</span>
        </div>
        <div className="sidebar-build">{statusLabel}</div>
        <div className="sidebar-status-dot" style={{ background: statusColor }} />
      </div>
    </aside>
  );
}
