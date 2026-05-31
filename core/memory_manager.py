from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional
import json

from .agent_memory import AgentMemoryStore


class MemoryManager(AgentMemoryStore):
    """Compatibility wrapper for the original single-store memory manager."""

    def __init__(self, db_path: Optional[str] = None, max_history: int = 200):
        resolved_db_path = Path(db_path) if db_path else None
        agent_name = resolved_db_path.stem if resolved_db_path else "jarvis"
        super().__init__(agent_name=agent_name, db_path=str(resolved_db_path) if resolved_db_path else None, max_history=max_history)

    def add(self, role: str, content: str) -> None:
        self.add_message(role, content)

    def save_session(self, name: str) -> str:
        sessions_dir = self.db_path.parent / "sessions"
        sessions_dir.mkdir(parents=True, exist_ok=True)
        out_path = sessions_dir / f"{name}.json"
        messages = self.get_recent_context(self.max_history)
        try:
            out_path.write_text(json.dumps(messages, indent=2), encoding="utf-8")
            return str(out_path)
        except Exception:
            return ""

    def load_session(self, path: str) -> bool:
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
            for entry in data:
                role = entry.get("role")
                content = entry.get("content") or entry.get("text")
                if role and content:
                    self.add_message(role, content, entry.get("metadata"))
            return True
        except Exception:
            return False

    def clear_memory(self) -> None:
        self.clear()


__all__ = ["MemoryManager"]
