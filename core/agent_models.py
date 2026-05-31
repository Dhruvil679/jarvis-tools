from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional
import re
import json


def slugify(value: str) -> str:
    text = (value or "").strip().lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-")


@dataclass(slots=True)
class AgentDefinition:
    name: str
    slug: str
    role: str
    summary: str
    prompt: str
    tools: List[str] = field(default_factory=list)
    keywords: List[str] = field(default_factory=list)
    skills: List[str] = field(default_factory=list)
    voice: Dict[str, Any] = field(default_factory=dict)
    config: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)
    paths: Dict[str, str] = field(default_factory=dict)
    memory_db: str = ""
    timeout_seconds: int = 60

    @property
    def display_name(self) -> str:
        return self.metadata.get("display_name", self.name)


@dataclass(slots=True)
class RouteDecision:
    mode: str
    primary_agent: str
    collaborators: List[str] = field(default_factory=list)
    confidence: float = 0.0
    reason: str = ""
    signals: List[str] = field(default_factory=list)
    handoff_chain: List[str] = field(default_factory=list)
    confidence_scores: Dict[str, float] = field(default_factory=dict)


@dataclass(slots=True)
class AgentTask:
    agent: str
    objective: str
    focus: str
    step: int = 0
    depends_on: List[str] = field(default_factory=list)
    task_id: str = ""


@dataclass(slots=True)
class AgentAction:
    tool: str
    path: str = ""
    content: str = ""
    command: str = ""
    query: str = ""
    key: str = ""
    value: str = ""
    agent: str = ""
    target: str = ""
    cwd: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ToolExecutionRecord:
    task_id: str
    agent: str
    tool: str
    status: str
    duration_seconds: float
    result: str
    error: str = ""
    path: str = ""
    command: str = ""
    iteration: int = 0
    ts: float = 0.0
    payload: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "agent": self.agent,
            "tool": self.tool,
            "status": self.status,
            "duration_seconds": self.duration_seconds,
            "result": self.result,
            "error": self.error,
            "path": self.path,
            "command": self.command,
            "iteration": self.iteration,
            "ts": self.ts,
            "payload": self.payload,
        }


@dataclass(slots=True)
class AgentResult:
    agent: str
    task: str
    result: str
    prompt: str
    memory_path: str
    elapsed_seconds: float
    structured_output: Dict[str, Any] = field(default_factory=dict)
    confidence: float = 0.0
    status: str = "complete"
    handoff_from: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def content(self) -> str:
        return json.dumps(self.structured_output or self.to_dict(), ensure_ascii=False)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "agent": self.agent,
            "task": self.task,
            "result": self.result,
            "confidence": self.confidence,
            "status": self.status,
            "handoff_from": self.handoff_from,
            "elapsed_seconds": self.elapsed_seconds,
            "metadata": self.metadata,
            "structured_output": self.structured_output,
            "memory_path": self.memory_path,
        }


@dataclass(slots=True)
class CollaborationEvent:
    ts: float
    event_type: str
    source_agent: Optional[str] = None
    target_agent: Optional[str] = None
    task: str = ""
    message: str = ""
    confidence: float = 0.0
    status: str = ""
    payload: Dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class AgentStatusSnapshot:
    agent: str
    state: str
    confidence: float = 0.0
    active_task: str = ""
    last_message: str = ""
    last_sender: str = ""
    last_update: float = 0.0
    run_count: int = 0
    error_count: int = 0


@dataclass(slots=True)
class OrchestrationResult:
    user_text: str
    route: RouteDecision
    plan: List[AgentTask] = field(default_factory=list)
    agent_outputs: Dict[str, AgentResult] = field(default_factory=dict)
    execution_records: List[ToolExecutionRecord] = field(default_factory=list)
    final_response: str = ""
    merged_output: Dict[str, Any] = field(default_factory=dict)
    timeline: List[CollaborationEvent] = field(default_factory=list)
    execution_logs: List[str] = field(default_factory=list)
    statuses: Dict[str, AgentStatusSnapshot] = field(default_factory=dict)
    mode: str = "single"
