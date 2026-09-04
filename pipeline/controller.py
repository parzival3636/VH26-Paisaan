"""
pipeline/controller.py — Self-Tuning PID Threshold Controller & Cold Lane Re-Scorer

Components:
1. PIDThresholdController:
   Feedback control loop that recomputes every 5 seconds:
     error = target_p0_latency_ms - actual_p0_latency_ms_rolling_avg
     adjustment = (Kp * error) + (Ki * integral) + (Kd * derivative)
   Dynamically auto-tunes EXECUTE_THRESHOLD to keep P0 fast-lane latency under SLA.

2. ColdLaneRescorer:
   Background worker process that scans cold deferred events every 3-5 seconds,
   re-evaluates their urgency against current live_state, and promotes them
   back to standard micro-batch or fast lane as system load eases.
"""

import time
import logging
import asyncio
from typing import Any, Optional, Callable

from pipeline.scoring import SystemState, score_event, Thresholds, Action

logger = logging.getLogger("pipeline.controller")


def clamp(val: float, min_val: float, max_val: float) -> float:
    return max(min_val, min(max_val, val))


class PIDThresholdController:
    """
    PID feedback loop that auto-adjusts EXECUTE_THRESHOLD based on P0 latency error.
    Kp=0.01, Ki=0.001, Kd=0.005
    """
    def __init__(
        self,
        target_p0_latency_ms: float = 50.0,
        kp: float = 0.01,
        ki: float = 0.001,
        kd: float = 0.005,
        min_threshold: float = 4.0,
        max_threshold: float = 9.0,
    ):
        self.target_p0_latency_ms = target_p0_latency_ms
        self.kp = kp
        self.ki = ki
        self.kd = kd
        self.min_threshold = min_threshold
        self.max_threshold = max_threshold

        self.current_execute_threshold = 6.0
        self.integral = 0.0
        self.last_error = 0.0
        self.last_time = time.monotonic()
        self.history: list[dict[str, Any]] = []

    def update(self, actual_p0_latency_ms: float) -> float:
        now = time.monotonic()
        dt = max(now - self.last_time, 0.1)

        # positive error means actual latency is below target (headroom available -> lower threshold to allow more events)
        # negative error means actual latency exceeded target (overload -> raise threshold to protect P0 SLA)
        error = actual_p0_latency_ms - self.target_p0_latency_ms

        self.integral += error * dt
        # anti-windup clamping for integral term
        self.integral = clamp(self.integral, -1000.0, 1000.0)

        derivative = (error - self.last_error) / dt
        adjustment = (self.kp * error) + (self.ki * self.integral) + (self.kd * derivative)

        old_val = self.current_execute_threshold
        self.current_execute_threshold = clamp(old_val + adjustment, self.min_threshold, self.max_threshold)

        self.last_error = error
        self.last_time = now

        record = {
            "timestamp": time.time(),
            "target_latency": self.target_p0_latency_ms,
            "actual_latency": round(actual_p0_latency_ms, 2),
            "error": round(error, 2),
            "adjustment": round(adjustment, 4),
            "execute_threshold": round(self.current_execute_threshold, 3),
        }
        self.history.append(record)
        if len(self.history) > 60:
            self.history.pop(0)

        if abs(self.current_execute_threshold - old_val) > 0.01:
            logger.info(f"PID Controller tuned EXECUTE_THRESHOLD: {old_val:.2f} -> {self.current_execute_threshold:.2f} (error: {error:.1f}ms)")

        return self.current_execute_threshold

    def get_status(self) -> dict[str, Any]:
        return {
            "target_p0_latency_ms": self.target_p0_latency_ms,
            "current_execute_threshold": round(self.current_execute_threshold, 3),
            "last_error_ms": round(self.last_error, 2),
            "kp": self.kp,
            "ki": self.ki,
            "kd": self.kd,
            "history": self.history[-10:],
        }


class ColdLaneRescorer:
    """
    Scans cold deferred queue events every 3-5s, re-scores them against current live state,
    and promotes them back into standard/fast execution queues when load eases.
    """
    def __init__(self, check_interval: float = 4.0):
        self.check_interval = check_interval
        self._running = False
        self.promotions_count = 0

    async def start(
        self,
        cold_queue_getter: Callable[[], list[dict[str, Any]]],
        promote_callback: Callable[[dict[str, Any], str], None],
        get_current_state: Callable[[], SystemState],
    ):
        self._running = True
        logger.info("ColdLaneRescorer background loop started.")

        while self._running:
            try:
                await asyncio.sleep(self.check_interval)
                state = get_current_state()
                events = cold_queue_getter()

                if not events:
                    continue

                for event in list(events):
                    time_waiting = time.time() - event.get("timestamp", time.time())
                    rescored = score_event(event, state, time_waiting=time_waiting)

                    act = rescored.get("action")
                    if act in (Action.EXECUTE.value, Action.BATCH.value):
                        promote_callback(event, act)
                        self.promotions_count += 1
                        logger.info(f"ColdLaneRescorer promoted event {event.get('event_id')} to {act} after {time_waiting:.1f}s waiting.")

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in ColdLaneRescorer: {e}")

    def stop(self):
        self._running = False


pid_controller = PIDThresholdController()
cold_rescorer = ColdLaneRescorer()
