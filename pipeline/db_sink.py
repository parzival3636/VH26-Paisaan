"""
pipeline/db_sink.py — Permanent Database Storage Sink for Processed Transactions

Acts as the long-term order history database (like Amazon's permanent order store).
Consumes processed events from Kafka / Gateway and writes them to a persistent database.
"""

import sqlite3
import os
import time
import json
import logging
from typing import Any, Optional

logger = logging.getLogger("pipeline.db_sink")

DB_PATH = os.environ.get("DATABASE_PATH", "permanent_order_history.db")


class DatabaseSink:
    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=10.0)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS order_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_id TEXT UNIQUE NOT NULL,
                    producer_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    monetary_amount REAL DEFAULT 0.0,
                    score REAL NOT NULL,
                    lane_action TEXT NOT NULL,
                    priority_band TEXT NOT NULL,
                    durability_mode TEXT NOT NULL,
                    payload_json TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_event_id ON order_history(event_id);
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_producer ON order_history(producer_id);
            """)
            conn.commit()
        logger.info(f"Initialized Database Sink at: {os.path.abspath(self.db_path)}")

    def record_transaction(self, event_record: dict[str, Any]) -> bool:
        eid = event_record.get("full_event_id") or event_record.get("event_id")
        if not eid:
            return False

        producer = event_record.get("producer", "unknown")
        etype = event_record.get("type", "unknown")
        score = event_record.get("final_score", 0.0)
        action = event_record.get("action", "execute")
        band = event_record.get("band", "Standard")
        durability = event_record.get("durability", "kafka")
        payload = event_record.get("components", {})

        amount = 0.0
        if isinstance(payload, dict):
            amount = payload.get("monetary", 0.0)

        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT OR IGNORE INTO order_history (
                        event_id, producer_id, event_type, monetary_amount,
                        score, lane_action, priority_band, durability_mode, payload_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
                """, (
                    eid, producer, etype, amount,
                    score, action, band, durability, json.dumps(payload)
                ))
                conn.commit()
            return True
        except Exception as e:
            logger.error(f"Failed to record transaction to DB sink: {e}")
            return False

    def query_history(self, limit: int = 50, etype: Optional[str] = None) -> list[dict[str, Any]]:
        query = "SELECT * FROM order_history"
        params = []
        if etype:
            query += " WHERE event_type = ?"
            params.append(etype)
        query += " ORDER BY id DESC LIMIT ?"
        params.append(limit)

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query, params)
            rows = cursor.fetchall()
            return [dict(r) for r in rows]

    def get_total_orders_count(self) -> int:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM order_history;")
            return cursor.fetchone()[0]


# Global singleton database sink
db_sink = DatabaseSink()
