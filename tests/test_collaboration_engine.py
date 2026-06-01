from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from core.agent_router import AgentRouter
from core.collaboration_engine import CollaborationEngine


def test_collaboration_engine_creates_plan_and_persists_messages() -> None:
    with TemporaryDirectory() as temp_dir:
        engine = CollaborationEngine(db_path=str(Path(temp_dir) / "collaboration.db"))
        route = AgentRouter().route("Build a restaurant SaaS platform")
        plan = engine.build_collaboration_plan("task-123", "Build a restaurant SaaS platform", route)

        assert plan["chain"] == ["oracle", "friday", "ultron", "vision", "gecko"]
        assert len(plan["tasks"]) == 5
        assert len(plan["collaborations"]) == 5

        collaborations = engine.list_recent(10)
        assert len(collaborations) == 5
        assert all(item["message_count"] >= 1 for item in collaborations)
        assert all("progress_percent" in item for item in collaborations)

        first = engine.get_collaboration(plan["collaborations"][0]["collaboration_id"])
        assert first is not None
        assert first["parent_agent"] == "orchestrator"
        assert first["child_agent"] == "oracle"
        assert len(first["messages"]) == 1

        engine.close()
