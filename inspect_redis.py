"""
inspect_redis.py — Live Redis State & Adaptive Lane Inspector

Monitors real-time pipeline state in Redis:
  1. Producer Quota Counters (`quota:<producer>:<window>`)
  2. Adaptive Lane Routing Queues (`lane:execute`, `lane:batch`, `lane:defer`, `lane:shed`)
  3. Scored Event Hash Records (`event:<id>`)

Run in a separate terminal while demo.py is active.
"""

import sys
import time

try:
    import redis
except ImportError:
    print("Error: redis package not installed.")
    sys.exit(1)


def main():
    r = redis.Redis(host="localhost", port=6379, decode_responses=True)
    try:
        r.ping()
    except Exception as exc:
        print(f"Cannot connect to Redis at localhost:6379 ({exc})")
        sys.exit(1)

    print("==========================================================================")
    print(" LIVE REDIS PIPELINE & ADAPTIVE LANE INSPECTOR")
    print(" Connected to Redis @ localhost:6379")
    print(" Press Ctrl+C to stop")
    print("==========================================================================")

    try:
        while True:
            now = time.strftime("%H:%M:%S")
            print(f"\n[{now}] === REDIS STATE SNAPSHOT ===")

            # 1. Quota Counters
            quota_keys = sorted(r.keys("quota:*"))
            print(f"\n -- Producer Rate Limit Counters in Redis ({len(quota_keys)} active windows):")
            if not quota_keys:
                print("    (no active quota keys — launch python demo.py)")
            else:
                for k in quota_keys:
                    val = r.get(k)
                    ttl = r.ttl(k)
                    producer = k.split(":")[1] if ":" in k else k
                    v_str = str(val or 0)
                    status = "OVER QUOTA (>100)" if int(val or 0) > 100 else "WITHIN QUOTA"
                    print(f"    > {k:<36} | {producer:<18} | Count: {v_str:<4} | {status} (TTL: {ttl}s)")

            # 2. Adaptive Lane Queues in Redis
            print("\n -- Adaptive Lane Queues Stored in Redis:")
            for lane in ["execute", "batch", "defer", "shed"]:
                lane_key = f"lane:{lane}"
                items = r.lrange(lane_key, 0, 4)
                cnt = r.llen(lane_key)
                print(f"    > Lane [{lane.upper():<7}]: {cnt:<5} recent events in Redis queue")
                for item in items:
                    print(f"       * {item}")

            # 3. Individual Scored Event Records in Redis
            event_keys = r.keys("event:*")
            print(f"\n -- Scored Event Hash Records in Redis: {len(event_keys)} cached events")
            if event_keys:
                sample_key = event_keys[0]
                data = r.hgetall(sample_key)
                print(f"    Sample Record ({sample_key}): {data}")

            time.sleep(1.5)
    except KeyboardInterrupt:
        print("\nInspector stopped.")


if __name__ == "__main__":
    main()
