from __future__ import annotations

from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional
import sqlite3
import threading
import time
import uuid

from .agent_models import AgentTask, RouteDecision
from .logger import get_logger


logger = get_logger(__name__)


@dataclass(slots=True)
class CollaborationRecord:
    collaboration_id: str
    task_id: str
    parent_agent: str
    child_agent: str
    status: str
    created_at: float

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class CollaborationMessageRecord:
    message_id: str
    collaboration_id: str
    sender_agent: str
    receiver_agent: str
    message: str
    timestamp: float

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class CollaborationEngine:
    def __init__(self, db_path: Optional[str] = None) -> None:
        self.repo_root = Path(__file__).resolve().parent.parent
        self.db_path = Path(db_path) if db_path else self.repo_root / "memory" / "collaboration.db"
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
                    CREATE TABLE IF NOT EXISTS collaborations (
                        collaboration_id TEXT PRIMARY KEY,
                        task_id TEXT NOT NULL,
                        parent_agent TEXT NOT NULL,
                        child_agent TEXT NOT NULL,
                        status TEXT NOT NULL,
                        created_at REAL NOT NULL
                    )
                    """
                )
                self._conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS collaboration_messages (
                        message_id TEXT PRIMARY KEY,
                        collaboration_id TEXT NOT NULL,
                        sender_agent TEXT NOT NULL,
                        receiver_agent TEXT NOT NULL,
                        message TEXT NOT NULL,
                        timestamp REAL NOT NULL,
                        FOREIGN KEY(collaboration_id) REFERENCES collaborations(collaboration_id)
                    )
                    """
                )
                self._conn.execute("CREATE INDEX IF NOT EXISTS idx_collaborations_task_id ON collaborations(task_id)")
                self._conn.execute("CREATE INDEX IF NOT EXISTS idx_collaborations_status ON collaborations(status)")
                self._conn.execute("CREATE INDEX IF NOT EXISTS idx_collaborations_created_at ON collaborations(created_at)")
                self._conn.execute("CREATE INDEX IF NOT EXISTS idx_collab_messages_collab_id ON collaboration_messages(collaboration_id)")
                self._conn.execute("CREATE INDEX IF NOT EXISTS idx_collab_messages_timestamp ON collaboration_messages(timestamp)")

    def create_collaboration(
        self,
        task_id: str,
        parent_agent: str,
        child_agent: str,
        status: str = "active",
    ) -> CollaborationRecord:
        record = CollaborationRecord(
            collaboration_id=uuid.uuid4().hex,
            task_id=task_id,
            parent_agent=parent_agent,
            child_agent=child_agent,
            status=status,
            created_at=time.time(),
        )
        with self._lock:
            with self._conn:
                self._conn.execute(
                    """
                    INSERT INTO collaborations (collaboration_id, task_id, parent_agent, child_agent, status, created_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        record.collaboration_id,
                        record.task_id,
                        record.parent_agent,
                        record.child_agent,
                        record.status,
                        record.created_at,
                    ),
                )
        logger.info(
            "Collaboration created: collaboration_id=%s task_id=%s %s->%s status=%s",
            record.collaboration_id,
            record.task_id,
            record.parent_agent,
            record.child_agent,
            record.status,
        )
        return record

    def record_message(
        self,
        collaboration_id: str,
        sender_agent: str,
        receiver_agent: str,
        message: str,
    ) -> CollaborationMessageRecord:
        record = CollaborationMessageRecord(
            message_id=uuid.uuid4().hex,
            collaboration_id=collaboration_id,
            sender_agent=sender_agent,
            receiver_agent=receiver_agent,
            message=message,
            timestamp=time.time(),
        )
        with self._lock:
            with self._conn:
                self._conn.execute(
                    """
                    INSERT INTO collaboration_messages (message_id, collaboration_id, sender_agent, receiver_agent, message, timestamp)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        record.message_id,
                        record.collaboration_id,
                        record.sender_agent,
                        record.receiver_agent,
                        record.message,
                        record.timestamp,
                    ),
                )
        logger.info(
            "Collaboration message: collaboration_id=%s sender=%s receiver=%s",
            collaboration_id,
            sender_agent,
            receiver_agent,
        )
        return record

    def update_status(self, collaboration_id: str, status: str) -> Optional[CollaborationRecord]:
        with self._lock:
            current = self.get_collaboration(collaboration_id)
            if current is None:
                return None
            with self._conn:
                self._conn.execute(
                    "UPDATE collaborations SET status = ? WHERE collaboration_id = ?",
                    (status, collaboration_id),
                )
        return CollaborationRecord(
            collaboration_id=current["collaboration_id"],
            task_id=current["task_id"],
            parent_agent=current["parent_agent"],
            child_agent=current["child_agent"],
            status=status,
            created_at=current["created_at"],
        )

    def complete_collaboration(self, collaboration_id: str) -> Optional[CollaborationRecord]:
        logger.info("Collaboration completed: collaboration_id=%s", collaboration_id)
        return self.update_status(collaboration_id, "completed")

    def fail_collaboration(self, collaboration_id: str) -> Optional[CollaborationRecord]:
        logger.info("Collaboration failed: collaboration_id=%s", collaboration_id)
        return self.update_status(collaboration_id, "failed")

    def get_collaboration(self, collaboration_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            cursor = self._conn.cursor()
            cursor.execute("SELECT * FROM collaborations WHERE collaboration_id = ?", (collaboration_id,))
            row = cursor.fetchone()
            if row is None:
                return None
            data = dict(row)
            data["message_count"] = self._count_messages(collaboration_id)
            data["progress_percent"] = self._progress_percent(data["status"], data["message_count"])
            data["messages"] = [message.to_dict() for message in self.get_messages(collaboration_id)]
            return data

    def list_collaborations(
        self,
        limit: int = 100,
        status: str = "",
        agent: str = "",
    ) -> List[Dict[str, Any]]:
        query = "SELECT * FROM collaborations"
        clauses: List[str] = []
        params: List[Any] = []
        if status:
            clauses.append("status = ?")
            params.append(status)
        if agent:
            clauses.append("(parent_agent = ? OR child_agent = ?)")
            params.extend([agent, agent])
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(int(limit))
        with self._lock:
            cursor = self._conn.cursor()
            cursor.execute(query, params)
            rows = cursor.fetchall()
        return [self._serialize_row(dict(row)) for row in rows]

    def list_recent(self, limit: int = 20) -> List[Dict[str, Any]]:
        return self.list_collaborations(limit=limit)

    def get_messages(self, collaboration_id: str) -> List[CollaborationMessageRecord]:
        with self._lock:
            cursor = self._conn.cursor()
            cursor.execute(
                """
                SELECT message_id, collaboration_id, sender_agent, receiver_agent, message, timestamp
                FROM collaboration_messages
                WHERE collaboration_id = ?
                ORDER BY timestamp ASC
                """,
                (collaboration_id,),
            )
            rows = cursor.fetchall()
        return [
            CollaborationMessageRecord(
                message_id=row["message_id"],
                collaboration_id=row["collaboration_id"],
                sender_agent=row["sender_agent"],
                receiver_agent=row["receiver_agent"],
                message=row["message"],
                timestamp=row["timestamp"],
            )
            for row in rows
        ]

    def build_collaboration_plan(self, task_id: str, text: str, route: RouteDecision) -> Dict[str, Any]:
        normalized = (text or "").lower()
        if any(keyword in normalized for keyword in ["restaurant", "saas", "platform", "build", "launch", "product"]):
            chain = ["oracle", "friday", "ultron", "vision", "gecko"]
            focuses = {
                "oracle": "Research competitors, pricing, and market positioning.",
                "friday": "Create a project roadmap, milestones, and risk register.",
                "ultron": "Design backend architecture, APIs, and data model.",
                "vision": "Design frontend architecture, UI flow, and interaction surfaces.",
                "gecko": "Draft go-to-market strategy, SEO, and launch marketing.",
            }
        else:
            chain = route.handoff_chain or ([route.primary_agent] + route.collaborators)
            chain = [agent for agent in chain if agent]
            if route.mode != "multi" and chain:
                chain = [chain[0]]
            focuses = {
                "friday": "Provide planning, coordination, and execution summary.",
                "oracle": "Research context and collect external insights.",
                "vision": "Inspect the visual or UI aspects of the task.",
                "ultron": "Implement software and architecture changes.",
                "hulk": "Break work into terminal and execution steps.",
                "spectre": "Review risk, privacy, and compliance implications.",
                "herald": "Draft communications or marketing copy.",
                "veronica": "Clarify product and operational requirements.",
                "gecko": "Shape growth, marketing, and SEO strategy.",
            }

        tasks: List[AgentTask] = []
        collaborations: List[Dict[str, Any]] = []
        previous_agent = "orchestrator"
        for index, agent in enumerate(chain):
            focus = focuses.get(agent, "Contribute specialist analysis.")
            objective = f"{focus} User request: {text.strip()}"
            task = AgentTask(
                agent=agent,
                objective=objective,
                focus=focus,
                step=index,
                depends_on=[previous_agent] if index > 0 else [],
                task_id=f"{task_id}:{index}:{agent}",
            )
            tasks.append(task)
            collaboration = self.create_collaboration(task_id=task_id, parent_agent=previous_agent, child_agent=agent)
            collaborations.append(collaboration.to_dict())
            self.record_message(
                collaboration.collaboration_id,
                sender_agent=previous_agent,
                receiver_agent=agent,
                message=objective,
            )
            previous_agent = agent

        return {
            "task_id": task_id,
            "chain": chain,
            "tasks": tasks,
            "collaborations": collaborations,
        }

    def _serialize_row(self, row: Dict[str, Any]) -> Dict[str, Any]:
        row["message_count"] = self._count_messages(row["collaboration_id"])
        row["progress_percent"] = self._progress_percent(row["status"], row["message_count"])
        return row

    def _count_messages(self, collaboration_id: str) -> int:
        cursor = self._conn.cursor()
        cursor.execute("SELECT COUNT(1) FROM collaboration_messages WHERE collaboration_id = ?", (collaboration_id,))
        return int(cursor.fetchone()[0] or 0)

    def _progress_percent(self, status: str, message_count: int) -> int:
        if status in {"completed", "failed"}:
            return 100
        if message_count <= 0:
            return 0
        return min(95, 20 + (message_count * 20))

    def close(self) -> None:
        try:
            self._conn.close()
        except Exception:
            pass


__all__ = [
    "CollaborationEngine",
    "CollaborationMessageRecord",
    "CollaborationRecord",
]
