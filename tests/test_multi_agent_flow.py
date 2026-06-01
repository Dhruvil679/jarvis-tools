from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import asyncio
import sqlite3
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from fastapi.testclient import TestClient

from api.app import create_app
from config.config import config
from core.agent_manager import AgentManager
from core.agent_router import AgentRouter
from core.artifact_manager import ArtifactManager, ToolAuditStore
from core.collaboration_engine import CollaborationEngine
from core.orchestrator import JarvisOrchestrator
from core.skill_engine import SkillEngine
from core.trace_manager import TraceManager
from core.tool_executor import ToolExecutor


def test_multi_agent_collaboration_flow_and_api_routes() -> None:
    with TemporaryDirectory() as temp_workspace:
        workspace_root = Path(temp_workspace)
        memory_root = workspace_root / "memory"
        memory_root.mkdir(parents=True, exist_ok=True)

        skill_engine = SkillEngine()
        trace_manager = TraceManager(db_path=str(memory_root / "executions.db"))
        collaboration_engine = CollaborationEngine(db_path=str(memory_root / "collaboration.db"))
        artifact_manager = ArtifactManager(db_path=str(memory_root / "artifacts.db"))
        tool_audit = ToolAuditStore(db_path=str(memory_root / "tool_audit.db"))
        agent_manager = AgentManager(
            agents_root=config.AGENTS_ROOT,
            memory_root=str(memory_root),
            skill_engine=skill_engine,
            llm_client=None,
            trace_manager=trace_manager,
        )
        agent_router = AgentRouter(routes_path=config.ROUTE_CONFIG)
        tool_executor = ToolExecutor(
            agent_manager=agent_manager,
            skill_engine=skill_engine,
            workspace_root=str(workspace_root),
            trace_manager=trace_manager,
            artifact_manager=artifact_manager,
            tool_audit=tool_audit,
        )
        orchestrator = JarvisOrchestrator(
            agent_manager=agent_manager,
            agent_router=agent_router,
            skill_engine=skill_engine,
            tool_executor=tool_executor,
            trace_manager=trace_manager,
            collaboration_engine=collaboration_engine,
        )

        app = create_app()
        existing_runtime = app.state.runtime
        for key in ("orchestrator", "agent_manager", "tool_executor", "trace_manager", "collaboration_engine", "artifact_manager", "tool_audit"):
            if key in existing_runtime and hasattr(existing_runtime[key], "close"):
                existing_runtime[key].close()
        app.state.runtime = {
            "skill_engine": skill_engine,
            "ollama": None,
            "agent_manager": agent_manager,
            "agent_router": agent_router,
            "tool_executor": tool_executor,
            "trace_manager": trace_manager,
            "collaboration_engine": collaboration_engine,
            "artifact_manager": artifact_manager,
            "tool_audit": tool_audit,
            "orchestrator": orchestrator,
        }

        try:
            result = asyncio.run(orchestrator.process("Build a restaurant SaaS platform", mode="auto"))

            assert result.mode == "multi"
            assert {"oracle", "friday", "ultron", "vision", "gecko"}.issubset(set(result.agent_outputs.keys()))

            rows = collaboration_engine.list_recent(20)
            assert len(rows) >= 5
            assert any(row["status"] == "completed" for row in rows)

            db = sqlite3.connect(memory_root / "collaboration.db")
            cur = db.cursor()
            cur.execute("SELECT COUNT(1) FROM collaborations")
            assert cur.fetchone()[0] >= 5
            db.close()

            with TestClient(app) as client:
                collabs = client.get("/collaborations?limit=10")
                assert collabs.status_code == 200
                assert len(collabs.json()["collaborations"]) >= 5

                recent = client.get("/collaborations/recent?limit=5")
                assert recent.status_code == 200
                assert len(recent.json()["collaborations"]) >= 5

                detail_id = collabs.json()["collaborations"][0]["collaboration_id"]
                detail = client.get(f"/collaborations/{detail_id}")
                assert detail.status_code == 200
                assert "messages" in detail.json()
        finally:
            orchestrator.shared_memory.close()
            agent_manager.close()
            trace_manager.close()
            collaboration_engine.close()
            artifact_manager.close()
            tool_audit.close()
