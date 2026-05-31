from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import asyncio
import json
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from config.config import config
from core.agent_manager import AgentManager
from core.skill_engine import SkillEngine
from core.tool_executor import ToolExecutor


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
            executor = ToolExecutor(agent_manager=manager, skill_engine=skill_engine, workspace_root=temp_dir)

            write_result = executor.execute_action(
                agent_name="ultron",
                task_id="task-write",
                action={"tool": "file_write", "path": "artifacts/demo.txt", "content": "hello world"},
                iteration=0,
                task_text="write demo file",
            )
            assert_true(write_result.status == "completed", f"file_write failed: {write_result.result}")
            written_path = Path(temp_dir) / "artifacts" / "demo.txt"
            assert_true(written_path.exists(), "file_write did not create the file")

            read_result = executor.execute_action(
                agent_name="ultron",
                task_id="task-read",
                action={"tool": "file_read", "path": "artifacts/demo.txt"},
                iteration=0,
                task_text="read demo file",
            )
            assert_true(read_result.status == "completed", f"file_read failed: {read_result.result}")
            assert_true("hello world" in read_result.result, "file_read did not return content")

            memory_store_result = executor.execute_action(
                agent_name="friday",
                task_id="task-memory",
                action={"tool": "memory_store", "key": "demo_key", "value": "remember this"},
                iteration=0,
                task_text="store memory",
            )
            assert_true(memory_store_result.status == "completed", f"memory_store failed: {memory_store_result.result}")

            memory_search_result = executor.execute_action(
                agent_name="friday",
                task_id="task-memory-search",
                action={"tool": "memory_search", "query": "remember this", "limit": 5},
                iteration=0,
                task_text="search memory",
            )
            assert_true(memory_search_result.status == "completed", f"memory_search failed: {memory_search_result.result}")
            assert_true("remember this" in memory_search_result.result, "memory_search did not find stored memory")

            skill_lookup_result = executor.execute_action(
                agent_name="oracle",
                task_id="task-skill",
                action={"tool": "skill_lookup", "query": "fastapi"},
                iteration=0,
                task_text="lookup skill",
            )
            assert_true(skill_lookup_result.status == "completed", f"skill_lookup failed: {skill_lookup_result.result}")
            parsed_lookup = json.loads(skill_lookup_result.result)
            assert_true("matches" in parsed_lookup, "skill_lookup payload missing matches")

            terminal_result = executor.execute_action(
                agent_name="hulk",
                task_id="task-terminal",
                action={"tool": "terminal_execute", "command": "python -V", "cwd": "."},
                iteration=0,
                task_text="validate runtime",
            )
            assert_true(terminal_result.status == "completed", f"terminal_execute failed: {terminal_result.result}")

            blocked_result = executor.execute_action(
                agent_name="hulk",
                task_id="task-blocked",
                action={"tool": "terminal_execute", "command": "rm -rf /", "cwd": "."},
                iteration=0,
                task_text="blocked command",
            )
            assert_true(blocked_result.status == "failed", "Blocked command should fail")
            assert_true("Blocked terminal command" in blocked_result.result or "not allowed" in blocked_result.result, "Blocked command error missing")
        finally:
            manager.close()

    print("TEST_EXECUTOR_PASSED")


if __name__ == "__main__":
    run()
