from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional
import sqlite3
import time

from .logger import get_logger


logger = get_logger(__name__)


DEFAULT_AGENT_SKILLS: Dict[str, List[str]] = {
    "friday": ["planning", "memory", "scheduling"],
    "oracle": ["research-assistant", "analyst"],
    "vision": ["frontend-expert", "ui-design-system"],
    "ultron": ["fastapi", "backend-architecture"],
    "gecko": ["ai-seo", "growth-marketing"],
    "hulk": ["browser-automation", "tests"],
    "spectre": ["ai-security", "cloud-security"],
    "herald": ["communication", "seo"],
    "veronica": ["product-manager", "agile-product-owner"],
}

DEFAULT_AGENT_PROFILES: Dict[str, Dict[str, str]] = {
    "friday": {
        "name": "Friday",
        "role": "daily briefing, notifications, scheduling, reminders, summaries",
        "summary": "Keeps JARVIS organized, concise, and aware of the user's day.",
    },
    "oracle": {
        "name": "Oracle",
        "role": "research, web intelligence, knowledge gathering, competitor analysis",
        "summary": "Finds facts, compares options, and turns the web into usable signal.",
    },
    "vision": {
        "name": "Vision",
        "role": "image understanding, monitoring, observations, screenshot analysis",
        "summary": "Interprets visual input and turns observations into concise insights.",
    },
    "ultron": {
        "name": "Ultron",
        "role": "software engineering, coding, architecture, debugging, code generation",
        "summary": "Designs, implements, and debugs software systems with high precision.",
    },
    "gecko": {
        "name": "Gecko",
        "role": "growth, marketing, SEO, content strategy",
        "summary": "Optimizes acquisition, content, and search visibility.",
    },
    "hulk": {
        "name": "Hulk",
        "role": "execution, automation, terminal operations, workflow handling",
        "summary": "Handles concrete execution, scripts, and mechanical follow-through.",
    },
    "spectre": {
        "name": "Spectre",
        "role": "security, compliance, privacy, risk review",
        "summary": "Reviews sensitive work for security, privacy, and policy concerns.",
    },
    "herald": {
        "name": "Herald",
        "role": "communication, drafting, announcements, outbound messaging",
        "summary": "Drafts clear communication for internal and external audiences.",
    },
    "veronica": {
        "name": "Veronica",
        "role": "product management, requirements, customer operations, support coordination",
        "summary": "Shapes requirements, customer flow, and operational alignment.",
    },
}

DEFAULT_SKILL_DESCRIPTIONS: Dict[str, str] = {
    "frontend-expert": "Frontend implementation, React components, and UI delivery.",
    "ui-design-system": "Design tokens, component architecture, and UI consistency.",
    "fastapi": "FastAPI routes, request validation, and backend API delivery.",
    "backend-architecture": "Backend structure, service boundaries, and data flow design.",
    "ai-seo": "Search strategy, discoverability, and AI-assisted SEO optimization.",
    "growth-marketing": "Acquisition experiments, growth loops, and campaign execution.",
    "research-assistant": "Research planning, fact gathering, and evidence synthesis.",
    "analyst": "Analysis, comparison, and interpretation of quantitative and qualitative data.",
    "planning": "Task organization, prioritization, and execution planning.",
    "memory": "Knowledge retention, summaries, and long-term context management.",
    "scheduling": "Calendar-aware scheduling, reminders, and time-based coordination.",
    "browser-automation": "Browser automation, navigation, and UI inspection.",
    "tests": "Validation workflows, test execution, and quality checks.",
    "ai-security": "Security analysis with AI-assisted threat and risk review.",
    "cloud-security": "Cloud security posture, hardening, and access control review.",
    "communication": "Internal communication, drafts, and status updates.",
    "seo": "Search engine optimization and visibility planning.",
    "product-manager": "Product requirements, roadmap planning, and stakeholder alignment.",
    "agile-product-owner": "Backlog refinement, sprint planning, and story decomposition.",
}


class AgentSkillRegistry:
    def __init__(self, db_path: Optional[str] = None) -> None:
        self.repo_root = Path(__file__).resolve().parent.parent
        self.db_path = Path(db_path) if db_path else self.repo_root / "memory" / "agent_skill_registry.db"
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._ensure_schema()
        self.seed_defaults()

    def _ensure_schema(self) -> None:
        with self._conn:
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS agents (
                    slug TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    role TEXT NOT NULL DEFAULT '',
                    summary TEXT NOT NULL DEFAULT '',
                    memory_db TEXT NOT NULL DEFAULT '',
                    active INTEGER NOT NULL DEFAULT 1,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                )
                """
            )
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS skills (
                    name TEXT PRIMARY KEY,
                    description TEXT NOT NULL DEFAULT '',
                    source_path TEXT NOT NULL DEFAULT '',
                    active INTEGER NOT NULL DEFAULT 1,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                )
                """
            )
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS agent_skills (
                    agent_slug TEXT NOT NULL,
                    skill_name TEXT NOT NULL,
                    position INTEGER NOT NULL DEFAULT 0,
                    created_at REAL NOT NULL,
                    PRIMARY KEY (agent_slug, skill_name),
                    FOREIGN KEY (agent_slug) REFERENCES agents(slug) ON DELETE CASCADE,
                    FOREIGN KEY (skill_name) REFERENCES skills(name) ON DELETE CASCADE
                )
                """
            )
            self._conn.execute("CREATE INDEX IF NOT EXISTS idx_agent_skills_agent ON agent_skills(agent_slug)")
            self._conn.execute("CREATE INDEX IF NOT EXISTS idx_agent_skills_skill ON agent_skills(skill_name)")

    def seed_defaults(self) -> None:
        now = time.time()
        with self._conn:
            for slug, skill_names in DEFAULT_AGENT_SKILLS.items():
                profile = DEFAULT_AGENT_PROFILES.get(slug, {})
                self._conn.execute(
                    """
                    INSERT INTO agents (slug, name, role, summary, memory_db, active, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, 1, ?, ?)
                    ON CONFLICT(slug) DO UPDATE SET
                        name=excluded.name,
                        role=excluded.role,
                        summary=excluded.summary,
                        memory_db=excluded.memory_db,
                        active=1,
                        updated_at=excluded.updated_at
                    """,
                    (
                        slug,
                        profile.get("name", slug.title()),
                        profile.get("role", ""),
                        profile.get("summary", ""),
                        str(self.repo_root / "memory" / f"{slug}.db"),
                        now,
                        now,
                    ),
                )
                for position, skill_name in enumerate(skill_names):
                    self._upsert_skill(skill_name, now)
                    self._conn.execute(
                        """
                        INSERT INTO agent_skills (agent_slug, skill_name, position, created_at)
                        VALUES (?, ?, ?, ?)
                        ON CONFLICT(agent_slug, skill_name) DO UPDATE SET
                            position=excluded.position
                        """,
                        (slug, skill_name, position, now),
                    )

    def _upsert_skill(self, skill_name: str, timestamp: float) -> None:
        description = DEFAULT_SKILL_DESCRIPTIONS.get(skill_name, "")
        source_path = self.resolve_skill_path(skill_name) or ""
        self._conn.execute(
            """
            INSERT INTO skills (name, description, source_path, active, created_at, updated_at)
            VALUES (?, ?, ?, 1, ?, ?)
            ON CONFLICT(name) DO UPDATE SET
                description=excluded.description,
                source_path=excluded.source_path,
                active=1,
                updated_at=excluded.updated_at
            """,
            (skill_name, description, source_path, timestamp, timestamp),
        )

    def resolve_skill_path(self, skill_name: str) -> Optional[str]:
        candidates = [
            self.repo_root / "Skills",
            self.repo_root / "skills",
        ]
        for base in candidates:
            if not base.exists():
                continue
            for path in base.rglob(skill_name):
                if path.is_dir() and path.name == skill_name:
                    return str(path)
        return None

    def list_agents(self) -> List[Dict[str, Any]]:
        cursor = self._conn.cursor()
        rows = cursor.execute("SELECT slug, name, role, summary, memory_db, active, created_at, updated_at FROM agents ORDER BY slug").fetchall()
        return [dict(row) for row in rows]

    def list_skills(self) -> List[Dict[str, Any]]:
        cursor = self._conn.cursor()
        rows = cursor.execute("SELECT name, description, source_path, active, created_at, updated_at FROM skills ORDER BY name").fetchall()
        return [dict(row) for row in rows]

    def get_agent_skills(self, agent_slug: str) -> List[str]:
        cursor = self._conn.cursor()
        rows = cursor.execute(
            "SELECT skill_name FROM agent_skills WHERE agent_slug = ? ORDER BY position ASC, skill_name ASC",
            (agent_slug,),
        ).fetchall()
        return [str(row["skill_name"]) for row in rows]

    def get_skill_snapshot(self) -> Dict[str, Any]:
        return {
            "db_path": str(self.db_path),
            "agents": self.list_agents(),
            "skills": self.list_skills(),
            "agent_skills": self.list_agent_skills(),
        }

    def list_agent_skills(self) -> List[Dict[str, Any]]:
        cursor = self._conn.cursor()
        rows = cursor.execute(
            """
            SELECT agent_slug, skill_name, position, created_at
            FROM agent_skills
            ORDER BY agent_slug, position, skill_name
            """
        ).fetchall()
        return [dict(row) for row in rows]

    def close(self) -> None:
        try:
            self._conn.close()
        except Exception:
            pass


__all__ = ["AgentSkillRegistry", "DEFAULT_AGENT_SKILLS"]
