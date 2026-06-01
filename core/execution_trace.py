from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any, Dict, Optional


@dataclass(slots=True)
class ExecutionTrace:
    execution_id: str
    task_id: str
    parent_task_id: str = ""
    agent_name: str = ""
    action_type: str = ""
    status: str = ""
    start_time: float = 0.0
    end_time: float = 0.0
    duration_ms: float = 0.0
    result_summary: str = ""
    error_message: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_row(cls, row: Dict[str, Any]) -> "ExecutionTrace":
        return cls(
            execution_id=row.get("execution_id", ""),
            task_id=row.get("task_id", ""),
            parent_task_id=row.get("parent_task_id", "") or "",
            agent_name=row.get("agent_name", "") or "",
            action_type=row.get("action_type", "") or "",
            status=row.get("status", "") or "",
            start_time=float(row.get("start_time", 0.0) or 0.0),
            end_time=float(row.get("end_time", 0.0) or 0.0),
            duration_ms=float(row.get("duration_ms", 0.0) or 0.0),
            result_summary=row.get("result_summary", "") or "",
            error_message=row.get("error_message", "") or "",
        )


__all__ = ["ExecutionTrace"]
