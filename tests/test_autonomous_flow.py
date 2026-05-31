from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import asyncio
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from config.config import config
from core.agent_manager import AgentManager
from core.agent_router import AgentRouter
from core.orchestrator import JarvisOrchestrator
from core.skill_engine import SkillEngine
from core.tool_executor import ToolExecutor


def assert_true(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def run() -> None:
    with TemporaryDirectory() as temp_workspace:
        temp_memory = Path(temp_workspace) / "memory"
        temp_memory.mkdir(parents=True, exist_ok=True)

        skill_engine = SkillEngine()
        agent_manager = AgentManager(
            agents_root=config.AGENTS_ROOT,
            memory_root=str(temp_memory),
            skill_engine=skill_engine,
            llm_client=None,
        )
        agent_router = AgentRouter(routes_path=config.ROUTE_CONFIG)
        tool_executor = ToolExecutor(agent_manager=agent_manager, skill_engine=skill_engine, workspace_root=temp_workspace)
        orchestrator = JarvisOrchestrator(
            agent_manager=agent_manager,
            agent_router=agent_router,
            skill_engine=skill_engine,
            tool_executor=tool_executor,
        )
        try:
            result = asyncio.run(orchestrator.process("Create a React dashboard", mode="auto"))

            assert_true(result.mode == "multi", "Autonomous flow should route as multi-agent")
            assert_true(len(result.execution_records) > 0, "Expected tool execution records")
            assert_true(any(record.tool == "file_write" and record.status == "completed" for record in result.execution_records), "Missing file_write completion")
            assert_true(any(record.tool == "terminal_execute" and record.status == "completed" for record in result.execution_records), "Missing terminal validation")
            assert_true(any(record.agent == "ultron" for record in result.agent_outputs.values()), "Ultron should participate")

            generated_root = Path(temp_workspace) / "generated" / "react-dashboard"
            for relative in ["package.json", "src/App.tsx", "src/main.tsx", "src/index.css", "index.html"]:
                assert_true((generated_root / relative).exists(), f"Missing generated artifact: {relative}")

            assert_true(result.merged_output.get("artifacts"), "Merged output should include artifacts")
            assert_true(result.final_response, "Final response should not be empty")
        finally:
            orchestrator.shared_memory.close()
            agent_manager.close()

    print("TEST_AUTONOMOUS_FLOW_PASSED")


if __name__ == "__main__":
    run()
