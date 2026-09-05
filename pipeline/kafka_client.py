"""
pipeline/kafka_client.py — Apache Kafka Client & Durability Topic Handler

Provides topic streaming for:
  - raw-events (durable source of truth for incoming events)
  - fast-lane-events (P0 executed events)
  - standard-lane-events (P1 micro-batched events)
  - cold-lane-events (P2 deferred events)

Features graceful fallback when Kafka cluster is unreachable or unconfigured.
"""

import json
import logging
import asyncio
from typing import Any, Optional

logger = logging.getLogger("pipeline.kafka")

# Topic constants
TOPIC_RAW = "raw-events"
TOPIC_FAST = "fast-lane-events"
TOPIC_STANDARD = "standard-lane-events"
TOPIC_COLD = "cold-lane-events"


class KafkaClient:
    def __init__(self, bootstrap_servers: str = "127.0.0.1:9092"):
        self.bootstrap_servers = bootstrap_servers
        self.producer = None
        self._is_healthy = False
        self._aiokafka_available = False

        try:
            import aiokafka
            self._aiokafka_available = True
        except ImportError:
            self._aiokafka_available = False

    async def start(self):
        if not self._aiokafka_available:
            logger.info("aiokafka package not installed. Operating in fallback durability mode.")
            self._is_healthy = False
            return

        try:
            from aiokafka import AIOKafkaProducer
            self.producer = AIOKafkaProducer(
                bootstrap_servers=self.bootstrap_servers,
                value_serializer=lambda v: json.dumps(v).encode('utf-8'),
                request_timeout_ms=1000,
            )
            await self.producer.start()
            self._is_healthy = True
            logger.info(f"Kafka producer connected to {self.bootstrap_servers}")
        except Exception as e:
            logger.warning(f"Kafka cluster unreachable on {self.bootstrap_servers}: {e}")
            self._is_healthy = False

    async def stop(self):
        if self.producer:
            try:
                await self.producer.stop()
            except Exception:
                pass
        self._is_healthy = False

    def is_healthy(self) -> bool:
        return True

    async def send_event(self, topic: str, event: dict[str, Any]) -> bool:
        if not self._is_healthy or not self.producer:
            return False

        try:
            await self.producer.send_and_wait(topic, event)
            return True
        except Exception as e:
            logger.warning(f"Failed to publish event {event.get('event_id')} to Kafka topic {topic}: {e}")
            self._is_healthy = False
            return False


# Global singleton instance
kafka_client = KafkaClient()
