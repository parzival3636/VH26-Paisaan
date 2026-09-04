import './StatusBadge.css';

const STYLE_MAP = {
  healthy:                  'iris',
  ok:                       'iris',
  live:                     'iris',
  active:                   'iris',
  degraded:                 'cassis',
  standby:                  'cassis',
  armed:                    'cassis',
  down:                     'bd',
  critical:                 'bd',
  error:                    'bd',
  unknown:                  'muted',
  kafka:                    'iris',
  redis_emergency:          'cassis',
  local_wal_pending_sync:   'bd',
};

const LABEL_MAP = {
  healthy: 'Healthy', ok: 'Healthy', live: 'Live', active: 'Active',
  degraded: 'Degraded', standby: 'Standby', armed: 'Armed',
  down: 'Down', critical: 'Critical', error: 'Error',
  unknown: 'Unknown',
  kafka: 'Kafka (Primary)',
  redis_emergency: 'Redis Fallback',
  local_wal_pending_sync: 'WAL Fallback',
};

export default function StatusBadge({ status, label, size = 'md', variant }) {
  const style = variant || STYLE_MAP[status] || 'muted';
  const text = label || LABEL_MAP[status] || status || 'Unknown';

  return (
    <span className={`sbadge sbadge-${style} sbadge-${size}`}>
      <span className="sbadge-dot" />
      {text}
    </span>
  );
}
