import { usePipeline } from '../context/PipelineContext';
import { ThresholdLineChart } from '../components/charts/Charts';
import './ThresholdGraph.css';

export default function ThresholdGraph() {
  const { state } = usePipeline();
  const pid = state.pid || {};
  const latest = state.thresholdHistory[state.thresholdHistory.length - 1];

  return (
    <div className="threshold-view">
      <div className="threshold-body">
        <div className="card threshold-main">
          <div className="card-header">
            <span className="card-title">Threshold History</span>
            <span className="card-sub">Execute / Batch / Defer · Last 30 min · PID-adjusted every 5s</span>
          </div>
          <div style={{ padding: '16px 8px 8px' }}>
            {state.thresholdHistory.length < 2 ? (
              <div className="empty-state">Collecting threshold data…</div>
            ) : (
              <ThresholdLineChart data={state.thresholdHistory} />
            )}
          </div>
          <div className="threshold-legend">
            <span className="leg-item violet">● Execute (default 6.0)</span>
            <span className="leg-item blue">● Batch (default 3.0)</span>
            <span className="leg-item teal">● Defer (default 1.0)</span>
          </div>
        </div>

        <div className="threshold-side">
          <div className="card">
            <div className="card-header"><span className="card-title">Current Values</span></div>
            <div className="threshold-vals">
              <div className="tval-row">
                <span className="tval-label">Execute</span>
                <span className="tval-num violet">{(latest?.execute ?? pid.current_execute_threshold ?? 6.0).toFixed(3)}</span>
              </div>
              <div className="tval-row">
                <span className="tval-label">Batch</span>
                <span className="tval-num blue">{(latest?.batch ?? pid.batch_threshold ?? 3.0).toFixed(3)}</span>
              </div>
              <div className="tval-row">
                <span className="tval-label">Defer</span>
                <span className="tval-num teal">{(latest?.defer ?? pid.defer_threshold ?? 1.0).toFixed(3)}</span>
              </div>
            </div>
          </div>

          <div className="card">
            <div className="card-header"><span className="card-title">PID Parameters</span></div>
            <div className="pid-params">
              <div className="pid-row"><span>Kp</span><b>0.01</b></div>
              <div className="pid-row"><span>Ki</span><b>0.001</b></div>
              <div className="pid-row"><span>Kd</span><b>0.005</b></div>
              <div className="pid-row"><span>Target P0</span><b>{pid.target_p0_ms ?? 100}ms</b></div>
              <div className="pid-row"><span>Actual P0</span><b>{pid.p0_latency?.toFixed(1) ?? '—'}ms</b></div>
              <div className="pid-row"><span>Error</span><b>{pid.error?.toFixed(3) ?? '—'}</b></div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
