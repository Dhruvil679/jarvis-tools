from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional
import json
import os
import shlex
import subprocess
import time
import uuid
import shutil

from .agent_models import AgentAction, ToolExecutionRecord
from .logger import get_logger


logger = get_logger(__name__)

ALLOWED_TERMINAL_BINARIES = {
    "python",
    "python3",
    "py",
    "npm",
    "git",
    "pytest",
    "uvicorn",
}

BLOCKED_COMMAND_PATTERNS = [
    "rm -rf",
    "del /s",
    "del /f",
    "shutdown",
    "format ",
    " format",
    "rmdir /s",
    "rd /s",
    "diskpart",
    "mkfs",
    "reg delete",
    "remove-item",
    "restart-computer",
    "stop-computer",
    "clear-disk",
    "format-volume",
]


@dataclass(slots=True)
class ToolExecutionResult:
    tool: str
    status: str
    result: str
    duration_seconds: float
    error: str = ""
    path: str = ""
    command: str = ""
    cwd: str = ""
    output: str = ""
    task_id: str = ""
    agent: str = ""
    iteration: int = 0
    payload: Dict[str, Any] = None  # type: ignore[assignment]

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["payload"] = self.payload or {}
        return data


class ToolExecutor:
    def __init__(self, agent_manager: Any, skill_engine: Optional[Any] = None, workspace_root: Optional[str] = None) -> None:
        self.agent_manager = agent_manager
        self.skill_engine = skill_engine
        self.workspace_root = Path(workspace_root) if workspace_root else Path(__file__).resolve().parent.parent
        self.workspace_root = self.workspace_root.resolve()

    def execute_actions(
        self,
        agent_name: str,
        task_id: str,
        actions: List[Dict[str, Any]],
        iteration: int,
        task_text: str,
    ) -> List[ToolExecutionRecord]:
        results: List[ToolExecutionRecord] = []
        for action in actions:
            outcome = self.execute_action(
                agent_name=agent_name,
                task_id=task_id,
                action=action,
                iteration=iteration,
                task_text=task_text,
            )
            results.append(outcome)
        return results

    def execute_action(
        self,
        agent_name: str,
        task_id: str,
        action: Dict[str, Any] | AgentAction,
        iteration: int,
        task_text: str,
    ) -> ToolExecutionRecord:
        started_at = time.time()
        payload = self._action_payload(action)
        tool = str(payload.get("tool", "")).strip().lower()
        memory = self.agent_manager.get_memory(agent_name)
        memory.record_task(
            task_id=task_id,
            task=task_text,
            state="running",
            tool=tool,
            result="",
            error="",
            duration_seconds=0.0,
            iteration=iteration,
            metadata=payload,
        )

        try:
            if tool == "file_write":
                result = self._file_write(payload)
            elif tool == "file_read":
                result = self._file_read(payload)
            elif tool == "terminal_execute":
                result = self._terminal_execute(payload)
            elif tool == "skill_lookup":
                result = self._skill_lookup(agent_name, payload)
            elif tool == "memory_store":
                result = self._memory_store(agent_name, task_id, payload)
            elif tool == "memory_search":
                result = self._memory_search(agent_name, payload)
            else:
                raise ValueError(f"Unsupported tool: {tool}")

            duration = time.time() - started_at
            record = ToolExecutionRecord(
                task_id=task_id,
                agent=agent_name,
                tool=tool,
                status="completed",
                duration_seconds=duration,
                result=result,
                path=str(payload.get("path", "")),
                command=str(payload.get("command", "")),
                iteration=iteration,
                ts=time.time(),
                payload=payload,
            )
            memory.record_task(
                task_id=task_id,
                task=task_text,
                state="completed",
                tool=tool,
                result=result,
                error="",
                duration_seconds=duration,
                iteration=iteration,
                metadata={**payload, "tool_result": result},
            )
            memory.log_event(
                "tool_completed",
                source_agent=agent_name,
                target_agent=agent_name,
                task=task_text,
                message=result,
                confidence=1.0,
                payload=record.to_dict(),
            )
            return record
        except Exception as exc:
            duration = time.time() - started_at
            error_text = str(exc)
            record = ToolExecutionRecord(
                task_id=task_id,
                agent=agent_name,
                tool=tool,
                status="failed",
                duration_seconds=duration,
                result=error_text,
                error=repr(exc),
                path=str(payload.get("path", "")),
                command=str(payload.get("command", "")),
                iteration=iteration,
                ts=time.time(),
                payload=payload,
            )
            memory.record_task(
                task_id=task_id,
                task=task_text,
                state="failed",
                tool=tool,
                result="",
                error=error_text,
                duration_seconds=duration,
                iteration=iteration,
                metadata={**payload, "error": repr(exc)},
            )
            memory.log_event(
                "tool_failed",
                source_agent=agent_name,
                target_agent=agent_name,
                task=task_text,
                message=error_text,
                confidence=0.0,
                payload=record.to_dict(),
            )
            return record

    def lookup_skill(self, query: str) -> Dict[str, Any]:
        if not self.skill_engine:
            return {"query": query, "matches": [], "metadata": {}}
        matches = self.skill_engine.match_skills(query, max_results=8)
        names = [skill.name for skill in matches]
        metadata = {skill.name: skill.to_metadata() for skill in matches}
        return {"query": query, "matches": names, "metadata": metadata}

    def _action_payload(self, action: Dict[str, Any] | AgentAction) -> Dict[str, Any]:
        if isinstance(action, AgentAction):
            return {
                "tool": action.tool,
                "path": action.path,
                "content": action.content,
                "command": action.command,
                "query": action.query,
                "key": action.key,
                "value": action.value,
                "agent": action.agent,
                "target": action.target,
                "cwd": action.cwd,
                "metadata": action.metadata,
            }
        return dict(action or {})

    def _resolve_path(self, raw_path: str) -> Path:
        if not raw_path:
            raise ValueError("Path is required")
        path = Path(raw_path)
        if not path.is_absolute():
            path = self.workspace_root / path
        resolved = path.resolve(strict=False)
        if not self._is_within_workspace(resolved):
            raise ValueError(f"Path outside workspace: {raw_path}")
        return resolved

    def _resolve_cwd(self, raw_cwd: str) -> Path:
        if not raw_cwd:
            return self.workspace_root
        path = Path(raw_cwd)
        if not path.is_absolute():
            path = self.workspace_root / path
        resolved = path.resolve(strict=False)
        if not self._is_within_workspace(resolved):
            raise ValueError(f"CWD outside workspace: {raw_cwd}")
        return resolved

    def _is_within_workspace(self, path: Path) -> bool:
        try:
            path.relative_to(self.workspace_root)
            return True
        except Exception:
            return False

    def _file_write(self, payload: Dict[str, Any]) -> str:
        path = self._resolve_path(str(payload.get("path", "")))
        content = str(payload.get("content", ""))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return json.dumps({"written": str(path), "bytes": len(content.encode("utf-8"))}, ensure_ascii=False)

    def _file_read(self, payload: Dict[str, Any]) -> str:
        path = self._resolve_path(str(payload.get("path", "")))
        if not path.exists():
            raise FileNotFoundError(f"Missing file: {path}")
        return path.read_text(encoding="utf-8")

    def _terminal_execute(self, payload: Dict[str, Any]) -> str:
        command = str(payload.get("command", "")).strip()
        if not command:
            raise ValueError("Command is required")
        lowered = command.lower()
        for pattern in BLOCKED_COMMAND_PATTERNS:
            if pattern in lowered:
                raise ValueError(f"Blocked terminal command: {pattern}")

        args = shlex.split(command, posix=False)
        if not args:
            raise ValueError("Command parsing failed")

        executable = Path(args[0]).name.lower()
        if executable not in ALLOWED_TERMINAL_BINARIES:
            raise ValueError(f"Terminal command not allowed: {args[0]}")

        if executable == "python" and len(args) >= 3 and args[1] == "-m":
            module = args[2].lower()
            if module not in {"pytest", "uvicorn"}:
                raise ValueError(f"Python module not allowed: {module}")
        elif executable == "npm":
            allowed_npm_args = {"install", "ci", "run", "test", "build", "audit", "exec"}
            if len(args) > 1 and args[1].lower() not in allowed_npm_args:
                raise ValueError(f"NPM command not allowed: {args[1]}")
        elif executable == "git":
            allowed_git_args = {"status", "diff", "log", "show", "branch", "rev-parse", "add", "commit", "pull", "push"}
            if len(args) > 1 and args[1].lower() not in allowed_git_args:
                raise ValueError(f"Git command not allowed: {args[1]}")
        elif executable == "pytest":
            pass
        elif executable == "uvicorn":
            pass

        cwd = self._resolve_cwd(str(payload.get("cwd", "")))
        env = os.environ.copy()
        env.setdefault("PYTHONUNBUFFERED", "1")

        resolved_binary = shutil.which(args[0])
        if resolved_binary is None and os.name == "nt":
            if executable == "npm":
                resolved_binary = shutil.which("npm.cmd") or shutil.which("npm.exe")
            elif executable == "python":
                resolved_binary = shutil.which("python.exe") or shutil.which("py.exe")
        if resolved_binary:
            args[0] = resolved_binary

        completed = subprocess.run(
            args,
            cwd=str(cwd),
            env=env,
            capture_output=True,
            text=True,
            check=False,
            shell=False,
        )

        output = "\n".join(part for part in [completed.stdout.strip(), completed.stderr.strip()] if part)
        if completed.returncode != 0:
            raise RuntimeError(f"Command failed with exit code {completed.returncode}: {output}".strip())
        return output or f"Command completed: {command}"

    def _skill_lookup(self, agent_name: str, payload: Dict[str, Any]) -> str:
        query = str(payload.get("query") or payload.get("skill") or payload.get("name") or "").strip()
        if not query:
            agent = self.agent_manager.get_agent(agent_name)
            query = " ".join(agent.skills if agent else [])
        if not query:
            query = agent_name
        data = self.lookup_skill(query)
        return json.dumps(data, ensure_ascii=False)

    def _memory_store(self, agent_name: str, task_id: str, payload: Dict[str, Any]) -> str:
        memory = self.agent_manager.get_memory(agent_name)
        key = str(payload.get("key", "")).strip()
        value = str(payload.get("value", payload.get("content", ""))).strip()
        note = str(payload.get("note", "")).strip()
        confidence = float(payload.get("confidence", 1.0) or 1.0)
        if key and value:
            memory.remember_fact(key, value, confidence=confidence)
            return json.dumps({"stored": "fact", "key": key, "value": value}, ensure_ascii=False)
        if value:
            memory.remember_summary(task_id or agent_name, value)
            if note:
                memory.add_message("assistant", note, {"task_id": task_id, "kind": "memory_store"})
            return json.dumps({"stored": "summary", "value": value}, ensure_ascii=False)
        raise ValueError("memory_store requires key/value or content")

    def _memory_search(self, agent_name: str, payload: Dict[str, Any]) -> str:
        query = str(payload.get("query", "")).strip().lower()
        limit = int(payload.get("limit", 10) or 10)
        memory = self.agent_manager.get_memory(agent_name)
        snapshot = memory.snapshot(limit=max(1, min(limit, 50)))
        results: List[Dict[str, Any]] = []
        for section in ("messages", "summaries", "facts", "events", "tasks"):
            for item in snapshot.get(section, []):
                text = json.dumps(item, ensure_ascii=False).lower()
                if not query or query in text:
                    results.append({"section": section, "item": item})
        return json.dumps({"query": query, "results": results[:limit]}, ensure_ascii=False)


__all__ = ["ToolExecutor", "ToolExecutionResult", "ALLOWED_TERMINAL_BINARIES"]
