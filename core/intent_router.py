"""IntentRouter: simple intent detection and skill recommendation."""

from __future__ import annotations

from typing import Any, Dict
import re

from .agent_router import AgentRouter
from .skill_engine import SkillEngine


class IntentRouter:
    def __init__(self, skill_engine: SkillEngine = None):
        self.skill_engine = skill_engine or SkillEngine()
        self.agent_router = AgentRouter()
        self.intent_map = {
            "coding": ["build", "create", "implement", "develop", "react", "frontend", "website", "api"],
            "marketing": ["seo", "marketing", "email", "strategy", "content", "audience"],
            "automation": ["automate", "script", "cron", "workflow", "automation", "run script"],
            "research": ["research", "find", "investigate", "compare", "analysis"],
            "chat": ["hello", "hi", "how are you", "what's up", "hey"],
        }

    def _score_intent(self, text: str) -> str:
        t = (text or "").lower()
        best = ("chat", 0)
        for intent, keywords in self.intent_map.items():
            score = 0
            for keyword in keywords:
                if keyword in t:
                    score += 1
            if score > best[1]:
                best = (intent, score)
        return best[0]

    def route(self, text: str) -> Dict[str, Any]:
        intent = self._score_intent(text)
        decision = self.agent_router.route(text)
        autonomous = decision.mode == "multi"
        if re.search(r"build (a |the )?complete|build complete|complete website|full project|implement the whole", text, re.I):
            autonomous = True

        skills = self.skill_engine.match_skills(text)
        skill_names = [skill.name for skill in skills]

        from .logger import get_logger

        logger = get_logger(__name__)
        logger.info("Intent detected: %s; matched skills: %s", intent, skill_names)

        return {
            "intent": intent,
            "skills": skill_names,
            "autonomous": autonomous,
            "agent": decision.primary_agent,
            "mode": decision.mode,
            "collaborators": decision.collaborators,
        }


__all__ = ["IntentRouter"]

