from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional
import json
import sqlite3
import threading
import time

from .agent_models import slugify

DEFAULT_MEMORY_ROOT = Path(__file__).resolve().parent.parent / "memory"


class AgentMemoryStore:
    def __init__(
        self,
        agent_name: str = "jarvis",
        db_path: Optional[str] = None,
        memory_root: Optional[str] = None,
        max_history: int = 200,
    ) -> None:
        self.agent_name = slugify(agent_name)
        self.max_history = int(max_history)
        self.memory_root = Path(memory_root) if memory_root else DEFAULT_MEMORY_ROOT
        self.db_path = Path(db_path) if db_path else self.memory_root / f"{self.agent_name}.db"
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_db()

    def _init_db(self) -> None:
        with self._conn:
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    ts REAL NOT NULL,
                    metadata TEXT DEFAULT '{}'
                )
                """
            )
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS summaries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    ts REAL NOT NULL
                )
                """
            )
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS facts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    key TEXT NOT NULL UNIQUE,
                    value TEXT NOT NULL,
                    confidence REAL NOT NULL DEFAULT 1.0,
                    ts REAL NOT NULL
                )
                """
            )
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_type TEXT NOT NULL,
                    source_agent TEXT,
                    target_agent TEXT,
                    task TEXT,
                    message TEXT,
                    confidence REAL NOT NULL DEFAULT 0.0,
                    payload TEXT DEFAULT '{}',
                    ts REAL NOT NULL
                )
                """
            )
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS status (
                    agent TEXT PRIMARY KEY,
                    state TEXT NOT NULL,
                    confidence REAL NOT NULL DEFAULT 0.0,
                    active_task TEXT DEFAULT '',
                    last_message TEXT DEFAULT '',
                    last_sender TEXT DEFAULT '',
                    last_update REAL NOT NULL DEFAULT 0.0,
                    run_count INTEGER NOT NULL DEFAULT 0,
                    error_count INTEGER NOT NULL DEFAULT 0
                )
                """
            )
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS tasks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id TEXT NOT NULL,
                    agent TEXT NOT NULL,
                    task TEXT NOT NULL,
                    tool TEXT DEFAULT '',
                    state TEXT NOT NULL,
                    result TEXT DEFAULT '',
                    error TEXT DEFAULT '',
                    duration_seconds REAL NOT NULL DEFAULT 0.0,
                    iteration INTEGER NOT NULL DEFAULT 0,
                    metadata TEXT DEFAULT '{}',
                    ts REAL NOT NULL
                )
                """
            )
            self._conn.execute("CREATE INDEX IF NOT EXISTS idx_messages_ts ON messages(ts)")
            self._conn.execute("CREATE INDEX IF NOT EXISTS idx_summaries_ts ON summaries(ts)")
            self._conn.execute("CREATE INDEX IF NOT EXISTS idx_events_ts ON events(ts)")
            self._conn.execute("CREATE INDEX IF NOT EXISTS idx_status_state ON status(state)")
            self._conn.execute("CREATE INDEX IF NOT EXISTS idx_tasks_task_id ON tasks(task_id)")
            self._conn.execute("CREATE INDEX IF NOT EXISTS idx_tasks_state ON tasks(state)")

    def add_message(self, role: str, content: str, metadata: Optional[Dict[str, Any]] = None) -> None:
        if not content:
            return
        payload = json.dumps(metadata or {}, ensure_ascii=True)
        ts = time.time()
        with self._lock:
            with self._conn:
                self._conn.execute(
                    "INSERT INTO messages (role, content, ts, metadata) VALUES (?, ?, ?, ?)",
                    (role, content, ts, payload),
                )
            self._trim_if_needed()

    def remember_fact(self, key: str, value: str, confidence: float = 1.0) -> None:
        if not key or not value:
            return
        with self._lock:
            with self._conn:
                self._conn.execute(
                    """
                    INSERT INTO facts (key, value, confidence, ts)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(key) DO UPDATE SET
                        value=excluded.value,
                        confidence=excluded.confidence,
                        ts=excluded.ts
                    """,
                    (key, value, float(confidence), time.time()),
                )

    def remember_summary(self, source: str, summary: str) -> None:
        if not summary:
            return
        with self._lock:
            with self._conn:
                self._conn.execute(
                    "INSERT INTO summaries (source, summary, ts) VALUES (?, ?, ?)",
                    (source, summary, time.time()),
                )

    def log_event(
        self,
        event_type: str,
        source_agent: Optional[str] = None,
        target_agent: Optional[str] = None,
        task: str = "",
        message: str = "",
        confidence: float = 0.0,
        payload: Optional[Dict[str, Any]] = None,
    ) -> None:
        payload_text = json.dumps(payload or {}, ensure_ascii=True)
        with self._lock:
            with self._conn:
                self._conn.execute(
                    """
                    INSERT INTO events (event_type, source_agent, target_agent, task, message, confidence, payload, ts)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        event_type,
                        source_agent,
                        target_agent,
                        task,
                        message,
                        float(confidence),
                        payload_text,
                        time.time(),
                    ),
                )

    def set_status(
        self,
        state: str,
        confidence: float = 0.0,
        active_task: str = "",
        last_message: str = "",
        last_sender: str = "",
        increment_run: bool = False,
        increment_error: bool = False,
    ) -> None:
        ts = time.time()
        with self._lock:
            with self._conn:
                self._conn.execute(
                    """
                    INSERT INTO status (agent, state, confidence, active_task, last_message, last_sender, last_update, run_count, error_count)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(agent) DO UPDATE SET
                        state=excluded.state,
                        confidence=excluded.confidence,
                        active_task=excluded.active_task,
                        last_message=excluded.last_message,
                        last_sender=excluded.last_sender,
                        last_update=excluded.last_update,
                        run_count=status.run_count + ?,
                        error_count=status.error_count + ?
                    """,
                    (
                        self.agent_name,
                        state,
                        float(confidence),
                        active_task,
                        last_message,
                        last_sender,
                        ts,
                        1 if increment_run else 0,
                        1 if increment_error else 0,
                        1 if increment_run else 0,
                        1 if increment_error else 0,
                    ),
                )

    def record_task(
        self,
        task_id: str,
        task: str,
        state: str,
        tool: str = "",
        result: str = "",
        error: str = "",
        duration_seconds: float = 0.0,
        iteration: int = 0,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        payload = json.dumps(metadata or {}, ensure_ascii=True)
        with self._lock:
            with self._conn:
                self._conn.execute(
                    """
                    INSERT INTO tasks (task_id, agent, task, tool, state, result, error, duration_seconds, iteration, metadata, ts)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        task_id,
                        self.agent_name,
                        task,
                        tool,
                        state,
                        result,
                        error,
                        float(duration_seconds),
                        int(iteration),
                        payload,
                        time.time(),
                    ),
                )

    def get_status(self) -> Dict[str, Any]:
        try:
            cursor = self._conn.cursor()
            cursor.execute(
                "SELECT agent, state, confidence, active_task, last_message, last_sender, last_update, run_count, error_count FROM status WHERE agent = ?",
                (self.agent_name,),
            )
            row = cursor.fetchone()
            if not row:
                return {
                    "agent": self.agent_name,
                    "state": "idle",
                    "confidence": 0.0,
                    "active_task": "",
                    "last_message": "",
                    "last_sender": "",
                    "last_update": 0.0,
                    "run_count": 0,
                    "error_count": 0,
                }
            return dict(row)
        except Exception:
            return {
                "agent": self.agent_name,
                "state": "idle",
                "confidence": 0.0,
                "active_task": "",
                "last_message": "",
                "last_sender": "",
                "last_update": 0.0,
                "run_count": 0,
                "error_count": 0,
            }

    def get_tasks(self, limit: int = 50) -> List[Dict[str, Any]]:
        try:
            cursor = self._conn.cursor()
            cursor.execute(
                """
                SELECT task_id, agent, task, tool, state, result, error, duration_seconds, iteration, metadata, ts
                FROM tasks
                ORDER BY ts DESC
                LIMIT ?
                """,
                (int(limit),),
            )
            rows = cursor.fetchall()
            rows.reverse()
            tasks: List[Dict[str, Any]] = []
            for row in rows:
                try:
                    metadata = json.loads(row["metadata"] or "{}")
                except Exception:
                    metadata = {}
                tasks.append(
                    {
                        "task_id": row["task_id"],
                        "agent": row["agent"],
                        "task": row["task"],
                        "tool": row["tool"],
                        "state": row["state"],
                        "result": row["result"],
                        "error": row["error"],
                        "duration_seconds": row["duration_seconds"],
                        "iteration": row["iteration"],
                        "metadata": metadata,
                        "ts": row["ts"],
                    }
                )
            return tasks
        except Exception:
            return []

    def get_recent_messages(self, limit: int = 20) -> List[Dict[str, Any]]:
        try:
            cursor = self._conn.cursor()
            cursor.execute(
                "SELECT role, content, ts, metadata FROM messages ORDER BY ts DESC LIMIT ?",
                (int(limit),),
            )
            rows = cursor.fetchall()
            rows.reverse()
            results: List[Dict[str, Any]] = []
            for row in rows:
                try:
                    metadata = json.loads(row["metadata"] or "{}")
                except Exception:
                    metadata = {}
                results.append(
                    {
                        "role": row["role"],
                        "content": row["content"],
                        "ts": row["ts"],
                        "metadata": metadata,
                    }
                )
            return results
        except Exception:
            return []

    def get_recent_context(self, limit: int = 20) -> List[Dict[str, Any]]:
        return self.get_recent_messages(limit)

    def get_summaries(self, limit: int = 20) -> List[Dict[str, Any]]:
        try:
            cursor = self._conn.cursor()
            cursor.execute(
                "SELECT source, summary, ts FROM summaries ORDER BY ts DESC LIMIT ?",
                (int(limit),),
            )
            rows = cursor.fetchall()
            rows.reverse()
            return [{"source": row["source"], "summary": row["summary"], "ts": row["ts"]} for row in rows]
        except Exception:
            return []

    def get_facts(self, limit: int = 50) -> List[Dict[str, Any]]:
        try:
            cursor = self._conn.cursor()
            cursor.execute(
                "SELECT key, value, confidence, ts FROM facts ORDER BY ts DESC LIMIT ?",
                (int(limit),),
            )
            rows = cursor.fetchall()
            rows.reverse()
            return [
                {
                    "key": row["key"],
                    "value": row["value"],
                    "confidence": row["confidence"],
                    "ts": row["ts"],
                }
                for row in rows
            ]
        except Exception:
            return []

    def get_events(self, limit: int = 50) -> List[Dict[str, Any]]:
        try:
            cursor = self._conn.cursor()
            cursor.execute(
                """
                SELECT event_type, source_agent, target_agent, task, message, confidence, payload, ts
                FROM events
                ORDER BY ts DESC
                LIMIT ?
                """,
                (int(limit),),
            )
            rows = cursor.fetchall()
            rows.reverse()
            result: List[Dict[str, Any]] = []
            for row in rows:
                try:
                    payload = json.loads(row["payload"] or "{}")
                except Exception:
                    payload = {}
                result.append(
                    {
                        "event_type": row["event_type"],
                        "source_agent": row["source_agent"],
                        "target_agent": row["target_agent"],
                        "task": row["task"],
                        "message": row["message"],
                        "confidence": row["confidence"],
                        "payload": payload,
                        "ts": row["ts"],
                    }
                )
            return result
        except Exception:
            return []

    def snapshot(self, limit: int = 20) -> Dict[str, Any]:
        return {
            "agent": self.agent_name,
            "db_path": str(self.db_path),
            "messages": self.get_recent_messages(limit),
            "summaries": self.get_summaries(limit),
            "facts": self.get_facts(limit),
            "events": self.get_events(limit),
            "tasks": self.get_tasks(limit),
            "status": self.get_status(),
        }

    def _trim_if_needed(self) -> None:
        cursor = self._conn.cursor()
        cursor.execute("SELECT COUNT(1) FROM messages")
        total = int(cursor.fetchone()[0] or 0)
        if total <= self.max_history:
            return
        to_delete = total - self.max_history
        cursor.execute(
            "DELETE FROM messages WHERE id IN (SELECT id FROM messages ORDER BY ts ASC LIMIT ?)",
            (to_delete,),
        )
        self._conn.commit()

    def clear(self) -> None:
        with self._lock:
            with self._conn:
                self._conn.execute("DELETE FROM messages")
                self._conn.execute("DELETE FROM summaries")
                self._conn.execute("DELETE FROM facts")
                self._conn.execute("DELETE FROM events")
                self._conn.execute("DELETE FROM status")
                self._conn.execute("DELETE FROM tasks")

    def close(self) -> None:
        try:
            self._conn.close()
        except Exception:
            pass


__all__ = ["AgentMemoryStore"]
