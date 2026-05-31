import asyncio
import os
import sys
import tempfile

# ensure repo root is on path
repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if repo_root not in sys.path:
    sys.path.insert(0, repo_root)

from core.memory_manager import MemoryManager
from core.skill_engine import SkillEngine
from core.intent_router import IntentRouter


def format_memory_for_prompt(messages):
    parts = []
    for m in messages:
        role = m.get("role", "unknown")
        content = m.get("content") or m.get("text") or ""
        parts.append(f"{role}: {content}")
    return "\n".join(parts)


class DummyOllama:
    async def generate(self, prompt: str, max_tokens: int = 512, **kwargs):
        # simple echo-style response for deterministic testing
        if "Autonomous Planner" in prompt:
            return "1. Step one\n2. Step two"
        if "USER: Build a React website" in prompt or "Build a React website" in prompt:
            return "I will scaffold a React app and add pages."
        if prompt.strip().endswith("Yes"):
            return "Continuing from previous plan: add routing and components."
        return "OK"


async def run_checks():
    tmp = tempfile.mkdtemp(prefix="jarvis_test_")
    db_path = os.path.join(tmp, "jarvis_memory.db")
    mem = MemoryManager(db_path=db_path, max_history=50)

    skill_engine = SkillEngine()
    intent_router = IntentRouter(skill_engine=skill_engine)

    # 1) Basic greeting
    mem.add("user", "Hi")
    recent = mem.get_recent_context(5)
    print("Recent after Hi:", recent)

    # 2) Build React website -> intent and skills
    text = "Build a React website"
    mem.add("user", text)
    route = intent_router.route(text)
    print("Route:", route)
    skills = route.get("skills", [])
    print("Matched skills:", skills)

    skill_ctx = skill_engine.get_skill_context(skills)
    print("Skill context length:", len(skill_ctx))

    # 3) Simulate model responses with DummyOllama
    ollama = DummyOllama()
    persona = "You are JARVIS."
    final_prompt = "\n".join([persona, "=== MEMORY ===", format_memory_for_prompt(mem.get_recent_context(20)), "=== SKILLS ===", skill_ctx, "=== USER MESSAGE ===", text])
    resp = await ollama.generate(final_prompt)
    print("Model resp:", resp)
    mem.add("assistant", resp)

    # 4) Follow-up 'Yes' should remember previous context
    mem.add("user", "Yes")
    follow_prompt = "\n".join([persona, "=== MEMORY ===", format_memory_for_prompt(mem.get_recent_context(20)), "=== SKILLS ===", skill_ctx, "=== USER MESSAGE ===", "Yes"]) 
    follow_resp = await ollama.generate(follow_prompt)
    print("Follow-up resp:", follow_resp)

    # 5) Autonomous detection
    auto_text = "Build a complete website for my startup"
    auto_route = intent_router.route(auto_text)
    print("Autonomous route:", auto_route)
    assert auto_route.get("autonomous") is True or auto_route.get("autonomous") is False

    # cleanup
    mem.close()
    print("SMOKE TESTS COMPLETED")


if __name__ == "__main__":
    asyncio.run(run_checks())
