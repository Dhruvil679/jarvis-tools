from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional
import json
import sqlite3
import threading
import time
import uuid

from .execution_trace import ExecutionTrace
from .logger import get_logger


logger = get_logger(__name__)


class TraceManager:
    def __init__(self, db_path: Optional[str] = None) -> None:
        self.repo_root = Path(__file__).resolve().parent.parent
        self.db_path = Path(db_path) if db_path else self.repo_root / "memory" / "executions.db"
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_db()

    def _init_db(self) -> None:
        with self._lock:
            with self._conn:
                self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS execution_traces (
                    execution_id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL,
                    parent_task_id TEXT DEFAULT '',
                    agent_name TEXT DEFAULT '',
                    action_type TEXT DEFAULT '',
                    status TEXT DEFAULT '',
                    start_time REAL NOT NULL,
                    end_time REAL NOT NULL DEFAULT 0.0,
                    duration_ms REAL NOT NULL DEFAULT 0.0,
                    result_summary TEXT DEFAULT '',
                    error_message TEXT DEFAULT ''
                )
                """
                )
                self._conn.execute("CREATE INDEX IF NOT EXISTS idx_execution_traces_task_id ON execution_traces(task_id)")
                self._conn.execute("CREATE INDEX IF NOT EXISTS idx_execution_traces_parent_task_id ON execution_traces(parent_task_id)")
                self._conn.execute("CREATE INDEX IF NOT EXISTS idx_execution_traces_agent_name ON execution_traces(agent_name)")
                self._conn.execute("CREATE INDEX IF NOT EXISTS idx_execution_traces_status ON execution_traces(status)")
                self._conn.execute("CREATE INDEX IF NOT EXISTS idx_execution_traces_start_time ON execution_traces(start_time)")

    def create_trace(self, **kwargs: Any) -> ExecutionTrace:
        execution_id = str(kwargs.get("execution_id") or uuid.uuid4().hex)
        trace = ExecutionTrace(
            execution_id=execution_id,
            task_id=str(kwargs.get("task_id") or ""),
            parent_task_id=str(kwargs.get("parent_task_id") or ""),
            agent_name=str(kwargs.get("agent_name") or ""),
            action_type=str(kwargs.get("action_type") or ""),
            status=str(kwargs.get("status") or "running"),
            start_time=float(kwargs.get("start_time") or time.time()),
            end_time=float(kwargs.get("end_time") or 0.0),
            duration_ms=float(kwargs.get("duration_ms") or 0.0),
            result_summary=str(kwargs.get("result_summary") or ""),
            error_message=str(kwargs.get("error_message") or ""),
        )
        with self._lock:
            with self._conn:
                self._conn.execute(
                """
                INSERT OR REPLACE INTO execution_traces (
                    execution_id, task_id, parent_task_id, agent_name, action_type, status,
                    start_time, end_time, duration_ms, result_summary, error_message
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    trace.execution_id,
                    trace.task_id,
                    trace.parent_task_id,
                    trace.agent_name,
                    trace.action_type,
                    trace.status,
                    trace.start_time,
                    trace.end_time,
                    trace.duration_ms,
                    trace.result_summary,
                    trace.error_message,
                ),
                )
        logger.info(
            "Trace created: execution_id=%s task_id=%s agent=%s action_type=%s status=%s",
            trace.execution_id,
            trace.task_id,
            trace.agent_name,
            trace.action_type,
            trace.status,
        )
        return trace

    def update_trace(self, execution_id: str, **kwargs: Any) -> Optional[ExecutionTrace]:
        with self._lock:
            existing = self.get_trace(execution_id)
            if existing is None:
                return None
            payload = existing.to_dict()
            payload.update({k: v for k, v in kwargs.items() if v is not None})
            trace = ExecutionTrace.from_row(payload)
            with self._conn:
                self._conn.execute(
                """
                UPDATE execution_traces SET
                    task_id=?, parent_task_id=?, agent_name=?, action_type=?, status=?,
                    start_time=?, end_time=?, duration_ms=?, result_summary=?, error_message=?
                WHERE execution_id=?
                """,
                (
                    trace.task_id,
                    trace.parent_task_id,
                    trace.agent_name,
                    trace.action_type,
                    trace.status,
                    trace.start_time,
                    trace.end_time,
                    trace.duration_ms,
                    trace.result_summary,
                    trace.error_message,
                    execution_id,
                ),
                )
        logger.info(
            "Trace updated: execution_id=%s status=%s duration_ms=%.2f",
            trace.execution_id,
            trace.status,
            trace.duration_ms,
        )
        return trace

    def complete_trace(self, execution_id: str, result_summary: str = "") -> Optional[ExecutionTrace]:
        with self._lock:
            started = self.get_trace(execution_id)
            if started is None:
                return None
            end_time = time.time()
            duration_ms = max(0.0, (end_time - started.start_time) * 1000.0)
            logger.info("Trace completed: execution_id=%s", execution_id)
            return self.update_trace(
                execution_id,
                status="completed",
                end_time=end_time,
                duration_ms=duration_ms,
                result_summary=result_summary or started.result_summary,
                error_message="",
            )

    def fail_trace(self, execution_id: str, error_message: str) -> Optional[ExecutionTrace]:
        with self._lock:
            started = self.get_trace(execution_id)
            if started is None:
                return None
            end_time = time.time()
            duration_ms = max(0.0, (end_time - started.start_time) * 1000.0)
            logger.info("Trace failed: execution_id=%s error=%s", execution_id, error_message)
            return self.update_trace(
                execution_id,
                status="failed",
                end_time=end_time,
                duration_ms=duration_ms,
                error_message=error_message,
            )

    def health_check(self) -> Dict[str, Any]:
        try:
            with self._lock:
                cursor = self._conn.cursor()
                cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='execution_traces'")
                table_exists = cursor.fetchone() is not None
                cursor.execute("SELECT COUNT(1) FROM execution_traces")
                count = int(cursor.fetchone()[0] or 0) if table_exists else 0
                return {
                    "ok": table_exists,
                    "db_path": str(self.db_path),
                    "table_exists": table_exists,
                    "trace_count": count,
                }
        except Exception as exc:
            return {
                "ok": False,
                "db_path": str(self.db_path),
                "table_exists": False,
                "trace_count": 0,
                "error": str(exc),
            }

    def get_trace(self, execution_id: str) -> Optional[ExecutionTrace]:
        with self._lock:
            cursor = self._conn.cursor()
            cursor.execute("SELECT * FROM execution_traces WHERE execution_id = ?", (execution_id,))
            row = cursor.fetchone()
            return ExecutionTrace.from_row(dict(row)) if row else None

    def list_traces(self, limit: int = 100, agent_name: str = "", status: str = "") -> List[ExecutionTrace]:
        query = "SELECT * FROM execution_traces"
        clauses: List[str] = []
        params: List[Any] = []
        if agent_name:
            clauses.append("agent_name = ?")
            params.append(agent_name)
        if status:
            clauses.append("status = ?")
            params.append(status)
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY start_time DESC LIMIT ?"
        params.append(int(limit))
        with self._lock:
            cursor = self._conn.cursor()
            cursor.execute(query, params)
            rows = cursor.fetchall()
            return [ExecutionTrace.from_row(dict(row)) for row in rows]

    def snapshot(self, limit: int = 100) -> Dict[str, Any]:
        traces = self.list_traces(limit=limit)
        return {
            "db_path": str(self.db_path),
            "traces": [trace.to_dict() for trace in traces],
        }

    def close(self) -> None:
        try:
            self._conn.close()
        except Exception:
            pass


__all__ = ["TraceManager"]
