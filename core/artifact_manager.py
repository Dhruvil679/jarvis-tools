from __future__ import annotations

from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional
import sqlite3
import threading
import time
import uuid

from .logger import get_logger


logger = get_logger(__name__)


@dataclass(slots=True)
class ArtifactRecord:
    artifact_id: str
    type: str
    path: str
    created_by: str
    created_at: float

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class ArtifactManager:
    def __init__(self, db_path: Optional[str] = None) -> None:
        self.repo_root = Path(__file__).resolve().parent.parent
        self.db_path = Path(db_path) if db_path else self.repo_root / "memory" / "artifacts.db"
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
                    CREATE TABLE IF NOT EXISTS artifacts (
                        artifact_id TEXT PRIMARY KEY,
                        type TEXT NOT NULL,
                        path TEXT NOT NULL UNIQUE,
                        created_by TEXT NOT NULL,
                        created_at REAL NOT NULL
                    )
                    """
                )
                self._conn.execute("CREATE INDEX IF NOT EXISTS idx_artifacts_type ON artifacts(type)")
                self._conn.execute("CREATE INDEX IF NOT EXISTS idx_artifacts_created_by ON artifacts(created_by)")
                self._conn.execute("CREATE INDEX IF NOT EXISTS idx_artifacts_created_at ON artifacts(created_at)")

    def track_artifact(self, artifact_type: str, path: str, created_by: str) -> ArtifactRecord:
        record = ArtifactRecord(
            artifact_id=uuid.uuid4().hex,
            type=artifact_type,
            path=path,
            created_by=created_by,
            created_at=time.time(),
        )
        with self._lock:
            with self._conn:
                self._conn.execute(
                    """
                    INSERT OR REPLACE INTO artifacts (artifact_id, type, path, created_by, created_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (record.artifact_id, record.type, record.path, record.created_by, record.created_at),
                )
        logger.info(
            "Artifact tracked: artifact_id=%s type=%s path=%s created_by=%s",
            record.artifact_id,
            record.type,
            record.path,
            record.created_by,
        )
        return record

    def get_artifact(self, artifact_id: str) -> Optional[ArtifactRecord]:
        with self._lock:
            cursor = self._conn.cursor()
            cursor.execute("SELECT * FROM artifacts WHERE artifact_id = ?", (artifact_id,))
            row = cursor.fetchone()
        if not row:
            return None
        return ArtifactRecord(
            artifact_id=row["artifact_id"],
            type=row["type"],
            path=row["path"],
            created_by=row["created_by"],
            created_at=row["created_at"],
        )

    def list_artifacts(self, limit: int = 100) -> List[ArtifactRecord]:
        with self._lock:
            cursor = self._conn.cursor()
            cursor.execute("SELECT * FROM artifacts ORDER BY created_at DESC LIMIT ?", (int(limit),))
            rows = cursor.fetchall()
        return [
            ArtifactRecord(
                artifact_id=row["artifact_id"],
                type=row["type"],
                path=row["path"],
                created_by=row["created_by"],
                created_at=row["created_at"],
            )
            for row in rows
        ]

    def close(self) -> None:
        try:
            self._conn.close()
        except Exception:
            pass


class ToolAuditStore:
    def __init__(self, db_path: Optional[str] = None) -> None:
        self.repo_root = Path(__file__).resolve().parent.parent
        self.db_path = Path(db_path) if db_path else self.repo_root / "memory" / "tool_audit.db"
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
                    CREATE TABLE IF NOT EXISTS tool_audit (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        agent TEXT NOT NULL,
                        tool TEXT NOT NULL,
                        status TEXT NOT NULL,
                        timestamp REAL NOT NULL,
                        result_summary TEXT DEFAULT ''
                    )
                    """
                )
                self._conn.execute("CREATE INDEX IF NOT EXISTS idx_tool_audit_timestamp ON tool_audit(timestamp)")
                self._conn.execute("CREATE INDEX IF NOT EXISTS idx_tool_audit_agent ON tool_audit(agent)")
                self._conn.execute("CREATE INDEX IF NOT EXISTS idx_tool_audit_tool ON tool_audit(tool)")

    def log(self, agent: str, tool: str, status: str, result_summary: str = "") -> None:
        with self._lock:
            with self._conn:
                self._conn.execute(
                    "INSERT INTO tool_audit (agent, tool, status, timestamp, result_summary) VALUES (?, ?, ?, ?, ?)",
                    (agent, tool, status, time.time(), result_summary),
                )

    def list_audit(self, limit: int = 200) -> List[Dict[str, Any]]:
        with self._lock:
            cursor = self._conn.cursor()
            cursor.execute(
                "SELECT agent, tool, status, timestamp, result_summary FROM tool_audit ORDER BY timestamp DESC LIMIT ?",
                (int(limit),),
            )
            rows = cursor.fetchall()
        return [dict(row) for row in rows]

    def close(self) -> None:
        try:
            self._conn.close()
        except Exception:
            pass


__all__ = ["ArtifactManager", "ArtifactRecord", "ToolAuditStore"]
