import { useState } from 'react';
import { API_BASE } from '../context/PipelineContext';
import './Benchmark.css';

export default function Benchmark() {
  const [loading, setLoading] = useState(false);
  const [results, setResults] = useState(null);
  const [numEvents, setNumEvents] = useState(5000);
  const [loadMultiplier, setLoadMultiplier] = useState(20);

  const runBenchmark = async () => {
    setLoading(true);
    setResults(null);
    
    try {
      const res = await fetch(`${API_BASE}/benchmark/run?num_events=${numEvents}&load_multiplier=${loadMultiplier}`, {
        method: 'POST',
      });
      const data = await res.json();
      setResults(data);
    } catch (e) {
      console.error('Benchmark failed:', e);
      alert('Benchmark failed: ' + e.message);
    } finally {
      setLoading(false);
    }
  };

  const formatNumber = (num) => num?.toLocaleString() || '0';
  const formatPercent = (num) => num >= 0 ? `+${num.toFixed(1)}%` : `${num.toFixed(1)}%`;
  
  return (
    <div className="benchmark-view">
      {/* Header */}
      <div className="page-header">
        <div>
          <h1 className="page-title">Performance Benchmark</h1>
          <p className="page-desc">
            Side-by-side comparison: Naive FIFO vs Intelligent Adaptive Pipeline under extreme load
          </p>
        </div>
      </div>

      {/* Configuration */}
      <div className="card bench-config-card">
        <div className="card-header">
          <span className="card-title">Benchmark Configuration</span>
        </div>
        <div className="bench-config">
          <div className="bench-config-item">
            <label>Number of Events</label>
            <input
              type="number"
              value={numEvents}
              onChange={(e) => setNumEvents(parseInt(e.target.value))}
              min="1000"
              max="50000"
              step="1000"
            />
          </div>
          <div className="bench-config-item">
            <label>Load Multiplier</label>
            <select value={loadMultiplier} onChange={(e) => setLoadMultiplier(parseInt(e.target.value))}>
              <option value="1">1x (1,000 req/min)</option>
              <option value="5">5x (5,000 req/min)</option>
              <option value="10">10x (10,000 req/min)</option>
              <option value="20">20x (20,000 req/min) - Flash Sale</option>
              <option value="50">50x (50,000 req/min) - Extreme</option>
              <option value="100">100x (100,000 req/min) - Black Friday</option>
            </select>
          </div>
          <button
            className="bench-run-btn"
            onClick={runBenchmark}
            disabled={loading}
          >
            {loading ? (
              <>
                <div className="spinner-small" />
                Running Benchmark...
              </>
            ) : (
              <>
                <span className="material-symbols-outlined">rocket_launch</span>
                Run Benchmark
              </>
            )}
          </button>
        </div>
      </div>

      {/* Results */}
      {results && (
        <>
          {/* Summary Cards */}
          <div className="bench-summary-grid">
            <div className="bench-summary-card savings">
              <div className="bench-summary-icon">
                <span className="material-symbols-outlined">savings</span>
              </div>
              <div className="bench-summary-content">
                <div className="bench-summary-label">Cost Savings</div>
                <div className="bench-summary-value">
                  ${results.improvements.cost_savings_usd.toFixed(4)}
                </div>
                <div className="bench-summary-sub">
                  {formatPercent(results.improvements.cost_savings_percent)} reduction
                </div>
              </div>
            </div>

            <div className="bench-summary-card energy">
              <div className="bench-summary-icon">
                <span className="material-symbols-outlined">bolt</span>
              </div>
              <div className="bench-summary-content">
                <div className="bench-summary-label">Energy Savings</div>
                <div className="bench-summary-value">
                  {results.improvements.energy_savings_percent.toFixed(1)}%
                </div>
                <div className="bench-summary-sub">
                  {(results.baseline.energy_joules - results.adaptive.energy_joules).toFixed(0)} joules saved
                </div>
              </div>
            </div>

            <div className="bench-summary-card latency">
              <div className="bench-summary-icon">
                <span className="material-symbols-outlined">speed</span>
              </div>
              <div className="bench-summary-content">
                <div className="bench-summary-label">Latency Improvement</div>
                <div className="bench-summary-value">
                  {results.improvements.latency_reduction_percent.toFixed(1)}%
                </div>
                <div className="bench-summary-sub">
                  {(results.baseline.avg_latency_ms - results.adaptive.avg_latency_ms).toFixed(1)}ms faster avg
                </div>
              </div>
            </div>
          </div>

          {/* Detailed Comparison */}
          <div className="bench-comparison">
            <div className="card bench-system-card baseline">
              <div className="card-header">
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <span className="material-symbols-outlined" style={{ color: '#EF4444' }}>
                    view_list
                  </span>
                  <span className="card-title">Naive FIFO Baseline</span>
                </div>
                <span className="sbadge sbadge-red sbadge-sm">20 Fixed Workers</span>
              </div>
              <div className="bench-metrics">
                <MetricRow label="Processed" value={formatNumber(results.baseline.processed)} />
                <MetricRow label="Avg Latency" value={`${results.baseline.avg_latency_ms}ms`} />
                <MetricRow label="P95 Latency" value={`${results.baseline.p95_latency_ms}ms`} />
                <MetricRow label="P99 Latency" value={`${results.baseline.p99_latency_ms}ms`} />
                <MetricRow label="Duration" value={`${results.baseline.duration_sec}s`} />
                <div className="metric-divider" />
                <MetricRow label="Energy Consumed" value={`${results.baseline.energy_joules.toFixed(0)} J`} />
                <MetricRow label="Compute Cost" value={`$${results.baseline.compute_cost_usd.toFixed(4)}`} />
                <MetricRow label="Energy Cost" value={`$${results.baseline.energy_cost_usd.toFixed(4)}`} />
                <MetricRow label="Total Cost" value={`$${results.baseline.total_cost_usd.toFixed(4)}`} highlight />
              </div>
            </div>

            <div className="bench-vs-divider">
              <div className="bench-vs-circle">VS</div>
              <div className="bench-vs-arrow">→</div>
            </div>

            <div className="card bench-system-card adaptive">
              <div className="card-header">
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <span className="material-symbols-outlined" style={{ color: '#8B1538' }}>
                    auto_awesome
                  </span>
                  <span className="card-title">Intelligent Adaptive Pipeline</span>
                </div>
                <span className="sbadge sbadge-iris sbadge-sm">2-10 Dynamic Workers</span>
              </div>
              <div className="bench-metrics">
                <MetricRow label="Processed" value={formatNumber(results.adaptive.processed)} />
                <MetricRow label="Avg Latency" value={`${results.adaptive.avg_latency_ms}ms`} better={results.adaptive.avg_latency_ms < results.baseline.avg_latency_ms} />
                <MetricRow label="P95 Latency" value={`${results.adaptive.p95_latency_ms}ms`} better={results.adaptive.p95_latency_ms < results.baseline.p95_latency_ms} />
                <MetricRow label="P99 Latency" value={`${results.adaptive.p99_latency_ms}ms`} better={results.adaptive.p99_latency_ms < results.baseline.p99_latency_ms} />
                <MetricRow label="Duration" value={`${results.adaptive.duration_sec}s`} better={results.adaptive.duration_sec < results.baseline.duration_sec} />
                <div className="metric-divider" />
                <MetricRow label="Energy Consumed" value={`${results.adaptive.energy_joules.toFixed(0)} J`} better />
                <MetricRow label="Compute Cost" value={`$${results.adaptive.compute_cost_usd.toFixed(4)}`} better />
                <MetricRow label="Energy Cost" value={`$${results.adaptive.energy_cost_usd.toFixed(4)}`} better />
                <MetricRow label="Total Cost" value={`$${results.adaptive.total_cost_usd.toFixed(4)}`} highlight better />
              </div>
            </div>
          </div>

          {/* Energy Breakdown */}
          <div className="card">
            <div className="card-header">
              <span className="card-title">Energy Cost Model (Similar to LLM Joules/Token)</span>
            </div>
            <div className="bench-energy-breakdown">
              <div className="bench-energy-item">
                <div className="bench-energy-label">Base Processing</div>
                <div className="bench-energy-desc">0.5 joules per event (CPU cycles, memory access)</div>
              </div>
              <div className="bench-energy-item">
                <div className="bench-energy-label">Queue Waiting</div>
                <div className="bench-energy-desc">0.1 joules per second in queue (holding state, context switching)</div>
              </div>
              <div className="bench-energy-item">
                <div className="bench-energy-label">Batch Context Switch</div>
                <div className="bench-energy-desc">0.2 joules per batch (grouping overhead)</div>
              </div>
              <div className="bench-energy-item">
                <div className="bench-energy-label">Peak Load Overhead</div>
                <div className="bench-energy-desc">2x multiplier during saturation (thermal throttling, contention)</div>
              </div>
            </div>
          </div>
        </>
      )}
    </div>
  );
}

function MetricRow({ label, value, highlight, better }) {
  return (
    <div className={`metric-row ${highlight ? 'highlight' : ''}`}>
      <span className="metric-label">{label}</span>
      <span className={`metric-value ${better ? 'better' : ''}`}>
        {better && <span className="material-symbols-outlined metric-check">check_circle</span>}
        {value}
      </span>
    </div>
  );
}
