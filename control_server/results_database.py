"""
ResultsDatabase — SQLite Backend
=================================
Persistent storage for experiment results using SQLite.
Results survive server restarts.

Database file: cqne_results.db (in the control_server directory)

Schema:
  experiments table:
    - exp_id     TEXT PRIMARY KEY
    - type       TEXT (entangle/teleport/ghz)
    - data       TEXT (JSON blob of full result)
    - created_at REAL (unix timestamp)
    - fidelity   REAL (nullable, for entangle experiments)
    - duration_ms REAL
    - error      TEXT (nullable)

The same public API as before — drop-in replacement for the
in-memory version. All callers (control_server, yaml_runner,
experiment_executor) work without any changes.
"""

import json
import sqlite3
import logging
import time
from pathlib import Path
from typing import Optional

logger = logging.getLogger("ResultsDatabase")

DEFAULT_DB_PATH = Path(__file__).parent / "cqne_results.db"


class ResultsDatabase:
    def __init__(self, db_path: Optional[str] = None):
        self._db_path = str(db_path or DEFAULT_DB_PATH)
        self._init_db()
        logger.info("ResultsDatabase initialised (SQLite: %s)", self._db_path)

    def _init_db(self):
        """Create the experiments table if it doesn't exist."""
        with self._connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS experiments (
                    exp_id      TEXT PRIMARY KEY,
                    type        TEXT NOT NULL,
                    data        TEXT NOT NULL,
                    created_at  REAL NOT NULL,
                    fidelity    REAL,
                    duration_ms REAL,
                    error       TEXT,
                    routed      INTEGER DEFAULT 0,
                    hops        INTEGER DEFAULT 0,
                    source      TEXT,
                    target      TEXT
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_type ON experiments(type)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_created ON experiments(created_at)
            """)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def save(self, result: dict) -> None:
        """Save an experiment result to the database."""
        exp_id = result.get("exp_id")
        if exp_id is None:
            raise ValueError("Result missing 'exp_id' field.")

        exp_type = result.get("type", "unknown")
        created_at = result.get("started_at", time.time())
        fidelity = result.get("fidelity")
        duration_ms = result.get("duration_ms")
        error = result.get("error")
        routed = 1 if result.get("routed") else 0
        hops = result.get("hops", 0)
        source = result.get("source", "")
        target = result.get("target", "")

        # Store full result as JSON
        data_json = json.dumps(result, default=str)

        with self._connect() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO experiments
                    (exp_id, type, data, created_at, fidelity, duration_ms, error, routed, hops, source, target)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (exp_id, exp_type, data_json, created_at, fidelity, duration_ms, error, routed, hops, source, target))

        logger.debug("Saved experiment '%s' (%s)", exp_id, exp_type)

    def get(self, exp_id: str) -> Optional[dict]:
        """Retrieve a single experiment by ID."""
        with self._connect() as conn:
            row = conn.execute("SELECT data FROM experiments WHERE exp_id = ?", (exp_id,)).fetchone()
            if row is None:
                return None
            return json.loads(row["data"])

    def all(self) -> list[dict]:
        """Return all experiments ordered by creation time."""
        with self._connect() as conn:
            rows = conn.execute("SELECT data FROM experiments ORDER BY created_at ASC").fetchall()
            return [json.loads(r["data"]) for r in rows]

    def by_type(self, exp_type: str) -> list[dict]:
        """Return all experiments of a given type."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT data FROM experiments WHERE type = ? ORDER BY created_at ASC",
                (exp_type,)
            ).fetchall()
            return [json.loads(r["data"]) for r in rows]

    def summary(self) -> dict:
        """Return a summary of all experiments."""
        with self._connect() as conn:
            total = conn.execute("SELECT COUNT(*) as c FROM experiments").fetchone()["c"]
            types = conn.execute("SELECT type, COUNT(*) as c FROM experiments GROUP BY type").fetchall()
            errors = conn.execute("SELECT COUNT(*) as c FROM experiments WHERE error IS NOT NULL").fetchone()["c"]

            by_type = {r["type"]: r["c"] for r in types}

            return {
                "total": total,
                "by_type": by_type,
                "errors": errors,
                "success": total - errors,
            }

    def recent(self, limit: int = 50) -> list[dict]:
        """Return the most recent N experiments."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT data FROM experiments ORDER BY created_at DESC LIMIT ?",
                (limit,)
            ).fetchall()
            return [json.loads(r["data"]) for r in reversed(rows)]

    def fidelity_history(self, exp_type: str = "entangle", limit: int = 100) -> list[dict]:
        """Return fidelity values over time for charting."""
        with self._connect() as conn:
            rows = conn.execute("""
                SELECT exp_id, created_at, fidelity, duration_ms, source, target
                FROM experiments
                WHERE type = ? AND fidelity IS NOT NULL
                ORDER BY created_at DESC
                LIMIT ?
            """, (exp_type, limit)).fetchall()

            return [
                {
                    "exp_id": r["exp_id"],
                    "created_at": r["created_at"],
                    "fidelity": r["fidelity"],
                    "duration_ms": r["duration_ms"],
                    "source": r["source"],
                    "target": r["target"],
                }
                for r in reversed(rows)
            ]

    def stats(self) -> dict:
        """Return detailed statistics for the dashboard."""
        with self._connect() as conn:
            total = conn.execute("SELECT COUNT(*) as c FROM experiments").fetchone()["c"]

            avg_fidelity = conn.execute(
                "SELECT AVG(fidelity) as avg_f FROM experiments WHERE fidelity IS NOT NULL"
            ).fetchone()["avg_f"]

            avg_duration = conn.execute(
                "SELECT AVG(duration_ms) as avg_d FROM experiments WHERE duration_ms IS NOT NULL"
            ).fetchone()["avg_d"]

            routed_count = conn.execute(
                "SELECT COUNT(*) as c FROM experiments WHERE routed = 1"
            ).fetchone()["c"]

            return {
                "total_experiments": total,
                "avg_fidelity": round(avg_fidelity, 4) if avg_fidelity else None,
                "avg_duration_ms": round(avg_duration, 2) if avg_duration else None,
                "routed_teleports": routed_count,
            }

    def reset(self) -> None:
        """Clear all experiment results from the database."""
        with self._connect() as conn:
            conn.execute("DELETE FROM experiments")
        logger.info("Experiment results cleared (SQLite)")

    def count(self) -> int:
        """Return total number of experiments."""
        with self._connect() as conn:
            return conn.execute("SELECT COUNT(*) as c FROM experiments").fetchone()["c"]
