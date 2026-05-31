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
from core.skill_engine import SkillEngine


def assert_true(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def run() -> None:
    with TemporaryDirectory() as temp_dir:
        skill_engine = SkillEngine()
        manager = AgentManager(
            agents_root=config.AGENTS_ROOT,
            memory_root=temp_dir,
            skill_engine=skill_engine,
            llm_client=None,
        )
        try:
            result = asyncio.run(manager.run_agent("ultron", "Create a React dashboard"))
            structured = result.structured_output

            assert_true(result.status in {"running", "completed"}, f"Unexpected status: {result.status}")
            assert_true("thought" in structured, "Agent output missing thought")
            assert_true("actions" in structured, "Agent output missing actions")
            assert_true(isinstance(structured["actions"], list), "Actions must be a list")
            assert_true(len(structured["actions"]) > 0, "Fallback planner should generate actions")
            assert_true(any(action.get("tool") == "file_write" for action in structured["actions"] if isinstance(action, dict)), "Expected file_write action")
            assert_true(any(action.get("tool") == "terminal_execute" for action in structured["actions"] if isinstance(action, dict)) is False, "Ultron should not validate by itself")
        finally:
            manager.close()

    print("TEST_AGENT_ACTIONS_PASSED")


if __name__ == "__main__":
    run()
