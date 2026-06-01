from __future__ import annotations

import asyncio
from pathlib import Path
import json
import sqlite3
import sys

from fastapi.testclient import TestClient

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from api.app import app
from config.config import config
from core.agent_manager import AgentManager
from core.agent_router import AgentRouter
from core.agent_memory import AgentMemoryStore
from core.orchestrator import JarvisOrchestrator
from core.skill_engine import SkillEngine
from core.ollama_client import OllamaClient


def assert_true(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def run() -> None:
    skill_engine = SkillEngine()
    agent_manager = AgentManager(
        agents_root=config.AGENTS_ROOT,
        memory_root=config.MEMORY_ROOT,
        skill_engine=skill_engine,
        llm_client=None,
    )
    agent_router = AgentRouter(routes_path=config.ROUTE_CONFIG)
    orchestrator = JarvisOrchestrator(
        agent_manager=agent_manager,
        agent_router=agent_router,
        skill_engine=skill_engine,
    )

    agent_names = [agent.slug for agent in agent_manager.list_agents()]
    assert_true(len(agent_names) == 9, f"Expected 9 agents, found {len(agent_names)}")
    for expected in ["friday", "oracle", "vision", "ultron", "hulk", "spectre", "herald", "veronica", "gecko"]:
        assert_true(expected in agent_names, f"Missing agent: {expected}")

    expected_skill_map = {
        "vision": ["frontend-expert", "ui-design-system"],
        "ultron": ["fastapi", "backend-architecture"],
        "gecko": ["ai-seo", "growth-marketing"],
        "oracle": ["research-assistant", "analyst"],
        "friday": ["planning", "memory", "scheduling"],
    }
    for agent_slug, expected_skills in expected_skill_map.items():
        agent = agent_manager.get_agent(agent_slug)
        assert_true(agent is not None, f"Missing agent object: {agent_slug}")
        assert_true(agent.skills == expected_skills, f"Registry skills mismatch for {agent_slug}: {agent.skills}")

    registry_db = Path(config.AGENT_SKILL_REGISTRY)
    assert_true(registry_db.exists(), f"Missing registry DB: {registry_db}")
    registry_conn = sqlite3.connect(registry_db)
    registry_tables = {row[0] for row in registry_conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    registry_conn.close()
    for table in ["agents", "skills", "agent_skills"]:
        assert_true(table in registry_tables, f"Registry DB missing table {table}")

    friday_memory = agent_manager.get_memory("friday")
    friday_memory.add_message("user", "Integration memory check")
    recent = friday_memory.get_recent_messages(5)
    assert_true(any(entry["content"] == "Integration memory check" for entry in recent), "Agent memory write failed")

    shared_memory = AgentMemoryStore(agent_name="jarvis")
    shared_memory.add_message("user", "Shared memory check")
    assert_true(any(entry["content"] == "Shared memory check" for entry in shared_memory.get_recent_context(5)), "Shared memory write failed")
    shared_memory.close()

    skills = skill_engine.list_skills()
    assert_true(len(skills) > 0, "Skill discovery returned no skills")

    routing_cases = {
        "build a react dashboard": "ultron",
        "create seo strategy": "gecko",
        "review this contract": "spectre",
        "summarize today's news": "friday",
        "research competitors": "oracle",
        "write announcement": "herald",
    }
    for text, expected_agent in routing_cases.items():
        decision = agent_router.route(text)
        assert_true(decision.primary_agent == expected_agent, f"Route mismatch for '{text}': {decision.primary_agent} != {expected_agent}")
        assert_true(len(decision.handoff_chain) >= 1, "Missing handoff chain")

    single_result = orchestrator.agent_router.route("review this contract", mode="single")
    assert_true(single_result.mode == "single", "Single-route mode should stay single")

    multi_decision = orchestrator.agent_router.route("Build restaurant SaaS")
    assert_true(multi_decision.mode == "multi", "Broad build request should use multi-agent mode")
    orchestration = orchestrator.agent_router.decompose("Build restaurant SaaS", multi_decision)
    assert_true(len(orchestration) >= 2, "Multi-agent decomposition should include collaborators")

    collaboration_decision = orchestrator.agent_router.route("customer support screenshot fix and execute script")
    assert_true(collaboration_decision.mode == "multi", "Collaboration chain should use multi-agent mode")
    assert_true(
        collaboration_decision.handoff_chain[:4] == ["veronica", "vision", "ultron", "hulk"],
        f"Unexpected collaboration chain: {collaboration_decision.handoff_chain}",
    )
    collaboration_result = asyncio.run(orchestrator.process("customer support screenshot fix and execute script", mode="auto"))
    assert_true(collaboration_result.mode == "multi", "Orchestrator should execute multi-agent collaboration")
    assert_true(len(collaboration_result.timeline) >= 6, "Timeline should include isolated agent events")
    assert_true(any(event.event_type == "agent_started" for event in collaboration_result.timeline), "Missing agent start events")
    assert_true(any(event.event_type == "agent_completed" for event in collaboration_result.timeline), "Missing agent completion events")
    assert_true(len(collaboration_result.execution_records) > 0, "Missing tool execution records")
    assert_true(any(record.tool for record in collaboration_result.execution_records), "Execution records should include tools")
    assert_true("veronica" in collaboration_result.agent_outputs, "Missing Veronica output")
    for output in collaboration_result.agent_outputs.values():
        structured = output.structured_output
        for key in ["agent", "task", "result", "thought", "actions"]:
            assert_true(key in structured, f"Missing structured key {key}")
        assert_true(output.content.startswith("{"), "Agent output should serialize to JSON")
        assert_true(output.status in {"running", "completed", "failed"}, f"Unexpected agent status: {output.status}")

    client = TestClient(app)
    health = client.get("/health")
    assert_true(health.status_code == 200 and health.json()["status"] == "ok", "Health endpoint failed")
    agents_response = client.get("/agents")
    assert_true(agents_response.status_code == 200, "/agents failed")
    assert_true(len(agents_response.json()) == 9, "/agents should return 9 agents")
    status_response = client.get("/agents/status")
    assert_true(status_response.status_code == 200, "/agents/status failed")
    registry_response = client.get("/agent-skill-registry")
    assert_true(registry_response.status_code == 200, "/agent-skill-registry failed")
    registry_payload = registry_response.json()
    assert_true(len(registry_payload["agents"]) == 9, "Registry should include 9 agents")
    skills_response = client.get("/skills")
    assert_true(skills_response.status_code == 200, "/skills failed")
    memory_response = client.get("/memory", params={"agent": "friday", "limit": 5})
    assert_true(memory_response.status_code == 200, "/memory failed")
    app.state.runtime["agent_manager"].llm_client = None
    chat_response = client.post("/chat", json={"message": "customer support screenshot fix and execute script", "mode": "auto"})
    assert_true(chat_response.status_code == 200, "/chat failed")
    chat_payload = chat_response.json()
    assert_true("timeline" in chat_payload, "Chat payload missing timeline")
    assert_true("execution_logs" in chat_payload, "Chat payload missing execution logs")
    assert_true("task_executions" in chat_payload, "Chat payload missing task executions")
    assert_true("statuses" in chat_payload, "Chat payload missing statuses")

    class IsolationLLM:
        async def generate(self, prompt: str, max_tokens: int = 512, retries: int = 2, backoff: float = 0.8) -> str:
            lowered = prompt.lower()
            if "vision" in lowered:
                await asyncio.sleep(0.05)
                return json.dumps({"agent": "Vision", "task": "timeout", "result": "late"})
            if "hulk" in lowered:
                raise RuntimeError("simulated hulk failure")
            return json.dumps({"agent": "Stub", "task": "stub", "result": "ok"})

    isolated_manager = AgentManager(
        agents_root=config.AGENTS_ROOT,
        memory_root=config.MEMORY_ROOT,
        skill_engine=skill_engine,
        llm_client=IsolationLLM(),
    )
    isolated_vision = isolated_manager.get_agent("vision")
    isolated_vision.config["timeout_seconds"] = 0.01
    isolated_vision.timeout_seconds = 0.01
    isolated_router = AgentRouter(routes_path=config.ROUTE_CONFIG)
    isolated_orchestrator = JarvisOrchestrator(
        agent_manager=isolated_manager,
        agent_router=isolated_router,
        skill_engine=skill_engine,
    )
    isolation_result = asyncio.run(isolated_orchestrator.process("customer support screenshot fix and execute script", mode="auto"))
    assert_true(isolation_result.mode == "multi", "Isolation run should still use multi-agent mode")
    assert_true(any(output.status == "failed" for output in isolation_result.agent_outputs.values()), "Expected at least one failed agent")
    assert_true(any(output.status == "completed" for output in isolation_result.agent_outputs.values()), "Expected at least one completed agent")
    assert_true(any("performance" in log.lower() for log in isolation_result.execution_logs), "Missing performance logging")

    memory_root = Path(config.MEMORY_ROOT)
    for expected in ["friday", "oracle", "vision", "ultron", "hulk", "spectre", "herald", "veronica", "gecko"]:
        db_path = memory_root / f"{expected}.db"
        assert_true(db_path.exists(), f"Missing memory DB: {db_path}")
        conn = sqlite3.connect(db_path)
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        conn.close()
        for table in ["messages", "summaries", "facts", "events", "status", "tasks"]:
            assert_true(table in tables, f"{db_path.name} missing table {table}")

    dashboard_root = REPO_ROOT / "dashboard"
    for file_name in ["package.json", "src/App.tsx", "src/main.tsx", "src/index.css"]:
        assert_true((dashboard_root / file_name).exists(), f"Missing dashboard file: {file_name}")

    print("INTEGRATION_TESTS_PASSED")


if __name__ == "__main__":
    run()
