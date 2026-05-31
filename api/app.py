from __future__ import annotations

from dataclasses import asdict
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from config.config import config
from core.agent_manager import AgentManager
from core.agent_router import AgentRouter
from core.logger import get_logger
from core.ollama_client import OllamaClient
from core.orchestrator import JarvisOrchestrator
from core.skill_engine import SkillEngine
from core.tool_executor import ToolExecutor


logger = get_logger(__name__)


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1)
    mode: str = "auto"
    agent: Optional[str] = None


def create_runtime() -> Dict[str, Any]:
    skill_engine = SkillEngine()
    ollama = OllamaClient(base_url=config.OLLAMA_URL, model=config.MODEL, timeout=config.OLLAMA_TIMEOUT)
    agent_manager = AgentManager(
        agents_root=config.AGENTS_ROOT,
        memory_root=config.MEMORY_ROOT,
        skill_engine=skill_engine,
        llm_client=ollama,
    )
    agent_router = AgentRouter(routes_path=config.ROUTE_CONFIG)
    tool_executor = ToolExecutor(agent_manager=agent_manager, skill_engine=skill_engine)
    orchestrator = JarvisOrchestrator(
        agent_manager=agent_manager,
        agent_router=agent_router,
        skill_engine=skill_engine,
        tool_executor=tool_executor,
    )
    return {
        "skill_engine": skill_engine,
        "ollama": ollama,
        "agent_manager": agent_manager,
        "agent_router": agent_router,
        "tool_executor": tool_executor,
        "orchestrator": orchestrator,
    }


def create_app() -> FastAPI:
    app = FastAPI(title="JARVIS OS API", version="2.0.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.state.runtime = create_runtime()

    @app.get("/health")
    def health() -> Dict[str, str]:
        return {"status": "ok"}

    @app.get("/agents")
    def agents() -> List[Dict[str, Any]]:
        manager: AgentManager = app.state.runtime["agent_manager"]
        return [
            {
                "name": agent.name,
                "slug": agent.slug,
                "role": agent.role,
                "summary": agent.summary,
                "tools": agent.tools,
                "keywords": agent.keywords,
                "skills": agent.skills,
                "voice": agent.voice,
                "config": agent.config,
                "timeout_seconds": agent.timeout_seconds,
                "paths": agent.paths,
            }
            for agent in manager.list_agents()
        ]

    @app.get("/agents/status")
    def agent_status() -> Dict[str, Any]:
        manager: AgentManager = app.state.runtime["agent_manager"]
        return {
            "agents": manager.status_snapshot(),
            "active_agent": manager.list_agents()[0].slug if manager.list_agents() else None,
        }

    @app.post("/chat")
    async def chat(payload: ChatRequest) -> Dict[str, Any]:
        orchestrator: JarvisOrchestrator = app.state.runtime["orchestrator"]
        result = await orchestrator.process(payload.message, mode=payload.mode, preferred_agent=payload.agent)
        return {
            "user_text": result.user_text,
            "mode": result.mode,
            "route": {
                "mode": result.route.mode,
                "primary_agent": result.route.primary_agent,
                "collaborators": result.route.collaborators,
                "confidence": result.route.confidence,
                "reason": result.route.reason,
                "signals": result.route.signals,
                "handoff_chain": result.route.handoff_chain,
                "confidence_scores": result.route.confidence_scores,
            },
            "plan": [asdict(step) for step in result.plan],
            "agent_outputs": {
                name: {
                    "agent": output.agent,
                    "task": output.task,
                    "content": output.content,
                    "result": output.result,
                    "confidence": output.confidence,
                    "status": output.status,
                    "handoff_from": output.handoff_from,
                    "elapsed_seconds": output.elapsed_seconds,
                    "metadata": output.metadata,
                    "structured_output": output.structured_output,
                }
                for name, output in result.agent_outputs.items()
            },
            "final_response": result.final_response,
            "merged_output": result.merged_output,
            "task_executions": [asdict(record) for record in result.execution_records],
            "timeline": [asdict(event) for event in result.timeline],
            "execution_logs": result.execution_logs,
            "statuses": {
                name: asdict(status)
                for name, status in result.statuses.items()
            },
        }

    @app.get("/memory")
    def memory(agent: str = Query("jarvis"), limit: int = Query(20, ge=1, le=100)) -> Dict[str, Any]:
        manager: AgentManager = app.state.runtime["agent_manager"]
        shared_memory = app.state.runtime["orchestrator"].shared_memory
        if agent == "jarvis":
            return shared_memory.snapshot(limit)
        memory_store = manager.get_memory(agent)
        return memory_store.snapshot(limit)

    @app.get("/skills")
    def skills() -> Dict[str, Any]:
        engine: SkillEngine = app.state.runtime["skill_engine"]
        return {
            "skills": engine.get_skill_metadata(),
            "names": engine.list_skills(),
        }

    @app.get("/agent-skill-registry")
    def agent_skill_registry() -> Dict[str, Any]:
        manager: AgentManager = app.state.runtime["agent_manager"]
        registry = manager.registry
        return registry.get_skill_snapshot()

    return app


app = create_app()
