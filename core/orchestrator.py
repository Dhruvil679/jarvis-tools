from __future__ import annotations

import asyncio
import json
import uuid
from typing import Any, Dict, List, Optional
import time

from .agent_manager import AgentManager
from .agent_memory import AgentMemoryStore
from .agent_models import AgentResult, AgentStatusSnapshot, AgentTask, CollaborationEvent, OrchestrationResult, RouteDecision, ToolExecutionRecord
from .agent_router import AgentRouter
from .logger import get_logger
from .tool_executor import ToolExecutor


logger = get_logger(__name__)


class JarvisOrchestrator:
    def __init__(
        self,
        agent_manager: AgentManager,
        agent_router: AgentRouter,
        skill_engine: Optional[Any] = None,
        shared_memory: Optional[AgentMemoryStore] = None,
        tool_executor: Optional[ToolExecutor] = None,
    ) -> None:
        self.agent_manager = agent_manager
        self.agent_router = agent_router
        self.skill_engine = skill_engine
        self.shared_memory = shared_memory or AgentMemoryStore(agent_name="jarvis")
        self.tool_executor = tool_executor or ToolExecutor(agent_manager=agent_manager, skill_engine=skill_engine)

    async def process(self, user_text: str, mode: str = "auto", preferred_agent: Optional[str] = None) -> OrchestrationResult:
        started_at = time.time()
        self.shared_memory.set_status(
            "running",
            confidence=0.0,
            active_task=user_text,
            last_message=user_text,
            last_sender="user",
            increment_run=True,
        )
        self.shared_memory.add_message("user", user_text, {"scope": "orchestrator", "mode": mode})

        route = self.agent_router.route(user_text, preferred_agent=preferred_agent, mode=mode)
        timeline: List[CollaborationEvent] = []
        execution_logs: List[str] = []
        timeline.append(
            CollaborationEvent(
                ts=time.time(),
                event_type="route_decided",
                source_agent="orchestrator",
                target_agent=route.primary_agent,
                task=user_text,
                message=route.reason,
                confidence=route.confidence,
                status=route.mode,
                payload={
                    "collaborators": route.collaborators,
                    "handoff_chain": route.handoff_chain,
                    "signals": route.signals,
                },
            )
        )
        execution_logs.append(
            f"Route decided: primary={route.primary_agent} mode={route.mode} confidence={route.confidence:.2f}"
        )

        skill_names: List[str] = []
        skill_context = ""
        if self.skill_engine is not None:
            try:
                matched = self.skill_engine.match_skills(user_text)
                skill_names = [skill.name for skill in matched]
                skill_context = self.skill_engine.get_skill_context(skill_names)
            except Exception as exc:
                logger.warning("Skill resolution failed: %s", exc)

        tasks = self.agent_router.decompose(user_text, route)
        if route.mode == "multi":
            friday_tasks = [task for task in tasks if task.agent == "friday"]
            other_tasks = [task for task in tasks if task.agent != "friday"]
            if friday_tasks:
                tasks = [*friday_tasks, *other_tasks]
        for task_index, task in enumerate(tasks):
            task.step = task_index
            task.depends_on = [tasks[task_index - 1].agent] if task_index > 0 else []
        execution_logs.append(f"Launching isolated fan-out: agents={len(tasks)}")
        dependency_events: Dict[str, asyncio.Event] = {task.agent: asyncio.Event() for task in tasks}

        task_results = await asyncio.gather(
            *[
                self._execute_agent_task(task, user_text, route, index, len(tasks), dependency_events)
                for index, task in enumerate(tasks)
            ],
            return_exceptions=True,
        )

        outputs: Dict[str, AgentResult] = {}
        execution_records: List[ToolExecutionRecord] = []
        for index, item in enumerate(task_results):
            task = tasks[index]
            if isinstance(item, Exception):
                elapsed = time.time() - started_at
                logger.exception("Unexpected orchestration failure for %s", task.agent)
                failed_result = AgentResult(
                    agent=task.agent,
                    task=task.objective,
                    result=str(item),
                    prompt="",
                    memory_path=str(self.agent_manager.get_memory(task.agent).db_path),
                    elapsed_seconds=elapsed,
                    structured_output={
                        "agent": task.agent,
                        "task": task.objective,
                        "result": str(item),
                        "error": repr(item),
                        "status": "failed",
                    },
                    confidence=0.0,
                    status="failed",
                    handoff_from="user",
                    metadata={"error": repr(item), "timeout_seconds": self.agent_manager.get_agent(task.agent).timeout_seconds if self.agent_manager.get_agent(task.agent) else None},
                )
                outputs[task.agent] = failed_result
                timeline.append(
                    CollaborationEvent(
                        ts=time.time(),
                        event_type="agent_failed",
                        source_agent=task.agent,
                        target_agent="orchestrator",
                        task=task.objective,
                        message=str(item),
                        confidence=0.0,
                        status="failed",
                        payload={"error": repr(item)},
                    )
                )
                execution_logs.append(f"Agent failed: {task.agent} error={item}")
                continue

            result = item["result"]
            outputs[result.agent] = result
            timeline.extend(item["timeline"])
            execution_logs.extend(item["execution_logs"])
            execution_records.extend(item["execution_records"])

        merged_output = await self._merge_outputs(user_text, route, outputs, skill_context, execution_records)
        final_response = merged_output.get("final_response", "")

        timeline.append(
            CollaborationEvent(
                ts=time.time(),
                event_type="merge_completed",
                source_agent="orchestrator",
                target_agent="user",
                task=user_text,
                message=final_response,
                confidence=float(merged_output.get("confidence", route.confidence) or route.confidence),
                status="completed",
                payload=merged_output,
            )
        )
        timeline.sort(key=lambda event: event.ts)

        elapsed_seconds = time.time() - started_at
        execution_logs.append(f"Merge completed in {elapsed_seconds:.2f}s")
        execution_logs.append(
            f"Orchestrator performance: elapsed={elapsed_seconds:.2f}s agents={len(outputs)} completed={sum(1 for item in outputs.values() if item.status == 'completed')} failed={sum(1 for item in outputs.values() if item.status == 'failed')}"
        )

        self.shared_memory.add_message(
            "assistant",
            json.dumps(merged_output, ensure_ascii=False),
            {"route": route.primary_agent, "mode": route.mode, "agents": list(outputs.keys()), "elapsed_seconds": elapsed_seconds},
        )

        overall_state = "completed" if any(item.status == "completed" for item in outputs.values()) else "failed"
        self.shared_memory.set_status(
            overall_state,
            confidence=max((item.confidence for item in outputs.values()), default=0.0),
            active_task=user_text,
            last_message=final_response or merged_output.get("result", ""),
            last_sender=route.primary_agent,
        )
        logger.info(
            "Orchestrator performance: mode=%s route=%s agents=%d elapsed=%.2fs state=%s",
            route.mode,
            route.primary_agent,
            len(outputs),
            elapsed_seconds,
            overall_state,
        )

        return OrchestrationResult(
            user_text=user_text,
            route=route,
            plan=tasks,
            agent_outputs=outputs,
            execution_records=execution_records,
            final_response=final_response,
            merged_output=merged_output,
            timeline=timeline,
            execution_logs=execution_logs,
            statuses=self._collect_statuses(),
            mode=route.mode,
        )

    async def _execute_agent_task(
        self,
        task: AgentTask,
        user_text: str,
        route: RouteDecision,
        index: int,
        total: int,
        dependency_events: Dict[str, asyncio.Event],
    ) -> Dict[str, Any]:
        started_at = time.time()
        task_id = task.task_id or uuid.uuid4().hex
        timeline: List[CollaborationEvent] = [
            CollaborationEvent(
                ts=started_at,
                event_type="agent_started",
                source_agent="orchestrator",
                target_agent=task.agent,
                task=task.objective,
                message=task.focus,
                confidence=route.confidence,
                status="running",
                payload={
                    "step": task.step,
                    "depends_on": task.depends_on,
                    "index": index,
                    "total": total,
                },
            )
        ]
        execution_logs = [f"Agent start: {task.agent} step={task.step} task_id={task_id}"]
        execution_records: List[ToolExecutionRecord] = []
        agent = self.agent_manager.get_agent(task.agent)
        timeout_seconds = agent.timeout_seconds if agent else None
        execution_context: List[Dict[str, Any]] = []
        final_result: Optional[AgentResult] = None
        last_result: Optional[AgentResult] = None
        if agent is not None:
            self.agent_manager.get_memory(task.agent).record_task(
                task_id=task_id,
                task=task.objective,
                state="pending",
                tool="",
                result="",
                error="",
                duration_seconds=0.0,
                iteration=0,
                metadata={"step": task.step, "depends_on": task.depends_on, "total": total, "index": index},
            )

        try:
            if task.depends_on:
                await asyncio.gather(
                    *[
                        dependency_events[dependency].wait()
                        for dependency in task.depends_on
                        if dependency in dependency_events
                    ]
                )

            for iteration in range(5):
                result = await self.agent_manager.run_agent(
                    task.agent,
                    task.objective,
                    collaboration_context=None,
                    incoming_messages=None,
                    handoff_from="user",
                    execution_context=execution_context,
                    iteration=iteration,
                    timeout_seconds=timeout_seconds,
                )
                last_result = result
                timeline.append(
                    CollaborationEvent(
                        ts=time.time(),
                        event_type="agent_planned" if result.structured_output.get("actions") else "agent_completed",
                        source_agent=task.agent,
                        target_agent="orchestrator",
                        task=task.objective,
                        message=str(result.structured_output.get("result", result.result)),
                        confidence=result.confidence,
                        status=result.status,
                        payload=result.structured_output,
                    )
                )
                execution_logs.append(
                    f"Agent iteration {iteration}: {task.agent} status={result.status} elapsed={result.elapsed_seconds:.2f}s confidence={result.confidence:.2f}"
                )

                actions = result.structured_output.get("actions", []) or []
                if not actions:
                    final_result = result
                    break

                tool_results = await asyncio.to_thread(
                    self.tool_executor.execute_actions,
                    task.agent,
                    task_id,
                    [action for action in actions if isinstance(action, dict)],
                    iteration,
                    task.objective,
                )
                execution_records.extend(tool_results)
                execution_context = [record.to_dict() for record in tool_results]

                for tool_result in tool_results:
                    event_type = "tool_completed" if tool_result.status == "completed" else "tool_failed"
                    timeline.append(
                        CollaborationEvent(
                            ts=tool_result.ts or time.time(),
                            event_type=event_type,
                            source_agent=task.agent,
                            target_agent=task.agent,
                            task=task.objective,
                            message=tool_result.result,
                            confidence=1.0 if tool_result.status == "completed" else 0.0,
                            status=tool_result.status,
                            payload=tool_result.to_dict(),
                        )
                    )
                    execution_logs.append(
                        f"Tool {tool_result.tool}: {tool_result.status} duration={tool_result.duration_seconds:.2f}s result={(tool_result.result[:180] + '...') if len(tool_result.result) > 180 else tool_result.result}"
                    )

                if all(record.status == "failed" for record in tool_results):
                    final_result = result
                    break

                final_result = result
            else:
                execution_logs.append(f"Iteration limit reached for {task.agent}")

            if final_result is None:
                final_result = last_result

            if final_result is None:
                raise RuntimeError(f"No result returned for {task.agent}")

            if final_result.status != "completed":
                failure_reason = "Iteration limit reached" if final_result.status == "running" else "One or more tool executions failed"
                final_result = AgentResult(
                    agent=task.agent,
                    task=task.objective,
                    result=final_result.result,
                    prompt=final_result.prompt,
                    memory_path=final_result.memory_path,
                    elapsed_seconds=time.time() - started_at,
                    structured_output={
                        **final_result.structured_output,
                        "status": "failed",
                        "error": failure_reason,
                    },
                    confidence=final_result.confidence,
                    status="failed",
                    handoff_from=final_result.handoff_from,
                    metadata={**final_result.metadata, "execution_records": len(execution_records)},
                )

            if final_result.status == "failed" and agent is not None:
                agent_memory = self.agent_manager.get_memory(task.agent)
                agent_memory.set_status(
                    "failed",
                    confidence=final_result.confidence,
                    active_task=task.objective,
                    last_message=final_result.result,
                    last_sender="orchestrator",
                    increment_error=True,
                )
                agent_memory.log_event(
                    "agent_failed",
                    source_agent=task.agent,
                    target_agent="orchestrator",
                    task=task.objective,
                    message=final_result.result,
                    confidence=final_result.confidence,
                    payload={"execution_records": [record.to_dict() for record in execution_records]},
                )

            execution_logs.append(
                f"Agent finished: {task.agent} status={final_result.status} elapsed={final_result.elapsed_seconds:.2f}s confidence={final_result.confidence:.2f}"
            )
            dependency_events[task.agent].set()
            return {
                "task": task,
                "result": final_result,
                "timeline": timeline,
                "execution_logs": execution_logs,
                "execution_records": execution_records,
            }
        except Exception as exc:
            elapsed = time.time() - started_at
            logger.exception("Agent task execution failed: %s", task.agent)
            failed_result = AgentResult(
                agent=task.agent,
                task=task.objective,
                result=str(exc),
                prompt="",
                memory_path=str(self.agent_manager.get_memory(task.agent).db_path),
                elapsed_seconds=elapsed,
                structured_output={
                    "agent": task.agent,
                    "task": task.objective,
                    "result": str(exc),
                    "error": repr(exc),
                    "status": "failed",
                },
                confidence=0.0,
                status="failed",
                handoff_from="user",
                metadata={
                    "error": repr(exc),
                    "timeout_seconds": timeout_seconds,
                },
            )
            timeline.append(
                CollaborationEvent(
                    ts=time.time(),
                    event_type="agent_failed",
                    source_agent=task.agent,
                    target_agent="orchestrator",
                    task=task.objective,
                    message=str(exc),
                    confidence=0.0,
                    status="failed",
                    payload={"error": repr(exc)},
                )
            )
            execution_logs.append(f"Agent failed: {task.agent} error={exc}")
            dependency_events[task.agent].set()
            return {
                "task": task,
                "result": failed_result,
                "timeline": timeline,
                "execution_logs": execution_logs,
                "execution_records": execution_records,
            }

    async def _merge_outputs(
        self,
        user_text: str,
        route: RouteDecision,
        outputs: Dict[str, AgentResult],
        skill_context: str,
        execution_records: List[ToolExecutionRecord],
    ) -> Dict[str, Any]:
        summary_lines = []
        for agent_name, result in outputs.items():
            summary_lines.append(f"{agent_name}: {result.result}")

        artifact_paths = []
        for record in execution_records:
            if record.tool == "file_write" and record.path:
                artifact_paths.append(record.path)

        merge_prompt = "\n".join(
            [
                "You are JARVIS Orchestrator.",
                "Synthesize the specialist responses into one concise operating-system-grade answer.",
                f"User request: {user_text}",
                f"Route mode: {route.mode}",
                f"Primary agent: {route.primary_agent}",
                f"Skill context: {skill_context}" if skill_context else "Skill context: none",
                "Specialist outputs:",
                "\n".join(summary_lines),
                f"Generated artifacts: {', '.join(artifact_paths) if artifact_paths else 'none'}",
                "Return a final merged response with a practical next-action structure.",
            ]
        )

        if self.agent_manager.llm_client is not None:
            merged = await self.agent_manager.llm_client.generate(merge_prompt, max_tokens=800)
            if merged:
                parsed = self._parse_json_payload(merged)
                if parsed is not None:
                    parsed.setdefault("agent", "JARVIS")
                    parsed.setdefault("task", user_text)
                    parsed.setdefault("result", parsed.get("result") or merged.strip())
                    parsed.setdefault("final_response", str(parsed.get("result") or merged.strip()))
                    parsed.setdefault("outputs", {name: result.structured_output for name, result in outputs.items()})
                    parsed.setdefault("execution_records", [record.to_dict() for record in execution_records])
                    parsed.setdefault("artifacts", artifact_paths)
                    return parsed

        header = "JARVIS Operating Summary"
        final_response = "\n".join([header, *summary_lines])
        merged_output = {
            "agent": "JARVIS",
            "task": user_text,
            "result": final_response,
            "final_response": final_response,
            "mode": route.mode,
            "primary_agent": route.primary_agent,
            "collaborators": route.collaborators,
            "confidence": route.confidence,
            "outputs": {name: result.structured_output for name, result in outputs.items()},
            "summary_lines": summary_lines,
            "execution_records": [record.to_dict() for record in execution_records],
            "artifacts": artifact_paths,
        }
        return merged_output

    def _format_task_context(self, tasks: List[AgentTask]) -> str:
        lines = [f"{task.step}:{task.agent}: {task.focus}" for task in tasks]
        return "\n".join(lines)

    def snapshot(self) -> Dict[str, Any]:
        return {
            "agents": self.agent_manager.status_snapshot(),
            "memory": self.shared_memory.snapshot(),
        }

    def _parse_json_payload(self, text: str) -> Optional[Dict[str, Any]]:
        cleaned = (text or "").strip()
        if not cleaned:
            return None
        candidate = cleaned
        if not candidate.startswith("{"):
            start = candidate.find("{")
            end = candidate.rfind("}")
            if start >= 0 and end > start:
                candidate = candidate[start : end + 1]
        try:
            maybe_payload = json.loads(candidate)
            if isinstance(maybe_payload, dict):
                return maybe_payload
        except Exception:
            return None
        return None

    def _build_initial_message(self, user_text: str) -> Dict[str, Any]:
        return {
            "from": "user",
            "to": "orchestrator",
            "task": user_text,
            "message": user_text,
            "payload": {"source": "user_request"},
        }

    def _build_handoff_message(self, result: AgentResult, next_agent: str, user_text: str) -> str:
        payload = {
            "from_agent": result.agent,
            "to_agent": next_agent,
            "task": result.task,
            "result": result.result,
            "confidence": result.confidence,
            "status": result.status,
            "original_request": user_text,
        }
        return json.dumps(payload, ensure_ascii=False)

    def _merge_structured_outputs(self, user_text: str, route: RouteDecision, outputs: List[AgentResult], skill_context: str) -> Dict[str, Any]:
        merged = {
            "agent": "JARVIS",
            "task": user_text,
            "result": outputs[-1].result if outputs else "",
            "final_response": outputs[-1].result if outputs else "",
            "mode": route.mode,
            "primary_agent": route.primary_agent,
            "collaborators": route.collaborators,
            "confidence": max((item.confidence for item in outputs), default=route.confidence),
            "skill_context": skill_context,
            "outputs": [output.structured_output for output in outputs],
        }
        if outputs:
            merged["result"] = self._compose_summary(outputs)
            merged["final_response"] = merged["result"]
        return merged

    def _compose_summary(self, outputs: List[AgentResult]) -> str:
        parts = []
        for result in outputs:
            parts.append(f"{result.agent}: {result.result}")
        return "\n".join(parts)

    def _collect_statuses(self) -> Dict[str, AgentStatusSnapshot]:
        status_map: Dict[str, AgentStatusSnapshot] = {}
        for entry in self.agent_manager.status_snapshot():
            status_map[entry["slug"]] = AgentStatusSnapshot(
                agent=entry["slug"],
                state=entry.get("state", "idle"),
                confidence=float(entry.get("confidence", 0.0) or 0.0),
                active_task=entry.get("active_task", ""),
                last_message=entry.get("last_message", ""),
                last_sender=entry.get("last_sender", ""),
                last_update=float(entry.get("last_update", 0.0) or 0.0),
                run_count=int(entry.get("run_count", 0) or 0),
                error_count=int(entry.get("error_count", 0) or 0),
            )
        return status_map


__all__ = ["JarvisOrchestrator"]
