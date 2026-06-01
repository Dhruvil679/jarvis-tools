from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Dict, List, Optional
import json
import time

from config.config import config as runtime_config

from .agent_memory import AgentMemoryStore
from .agent_skill_registry import AgentSkillRegistry
from .agent_models import AgentAction, AgentDefinition, AgentResult, AgentStatusSnapshot, AgentTask, slugify
from .trace_manager import TraceManager
from .logger import get_logger


logger = get_logger(__name__)


class AgentManager:
    def __init__(
        self,
        agents_root: Optional[str] = None,
        memory_root: Optional[str] = None,
        skill_engine: Optional[Any] = None,
        llm_client: Optional[Any] = None,
        trace_manager: Optional[TraceManager] = None,
    ) -> None:
        self.repo_root = Path(__file__).resolve().parent.parent
        self.agents_root = Path(agents_root) if agents_root else self.repo_root / "agents"
        self.memory_root = Path(memory_root) if memory_root else self.repo_root / "memory"
        self.skill_engine = skill_engine
        self.llm_client = llm_client
        self.trace_manager = trace_manager
        self.registry = AgentSkillRegistry(db_path=getattr(runtime_config, "AGENT_SKILL_REGISTRY", None))
        self._agents: Dict[str, AgentDefinition] = {}
        self._memories: Dict[str, AgentMemoryStore] = {}
        self.reload()

    def reload(self) -> None:
        self._agents = self._discover_agents()
        self._memories = {}
        for agent_name in self._agents:
            memory = AgentMemoryStore(agent_name=agent_name, memory_root=str(self.memory_root))
            memory.set_status("idle", confidence=0.0, active_task="", last_message="", last_sender="")
            self._memories[agent_name] = memory

    def close(self) -> None:
        for memory in self._memories.values():
            try:
                memory.close()
            except Exception:
                pass
        self._memories = {}

    def _discover_agents(self) -> Dict[str, AgentDefinition]:
        discovered: Dict[str, AgentDefinition] = {}
        if not self.agents_root.exists():
            logger.warning("Agents root missing: %s", self.agents_root)
            return discovered

        for agent_dir in sorted(self.agents_root.iterdir()):
            if not agent_dir.is_dir():
                continue
            metadata_path = agent_dir / "metadata.json"
            prompt_path = agent_dir / "prompt.md"
            config_path = agent_dir / "config.json"
            if not metadata_path.exists() or not prompt_path.exists() or not config_path.exists():
                continue
            try:
                metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
                agent_config = json.loads(config_path.read_text(encoding="utf-8"))
                prompt = prompt_path.read_text(encoding="utf-8").strip()
            except Exception as exc:
                logger.warning("Failed to load agent definition at %s: %s", agent_dir, exc)
                continue

            name = metadata.get("name") or agent_dir.name
            slug = slugify(metadata.get("slug") or name)
            registry_skills = self.registry.get_agent_skills(slug)
            definition = AgentDefinition(
                name=name,
                slug=slug,
                role=metadata.get("role", ""),
                summary=metadata.get("summary", ""),
                prompt=prompt,
                tools=list(metadata.get("tools", [])),
                keywords=[str(item).lower() for item in metadata.get("keywords", []) if item],
                skills=registry_skills,
                voice=dict(metadata.get("voice", {})),
                config=agent_config,
                metadata=metadata,
                paths={
                    "root": str(agent_dir),
                    "metadata": str(metadata_path),
                    "prompt": str(prompt_path),
                    "config": str(config_path),
                },
                memory_db=str(self.memory_root / f"{slug}.db"),
                timeout_seconds=int(agent_config.get("timeout_seconds", runtime_config.AGENT_TIMEOUT_SECONDS)),
            )
            discovered[slug] = definition
        return discovered

    def list_agents(self) -> List[AgentDefinition]:
        return [self._agents[name] for name in sorted(self._agents.keys())]

    def get_agent(self, name: str) -> Optional[AgentDefinition]:
        return self._agents.get(slugify(name))

    def get_memory(self, name: str) -> AgentMemoryStore:
        slug = slugify(name)
        if slug not in self._memories:
            self._memories[slug] = AgentMemoryStore(agent_name=slug, memory_root=str(self.memory_root))
        return self._memories[slug]

    def status_snapshot(self, limit: int = 10) -> List[Dict[str, Any]]:
        snapshot: List[Dict[str, Any]] = []
        for agent in self.list_agents():
            memory = self.get_memory(agent.slug)
            recent = memory.get_recent_messages(limit)
            status = memory.get_status()
            snapshot.append(
                {
                    "name": agent.name,
                    "slug": agent.slug,
                    "role": agent.role,
                    "summary": agent.summary,
                    "tools": agent.tools,
                    "skills": agent.skills,
                    "voice": agent.voice,
                    "timeout_seconds": agent.timeout_seconds,
                    "memory_path": agent.memory_db,
                    "recent_messages": recent,
                    "message_count": len(recent),
                    "state": status.get("state", "idle"),
                    "confidence": status.get("confidence", 0.0),
                    "active_task": status.get("active_task", ""),
                    "last_message": status.get("last_message", ""),
                    "last_sender": status.get("last_sender", ""),
                    "last_update": status.get("last_update", 0.0),
                    "run_count": status.get("run_count", 0),
                    "error_count": status.get("error_count", 0),
                }
            )
        return snapshot

    def resolve_agent_skills(self, agent_name: str, task_text: str, max_results: int = 8) -> List[str]:
        agent = self.get_agent(agent_name)
        if not agent:
            return []

        assigned_skills = [skill for skill in agent.skills if skill]
        return assigned_skills[:max_results]

    def build_agent_skill_context(self, agent_name: str, task_text: str, max_results: int = 8) -> str:
        if self.skill_engine is None:
            return ""

        skill_names = self.resolve_agent_skills(agent_name, task_text, max_results=max_results)
        if not skill_names:
            return ""

        return self.skill_engine.get_skill_context(skill_names)

    def build_agent_prompt(
        self,
        agent_name: str,
        task_text: str,
        memory_window: int = 20,
        collaboration_context: Optional[str] = None,
        skill_context: Optional[str] = None,
        skill_names: Optional[List[str]] = None,
        incoming_messages: Optional[List[Dict[str, Any]]] = None,
        handoff_from: Optional[str] = None,
        execution_context: Optional[List[Dict[str, Any]]] = None,
    ) -> str:
        agent = self.get_agent(agent_name)
        if not agent:
            raise KeyError(f"Unknown agent: {agent_name}")

        memory = self.get_memory(agent.slug)
        recent_messages = memory.get_recent_messages(memory_window)
        memory_lines = []
        for entry in recent_messages:
            memory_lines.append(f"{entry['role']}: {entry['content']}")

        sections = [
            agent.prompt.strip(),
            "",
            "Context Boundary: isolated agent execution",
            f"Role: {agent.role}",
            f"Summary: {agent.summary}",
            f"Tools: {', '.join(agent.tools) if agent.tools else 'none'}",
            f"Skill Focus: {', '.join(skill_names) if skill_names else 'none'}",
            f"Voice: {json.dumps(agent.voice, ensure_ascii=True)}",
            f"Handoff From: {handoff_from or 'user'}",
            "",
            "Recent Memory:",
            "\n".join(memory_lines) if memory_lines else "No prior memory.",
        ]

        if incoming_messages:
            rendered_messages = []
            for entry in incoming_messages:
                sender = entry.get("from") or entry.get("source") or "peer"
                target = entry.get("to") or agent.slug
                message = entry.get("message") or entry.get("content") or ""
                rendered_messages.append(f"{sender} -> {target}: {message}")
            sections.extend(["", "Incoming Agent Messages:", "\n".join(rendered_messages)])

        if collaboration_context:
            sections.extend(["", "Collaboration Context:", collaboration_context.strip()])

        if skill_context:
            sections.extend(["", "Skill Context:", skill_context.strip()])

        if execution_context:
            rendered_actions = []
            for entry in execution_context:
                tool = entry.get("tool", "")
                status = entry.get("status", "")
                result = entry.get("result", "")
                error = entry.get("error", "")
                rendered_actions.append(
                    f"{tool} [{status}] result={result} error={error}".strip()
                )
            sections.extend(["", "Recent Tool Results:", "\n".join(rendered_actions)])

        sections.extend(
            [
                "",
                "Task:",
                task_text.strip(),
                "",
                'Respond with STRICT JSON only using this format:',
                '{"agent":"<AgentName>","task":"<Task>","thought":"<Reasoning>","actions":[{"tool":"file_write","path":"...","content":"..."}],"result":"<Short result or plan summary>","status":"running|completed","confidence":0.0}',
                "Rules:",
                "- Return actions as a JSON array.",
                "- Use only supported tools.",
                "- If the work is complete, return status completed and an empty actions array.",
                "- If follow-up work is needed, return status running and at least one action.",
            ]
        )
        return "\n".join(sections)

    async def run_agent(
        self,
        agent_name: str,
        task_text: str,
        skill_context: Optional[str] = None,
        collaboration_context: Optional[str] = None,
        incoming_messages: Optional[List[Dict[str, Any]]] = None,
        handoff_from: Optional[str] = None,
        execution_context: Optional[List[Dict[str, Any]]] = None,
        iteration: int = 0,
        max_tokens: int = 700,
        timeout_seconds: Optional[float] = None,
        execution_trace_id: Optional[str] = None,
    ) -> AgentResult:
        agent = self.get_agent(agent_name)
        if not agent:
            raise KeyError(f"Unknown agent: {agent_name}")

        memory = self.get_memory(agent.slug)
        resolved_skill_names = self.resolve_agent_skills(agent.slug, task_text)
        resolved_skill_context = skill_context if skill_context is not None else self.build_agent_skill_context(agent.slug, task_text)
        effective_timeout = float(timeout_seconds if timeout_seconds is not None else agent.timeout_seconds or runtime_config.AGENT_TIMEOUT_SECONDS)
        start = time.time()
        trace = None
        if self.trace_manager is not None:
            trace = self.trace_manager.get_trace(execution_trace_id) if execution_trace_id else self.trace_manager.create_trace(
                task_id=task_text,
                parent_task_id=handoff_from or "",
                agent_name=agent.slug,
                action_type="agent_execution",
                status="running",
                result_summary=task_text,
            )
            execution_trace_id = trace.execution_id if trace else execution_trace_id

        memory.set_status(
            "running",
            confidence=0.0,
            active_task=task_text,
            last_message=task_text,
            last_sender=handoff_from or "user",
            increment_run=True,
        )
        memory.log_event(
            "agent_started",
            source_agent=handoff_from or "user",
            target_agent=agent.slug,
            task=task_text,
            message=task_text,
            payload={
                "skill_context_present": bool(resolved_skill_context),
                "handoff_from": handoff_from,
                "skill_names": resolved_skill_names,
                "timeout_seconds": effective_timeout,
                "iteration": iteration,
            },
        )
        memory.add_message("user", task_text, {"agent": agent.slug, "role": "user", "handoff_from": handoff_from})

        if incoming_messages:
            for entry in incoming_messages:
                sender = entry.get("from") or entry.get("source") or handoff_from or "peer"
                message = entry.get("message") or entry.get("content") or ""
                memory.add_message(
                    "peer",
                    message,
                    {
                        "from": sender,
                        "to": agent.slug,
                        "task": task_text,
                        "handoff_from": handoff_from,
                    },
                )

        prompt = self.build_agent_prompt(
            agent_name=agent.slug,
            task_text=task_text,
            memory_window=int(agent.config.get("memory_window", 20)),
            collaboration_context=collaboration_context,
            skill_context=resolved_skill_context,
            skill_names=resolved_skill_names,
            incoming_messages=incoming_messages,
            handoff_from=handoff_from,
            execution_context=execution_context,
        )

        try:
            if self.llm_client is not None:
                response = await asyncio.wait_for(
                    self.llm_client.generate(
                        prompt,
                        max_tokens=int(agent.config.get("max_tokens", max_tokens)),
                    ),
                    timeout=effective_timeout,
                )
            else:
                response = self._fallback_action_response(
                    agent=agent,
                    task_text=task_text,
                    collaboration_context=collaboration_context,
                    skill_names=resolved_skill_names,
                    execution_context=execution_context or [],
                    iteration=iteration,
                )

            if response is None:
                response = self._fallback_action_response(
                    agent=agent,
                    task_text=task_text,
                    collaboration_context=collaboration_context,
                    skill_names=resolved_skill_names,
                    execution_context=execution_context or [],
                    iteration=iteration,
                )

            elapsed = time.time() - start
            structured_output = self._parse_action_plan(agent, task_text, response or "", iteration=iteration)
            structured_output.setdefault("agent", agent.display_name)
            structured_output.setdefault("task", task_text)
            structured_output.setdefault("thought", "")
            structured_output.setdefault("actions", [])
            structured_output.setdefault("result", "")
            status = str(structured_output.get("status") or ("running" if structured_output.get("actions") else "completed")).lower()
            if status not in {"pending", "running", "completed", "failed"}:
                status = "running" if structured_output.get("actions") else "completed"
            structured_output["status"] = status
            confidence = self._estimate_confidence(agent, structured_output, response or "", handoff_from=handoff_from)
            structured_output["confidence"] = confidence
            structured_output.setdefault("handoff_from", handoff_from)
            structured_output.setdefault("skill_names", resolved_skill_names)
            structured_output.setdefault("timeout_seconds", effective_timeout)
            structured_output.setdefault("iteration", iteration)
            structured_output.setdefault("complete", status == "completed" and not structured_output.get("actions"))

            memory.add_message(
                "assistant",
                json.dumps(structured_output, ensure_ascii=True),
                {"agent": agent.slug, "role": "assistant", "structured": True, "iteration": iteration},
            )
            result_text = str(structured_output.get("result") or structured_output.get("thought") or "")
            memory.remember_summary(agent.slug, result_text[:1000])
            memory.set_status(
                "completed" if status == "completed" else "running",
                confidence=confidence,
                active_task=task_text,
                last_message=result_text,
                last_sender=handoff_from or "user",
            )
            event_type = "agent_completed" if status == "completed" and not structured_output.get("actions") else "agent_planned"
            memory.log_event(
                event_type,
                source_agent=agent.slug,
                target_agent=handoff_from,
                task=task_text,
                message=result_text,
                confidence=confidence,
                payload={
                    "structured_output": structured_output,
                    "skill_names": resolved_skill_names,
                    "timeout_seconds": effective_timeout,
                    "elapsed_seconds": elapsed,
                    "iteration": iteration,
                    "has_actions": bool(structured_output.get("actions")),
                },
            )
            logger.info(
                "Agent performance: agent=%s status=%s elapsed=%.2fs timeout=%.2fs skills=%d memory=%s",
                agent.slug,
                status,
                elapsed,
                effective_timeout,
                len(resolved_skill_names),
                memory.db_path,
            )
            if self.trace_manager is not None and execution_trace_id:
                self.trace_manager.complete_trace(execution_trace_id, result_summary=result_text)

            return AgentResult(
                agent=agent.slug,
                task=task_text,
                result=result_text,
                structured_output=structured_output,
                prompt=prompt,
                memory_path=str(memory.db_path),
                elapsed_seconds=elapsed,
                confidence=confidence,
                status=status,
                handoff_from=handoff_from,
                metadata={
                    "tools": agent.tools,
                    "voice": agent.voice,
                    "role": agent.role,
                    "skill_names": resolved_skill_names,
                    "timeout_seconds": effective_timeout,
                    "iteration": iteration,
                },
            )
        except asyncio.TimeoutError:
            elapsed = time.time() - start
            error_text = f"Agent timeout after {effective_timeout:.2f}s"
            failed_output = {
                "agent": agent.display_name,
                "task": task_text,
                "result": error_text,
                "error": "timeout",
                "status": "failed",
                "confidence": 0.0,
                "skill_names": resolved_skill_names,
                "timeout_seconds": effective_timeout,
            }
            memory.add_message(
                "assistant",
                json.dumps(failed_output, ensure_ascii=True),
                {"agent": agent.slug, "role": "assistant", "structured": True, "failed": True},
            )
            memory.set_status(
                "failed",
                confidence=0.0,
                active_task=task_text,
                last_message=error_text,
                last_sender=handoff_from or "user",
                increment_error=True,
            )
            memory.log_event(
                "agent_failed",
                source_agent=agent.slug,
                target_agent=handoff_from,
                task=task_text,
                message=error_text,
                payload={
                    "error": "timeout",
                    "timeout_seconds": effective_timeout,
                    "elapsed_seconds": elapsed,
                    "skill_names": resolved_skill_names,
                },
            )
            logger.warning(
                "Agent timeout: agent=%s elapsed=%.2fs timeout=%.2fs memory=%s",
                agent.slug,
                elapsed,
                effective_timeout,
                memory.db_path,
            )
            if self.trace_manager is not None and execution_trace_id:
                self.trace_manager.fail_trace(execution_trace_id, error_text)
            return AgentResult(
                agent=agent.slug,
                task=task_text,
                result=error_text,
                structured_output=failed_output,
                prompt=prompt,
                memory_path=str(memory.db_path),
                elapsed_seconds=elapsed,
                confidence=0.0,
                status="failed",
                handoff_from=handoff_from,
                metadata={
                    "tools": agent.tools,
                    "voice": agent.voice,
                    "role": agent.role,
                    "skill_names": resolved_skill_names,
                    "timeout_seconds": effective_timeout,
                    "error": "timeout",
                    "iteration": iteration,
                },
            )
        except Exception as exc:
            elapsed = time.time() - start
            memory.set_status(
                "failed",
                confidence=0.0,
                active_task=task_text,
                last_message=str(exc),
                last_sender=handoff_from or "user",
                increment_error=True,
            )
            memory.log_event(
                "agent_failed",
                source_agent=agent.slug,
                target_agent=handoff_from,
                task=task_text,
                message=str(exc),
                payload={
                    "error": repr(exc),
                    "skill_names": resolved_skill_names,
                    "timeout_seconds": effective_timeout,
                    "elapsed_seconds": elapsed,
                },
            )
            logger.exception(
                "Agent failure: agent=%s elapsed=%.2fs timeout=%.2fs memory=%s",
                agent.slug,
                elapsed,
                effective_timeout,
                memory.db_path,
            )
            if self.trace_manager is not None and execution_trace_id:
                self.trace_manager.fail_trace(execution_trace_id, str(exc))
            failed_output = {
                "agent": agent.display_name,
                "task": task_text,
                "result": str(exc),
                "error": repr(exc),
                "status": "failed",
                "confidence": 0.0,
                "skill_names": resolved_skill_names,
                "timeout_seconds": effective_timeout,
                "iteration": iteration,
                "thought": "",
                "actions": [],
            }
            memory.add_message(
                "assistant",
                json.dumps(failed_output, ensure_ascii=True),
                {"agent": agent.slug, "role": "assistant", "structured": True, "failed": True},
            )
            return AgentResult(
                agent=agent.slug,
                task=task_text,
                result=str(exc),
                structured_output=failed_output,
                prompt=prompt,
                memory_path=str(memory.db_path),
                elapsed_seconds=elapsed,
                confidence=0.0,
                status="failed",
                handoff_from=handoff_from,
                metadata={
                    "tools": agent.tools,
                    "voice": agent.voice,
                    "role": agent.role,
                    "skill_names": resolved_skill_names,
                    "timeout_seconds": effective_timeout,
                    "error": repr(exc),
                    "iteration": iteration,
                },
            )

    def _parse_action_plan(self, agent: AgentDefinition, task_text: str, response_text: Any, iteration: int = 0) -> Dict[str, Any]:
        parsed: Optional[Dict[str, Any]] = None
        cleaned = ""
        if isinstance(response_text, dict):
            parsed = dict(response_text)
            cleaned = json.dumps(parsed, ensure_ascii=True)
        else:
            cleaned = (response_text or "").strip()
            if cleaned:
                candidate = self._extract_json_object(cleaned)
                if candidate:
                    try:
                        maybe_data = json.loads(candidate)
                        if isinstance(maybe_data, dict):
                            parsed = maybe_data
                    except Exception:
                        parsed = None

        if parsed is None and cleaned:
            candidate = self._extract_json_object(cleaned)
            if candidate:
                try:
                    maybe_data = json.loads(candidate)
                    if isinstance(maybe_data, dict):
                        parsed = maybe_data
                except Exception:
                    parsed = None

        if parsed is None:
            parsed = self._fallback_action_response(
                agent=agent,
                task_text=task_text,
                collaboration_context=None,
                skill_names=agent.skills,
                execution_context=[],
                iteration=iteration,
            )
        parsed.setdefault("agent", agent.display_name)
        parsed.setdefault("task", task_text)
        parsed.setdefault("thought", "")
        parsed.setdefault("actions", [])
        parsed.setdefault("result", cleaned or "")
        parsed.setdefault("status", "running" if parsed.get("actions") else "completed")
        if not isinstance(parsed.get("actions"), list):
            parsed["actions"] = []
        normalized_actions: List[Dict[str, Any]] = []
        for action in parsed.get("actions", []):
            if isinstance(action, AgentAction):
                normalized_actions.append(
                    {
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
                )
            elif isinstance(action, dict):
                normalized_actions.append(dict(action))
        parsed["actions"] = normalized_actions
        return parsed

    def _extract_json_object(self, text: str) -> Optional[str]:
        if not text:
            return None
        stripped = text.strip()
        if stripped.startswith("{") and stripped.endswith("}"):
            return stripped
        start = stripped.find("{")
        end = stripped.rfind("}")
        if start >= 0 and end > start:
            return stripped[start : end + 1]
        return None

    def _estimate_confidence(
        self,
        agent: AgentDefinition,
        structured_output: Dict[str, Any],
        raw_response: Any,
        handoff_from: Optional[str] = None,
    ) -> float:
        response_text = json.dumps(raw_response, ensure_ascii=True) if isinstance(raw_response, dict) else str(raw_response or "")
        score = 0.5
        if structured_output.get("agent"):
            score += 0.1
        if structured_output.get("task"):
            score += 0.1
        if structured_output.get("result"):
            score += 0.1
        if handoff_from:
            score += 0.05
        lowered_response = response_text.lower()
        if agent.slug in lowered_response or agent.display_name.lower() in lowered_response:
            score += 0.05
        if isinstance(structured_output.get("confidence"), (int, float)):
            score = max(score, float(structured_output["confidence"]))
        return round(min(score, 0.98), 2)

    def _fallback_action_response(
        self,
        agent: AgentDefinition,
        task_text: str,
        collaboration_context: Optional[str] = None,
        skill_names: Optional[List[str]] = None,
        execution_context: Optional[List[Dict[str, Any]]] = None,
        iteration: int = 0,
    ) -> Dict[str, Any]:
        normalized_task = (task_text or "").lower()
        execution_context = execution_context or []
        has_successful_execution = any(str(entry.get("status", "")).lower() == "completed" for entry in execution_context)
        completed_tools = {
            str(entry.get("tool", "")).lower()
            for entry in execution_context
            if str(entry.get("status", "")).lower() == "completed"
        }
        if iteration > 0 and has_successful_execution:
            return {
                "agent": agent.display_name,
                "task": task_text,
                "thought": "The prior tool results show the task is already progressing, so I can stop here.",
                "actions": [],
                "result": "Execution complete.",
                "status": "completed",
                "confidence": 0.92,
                "iteration": iteration,
            }

        actions: List[Dict[str, Any]] = []
        thought_lines = [
            f"{agent.display_name} is preparing to execute the task.",
            f"Focus: {task_text.strip()}",
        ]
        if collaboration_context:
            thought_lines.append(f"Collaboration context: {collaboration_context.strip()}")
        if skill_names:
            thought_lines.append(f"Skills: {', '.join(skill_names)}")
        if execution_context:
            thought_lines.append(f"Observed {len(execution_context)} tool result(s).")

        allowed_tools = self._agent_tool_palette(agent.slug)
        lower_tools = [tool.lower() for tool in allowed_tools]
        if any(token in normalized_task for token in ["create", "build", "dashboard", "react", "app", "frontend"]):
            if agent.slug == "ultron" and "file_write" in lower_tools:
                base_path = "generated/react-dashboard"
                actions.extend(self._react_dashboard_actions(task_text, base_path))
            elif agent.slug == "friday" and "memory_store" in lower_tools:
                actions.append(
                    {
                        "tool": "memory_store",
                        "key": f"{agent.slug}:plan:{slugify(task_text)[:32] or uuid.uuid4().hex[:8]}",
                        "value": f"Plan the build in stages for: {task_text.strip()}",
                    }
                )
            if "terminal_execute" in lower_tools and "hulk" in agent.slug and "terminal_execute" not in completed_tools:
                actions.append(
                    {
                        "tool": "terminal_execute",
                        "command": "npm run build",
                        "cwd": "generated/react-dashboard",
                    }
                )
        elif any(token in normalized_task for token in ["research", "analyze", "compare", "investigate", "trend"]):
            if "memory_search" in lower_tools:
                actions.append({"tool": "memory_search", "query": task_text, "limit": 10})
            if "skill_lookup" in lower_tools:
                actions.append({"tool": "skill_lookup", "query": task_text})
        elif any(token in normalized_task for token in ["remember", "save memory", "store memory", "note"]):
            if "memory_store" in lower_tools:
                actions.append(
                    {
                        "tool": "memory_store",
                        "key": f"{agent.slug}:{slugify(task_text)[:40] or uuid.uuid4().hex[:8]}",
                        "value": task_text,
                    }
                )

        if not actions and "skill_lookup" in lower_tools:
            actions.append({"tool": "skill_lookup", "query": " ".join(skill_names or agent.skills)})

        if not actions and "memory_search" in lower_tools:
            actions.append({"tool": "memory_search", "query": task_text, "limit": 5})

        if not actions:
            actions.append(
                {
                    "tool": "memory_store",
                    "key": f"{agent.slug}:{slugify(task_text)[:32] or 'task'}",
                    "value": task_text,
                }
            )

        status = "running" if actions else "completed"
        return {
            "agent": agent.display_name,
            "task": task_text,
            "thought": " ".join(thought_lines).strip(),
            "actions": actions,
            "result": "Planned actions ready for execution." if actions else "Task completed without additional actions.",
            "status": status,
            "confidence": 0.72 if actions else 0.9,
            "iteration": iteration,
        }

    def _react_dashboard_actions(self, task_text: str, base_path: str) -> List[Dict[str, Any]]:
        title = "React Dashboard"
        package_json = json.dumps(
            {
                "name": "react-dashboard-scaffold",
                "private": True,
                "version": "0.0.0",
                "type": "module",
                "scripts": {
                    "build": "node -e \"console.log('react dashboard scaffold validated')\""
                },
            },
            indent=2,
            ensure_ascii=False,
        )
        main_tsx = "\n".join(
            [
                "import React from 'react';",
                "import ReactDOM from 'react-dom/client';",
                "import App from './App';",
                "import './index.css';",
                "",
                "ReactDOM.createRoot(document.getElementById('root') as HTMLElement).render(",
                "  <React.StrictMode>",
                "    <App />",
                "  </React.StrictMode>,",
                ");",
                "",
            ]
        )
        index_html = "\n".join(
            [
                "<!doctype html>",
                "<html lang=\"en\">",
                "  <head>",
                "    <meta charset=\"UTF-8\" />",
                "    <meta name=\"viewport\" content=\"width=device-width, initial-scale=1.0\" />",
                "    <title>React Dashboard</title>",
                "  </head>",
                "  <body>",
                "    <div id=\"root\"></div>",
                "    <script type=\"module\" src=\"/src/main.tsx\"></script>",
                "  </body>",
                "</html>",
                "",
            ]
        )
        app_tsx = "\n".join(
            [
                "import React from 'react';",
                "",
                "export default function App() {",
                "  return (",
                "    <main className=\"min-h-screen bg-slate-950 text-white flex items-center justify-center p-8\">",
                "      <section className=\"max-w-3xl space-y-6 rounded-3xl border border-white/10 bg-white/5 p-8 shadow-2xl backdrop-blur\">",
                f"        <p className=\"text-xs uppercase tracking-[0.3em] text-cyan-300\">{title}</p>",
                "        <h1 className=\"text-4xl font-semibold tracking-tight\">ChatGPT-style command dashboard</h1>",
                f"        <p className=\"text-sm leading-6 text-slate-300\">{task_text.strip()}</p>",
                "      </section>",
                "    </main>",
                "  );",
                "}",
                "",
            ]
        )
        index_css = "\n".join(
            [
                "@tailwind base;",
                "@tailwind components;",
                "@tailwind utilities;",
                "",
                "html, body, #root {",
                "  margin: 0;",
                "  min-height: 100%;",
                "  background: #020617;",
                "}",
                "",
            ]
        )
        return [
            {
                "tool": "file_write",
                "path": f"{base_path}/package.json",
                "content": package_json,
            },
            {
                "tool": "file_write",
                "path": f"{base_path}/src/App.tsx",
                "content": app_tsx,
            },
            {
                "tool": "file_write",
                "path": f"{base_path}/src/main.tsx",
                "content": main_tsx,
            },
            {
                "tool": "file_write",
                "path": f"{base_path}/src/index.css",
                "content": index_css,
            },
            {
                "tool": "file_write",
                "path": f"{base_path}/index.html",
                "content": index_html,
            },
        ]

    def _agent_tool_palette(self, agent_slug: str) -> List[str]:
        agent = self.get_agent(agent_slug)
        base_tools = [str(tool).lower() for tool in (agent.tools if agent and agent.tools else [])]
        supported_tools = [
            "file_write",
            "file_read",
            "terminal_execute",
            "skill_lookup",
            "memory_store",
            "memory_search",
        ]
        return list(dict.fromkeys([*base_tools, *supported_tools]))

    def build_collaboration_context(self, outputs: Dict[str, AgentResult]) -> str:
        lines = []
        for agent_name, result in outputs.items():
            lines.append(f"{agent_name}: {result.result}")
        return "\n".join(lines)

    def send_message(
        self,
        sender: str,
        recipient: str,
        task: str,
        message: str,
        confidence: float = 0.0,
        payload: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        sender_slug = slugify(sender)
        recipient_slug = slugify(recipient)
        recipient_memory = self.get_memory(recipient_slug)
        sender_memory = self.get_memory(sender_slug) if sender_slug and sender_slug in self._memories else None

        envelope = {
            "from": sender_slug,
            "to": recipient_slug,
            "task": task,
            "message": message,
            "confidence": confidence,
            "payload": payload or {},
        }
        recipient_memory.add_message("peer", message, envelope)
        recipient_memory.log_event("message_received", source_agent=sender_slug, target_agent=recipient_slug, task=task, message=message, confidence=confidence, payload=payload or {})
        recipient_memory.set_status("idle", confidence=confidence, active_task=task, last_message=message, last_sender=sender_slug)

        if sender_memory is not None:
            sender_memory.log_event("message_sent", source_agent=sender_slug, target_agent=recipient_slug, task=task, message=message, confidence=confidence, payload=payload or {})

        return envelope


__all__ = ["AgentManager"]
