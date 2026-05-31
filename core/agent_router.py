from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict, List, Optional
import json
import os
import re

from .agent_models import AgentTask, RouteDecision, slugify
from .logger import get_logger


logger = get_logger(__name__)

DEFAULT_ROUTE_RULES: Dict[str, Any] = {
    "single": {
        "friday": ["briefing", "summary", "today", "schedule", "calendar", "reminder", "notification"],
        "oracle": ["research", "competitor", "analysis", "compare", "investigate", "trend", "intelligence"],
        "vision": ["image", "screenshot", "see", "observe", "camera", "visual", "monitor"],
        "ultron": ["code", "build", "react", "python", "debug", "architecture", "software", "api"],
        "hulk": ["execute", "terminal", "automation", "workflow", "script", "run command", "batch"],
        "spectre": ["legal", "contract", "compliance", "risk", "policy", "privacy", "review"],
        "herald": ["email", "announcement", "social", "press", "message", "draft", "communication"],
        "veronica": ["customer", "support", "crm", "operations", "client", "ticket", "service"],
        "gecko": ["growth", "marketing", "seo", "content", "brand", "campaign", "traffic"],
    },
    "multi": [
        {
            "keywords": ["build", "launch", "startup", "saas", "platform", "product", "go to market"],
            "agents": ["oracle", "ultron", "gecko", "friday"],
        },
        {
            "keywords": ["research", "compare", "analyze", "strategy"],
            "agents": ["oracle", "gecko", "friday"],
        },
        {
            "keywords": ["dashboard", "system", "app", "workflow", "automation"],
            "agents": ["ultron", "hulk", "friday"],
        },
    ],
}

DEFAULT_COLLABORATION_PATTERNS: List[Dict[str, Any]] = [
    {
        "keywords": ["customer", "support", "ticket", "screenshot", "bug", "issue", "fix"],
        "chain": ["veronica", "vision", "ultron", "hulk"],
    },
    {
        "keywords": ["research", "competitor", "market", "analysis", "trend"],
        "chain": ["oracle", "gecko", "friday"],
    },
    {
        "keywords": ["build", "dashboard", "app", "platform", "saas", "website"],
        "chain": ["ultron", "hulk", "friday"],
    },
    {
        "keywords": ["announcement", "email", "press", "social", "message"],
        "chain": ["herald", "friday"],
    },
]


class AgentRouter:
    def __init__(self, routes_path: Optional[str] = None, route_rules: Optional[Dict[str, Any]] = None) -> None:
        self.routes_path = Path(routes_path) if routes_path else None
        self.route_rules = route_rules or self._load_route_rules()
        self._single_rules = self.route_rules.get("single", {})
        self._multi_rules = self.route_rules.get("multi", [])
        self._collaboration_patterns = self.route_rules.get("collaboration", DEFAULT_COLLABORATION_PATTERNS)
        self._default_order = [
            "friday",
            "oracle",
            "vision",
            "ultron",
            "hulk",
            "spectre",
            "herald",
            "veronica",
            "gecko",
        ]

    def _load_route_rules(self) -> Dict[str, Any]:
        if self.routes_path and self.routes_path.exists():
            try:
                return json.loads(self.routes_path.read_text(encoding="utf-8"))
            except Exception as exc:
                logger.warning("Failed to load route config %s: %s", self.routes_path, exc)
        fallback_path = Path(__file__).resolve().parent.parent / "config" / "agent_routes.json"
        if fallback_path.exists():
            try:
                return json.loads(fallback_path.read_text(encoding="utf-8"))
            except Exception as exc:
                logger.warning("Failed to load default route config %s: %s", fallback_path, exc)
        return DEFAULT_ROUTE_RULES

    def route(self, text: str, preferred_agent: Optional[str] = None, mode: str = "auto") -> RouteDecision:
        normalized = (text or "").lower()
        hinted_agent = slugify(preferred_agent or "")
        scores: Dict[str, float] = {}
        signals: List[str] = []

        for agent_name, keywords in self._single_rules.items():
            score = 0.0
            for keyword in keywords:
                if keyword in normalized:
                    score += 1.0
                    signals.append(f"{agent_name}:{keyword}")
            if f"@{agent_name}" in normalized or agent_name in normalized:
                score += 2.0
            scores[agent_name] = score

        if hinted_agent:
            scores[hinted_agent] = scores.get(hinted_agent, 0.0) + 3.5

        primary = self._best_agent(scores) or "friday"
        confidence = min(1.0, scores.get(primary, 0.0) / 4.0)
        collaborators = self._collaborators(primary, normalized)
        handoff_chain = self._handoff_chain(primary, normalized, collaborators)
        auto_multi = self._should_use_multi_agent(normalized, primary, collaborators) or len(handoff_chain) > 1

        if mode == "single":
            collaborators = []
            handoff_chain = [primary]
        elif mode == "multi":
            auto_multi = True
            if len(handoff_chain) < 2:
                handoff_chain = [primary, *collaborators]
        if len(handoff_chain) > 1:
            collaborators = [agent for agent in handoff_chain if agent != primary]

        decision_mode = "multi" if auto_multi and len(handoff_chain) > 1 else "single"
        reason = self._build_reason(primary, collaborators, signals, decision_mode)
        confidence_scores = self._build_confidence_scores(primary, handoff_chain, scores)

        return RouteDecision(
            mode=decision_mode,
            primary_agent=primary,
            collaborators=collaborators,
            confidence=confidence,
            reason=reason,
            signals=signals[:12],
            handoff_chain=handoff_chain,
            confidence_scores=confidence_scores,
        )

    def decompose(self, text: str, decision: RouteDecision) -> List[AgentTask]:
        task_brief = (text or "").strip()
        tasks: List[AgentTask] = []
        chain = decision.handoff_chain or ([decision.primary_agent] + decision.collaborators)
        role_descriptions = {
            "friday": "Provide a concise execution summary, risks, and next actions.",
            "oracle": "Research context, competitors, or important background information.",
            "vision": "Describe what should be observed in screenshots, images, or camera feeds.",
            "ultron": "Design or implement the software, architecture, or code changes.",
            "hulk": "Break the work into concrete executable steps or terminal operations.",
            "spectre": "Evaluate legal, privacy, compliance, or risk implications.",
            "herald": "Draft communication, announcements, or outbound messaging.",
            "veronica": "Clarify support, CRM, customer-ops, or operational considerations.",
            "gecko": "Shape growth, marketing, SEO, and content strategy.",
        }

        for step_index, agent_name in enumerate(chain):
            focus = role_descriptions.get(agent_name, "Contribute specialist analysis.")
            tasks.append(
                AgentTask(
                    agent=agent_name,
                    objective=f"{focus} User request: {task_brief}",
                    focus=focus,
                    step=step_index,
                    depends_on=[chain[step_index - 1]] if step_index > 0 else [],
                )
            )
        return tasks

    def _best_agent(self, scores: Dict[str, float]) -> Optional[str]:
        if not scores:
            return None
        ranked = sorted(scores.items(), key=lambda item: (item[1], item[0]), reverse=True)
        if ranked and ranked[0][1] > 0:
            return ranked[0][0]
        return None

    def _collaborators(self, primary: str, normalized: str) -> List[str]:
        collaborators: List[str] = []
        for rule in self._multi_rules:
            keywords = rule.get("keywords", [])
            agents = rule.get("agents", [])
            if any(keyword in normalized for keyword in keywords):
                for agent in agents:
                    if agent != primary and agent not in collaborators:
                        collaborators.append(agent)

        if primary != "friday" and any(term in normalized for term in ["build", "launch", "strategy", "platform", "saas", "dashboard"]):
            if "friday" not in collaborators:
                collaborators.append("friday")

        ordered = [agent for agent in self._default_order if agent in collaborators]
        return ordered

    def _handoff_chain(self, primary: str, normalized: str, collaborators: List[str]) -> List[str]:
        for pattern in self._collaboration_patterns:
            keywords = pattern.get("keywords", [])
            chain = [slugify(agent) for agent in pattern.get("chain", []) if slugify(agent)]
            if chain and any(keyword in normalized for keyword in keywords):
                if primary in chain:
                    chain = [primary, *[agent for agent in chain if agent != primary]]
                else:
                    chain = [primary, *chain]
                return self._dedupe_chain(chain)

        fallback_chain = [primary, *collaborators]
        return self._dedupe_chain(fallback_chain)

    def _dedupe_chain(self, chain: List[str]) -> List[str]:
        ordered: List[str] = []
        for agent in chain:
            if agent and agent not in ordered:
                ordered.append(agent)
        return ordered

    def _build_confidence_scores(self, primary: str, chain: List[str], base_scores: Dict[str, float]) -> Dict[str, float]:
        confidence_scores: Dict[str, float] = {}
        for index, agent in enumerate(chain):
            base = base_scores.get(agent, 0.0)
            chain_weight = max(0.4, 1.0 - index * 0.15)
            confidence_scores[agent] = round(min(1.0, 0.3 + (base * 0.1) + chain_weight * 0.4), 2)
        if primary not in confidence_scores:
            confidence_scores[primary] = round(min(1.0, 0.6 + base_scores.get(primary, 0.0) * 0.1), 2)
        return confidence_scores

    def _should_use_multi_agent(self, normalized: str, primary: str, collaborators: List[str]) -> bool:
        if len(collaborators) >= 2:
            return True
        broad_terms = [
            "build",
            "launch",
            "startup",
            "saas",
            "platform",
            "dashboard",
            "complete",
            "full project",
            "end to end",
            "strategy",
            "research",
        ]
        if any(term in normalized for term in broad_terms):
            return True
        if primary in {"ultron", "oracle", "gecko"} and len(collaborators) >= 1:
            return True
        return False

    def _build_reason(self, primary: str, collaborators: List[str], signals: List[str], mode: str) -> str:
        if mode == "multi" and collaborators:
            return f"Primary agent {primary} selected with collaborators {', '.join(collaborators)}"
        if signals:
            return f"Matched signals: {', '.join(signals[:4])}"
        return f"Defaulting to {primary}"

    def export_rules(self) -> Dict[str, Any]:
        return {
            "single": self._single_rules,
            "multi": self._multi_rules,
        }


__all__ = ["AgentRouter"]
