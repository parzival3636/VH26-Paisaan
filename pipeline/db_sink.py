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

    def get_db_info(self) -> dict[str, Any]:
        abs_path = os.path.abspath(self.db_path)
        size_bytes = os.path.getsize(abs_path) if os.path.exists(abs_path) else 0
        
        with self._get_connection() as conn:
            cursor = conn.cursor()
            try:
                cursor.execute("PRAGMA journal_mode;")
                row = cursor.fetchone()
                journal_mode = row[0] if row else "delete"
            except Exception:
                journal_mode = "unknown"
            
            try:
                cursor.execute("SELECT sqlite_version();")
                row = cursor.fetchone()
                sqlite_version = row[0] if row else "3.x"
            except Exception:
                sqlite_version = "3.x"
            
            try:
                cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%';")
                tables = [r[0] for r in cursor.fetchall()]
            except Exception:
                tables = []
            
            table_info = []
            for t in tables:
                try:
                    cursor.execute(f"SELECT COUNT(*) FROM {t};")
                    count = cursor.fetchone()[0]
                    cursor.execute(f"PRAGMA table_info({t});")
                    cols = [{"name": c[1], "type": c[2]} for c in cursor.fetchall()]
                    table_info.append({
                        "name": t,
                        "rows": count,
                        "columns": cols
                    })
                except Exception:
                    pass

        return {
            "db_path": abs_path,
            "filename": os.path.basename(abs_path),
            "size_bytes": size_bytes,
            "size_mb": round(size_bytes / (1024 * 1024), 2),
            "journal_mode": str(journal_mode),
            "sqlite_version": str(sqlite_version),
            "tables": table_info
        }

    def browse_records(
        self,
        limit: int = 25,
        offset: int = 0,
        event_type: Optional[str] = None,
        priority_band: Optional[str] = None,
        lane_action: Optional[str] = None,
        search: Optional[str] = None,
    ) -> dict[str, Any]:
        where_clauses = []
        params: list[Any] = []

        if event_type and event_type != "all":
            where_clauses.append("event_type = ?")
            params.append(event_type)

        if priority_band and priority_band != "all":
            where_clauses.append("priority_band = ?")
            params.append(priority_band)

        if lane_action and lane_action != "all":
            where_clauses.append("lane_action = ?")
            params.append(lane_action)

        if search and search.strip():
            term = f"%{search.strip()}%"
            where_clauses.append("(event_id LIKE ? OR producer_id LIKE ?)")
            params.extend([term, term])

        where_sql = (" WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

        count_sql = f"SELECT COUNT(*) FROM order_history{where_sql};"
        query_sql = f"SELECT * FROM order_history{where_sql} ORDER BY id DESC LIMIT ? OFFSET ?;"

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(count_sql, params)
            total_filtered = cursor.fetchone()[0]

            query_params = list(params) + [limit, offset]
            cursor.execute(query_sql, query_params)
            rows = [dict(r) for r in cursor.fetchall()]

            # Parse payload_json if string
            for r in rows:
                if isinstance(r.get("payload_json"), str):
                    try:
                        r["payload_json"] = json.loads(r["payload_json"])
                    except Exception:
                        pass

        return {
            "total_records": total_filtered,
            "limit": limit,
            "offset": offset,
            "rows": rows
        }


# Global singleton database sink
db_sink = DatabaseSink()
